"""
Poller v4 — Intervalle fixe 30s
- Check taille avant download (économie API)
- Gestion 429 avec pause 60s
- Cache log_dir en DB (zéro cold start au redémarrage)
- Cache positions PlayerList en mémoire
- Sauvegarde ADM dans Supabase Storage (72h retention)

Version kit : retiré le narrateur de sessions (session_tracker, table
sessions Supabase, hors périmètre), les hooks cartes/heatmap/zones
d'alerte (position_map, heatmap_task, zone_alert — dashboard SaaS) et
les intégrations économie/shop/NO PVP qui appelaient l'API SaaS de Nico
(codex-api) — inutilisables pour un kit self-hosted distribué (pas de
backend partagé, pas de clé API valide côté client).
"""

import asyncio
import httpx
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Callable, Awaitable

from backend.models import KillEvent, ServerConfig, CHANNEL_MAP
from backend.parser import parse_adm_content
from backend import database as db

logger = logging.getLogger("killfeed.poller")

NITRADO_API      = "https://api.nitrado.net"
INTERVAL_ACTIVE  = 10   # secondes si activité récente (kills ou PlayerList)
INTERVAL_IDLE    = 30   # secondes si serveur calme
ACTIVITY_WINDOW  = 120  # secondes sans activité avant de passer en idle
RETRY_429        = 60   # pause si rate limit Nitrado


# ─── Filtre d'événements ─────────────────────────────────────────────────────

_CONSCIOUSNESS_CAUSES = {"unconscious", "regained consciousness"}

def _passes_filter(event: KillEvent, guild_id: str) -> bool:
    from backend.models import KillType

    if event.kill_type == KillType.PVE:
        cause = (event.cause or "").lower()
        if cause in _CONSCIOUSNESS_CAUSES:
            return db.get_setting(guild_id, "show_consciousness", "0") == "1"

    if event.kill_type == KillType.SUICIDE:
        return db.get_setting(guild_id, "show_suicides", "1") == "1"

    if event.kill_type == KillType.PLACE:
        detail = (event.detail or "").lower()
        if detail in {"buried", "dug out", "dug_out"}:
            return db.get_setting(guild_id, "show_burials", "1") == "1"

    return True


class ServerPoller:
    def __init__(
        self,
        config: ServerConfig,
        on_kill: Callable[[KillEvent, ServerConfig, str, str], Awaitable[None]],
        bot=None,
    ):
        self.config  = config
        self.on_kill = on_kill
        self._bot    = bot

        self._running      = False
        self._client: Optional[httpx.AsyncClient] = None
        self._log_dir:     Optional[str] = None
        self._new_guild:   bool  = False
        self._current_adm: Optional[str] = None
        self._last_size:   int           = -1
        self._last_activity: float       = 0.0
        self._max_players:   int         = 0
        # Dernière fois que le fichier ADM a grossi ou changé — lu par
        # bot/tasks/server_watch.py pour détecter des logs figés.
        self.last_adm_change: float      = datetime.utcnow().timestamp()
        # cache : { player_name: (x, y, z, timestamp) }
        self._position_cache: dict[str, tuple[float, float, float, float]] = {}
        # downsampling historique : dernière position enregistrée en DB { player_name: (x, y, z, ts) }
        self._pos_hist_last: dict[str, tuple[float, float, float, float]] = {}

    def _get_interval(self) -> int:
        if datetime.utcnow().timestamp() - self._last_activity < ACTIVITY_WINDOW:
            return INTERVAL_ACTIVE
        return INTERVAL_IDLE

    def _cache_set(self, name: str, pos: tuple[float, float, float]):
        self._position_cache[name] = (*pos, datetime.utcnow().timestamp())

    def _cache_get(self, name: str) -> Optional[tuple[float, float, float]]:
        entry = self._position_cache.get(name)
        if not entry:
            return None
        x, y, z, ts = entry
        if datetime.utcnow().timestamp() - ts > 86400:  # 24h TTL
            del self._position_cache[name]
            return None
        return (x, y, z)

    # ─── Nitrado ──────────────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.config.nitrado_token}"}

    async def _http_get(self, url: str, **kwargs) -> Optional[httpx.Response]:
        try:
            r = await self._client.get(url, **kwargs)
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(
                    f"[{self.config.guild_id}] Rate limit Nitrado — pause {RETRY_429}s"
                )
                await asyncio.sleep(RETRY_429)
            else:
                logger.error(
                    f"[{self.config.guild_id}] HTTP {e.response.status_code} — {url}"
                )
            return None
        except Exception as e:
            logger.error(f"[{self.config.guild_id}] Erreur requête: {e}")
            return None

    def _parse_max_players(self, data: dict) -> int:
        """Slots max : 'slots' (canonique Nitrado) > query.player_max > config.maxPlayers."""
        query = data.get("query") or {}
        cfg   = (data.get("settings") or {}).get("config", {})
        try:
            return int(data.get("slots") or query.get("player_max") or cfg.get("maxPlayers") or 0)
        except (TypeError, ValueError):
            return 0

    async def _fetch_max_players(self):
        """Résout les slots indépendamment du cache log_dir (call /gameservers)."""
        r = await self._http_get(
            f"{NITRADO_API}/services/{self.config.service_id}/gameservers",
            headers=self._headers,
        )
        if not r:
            return
        data = r.json().get("data", {}).get("gameserver", {})
        self._max_players = self._parse_max_players(data)
        logger.info(f"[{self.config.guild_id}] Slots max résolus: {self._max_players}")

    async def _resolve_log_dir(self) -> Optional[str]:
        r = await self._http_get(
            f"{NITRADO_API}/services/{self.config.service_id}/gameservers",
            headers=self._headers,
        )
        if not r:
            return None

        data     = r.json()["data"]["gameserver"]
        username = data["username"]
        game     = data["game"].lower()

        self._max_players = self._parse_max_players(data)
        logger.info(f"[{self.config.guild_id}] Slots max résolus: {self._max_players}")

        if game == "dayzps":
            log_dir = f"games/{username}/noftp/dayzps/config"
        elif game == "dayzxb":
            log_dir = f"games/{username}/noftp/dayzxb/config"
        else:
            logger.error(f"[{self.config.guild_id}] Jeu non supporté: {game}")
            return None

        # Map : dossier mission (FIABLE) d'abord, settings.config.map en secours.
        # Auto-réparation : on corrige servers.map_name dès qu'il diffère
        # (les serveurs déjà enregistrés en "unknown"/Chernarus se soignent).
        mission   = data.get("settings", {}).get("config", {}).get("mission", "")
        resolved  = db.map_from_mission(mission) or (
            data.get("settings", {}).get("config", {}).get("map")
            or data.get("game_specific", {}).get("map")
            or data.get("map")
        )
        if resolved and resolved.lower() not in ("", "unknown") \
                and resolved.lower() != (self.config.map_name or "").lower():
            sb = db.get_client()
            sb.table("servers").update({"map_name": resolved})\
                .eq("server_id", self.config.server_id).execute()
            logger.info(
                f"[{self.config.guild_id}] map_name corrigé "
                f"'{self.config.map_name}' → '{resolved}' (mission={mission})"
            )
            self.config.map_name = resolved

        # Auto-réparation salons legacy génériques (mono-serveur uniquement)
        try:
            db.heal_generic_channels(self.config.guild_id, self.config.server_id)
        except Exception as e:
            logger.warning(f"[{self.config.guild_id}] heal_generic_channels: {e}")

        state = db.get_poller_state(self.config.guild_id, server_id=self.config.server_id)
        db.set_poller_state(
            self.config.guild_id,
            state["log_offset"],
            state["current_file"],
            state.get("last_poll", ""),
            log_dir,
            server_id=self.config.server_id,
        )
        logger.info(f"[{self.config.guild_id}] log_dir résolu: {log_dir}")
        return log_dir

    async def _get_latest_adm(self) -> Optional[dict]:
        r = await self._http_get(
            f"{NITRADO_API}/services/{self.config.service_id}"
            f"/gameservers/file_server/list?dir={self._log_dir}",
            headers=self._headers,
        )
        if not r:
            return None

        entries   = r.json().get("data", {}).get("entries", [])
        adm_files = [
            e for e in entries
            if isinstance(e, dict) and e.get("name", "").upper().endswith(".ADM")
        ]
        if not adm_files:
            return None

        adm_files.sort(key=lambda f: f.get("modified_at", 0), reverse=True)
        latest = adm_files[0]
        return {
            "path": f"{self._log_dir}/{latest['name']}",
            "size": latest.get("size", -1),
            "name": latest["name"],
        }

    async def _download_adm(self, adm_path: str) -> Optional[str]:
        r = await self._http_get(
            f"{NITRADO_API}/services/{self.config.service_id}"
            f"/gameservers/file_server/download?file={adm_path}",
            headers=self._headers,
        )
        if not r:
            return None

        download_url = r.json().get("data", {}).get("token", {}).get("url")
        if not download_url:
            return None

        r2 = await self._http_get(download_url)
        return r2.text if r2 else None

    # ─── Sauvegarde ADM ───────────────────────────────────────────────────────

    async def _save_adm_to_storage(self, filename: str, content: str):
        """Archive le fichier ADM sur le disque local + purge les vieux."""
        try:
            from bot.tasks.adm_storage import save_adm_to_storage, purge_old_adm
            loop = asyncio.get_event_loop()
            # Exécuter en thread pour ne pas bloquer le poller
            await loop.run_in_executor(
                None, save_adm_to_storage, self.config.guild_id, filename, content
            )
            deleted = await loop.run_in_executor(
                None, purge_old_adm, self.config.guild_id
            )
            if deleted:
                logger.info(f"[{self.config.guild_id}] ADM purge: {deleted} fichier(s) supprimé(s)")
        except Exception as e:
            logger.error(f"[{self.config.guild_id}] Erreur save ADM: {e}")

    async def _post_adm_to_logs(self, adm_path: str, adm_name: str):
        """Poste le fichier ADM complet d'une session terminée dans #logs-adm."""
        if not self._bot:
            return
        channel_id = db.get_channel(self.config.guild_id, "logs-adm", server_id=self.config.server_id)
        if not channel_id:
            return
        channel = self._bot.get_channel(int(channel_id))
        if not channel:
            return

        content = await self._download_adm(adm_path)
        if not content:
            return

        import io
        import discord
        from bot.discord_queue import enqueue

        data    = content.encode("utf-8")
        n_lines = content.count("\n") + 1
        embed = discord.Embed(
            title="📄 Session terminée — log ADM",
            description=f"`{adm_name}`\n{len(data) // 1024} Ko · {n_lines} lignes",
            color=discord.Color.from_rgb(90, 100, 110),
        )

        DISCORD_LIMIT = 25 * 1024 * 1024  # 25 Mo (upload bot non-boosté)
        if len(data) > DISCORD_LIMIT:
            # Trop gros pour un attachement → le fichier reste archivé en local
            # (plus d'URL signée : le kit n'expose aucun storage distant).
            from bot.tasks.adm_storage import get_adm_file_path
            path = get_adm_file_path(self.config.guild_id, adm_name)
            embed.description += "\n⚠️ Trop volumineux pour Discord — archivé localement."
            if path:
                embed.add_field(name="Fichier archivé", value=f"`{path}`", inline=False)
            await enqueue(channel, embed)
            return

        file = discord.File(io.BytesIO(data), filename=adm_name)
        await enqueue(channel, embed, file)
        logger.info(f"[{self.config.guild_id}] ADM posté dans #logs-adm: {adm_name}")

    # ─── Traitement ───────────────────────────────────────────────────────────

    async def _process(self, content: str, adm_name: str = ""):
        raw    = content.encode("utf-8")
        size   = len(raw)

        cursor = db.get_poller_state(self.config.guild_id, server_id=self.config.server_id)["log_offset"]

        if self._new_guild:
            self._new_guild = False
            logger.info(
                f"[{self.config.guild_id}] Nouvelle guild — "
                f"démarrage à l'offset {size} (historique ignoré)"
            )
            db.set_poller_state(
                self.config.guild_id, size,
                self._current_adm or "", "", self._log_dir or "",
                server_id=self.config.server_id,
            )
            return

        if size < cursor:
            cursor = 0
        if size == cursor:
            return

        new_content = raw[cursor:].decode("utf-8", errors="replace")
        kills, position_updates = parse_adm_content(
            new_content, date.today(), self.config.guild_id
        )

        if kills or position_updates is not None:
            self._last_activity = datetime.utcnow().timestamp()

        if position_updates:
            logger.info(
                f"[{self.config.guild_id}] PlayerList — "
                f"{len(position_updates)} position(s) mises à jour"
            )
        now_ts = datetime.utcnow().timestamp()
        for name, pos in position_updates.items():
            self._cache_set(name, pos)
            db.set_player_position(self.config.guild_id, name, *pos, server_id=self.config.server_id)

            last = self._pos_hist_last.get(name)
            if last is None:
                should_record = True
            else:
                lx, ly, _, lt = last
                dist = ((pos[0] - lx) ** 2 + (pos[1] - ly) ** 2) ** 0.5
                should_record = dist >= 50.0 or (now_ts - lt) >= 300
            if should_record:
                db.save_position_history(self.config.guild_id, name, *pos)
                self._pos_hist_last[name] = (*pos, now_ts)

        sid = self.config.server_id
        channels = db.get_all_channels(self.config.guild_id, server_id=self.config.server_id)
        for kill in kills:
            kill.server_id = sid  # tag server_id sur chaque event
            if db.kill_exists_ts(self.config.guild_id, sid,
                                  kill.timestamp.isoformat(),
                                  kill.kill_type.value, kill.victim_name):
                continue
            if kill.kill_type.value == "connection":
                if not kill.victim_pos:
                    kill.victim_pos = self._cache_get(kill.victim_name)
                if not kill.victim_pos:
                    kill.victim_pos = db.get_player_position(
                        self.config.guild_id, kill.victim_name, server_id=sid
                    )
            kill.id = db.save_kill(kill)

            # Auto-bans NO PVP / suicide (backend/moderation.py)
            if kill.kill_type.value in ("pvp", "suicide"):
                from backend.moderation import check_auto_ban
                asyncio.create_task(check_auto_ban(self._bot, self.config, kill))

            if kill.kill_type.value == "connection" and kill.cause == "connected":
                db.register_player(
                    kill.guild_id,
                    kill.victim_name,
                    kill.timestamp.date().isoformat(),
                    server_id=sid,
                )

            logger.info(
                f"[{self.config.guild_id}] {kill.kill_type.value.upper():14s} "
                f"{(kill.killer_name or kill.victim_name):15s}"
                + (f" → {kill.victim_name}" if kill.killer_name else "")
            )

            channel_type = CHANNEL_MAP.get(kill.kill_type)
            channel_id   = channels.get(channel_type) if channel_type else None

            # Fallback : si le salon n'est pas en DB, cherche par nom dans Discord
            if not channel_id and channel_type and self._bot:
                try:
                    from bot.channel_resolver import resolve_channel as _resolve
                    ch = await _resolve(
                        self._bot, self.config.guild_id, channel_type,
                        server_id=self.config.server_id,
                    )
                    if ch:
                        channel_id = str(ch.id)
                        channels[channel_type] = channel_id  # cache pour les events suivants du batch
                except Exception as _e:
                    logger.debug(f"[{self.config.guild_id}] channel_resolver '{channel_type}': {_e}")

            if not channel_id:
                if channel_type:
                    logger.debug(f"[{self.config.guild_id}] Salon '{channel_type}' introuvable — event ignoré")
            elif _passes_filter(kill, self.config.guild_id):
                try:
                    await self.on_kill(kill, self.config, channel_id, channel_type or "")
                except Exception as e:
                    logger.error(f"[{self.config.guild_id}] Erreur callback: {e}")

        db.set_poller_state(
            self.config.guild_id, size,
            self._current_adm or "", "", self._log_dir or "",
            server_id=sid,
        )

    # ─── [SUPPRIMÉ — kit] primes / shop ───────────────────────────────────────
    # Appelaient l'API SaaS (codex-api), que le kit n'a pas. Les auto-bans NO
    # PVP / suicide sont revenus en direct sur Nitrado : backend/moderation.py.

    # ─── Cycle principal ──────────────────────────────────────────────────────

    async def poll_once(self):
        if not self._log_dir:
            self._log_dir = await self._resolve_log_dir()
            if not self._log_dir:
                return

        # Slots max : résolus indépendamment du cache log_dir, retenté tant que 0
        if not self._max_players:
            await self._fetch_max_players()

        adm = await self._get_latest_adm()
        if not adm:
            return

        # Nouveau fichier ADM détecté → reset offset + sauvegarde
        if adm["path"] != self._current_adm:
            logger.info(f"[{self.config.guild_id}] Nouveau ADM: {adm['name']}")
            if self._current_adm:
                # Session précédente terminée → poster son ADM complet dans #logs-adm
                old_path = self._current_adm
                old_name = old_path.rsplit("/", 1)[-1]
                asyncio.create_task(self._post_adm_to_logs(old_path, old_name))
            self._current_adm = adm["path"]
            self._last_size   = -1
            self.last_adm_change = datetime.utcnow().timestamp()
            db.set_poller_state(
                self.config.guild_id, 0,
                adm["path"], "", self._log_dir or "",
                server_id=self.config.server_id,
            )
            # Télécharger et sauvegarder dans Supabase Storage
            content = await self._download_adm(adm["path"])
            if content:
                await self._save_adm_to_storage(adm["name"], content)
                await self._process(content, adm["name"])
            return

        if adm["size"] != -1 and adm["size"] == self._last_size:
            return

        content = await self._download_adm(adm["path"])
        if not content:
            return

        self._last_size = adm["size"]
        self.last_adm_change = datetime.utcnow().timestamp()
        await self._process(content, adm["name"])

    async def start(self):
        self._running = True
        self._client  = httpx.AsyncClient(timeout=30.0)

        state         = db.get_poller_state(self.config.guild_id, server_id=self.config.server_id)
        offset        = state["log_offset"]
        saved_file    = state["current_file"]
        saved_log_dir = state["log_dir"]

        if saved_log_dir:
            self._log_dir = saved_log_dir
        if saved_file:
            self._current_adm = saved_file
            logger.info(
                f"[{self.config.guild_id}] Reprise: {saved_file} (offset={offset})"
            )
        else:
            self._new_guild = True

        logger.info(
            f"[{self.config.guild_id}] Poller v4 démarré "
            f"(interval={INTERVAL_ACTIVE}s actif / {INTERVAL_IDLE}s idle"
            f" | service={self.config.service_id})"
        )

        while self._running:
            t0 = asyncio.get_event_loop().time()
            try:
                await self.poll_once()
            except Exception as e:
                logger.error(f"[{self.config.guild_id}] Erreur inattendue: {e}")

            elapsed  = asyncio.get_event_loop().time() - t0
            interval = self._get_interval()
            await asyncio.sleep(max(0, interval - elapsed))

    async def stop(self):
        self._running = False
        if self._client:
            await self._client.aclose()
        logger.info(f"[{self.config.guild_id}] Poller arrêté")