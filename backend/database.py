"""
Base de données du kit — SQLite locale, zéro dépendance réseau.

Le client `supabase-py` a été remplacé par backend/sqlite_client.py, qui
reproduit le sous-ensemble d'API réellement exercé (.table().select().eq()…
→ objet avec .data / .count). Aucun site d'appel n'a changé : l'interface
fluent et la convention synchrone sont identiques.

Le token Nitrado n'est plus stocké ni chiffré en base : il vient du .env via
bot/config.py::load_config() et est injecté dans ServerConfig à la lecture
(cf. _row_to_config). Le chiffrement Fernet protégeait une base Supabase
mutualisée entre clients — menace inexistante sur une installation locale.
"""

import logging
import discord
from typing import Optional
from datetime import datetime, timedelta, timezone
from backend.sqlite_client import SQLiteClient, create_client
from backend.models import ServerConfig, KillEvent
from bot.config import install_root, load_config

logger = logging.getLogger("killfeed.database")

MIGRATIONS_DIR = install_root() / "migrations"

# ─── Client SQLite ────────────────────────────────────────────────────────────

_client: SQLiteClient | None = None

def get_client() -> SQLiteClient:
    """Singleton — même point d'accès qu'avant (create_client une seule fois).
    Les migrations sont appliquées à la création (idempotentes)."""
    global _client
    if _client is None:
        path = load_config().db_path
        _client = create_client(path, MIGRATIONS_DIR)
        logger.info(f"[DB] SQLite locale : {path}")
    return _client

from contextlib import contextmanager

@contextmanager
def get_conn():
    """Compatibilité — retourne le client en tant que conn."""
    yield get_client()

def is_guild_activated(guild_id: str) -> bool:
    """Pas de licence dans la version communautaire — /setup ouvert à tous."""
    return True

# ─── Migrations ───────────────────────────────────────────────────────────────

def run_migrations():
    """Applique migrations/*.sql (CREATE … IF NOT EXISTS → rejouable)."""
    get_client()

def init_db():
    run_migrations()

def write_heartbeat(bot_version: str = "", guilds_count: int = 0,
                    active_servers: int = 0) -> None:
    """Écrase la ligne unique bot_heartbeat (id=1). Signal de vie du bot.
    Best-effort : ne lève jamais (le heartbeat ne doit pas casser le bot)."""
    from datetime import datetime, timezone
    try:
        now = datetime.now(timezone.utc).isoformat()
        get_client().table("bot_heartbeat").upsert({
            "id":             1,
            "last_beat":      now,
            "updated_at":     now,
            "bot_version":    bot_version,
            "guilds_count":   guilds_count,
            "active_servers": active_servers,
        }, on_conflict="id").execute()
    except Exception as e:
        logger.warning(f"[DB] write_heartbeat échec : {e}")

# ─── Channels — configuration ─────────────────────────────────────────────────

# Source unique de vérité pour les types de salons.
# Mirror dans codex-api/main.py (CHANNEL_EMOJIS) — maintenir synchronisé.
CHANNEL_CONFIG: dict[str, dict] = {
    "morts-pvp":         {"emoji": "💀",  "label": "Morts PVP",         "default": True},
    "morts-pve":         {"emoji": "☠️",   "label": "Morts PVE",         "default": True},
    "connexions":        {"emoji": "🎮",  "label": "Connexions",         "default": True},
    "constructions":     {"emoji": "🔨",  "label": "Constructions",      "default": False},
    "placements":        {"emoji": "📦",  "label": "Placements",         "default": False},
    "drapeaux":          {"emoji": "🚩",  "label": "Drapeaux",           "default": False},
    "statistiques":      {"emoji": "📊",  "label": "Statistiques",       "default": False},
    "logs-whitelist":    {"emoji": "📋",  "label": "Logs Whitelist",     "default": False},
    "logs-adm":          {"emoji": "📄",  "label": "Logs ADM",           "default": False},
    "alertes":           {"emoji": "🚨",  "label": "Alertes admin",      "default": False},
    "annonces":          {"emoji": "📢",  "label": "Annonces serveur",   "default": False},
}

CHANNEL_TYPES  = list(CHANNEL_CONFIG.keys())
CHANNEL_LABELS = {k: f"{v['emoji']}・{k}" for k, v in CHANNEL_CONFIG.items()}

# ─── Sync salons Discord ──────────────────────────────────────────────────────

def discord_utils_find_category(guild, name: str):
    for cat in guild.categories:
        if cat.name == name:
            return cat
    return None


def find_server_category(guild, server_name: str | None):
    """
    Catégorie Discord d'un serveur. Schéma actuel : '📡 CodeX — {server_name}'.
    1. Match exact (multi-serveur sûr).
    2. Fallback legacy : si une SEULE catégorie '📡 CodeX*' existe (guild mono-serveur
       ou ancien nom '📡 CodeX KillFeed'), on l'utilise. En multi-serveur (≥2 catégories
       CodeX) on N'AMBIGÜE PAS : match exact obligatoire, sinon None.
    """
    if server_name:
        cat = discord_utils_find_category(guild, f"📡 CodeX — {server_name}")
        if cat:
            return cat
    codex_cats = [c for c in guild.categories if c.name.startswith("📡 CodeX")]
    if len(codex_cats) == 1:
        return codex_cats[0]
    return None


def is_channel_explicitly_disabled(guild_id: str, ch_type: str, server_id: str = None) -> bool:
    """
    True si une ligne existe en DB pour ce salon AVEC enabled=0 (l'admin l'a refusé).
    Distingue 'jamais configuré' (pas de ligne → False, provisionnable) de
    'désactivé volontairement' (ligne enabled=0 → True, à ne PAS recréer au boot).
    """
    sb = get_client()
    q = sb.table("channels").select("enabled")\
        .eq("guild_id", guild_id).eq("type", ch_type)
    if server_id:
        q = q.eq("server_id", server_id)
    res = q.limit(1).execute()
    return bool(res.data) and not res.data[0].get("enabled")

async def sync_guild_channels(guild, guild_id: str, server_id: str = None) -> list[str]:
    existing = get_all_channels(guild_id, server_id=server_id)
    created  = []

    config = get_server_by_id(server_id) if server_id else get_server(guild_id)
    server_name = getattr(config, "server_name", None) if config else None
    category = find_server_category(guild, server_name)
    if not category:
        logger.warning(
            f"[{guild_id}] Catégorie '📡 CodeX — {server_name}' introuvable "
            f"(server_id={server_id}) — sync ignorée"
        )
        return []

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(
            read_messages=True, send_messages=True,
            attach_files=True, embed_links=True, read_message_history=True,
        ),
    }

    for ch_type, ch_id in existing.items():
        if not ch_id:
            continue

        # Salon vocal compteur — recréation spécifique
        if ch_type == "serverstate":
            channel = guild.get_channel(int(ch_id))
            if channel:
                continue
            voice_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True),
            }
            try:
                vc = await category.create_voice_channel(name="En-Ligne • 0/?", overwrites=voice_overwrites)
                set_channel(guild_id, "serverstate", str(vc.id), server_id=server_id or "")
                created.append("serverstate")
                logger.info(f"[{guild_id}] ✅ Salon vocal serverstate recréé")
            except Exception as e:
                logger.error(f"[{guild_id}] Erreur recréation salon serverstate: {e}")
            continue

        if ch_type not in CHANNEL_CONFIG:
            continue
        channel = guild.get_channel(int(ch_id))
        if channel:
            continue
        cfg  = CHANNEL_CONFIG.get(ch_type, {"emoji": "📌"})
        name = f"{cfg['emoji']}・{ch_type}"
        try:
            new_channel = await category.create_text_channel(name=name, overwrites=overwrites)
            set_channel(guild_id, ch_type, str(new_channel.id), server_id=server_id or "")
            clear_pinned_message(guild_id, ch_type, server_id=server_id or "")
            created.append(ch_type)
            logger.info(f"[{guild_id}] ✅ Salon recréé: #{name}")
        except Exception as e:
            logger.error(f"[{guild_id}] Erreur recréation salon {ch_type}: {e}")

    # Ne pas créer automatiquement les salons absents de la DB :
    # la création est du ressort du /setup et du dashboard.
    # Ce sync ne fait que RÉCUPÉRER les salons supprimés de Discord.

    return created

# ─── Servers ──────────────────────────────────────────────────────────────────

def save_server(guild_id: str, nitrado_token: str, service_id: str,
                server_name: str, map_name: str, platform: str, username: str,
                server_alias: str = "",
                guild_name: str = "",
                setup_by_id: str = "",
                setup_by_name: str = "") -> str:
    """Upsert sur (guild_id, service_id) — retourne le server_id UUID.

    `nitrado_token` est accepté pour ne pas changer la signature des appelants
    mais N'EST PLUS PERSISTÉ : la source unique du token est NITRADO_TOKEN dans
    le .env (cf. bot/config.py). La colonne a disparu du schéma.
    """
    sb = get_client()
    existing = sb.table("servers").select("server_id")\
        .eq("guild_id", guild_id).eq("service_id", service_id).limit(1).execute()
    if existing.data:
        server_id = existing.data[0]["server_id"]
        update_payload = {
            "server_name":   server_name,
            "server_alias":  server_alias,
            "map_name":      map_name,
            "platform":      platform,
            "username":      username,
            "active":        1,
        }
        if guild_name:   update_payload["guild_name"]     = guild_name
        if setup_by_id:  update_payload["setup_by_id"]    = setup_by_id
        if setup_by_name: update_payload["setup_by_name"] = setup_by_name
        sb.table("servers").update(update_payload)\
            .eq("guild_id", guild_id).eq("service_id", service_id).execute()
    else:
        res = sb.table("servers").insert({
            "guild_id":       guild_id,
            "service_id":     service_id,
            "server_name":    server_name,
            "server_alias":   server_alias,
            "map_name":       map_name,
            "platform":       platform,
            "username":       username,
            "active":         1,
            "guild_name":     guild_name,
            "setup_by_id":    setup_by_id,
            "setup_by_name":  setup_by_name,
        }).execute()
        server_id = res.data[0]["server_id"]
    return server_id


def _row_to_config(row: dict) -> ServerConfig:
    """Ligne `servers` → ServerConfig, token Nitrado injecté depuis le .env.

    Remplace l'ancien `decrypt_token(row["nitrado_token"])` : le token n'est
    plus ni stocké ni chiffré en base (voir save_server). Une seule source,
    NITRADO_TOKEN, partagée avec backend/nitrado_whitelist.py — fin des deux
    chemins de configuration divergents.
    """
    data = {k: row[k] for k in ServerConfig.model_fields if k in row}
    data["nitrado_token"] = load_config().nitrado_token
    return ServerConfig(**data)

def get_server(guild_id: str, service_id: str = None) -> Optional[ServerConfig]:
    """Retourne le serveur. Si service_id fourni → serveur précis. Sinon → premier actif."""
    sb = get_client()
    q = sb.table("servers").select("*").eq("guild_id", guild_id).eq("active", 1)
    if service_id:
        q = q.eq("service_id", service_id)
    res = q.limit(1).execute()
    return _row_to_config(res.data[0]) if res.data else None

def get_server_by_id(server_id: str) -> Optional[ServerConfig]:
    """Retourne un serveur par son UUID server_id."""
    sb = get_client()
    res = sb.table("servers").select("*").eq("server_id", server_id).eq("active", 1).limit(1).execute()
    return _row_to_config(res.data[0]) if res.data else None

def get_all_servers_for_guild(guild_id: str) -> list[ServerConfig]:
    """Retourne tous les serveurs actifs d'une guild."""
    sb = get_client()
    res = sb.table("servers").select("*").eq("guild_id", guild_id).eq("active", 1).execute()
    return [_row_to_config(row) for row in (res.data or [])]

def get_all_active_servers() -> list[ServerConfig]:
    sb = get_client()
    res = sb.table("servers").select("*").eq("active", 1).execute()
    return [_row_to_config(row) for row in (res.data or [])]

def deactivate_server(guild_id: str, service_id: str = None):
    sb = get_client()
    q = sb.table("servers").update({"active": 0}).eq("guild_id", guild_id)
    if service_id:
        q = q.eq("service_id", service_id)
    q.execute()

def get_retention(guild_id: str) -> int:
    sb = get_client()
    res = sb.table("servers").select("retention_days").eq("guild_id", guild_id).limit(1).execute()
    return res.data[0]["retention_days"] if res.data else 30

# ─── Multi-serveur — détection map + comptage ────────────────────────────────

# Dossier mission → carte (source FIABLE, contrairement à settings.config.map
# que Nitrado ne renseigne pas pour Sakhal/console).
def map_from_mission(mission: str) -> Optional[str]:
    """Déduit la carte depuis le nom du dossier mission. None si inconnu."""
    if not mission:
        return None
    m = mission.lower()
    if "nasdara" in m or "badlands" in m:   # 1.30 Badlands — dayzOffline.nasdara
        return "nasdara"
    if "sakhal" in m:
        return "sakhal"
    if "enoch" in m or "livonia" in m:
        return "livonia"
    if "namalsk" in m:
        return "namalsk"
    if "chernarus" in m:        # dayzOffline.chernarusplus, *.chernarus
        return "chernarus"
    return None

_active_count_cache: dict[str, tuple[int, float]] = {}

def count_active_servers(guild_id: str) -> int:
    """Nb de serveurs actifs d'une guild (caché 60s — appelé sur le hot path)."""
    import time
    c = _active_count_cache.get(guild_id)
    if c and time.monotonic() < c[1]:
        return c[0]
    sb = get_client()
    res = sb.table("servers").select("server_id", count="exact")\
        .eq("guild_id", guild_id).eq("active", 1).execute()
    n = res.count if res.count is not None else len(res.data or [])
    _active_count_cache[guild_id] = (n, time.monotonic() + 60)
    return n

def heal_generic_channels(guild_id: str, server_id: str) -> int:
    """
    Auto-réparation au boot : ré-affecte les salons 'génériques' legacy
    (server_id NULL/'') à un server_id réel.
    - Mono-serveur : à ce serveur.
    - Multi-serveur : ne touche RIEN — l'attribution est faite par
      reconcile_channels_to_categories() via la catégorie Discord réelle
      (source de vérité fiable, contrairement à un tri created_at).
    Idempotent. Retourne le nb réparé.
    """
    if not server_id:
        return 0
    sb = get_client()
    rows = sb.table("channels").select("type,server_id")\
        .eq("guild_id", guild_id).execute().data or []
    generic = [r for r in rows if not (r.get("server_id") or "")]
    if not generic:
        return 0

    if count_active_servers(guild_id) > 1:
        # Multi-serveur : on NE devine PAS (created_at peu fiable). C'est
        # reconcile_channels_to_categories() qui attribue via la catégorie
        # Discord réelle (source de vérité). Ici on ne touche rien.
        return 0

    sb.table("channels").update({"server_id": server_id})\
        .eq("guild_id", guild_id).or_("server_id.is.null,server_id.eq.").execute()
    invalidate_channels_cache(guild_id, server_id)
    invalidate_channels_cache(guild_id, None)
    logger.info(f"[{guild_id}] {len(generic)} salon(s) legacy ré-affecté(s) à {server_id}")
    return len(generic)


def reconcile_channels_to_categories(guild, guild_id: str, servers: list) -> int:
    """
    Réattribue chaque ligne 'channels' au serveur dont la CATÉGORIE DISCORD
    contient réellement le salon (source de vérité fiable, contrairement à
    l'heuristique created_at). Corrige les generic legacy ET les lignes
    mal attribuées (ex: position-map du serveur 1 portée par le serveur 2).

    `servers` = liste de ServerConfig de la guild (server_id + server_name).
    Retourne le nb de lignes corrigées.
    """
    # category Discord "📡 CodeX — {server_name}" → server_id
    cat_to_sid = {f"📡 CodeX — {s.server_name}": s.server_id for s in servers}
    if not cat_to_sid:
        return 0
    sb = get_client()
    rows = sb.table("channels").select("id,type,channel_id,server_id")\
        .eq("guild_id", guild_id).execute().data or []

    def _del(row):
        if row.get("id") is not None:
            sb.table("channels").delete().eq("id", row["id"]).execute()
        else:
            sb.table("channels").delete().eq("guild_id", guild_id)\
                .eq("type", row["type"]).eq("channel_id", row.get("channel_id") or "")\
                .execute()

    def _set_sid(row, sid):
        if row.get("id") is not None:
            sb.table("channels").update({"server_id": sid}).eq("id", row["id"]).execute()
        else:
            sb.table("channels").update({"server_id": sid})\
                .eq("guild_id", guild_id).eq("type", row["type"])\
                .eq("channel_id", row.get("channel_id") or "").execute()

    # Propriétaire réel de chaque ligne = serveur dont la catégorie Discord
    # contient le channel_id.
    enriched = []
    for row in rows:
        cid = row.get("channel_id") or ""
        true_sid = None
        if cid:
            try:
                ch  = guild.get_channel(int(cid))
                cat = getattr(ch, "category", None)
                true_sid = cat_to_sid.get(cat.name) if cat else None
            except (TypeError, ValueError):
                true_sid = None
        enriched.append((row, true_sid))

    owned: set = set()           # (server_id, type) déjà correctement occupés
    # Passe 1 : lignes déjà au bon serveur → priment
    for row, true_sid in enriched:
        if true_sid and (row.get("server_id") or "") == true_sid:
            owned.add((true_sid, row["type"]))

    fixed = 0
    # Passe 2 : lignes mal attribuées → dédoublonner (supprimer si le bon
    # serveur a déjà ce type, sinon réattribuer).
    for row, true_sid in enriched:
        if not true_sid or (row.get("server_id") or "") == true_sid:
            continue
        key = (true_sid, row["type"])
        if key in owned:
            _del(row)                       # doublon → on supprime la mauvaise
        else:
            _set_sid(row, true_sid)
            owned.add(key)
        fixed += 1

    if fixed:
        for s in servers:
            invalidate_channels_cache(guild_id, s.server_id)
        invalidate_channels_cache(guild_id, None)
        logger.info(f"[{guild_id}] {fixed} salon(s) corrigé(s) via catégorie Discord")
    return fixed

# ─── Channels ─────────────────────────────────────────────────────────────────

def set_channel(guild_id: str, ch_type: str, channel_id: str, server_id: str = ""):
    sb = get_client()
    sb.table("channels").upsert({
        "guild_id":   guild_id,
        "server_id":  server_id,
        "type":       ch_type,
        "channel_id": channel_id,
        "enabled":    1,
    }, on_conflict="guild_id,server_id,type").execute()
    invalidate_channels_cache(guild_id, server_id or None)

def disable_channel(guild_id: str, ch_type: str, server_id: str = ""):
    """enabled=0 plutôt que suppression : sync_guild_channels ne le recrée pas au boot."""
    sb = get_client()
    sb.table("channels").update({"enabled": 0})\
        .eq("guild_id", guild_id).eq("server_id", server_id).eq("type", ch_type).execute()
    invalidate_channels_cache(guild_id, server_id or None)

def get_channel(guild_id: str, ch_type: str, server_id: str = None) -> Optional[str]:
    # Multi-serveur : sans server_id et >1 serveur actif, on REFUSE de
    # renvoyer un salon au hasard (cause des croisements d'infos).
    if not server_id and count_active_servers(guild_id) > 1:
        logger.warning(
            f"[{guild_id}] get_channel('{ch_type}') sans server_id en multi-serveur "
            f"— ignoré (risque de croisement)"
        )
        return None
    sb = get_client()
    q = sb.table("channels").select("channel_id")\
        .eq("guild_id", guild_id).eq("type", ch_type).eq("enabled", 1)
    if server_id:
        q = q.eq("server_id", server_id)
    res = q.limit(1).execute()
    return res.data[0]["channel_id"] if res.data else None

_channels_cache: dict[str, tuple[dict, float]] = {}  # key → (result, expires_at)
_CHANNELS_TTL = 300  # 5 minutes

def get_all_channels(guild_id: str, server_id: str = None) -> dict[str, str]:
    import time
    cache_key = f"{guild_id}:{server_id or ''}"
    cached = _channels_cache.get(cache_key)
    if cached and time.monotonic() < cached[1]:
        return cached[0]

    # Multi-serveur : sans server_id et >1 serveur actif, flatten = croisement
    # garanti. On renvoie vide plutôt que de mélanger les 2 serveurs.
    if not server_id and count_active_servers(guild_id) > 1:
        logger.warning(
            f"[{guild_id}] get_all_channels sans server_id en multi-serveur "
            f"— vide (risque de croisement)"
        )
        _channels_cache[cache_key] = ({}, time.monotonic() + _CHANNELS_TTL)
        return {}

    sb = get_client()
    res = sb.table("channels").select("type,channel_id,server_id,enabled").eq("guild_id", guild_id).execute()
    rows = [r for r in (res.data or []) if r.get("enabled") and r.get("channel_id")]
    if not server_id:
        result = {row["type"]: row["channel_id"] for row in rows}
    else:
        specific = {row["type"]: row["channel_id"] for row in rows if (row.get("server_id") or "") == server_id}
        if count_active_servers(guild_id) > 1:
            # Multi-serveur : AUCUN fallback generic (sinon les salons legacy
            # du 1er serveur fuient sur le 2e). heal_generic_channels les
            # réattribue au 1er serveur → ils deviennent 'specific'.
            result = specific
        else:
            generic = {row["type"]: row["channel_id"] for row in rows if not (row.get("server_id") or "")}
            result = {**generic, **specific}

    _channels_cache[cache_key] = (result, time.monotonic() + _CHANNELS_TTL)
    return result

def invalidate_channels_cache(guild_id: str, server_id: str = None):
    """À appeler après set_channel() pour forcer le rechargement."""
    key = f"{guild_id}:{server_id or ''}"
    _channels_cache.pop(key, None)
    _channels_cache.pop(f"{guild_id}:", None)

def delete_guild_channels(guild_id: str):
    sb = get_client()
    sb.table("channels").delete().eq("guild_id", guild_id).execute()

# ─── Kills ────────────────────────────────────────────────────────────────────

def _to_int(v) -> Optional[int]:
    """Convertit une coordonnée float en int (perte sub-mètre acceptable)."""
    return int(v) if v is not None else None

def save_kill(event: KillEvent) -> int:
    sb = get_client()
    vx, vy, vz = (event.victim_pos or (None, None, None))
    kx, ky, kz = (event.killer_pos or (None, None, None))
    res = sb.table("kills").insert({
        "guild_id":    event.guild_id,
        "server_id":   event.server_id,
        "timestamp":   event.timestamp.isoformat(),
        "log_time":    event.log_time,
        "kill_type":   event.kill_type.value,
        "cause":       event.cause,
        "detail":      event.detail,
        "victim_name": event.victim_name,
        "victim_x":    _to_int(vx), "victim_y": _to_int(vy), "victim_z": _to_int(vz),
        "killer_name": event.killer_name,
        "killer_x":    _to_int(kx), "killer_y": _to_int(ky), "killer_z": _to_int(kz),
        "distance":    event.distance,
    }).execute()

    return res.data[0]["id"]

def kill_exists_ts(guild_id: str, server_id: Optional[str],
                   timestamp: str, kill_type: str, victim_name: str) -> bool:
    """Dédup par clé naturelle — remplace l'ancien check raw_line."""
    sb = get_client()
    q = (sb.table("kills").select("id")
           .eq("kill_type",   kill_type)
           .eq("victim_name", victim_name)
           .eq("timestamp",   timestamp))
    if server_id:
        q = q.eq("server_id", server_id)
    else:
        q = q.eq("guild_id", guild_id)
    return len(q.limit(1).execute().data) > 0

def get_recent_kills(guild_id: str, limit: int = 10, server_id: str = None) -> list[dict]:
    sb = get_client()
    q = sb.table("kills").select("*")
    if server_id:
        q = q.eq("server_id", server_id)
    else:
        q = q.eq("guild_id", guild_id)
    return q.order("timestamp", desc=True).limit(limit).execute().data

def get_kills_since(guild_id: str, since: str, server_id: str = None) -> list[dict]:
    sb = get_client()
    q = sb.table("kills").select("*")
    if server_id:
        q = q.eq("server_id", server_id)
    else:
        q = q.eq("guild_id", guild_id)
    return q.gte("timestamp", since).order("timestamp").execute().data

# ─── Fiche joueur / classement ────────────────────────────────────────────────
# SQL direct sur la connexion SQLite : le shim façon Supabase ne sait pas
# combiner « victime OU tueur » avec une comparaison insensible à la casse.

def get_player_events(guild_id: str, player_name: str) -> list[dict]:
    """Tous les événements où le joueur est victime OU tueur (casse ignorée)."""
    rows = get_client()._conn.execute(
        "SELECT * FROM kills WHERE guild_id = ? "
        "AND (victim_name = ? COLLATE NOCASE OR killer_name = ? COLLATE NOCASE) "
        "ORDER BY timestamp",
        (guild_id, player_name, player_name),
    ).fetchall()
    return [dict(r) for r in rows]

def get_player_first_seen(guild_id: str, player_name: str) -> Optional[str]:
    row = get_client()._conn.execute(
        "SELECT first_seen FROM player_registry WHERE guild_id = ? "
        "AND player_name = ? COLLATE NOCASE LIMIT 1",
        (guild_id, player_name),
    ).fetchone()
    return row["first_seen"] if row else None

def search_player_names(guild_id: str, prefix: str, limit: int = 25) -> list[str]:
    """Autocomplétion des commandes : joueurs déjà vus sur le serveur."""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = get_client()._conn.execute(
        "SELECT player_name FROM player_registry WHERE guild_id = ? "
        "AND player_name LIKE ? ESCAPE '\\' ORDER BY player_name LIMIT ?",
        (guild_id, f"{escaped}%", limit),
    ).fetchall()
    return [r["player_name"] for r in rows]

# ─── Positions joueurs ────────────────────────────────────────────────────────

def set_player_position(guild_id: str, player_name: str,
                        x: float, y: float, z: float,
                        player_id: str = None, server_id: str = None):
    """Upsert position avec updated_at explicite pour que les filtres temporels fonctionnent."""
    sb = get_client()
    sb.table("player_positions").upsert({
        "guild_id":    guild_id,
        "server_id":   server_id,
        "player_name": player_name,
        "player_id":   player_id,
        "x": _to_int(x), "y": _to_int(y), "z": _to_int(z),
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }, on_conflict="guild_id,player_name").execute()

def get_player_position(guild_id: str, player_name: str, server_id: str = None) -> Optional[tuple]:
    sb = get_client()
    q = sb.table("player_positions").select("x,y,z").eq("player_name", player_name)
    q = q.eq("server_id", server_id) if server_id else q.eq("guild_id", guild_id)
    res = q.limit(1).execute()
    if res.data:
        r = res.data[0]
        return (r["x"], r["y"], r["z"])
    return None

def get_all_positions(guild_id: str, server_id: str = None) -> list[dict]:
    sb = get_client()
    q = sb.table("player_positions").select("player_name,x,y,z,updated_at")
    q = q.eq("server_id", server_id) if server_id else q.eq("guild_id", guild_id)
    return q.execute().data

# ─── Poller state ─────────────────────────────────────────────────────────────

def get_poller_state(guild_id: str, server_id: str = None) -> dict:
    sb = get_client()
    q = sb.table("poller_state").select("*")
    q = q.eq("server_id", server_id) if server_id else q.eq("guild_id", guild_id)
    res = q.limit(1).execute()
    if res.data:
        return res.data[0]
    return {"guild_id": guild_id, "server_id": server_id, "log_offset": 0,
            "current_file": "", "last_poll": None, "log_dir": ""}

def set_poller_state(guild_id: str, log_offset: int, current_file: str,
                     last_poll: str, log_dir: str = "", server_id: str = None):
    sb = get_client()
    payload = {
        "guild_id":     guild_id,
        "server_id":    server_id,
        "log_offset":   log_offset,
        "current_file": current_file,
        "last_poll":    last_poll,
        "log_dir":      log_dir,
    }
    # Vérifier existence avant upsert (évite le 400 si la contrainte UNIQUE n'existe pas)
    q = sb.table("poller_state").select("guild_id")
    if server_id:
        q = q.eq("guild_id", guild_id).eq("server_id", server_id)
    else:
        q = q.eq("guild_id", guild_id).is_("server_id", "null")
    exists = q.limit(1).execute()

    if exists.data:
        upd = sb.table("poller_state").update(payload)
        if server_id:
            upd = upd.eq("guild_id", guild_id).eq("server_id", server_id)
        else:
            upd = upd.eq("guild_id", guild_id).is_("server_id", "null")
        upd.execute()
    else:
        sb.table("poller_state").insert(payload).execute()

# ─── Guild settings ───────────────────────────────────────────────────────────

def get_setting(guild_id: str, key: str, default: str = "0") -> str:
    sb = get_client()
    res = sb.table("guild_settings").select("value")\
        .eq("guild_id", guild_id).eq("key", key).limit(1).execute()
    return res.data[0]["value"] if res.data else default

def set_setting(guild_id: str, key: str, value: str):
    sb = get_client()
    sb.table("guild_settings").upsert({
        "guild_id": guild_id,
        "key":      key,
        "value":    value,
    }, on_conflict="guild_id,key").execute()

# ─── Player registry ──────────────────────────────────────────────────────────

def register_player(guild_id: str, player_name: str, first_seen: str, server_id: str = None):
    sb = get_client()
    sb.table("player_registry").upsert({
        "guild_id":    guild_id,
        "server_id":   server_id,
        "player_name": player_name,
        "first_seen":  first_seen,
    }, on_conflict="guild_id,player_name", ignore_duplicates=True).execute()

def get_new_players_since(guild_id: str, since: str, server_id: str = None) -> list[dict]:
    sb = get_client()
    q = sb.table("player_registry").select("player_name,first_seen")
    q = q.eq("server_id", server_id) if server_id else q.eq("guild_id", guild_id)
    return q.gte("first_seen", since).order("first_seen").execute().data

# ─── Messages épinglés ────────────────────────────────────────────────────────

def get_pinned_message(guild_id: str, msg_type: str, server_id: str = "") -> Optional[dict]:
    sb = get_client()
    res = sb.table("pinned_messages").select("message_id,channel_id")\
        .eq("guild_id", guild_id).eq("msg_type", msg_type)\
        .eq("server_id", server_id or "").limit(1).execute()
    return res.data[0] if res.data else None

def set_pinned_message(guild_id: str, msg_type: str, message_id: str,
                       channel_id: str, server_id: str = ""):
    sb = get_client()
    sb.table("pinned_messages").upsert({
        "guild_id":   guild_id,
        "server_id":  server_id or "",
        "msg_type":   msg_type,
        "message_id": message_id,
        "channel_id": channel_id,
    }, on_conflict="guild_id,server_id,msg_type").execute()

def clear_pinned_message(guild_id: str, msg_type: str, server_id: str = ""):
    sb = get_client()
    sb.table("pinned_messages").delete()\
        .eq("guild_id", guild_id).eq("msg_type", msg_type)\
        .eq("server_id", server_id or "").execute()

# ─── Historique positions ─────────────────────────────────────────────────────

def save_position_history(guild_id: str, player_name: str,
                           x: float, y: float, z: float):
    sb = get_client()
    sb.table("player_position_history").insert({
        "guild_id":    guild_id,
        "player_name": player_name,
        "x": _to_int(x), "y": _to_int(y), "z": _to_int(z),
    }).execute()

def purge_position_history(guild_id: str, days: int = 30) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sb = get_client()
    res = sb.table("player_position_history").delete()\
        .eq("guild_id", guild_id).lt("recorded_at", cutoff).execute()
    return len(res.data) if res.data else 0

# ─── Purge / Rétention ────────────────────────────────────────────────────────

def purge_old_events(guild_id: str) -> int:
    days = get_retention(guild_id)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sb = get_client()
    res = sb.table("kills").delete()\
        .eq("guild_id", guild_id).lt("timestamp", cutoff).execute()
    deleted = len(res.data) if res.data else 0
    if deleted > 0:
        logger.info(f"[{guild_id}] Purge: {deleted} events > {days}j supprimés")
    return deleted

def purge_all_guilds() -> int:
    servers = get_all_active_servers()
    guild_ids = list({s.guild_id for s in servers})
    total = 0
    for gid in guild_ids:
        total += purge_old_events(gid)
        total += purge_position_history(gid, days=7)
    logger.info(f"[DB] Purge nocturne terminée — {total} lignes supprimées au total")
    return total

def delete_server_data(guild_id: str, server_id: str):
    """Supprime toutes les données d'un serveur précis (server_id UUID).
    Ne supprime PAS guild_settings ni pinned_messages (partagés entre serveurs de la guild).
    Si c'était le dernier serveur, appelle delete_guild_completely() ensuite.
    """
    sb = get_client()
    tables_server = [
        "player_positions",
        "player_registry",
        "poller_state",
        "channels",
        "kills",
    ]
    for table in tables_server:
        try:
            sb.table(table).delete().eq("guild_id", guild_id).eq("server_id", server_id).execute()
        except Exception as e:
            logger.warning(f"[DB] delete_server_data — table {table}: {e}")

    # player_position_history n'a pas de server_id → on laisse (pas critique)
    # Supprimer la ligne servers elle-même
    try:
        sb.table("servers").delete().eq("guild_id", guild_id).eq("server_id", server_id).execute()
    except Exception as e:
        logger.warning(f"[DB] delete_server_data — servers: {e}")

    # Invalider le cache channels
    invalidate_channels_cache(guild_id, server_id)
    logger.info(f"[DB] Serveur {server_id} (guild {guild_id}) supprimé")


def delete_guild_completely(guild_id: str):
    """Suppression totale de toutes les données d'une guild (cascade complète)."""
    sb = get_client()
    tables = [
        "player_position_history",
        "player_positions",
        "player_registry",
        "pinned_messages",
        "poller_state",
        "channels",
        "guild_settings",
        "kills",
        "servers",
        "whitelist",
        "whitelist_requests",
        "whitelist_config",
    ]
    for table in tables:
        try:
            sb.table(table).delete().eq("guild_id", guild_id).execute()
        except Exception as e:
            logger.warning(f"[DB] delete_guild_completely — table {table}: {e}")

    # Archives ADM locales — data/adm/{guild_id}/
    try:
        from bot.tasks.adm_storage import delete_guild_adm
        delete_guild_adm(guild_id)
    except Exception as e:
        logger.warning(f"[DB] delete_guild_completely — archives ADM: {e}")

    # Invalider le cache channels
    _channels_cache.pop(guild_id, None)
    for key in list(_channels_cache.keys()):
        if key.startswith(f"{guild_id}:"):
            _channels_cache.pop(key, None)

    logger.info(f"[DB] Guild {guild_id} supprimée définitivement")

# ─── [SUPPRIMÉ — kit] Économie/défis/build map/wall map/flag map/zones ──────
# Toutes ces fonctions appartenaient au dashboard SaaS (économie/gamification,
# cartes, zones d'alerte) — hors périmètre du kit killfeed + whitelist.
# Voir l'historique git avant ce commit pour le code original.


def get_whitelist_player_names(guild_id: str) -> list[str]:
    """Liste des noms whitelistés (cache local, source de vérité = Nitrado)."""
    sb  = get_client()
    res = sb.table("whitelist").select("player_name").eq("guild_id", guild_id).execute()
    return [r["player_name"] for r in (res.data or []) if r.get("player_name")]