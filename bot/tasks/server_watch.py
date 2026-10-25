"""
bot/tasks/server_watch.py
Surveillance du serveur DayZ, toutes les 5 minutes (1 appel Nitrado) :

  • renomme le salon vocal « serverstate » : 🟢 En-Ligne • 12/60, 🟠 Redémarrage…,
    🔴 Hors-ligne. Discord limite le renommage d'un salon à 2 fois / 10 min :
    5 min est le rythme maximal tenable ;
  • alerte #alertes quand Nitrado signale le serveur arrêté (2 contrôles de
    suite, pour ignorer un simple redémarrage), puis quand il revient ;
  • alerte #alertes quand le fichier ADM ne bouge plus depuis 30 min alors
    que des joueurs sont connectés (KillFeed « aveugle »).

Les alertes sont coupées 15 min après un redémarrage lancé par le bot.
Le même tour réessaie les bans restés en attente (backend/moderation.py).
"""

import asyncio
import logging
import time
from typing import Optional

import discord
import httpx

from backend import database as db
from backend.models import ServerConfig
from bot.extra_channels import send_alert

logger = logging.getLogger("killfeed.server_watch")

NITRADO_API      = "https://api.nitrado.net"
CHECK_EVERY      = 300
DOWN_CONFIRM     = 2          # contrôles consécutifs avant alerte
ADM_STALE_SEC    = 30 * 60
RESTART_GRACE    = 15 * 60    # silence après un redémarrage planifié

UP_STATUSES = {"started", "restarting"}
STATUS_FR = {
    "started":             "en ligne",
    "restarting":          "redémarrage",
    "stopped":             "arrêté",
    "stopping":            "arrêt en cours",
    "suspended":           "suspendu (abonnement Nitrado)",
    "guardian_locked":     "bloqué par Nitrado Guardian",
    "gs_installation":     "installation en cours",
    "backup_restore":      "restauration de sauvegarde",
    "backup_creation":     "création de sauvegarde",
    "chunkfix":            "réparation en cours",
    "overviewmap_render":  "génération de carte",
}

# État par serveur : {server_key: {...}}
_state: dict[str, dict] = {}


async def fetch_gameserver(cfg: ServerConfig) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{NITRADO_API}/services/{cfg.service_id}/gameservers",
                headers={"Authorization": f"Bearer {cfg.nitrado_token}"},
            )
            r.raise_for_status()
            return r.json().get("data", {}).get("gameserver", {})
    except Exception as e:
        logger.warning(f"[{cfg.guild_id}] Lecture statut Nitrado : {e}")
        return None


def _players(gs: dict) -> tuple[Optional[int], int]:
    query = gs.get("query") or {}
    cur   = query.get("player_current")
    try:
        cur = int(cur) if cur is not None else None
    except (TypeError, ValueError):
        cur = None
    try:
        mx = int(gs.get("slots") or query.get("player_max") or 0)
    except (TypeError, ValueError):
        mx = 0
    return cur, mx


def _voice_name(status: str, cur: Optional[int], mx: int) -> str:
    if status == "started":
        return f"🟢 En-Ligne • {cur if cur is not None else '?'}/{mx or '?'}"
    if status == "restarting":
        return "🟠 Redémarrage…"
    return "🔴 Hors-ligne"


async def _update_voice(bot, cfg: ServerConfig, name: str) -> None:
    ch_id = db.get_channel(cfg.guild_id, "serverstate", server_id=cfg.server_id)
    if not ch_id:
        return
    ch = bot.get_channel(int(ch_id))
    if not isinstance(ch, discord.VoiceChannel) or ch.name == name:
        return
    try:
        # discord.py attend en silence si la limite de renommage est atteinte :
        # on abandonne plutôt que de bloquer la boucle, le prochain tour réessaie.
        await asyncio.wait_for(ch.edit(name=name, reason="Compteur joueurs"), timeout=15)
    except (asyncio.TimeoutError, discord.HTTPException) as e:
        logger.debug(f"[{cfg.guild_id}] Renommage serverstate reporté : {e}")


def _in_restart_grace(guild_id: str) -> bool:
    try:
        return time.time() - float(db.get_setting(guild_id, "restart_last_ts", "0")) < RESTART_GRACE
    except ValueError:
        return False


async def _check(bot, manager, cfg: ServerConfig) -> None:
    gs = await fetch_gameserver(cfg)
    if gs is None:
        return  # Nitrado injoignable : ni renommage ni alerte sur une panne réseau locale
    status   = (gs.get("status") or "").lower()
    cur, mx  = _players(gs)
    key      = cfg.server_id or cfg.guild_id
    st       = _state.setdefault(key, {"down": 0, "alerted_down": False, "alerted_stale": False})

    await _update_voice(bot, cfg, _voice_name(status, cur, mx))

    grace = _in_restart_grace(cfg.guild_id)

    # ── Serveur hors ligne ───────────────────────────────────────────────────
    if status in UP_STATUSES:
        st["down"] = 0
        if st["alerted_down"] and status == "started":
            st["alerted_down"] = False
            await send_alert(bot, cfg, discord.Embed(
                title="🟢 Serveur de nouveau en ligne",
                description=f"**{cfg.server_name}** répond à nouveau ({cur if cur is not None else '?'}/{mx or '?'} joueurs).",
                color=0x22C55E,
            ))
    else:
        st["down"] += 1
        if st["down"] >= DOWN_CONFIRM and not st["alerted_down"] and not grace:
            st["alerted_down"] = True
            await send_alert(bot, cfg, discord.Embed(
                title="🔴 Serveur hors ligne",
                description=(
                    f"**{cfg.server_name}** est **{STATUS_FR.get(status, status or 'inconnu')}** "
                    f"selon Nitrado depuis au moins {DOWN_CONFIRM * CHECK_EVERY // 60} minutes.\n"
                    "Vérifie le panneau Nitrado (redémarrage, abonnement, mise à jour)."
                ),
                color=0xEF4444,
            ))

    # ── Logs ADM figés ───────────────────────────────────────────────────────
    poller = manager.get_poller(cfg) if manager else None
    if poller is None:
        return
    stale = time.time() - poller.last_adm_change
    if status == "started" and (cur or 0) > 0 and stale > ADM_STALE_SEC and not grace:
        if not st["alerted_stale"]:
            st["alerted_stale"] = True
            await send_alert(bot, cfg, discord.Embed(
                title="⚠️ Logs ADM figés",
                description=(
                    f"{cur} joueur(s) connecté(s) mais le fichier ADM n'a pas bougé depuis "
                    f"{int(stale // 60)} minutes : le KillFeed ne reçoit plus rien.\n"
                    "Causes fréquentes : logs ADM désactivés dans les réglages Nitrado, "
                    "token Nitrado expiré. Lance `/diagnostic`."
                ),
                color=0xF59E0B,
            ))
    elif stale <= ADM_STALE_SEC and st["alerted_stale"]:
        st["alerted_stale"] = False
        await send_alert(bot, cfg, discord.Embed(
            title="✅ Logs ADM de nouveau reçus",
            description="Le KillFeed reçoit à nouveau les événements.",
            color=0x22C55E,
        ))


async def run_server_watch(bot, manager) -> None:
    await bot.wait_until_ready()
    await asyncio.sleep(60)  # laisse les pollers démarrer
    while not bot.is_closed():
        for cfg in db.get_all_active_servers():
            try:
                await _check(bot, manager, cfg)
            except Exception as e:
                logger.error(f"[{cfg.guild_id}] Surveillance serveur : {e}")
            try:
                from backend.moderation import retry_pending_bans
                await retry_pending_bans(bot, cfg)
            except Exception as e:
                logger.error(f"[{cfg.guild_id}] Bans en attente : {e}")
        await asyncio.sleep(CHECK_EVERY)
