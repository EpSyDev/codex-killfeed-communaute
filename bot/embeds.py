"""
Embeds Discord — CodeX KillFeed v4.0 (kit single-tenant)
Taxonomie v3 : PVP / PVE / SUICIDE / BUILD / PLACE / CONNECTION / FLAG

Version kit : la personnalisation par guild (thèmes, règles conditionnelles,
icônes CDN) a été retirée avec embed_themes.py / embed_rules.py / icons_v2.py
(dashboard SaaS, hors périmètre). Couleurs et icônes par slot reprennent
telles quelles les valeurs par défaut du thème "classique".
"""

import re
import discord
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from backend.models import KillEvent, KillType, ServerConfig
from bot.translations import translate_entity

# ─── Style par défaut (ex-thème "classique" d'embed_themes.py) ────────────────
# slot_key -> {"color": discord.Color, "icon": str}

_SLOT_STYLE: dict[str, dict] = {
    "pvp":        {"color": discord.Color.from_rgb(220, 38,  38),  "icon": "💀"},
    "pvp_ko":     {"color": discord.Color.from_rgb(220, 38,  38),  "icon": "💀"},
    "pve":        {"color": discord.Color.from_rgb(234, 88,  12),  "icon": "☠️"},
    "pve_ko":     {"color": discord.Color.from_rgb(202, 138,  4),  "icon": "☠️"},
    "pve_wake":   {"color": discord.Color.from_rgb( 22, 163, 74),  "icon": "☠️"},
    "suicide":    {"color": discord.Color.from_rgb(124, 58,  237), "icon": "💊"},
    "build":      {"color": discord.Color.from_rgb( 34, 197, 94),  "icon": "🔨"},
    "destruct":   {"color": discord.Color.from_rgb(194, 65,  12),  "icon": "🔨"},
    "place":      {"color": discord.Color.from_rgb( 59, 130, 246), "icon": "📦"},
    "bury":       {"color": discord.Color.from_rgb(146, 64,  14),  "icon": "📦"},
    "connect":    {"color": discord.Color.from_rgb(  6, 182, 212), "icon": "🟢"},
    "disconnect": {"color": discord.Color.from_rgb(107, 114, 128), "icon": "🔴"},
    "flag_up":    {"color": discord.Color.from_rgb(234, 179,   8), "icon": "🚩"},
    "flag_down":  {"color": discord.Color.from_rgb(100, 116, 139), "icon": "🚩"},
}

_DEFAULT_COLOR = discord.Color.from_rgb(55, 65, 81)


def _slot_color(slot_key: str) -> discord.Color:
    return _SLOT_STYLE.get(slot_key, {}).get("color", _DEFAULT_COLOR)


def _slot_icon(slot_key: str) -> str:
    return _SLOT_STYLE.get(slot_key, {}).get("icon", "")

# ─── Visuels statiques ────────────────────────────────────────────────────────

SEP = "━━━━━━━━━━━━━━━━━━━━"

ICON_CONNECTED    = Path("assets/icons/enter.webp")
ICON_DISCONNECTED = Path("assets/icons/leave.webp")
FLAGS_DIR         = Path("assets/icons/flags")
ICON_ZOMBIE       = Path("assets/Zmb.webp")

PVE_STATE_ICONS: dict[str, Path] = {
    "bleedout":               Path("assets/bleeding.webp"),
    "hemorrhage":             Path("assets/bleeding.webp"),
    "starvation":             Path("assets/starvation.webp"),
    "dehydration":            Path("assets/dehydration.webp"),
    "unconscious":            Path("assets/unconsciousness.webp"),
    "regained consciousness": Path("assets/consciousness.webp"),
}

FLAG_TRANSLATIONS: dict[str, str] = {
    "Flag_DayZ": "DayZ", "Flag_White": "Blanc", "Flag_Bohemia": "Bohemia Interactive",
    "Flag_Pirates": "Pirates", "Flag_Cannibals": "Cannibales", "Flag_BabyDeer": "Faon",
    "Flag_Refuge": "Refuge", "Flag_RSTA": "RSTA", "Flag_Snake": "Serpent",
    "Flag_CDF": "Forces de Défense Tchernariennes", "Flag_CHEL": "CHEL",
    "Flag_CMC": "Chernarus Mining Corp.", "Flag_Chedaki": "ChDKZ (Étoile Rouge)",
    "Flag_Chernarus": "République de Chernarus", "Flag_HunterZ": "Zombie Hunters",
    "Flag_NAPA": "NAPA", "Flag_Rooster": "Coq", "Flag_TEC": "TEC",
    "Flag_UEC": "United Earth Coalition", "Flag_Wolf": "Loup",
    "Flag_Zenit": "Zenit Radio", "Flag_APA": "Asian Pacific Alliance",
    "Flag_Altis": "République d'Altis", "Flag_Bear": "Ours", "Flag_BrainZ": "BrainZ",
    "Flag_Crook": "Crook", "Flag_Livonia": "République de Livonie",
    "Flag_LDF": "Forces de Défense de Livonie", "Flag_LivoniaPolice": "Police de Livonie",
    "Flag_NSahrani": "Sahrani du Nord", "Flag_Rex": "Rex", "Flag_SSahrani": "Sahrani du Sud",
    "Flag_Zagorky": "Zagorky",
}

# ─── Titres par défaut ────────────────────────────────────────────────────────

_TITLES = {
    KillType.PVP:        "ÉLIMINATION",
    KillType.PVE:        "MORT ENVIRONNEMENT",
    KillType.SUICIDE:    "SUICIDE",
    KillType.BUILD:      "CONSTRUCTION",
    KillType.PLACE:      "PLACEMENT",
    KillType.CONNECTION: "CONNEXION",
    KillType.FLAG:       "DRAPEAU",
}

# ─── Résolution slot_key ──────────────────────────────────────────────────────

def _resolve_slot(event: KillEvent) -> str:
    """Détermine le slot_key à utiliser pour couleur + icône."""
    kt     = event.kill_type
    cause  = (event.cause  or "").lower()
    detail = (event.detail or "").lower()

    if kt == KillType.PVP:
        return "pvp_ko" if detail == "ko" else "pvp"
    if kt == KillType.PVE:
        if cause == "unconscious":               return "pve_ko"
        if cause == "regained consciousness":    return "pve_wake"
        return "pve"
    if kt == KillType.SUICIDE:
        return "suicide"
    if kt == KillType.BUILD:
        return "destruct" if any(w in detail for w in ("dismantled", "folded", "unmounted", "packed")) else "build"
    if kt == KillType.PLACE:
        return "bury" if detail in ("buried", "dug out") else "place"
    if kt == KillType.CONNECTION:
        return "connect" if cause == "connected" else "disconnect"
    if kt == KillType.FLAG:
        return "flag_up" if detail == "raised" else "flag_down"
    return "pvp"

# ─── iZurvive ─────────────────────────────────────────────────────────────────

MAP_SLUGS = {
    "chernarus":     "chernarusplus",
    "chernarusplus": "chernarusplus",
    "livonia":       "livonia",
    "sakhal":        "sakhal",
    "namalsk":       "namalsk",
    "nasdara":       "nasdara",
}

def izurvive_url(x: float, y: float, map_name: str = "chernarus") -> str:
    slug = MAP_SLUGS.get(map_name.lower(), "chernarusplus")
    return f"https://www.izurvive.com/{slug}/#location={x:.1f};{y:.1f}"

def pos_label(pos: tuple | None) -> str:
    if not pos:
        return "Inconnue"
    return f"`{pos[0]:.0f} / {pos[1]:.0f}`"

# ─── Coups encaissés (PVP) ────────────────────────────────────────────────────

BODYPART_FR: dict[str, str] = {
    "head": "Tête", "brain": "Crâne", "torso": "Torse",
    "leftarm": "Bras G", "rightarm": "Bras D",
    "lefthand": "Main G", "righthand": "Main D",
    "leftleg": "Jambe G", "rightleg": "Jambe D",
    "leftfoot": "Pied G", "rightfoot": "Pied D",
}

def _summarize_hits(hits: list | None) -> str | None:
    if not hits:
        return None
    total_dmg = sum(h.get("damage", 0) for h in hits)
    counts: dict[str, int] = {}
    for h in hits:
        zone = BODYPART_FR.get((h.get("bodypart") or "").lower(), h.get("bodypart") or "?")
        counts[zone] = counts.get(zone, 0) + 1
    breakdown = " · ".join(
        f"{z} ×{n}" if n > 1 else z
        for z, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    )
    n = len(hits)
    return f"**{n}** coup{'s' if n > 1 else ''} · **{total_dmg:.0f}** dmg\n{breakdown}"

# ─── Durée de session ─────────────────────────────────────────────────────────

def _get_session_duration(guild_id: str, player_name: str, disconnect_time) -> str | None:
    from backend import database as db
    import logging as _logging
    _logger = _logging.getLogger("killfeed.embeds")

    if disconnect_time.tzinfo is None:
        disconnect_time = disconnect_time.replace(tzinfo=timezone.utc)

    sb  = db.get_client()
    res = sb.table("kills").select("timestamp") \
        .eq("guild_id", guild_id) \
        .eq("victim_name", player_name) \
        .eq("kill_type", "connection") \
        .eq("cause", "connected") \
        .lte("timestamp", disconnect_time.isoformat()) \
        .order("timestamp", desc=True) \
        .limit(1).execute()

    if not res.data:
        return None

    try:
        connected_at = datetime.fromisoformat(res.data[0]["timestamp"].replace("Z", "+00:00"))
        if connected_at.tzinfo is None:
            connected_at = connected_at.replace(tzinfo=timezone.utc)
        delta = disconnect_time - connected_at
        total = int(delta.total_seconds())
        if total < 0 or total > 86400:
            return None
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        if h > 0:   return f"{h}h {m:02d}m"
        if m > 0:   return f"{m}m {s:02d}s"
        return f"{s}s"
    except Exception as e:
        _logger.error(f"[SessionDuration] {player_name}: {e}")
        return None

# ─── Thumbnails ───────────────────────────────────────────────────────────────

def _attach_thumbnail(embed: discord.Embed, classname: str, icon_type: str) -> discord.File | None:
    """Version kit : plus de cache CDN d'icônes (icons_v2.py retiré, hors périmètre).
    Pas de thumbnail dynamique par classname pour l'instant."""
    return None

def _attach_fixed_thumbnail(embed: discord.Embed, icon_path: Path) -> discord.File | None:
    if not icon_path.exists():
        return None
    filename = icon_path.name.replace(" ", "_")
    embed.set_thumbnail(url=f"attachment://{filename}")
    return discord.File(str(icon_path), filename=filename)

def _attach_flag_thumbnail(embed: discord.Embed, flag_classname: str) -> discord.File | None:
    p = FLAGS_DIR / f"{flag_classname}.png"
    if not p.exists():
        return None
    embed.set_thumbnail(url=f"attachment://{p.name}")
    return discord.File(str(p), filename=p.name)

# ─── Builder principal ────────────────────────────────────────────────────────

def build_kill_embed(
    event:              KillEvent,
    server_name:        str,
    map_name:           str,
    show_positions_pvp: bool = True,
    channel_type:       str = "",
) -> tuple[discord.Embed, discord.File | None]:
    """
    Retourne (embed, file | None).
    Version kit : couleurs/icônes fixes (thème "classique"), pas de règles
    conditionnelles ni de toggle position par salon (embed_themes/embed_rules
    retirés, dashboard SaaS hors périmètre).
    """
    kt     = event.kill_type
    cause  = event.cause  or ""
    detail = event.detail or ""

    slot_key = _resolve_slot(event)
    icon     = _slot_icon(slot_key)
    title    = _TITLES.get(kt, "ÉVÉNEMENT")

    # Sous-titres dynamiques
    if kt == KillType.BUILD:
        if "dismantled" in detail: title = "DÉCONSTRUCTION"
        elif "folded"   in detail: title = "REPLIAGE"
        elif "packed"   in detail: title = "RANGEMENT"
    elif kt == KillType.PLACE:
        if detail == "buried":     title = "ENTERREMENT"
        elif detail == "dug out":  title = "DÉTERREMENT"
    elif kt == KillType.CONNECTION:
        if cause != "connected":   title = "DÉCONNEXION"
    elif kt == KillType.FLAG:
        title = "DRAPEAU LEVÉ" if detail == "raised" else "DRAPEAU BAISSÉ"
    elif kt == KillType.PVP and detail == "ko":
        title = "KO KILL"
    elif kt == KillType.PVE:
        if cause == "unconscious":               title = "KO"
        elif cause == "regained consciousness":  title = "RÉVEIL"

    color = _slot_color(slot_key)

    embed     = discord.Embed(color=color)
    icon_file = None
    embed.set_author(name=f"{icon}  {title}" if icon else title)
    embed.add_field(name=SEP, value="", inline=False)

    # ── PVP ───────────────────────────────────────────────────────
    if kt == KillType.PVP:
        embed.add_field(
            name="⚔️  Combat",
            value=f"**{event.killer_name}** `→` **{event.victim_name}**",
            inline=False,
        )
        if cause:
            embed.add_field(name="🔫  Arme", value=f"`{cause}`", inline=True)
        if event.distance is not None:
            embed.add_field(name="📏  Distance", value=f"`{event.distance:.0f} m`", inline=True)
        if show_positions_pvp and event.victim_pos:
            url = izurvive_url(event.victim_pos[0], event.victim_pos[1], map_name)
            embed.add_field(name="📍  Position", value=f"[{pos_label(event.victim_pos)}]({url})", inline=True)
        hits_summary = _summarize_hits(event.hits_taken)
        if hits_summary:
            embed.add_field(name="🩸  Coups encaissés", value=hits_summary, inline=False)
        icon_file = _attach_thumbnail(embed, cause, "pvp")

    # ── PVE ───────────────────────────────────────────────────────
    elif kt == KillType.PVE:
        embed.add_field(name="☠️  Victime",  value=f"**{event.victim_name}**", inline=True)
        if cause:
            embed.add_field(name="⚠️  Cause", value=f"`{translate_entity(cause)}`", inline=True)
        if event.victim_pos:
            url = izurvive_url(event.victim_pos[0], event.victim_pos[1], map_name)
            embed.add_field(name="📍  Position", value=f"[{pos_label(event.victim_pos)}]({url})", inline=True)
        state_icon = PVE_STATE_ICONS.get(cause.lower())
        if state_icon:
            icon_file = _attach_fixed_thumbnail(embed, state_icon)
        elif cause.lower().startswith("zmb"):
            icon_file = _attach_fixed_thumbnail(embed, ICON_ZOMBIE)
        else:
            icon_file = _attach_thumbnail(embed, cause, "pve")

    # ── SUICIDE ───────────────────────────────────────────────────
    elif kt == KillType.SUICIDE:
        embed.add_field(name="💊  Joueur",   value=f"**{event.victim_name}**", inline=True)
        if cause:
            embed.add_field(name="⚠️  Cause", value=f"`{cause}`", inline=True)
        if event.victim_pos:
            url = izurvive_url(event.victim_pos[0], event.victim_pos[1], map_name)
            embed.add_field(name="📍  Position", value=f"[{pos_label(event.victim_pos)}]({url})", inline=True)
        icon_file = _attach_thumbnail(embed, cause, "suicide")

    # ── BUILD ─────────────────────────────────────────────────────
    elif kt == KillType.BUILD:
        embed.add_field(name="👷  Joueur",     value=f"**{event.victim_name}**",  inline=True)
        if cause:
            embed.add_field(name="🧱  Structure", value=f"`{cause}`",             inline=True)
        if detail and not any(w in detail for w in ("dismantled","folded","packed","unmounted")):
            embed.add_field(name="🔧  Outil",     value=f"`{detail}`",            inline=True)
        if event.victim_pos:
            url = izurvive_url(event.victim_pos[0], event.victim_pos[1], map_name)
            embed.add_field(name="📍  Position",  value=f"[{pos_label(event.victim_pos)}]({url})", inline=True)
        icon_file = _attach_thumbnail(embed, cause, "construction")

    # ── PLACE ─────────────────────────────────────────────────────
    elif kt == KillType.PLACE:
        embed.add_field(name="👤  Joueur", value=f"**{event.victim_name}**", inline=True)
        if cause:
            field_name = "⛏️  Objet" if detail in ("buried", "dug out") else "📦  Objet"
            embed.add_field(name=field_name, value=f"`{cause}`", inline=True)
        if event.victim_pos:
            url = izurvive_url(event.victim_pos[0], event.victim_pos[1], map_name)
            embed.add_field(name="📍  Position", value=f"[{pos_label(event.victim_pos)}]({url})", inline=True)
        icon_type = "burial" if detail in ("buried", "dug out") else "placement"
        icon_file = _attach_thumbnail(embed, cause, icon_type)

    # ── CONNECTION ────────────────────────────────────────────────
    elif kt == KillType.CONNECTION:
        connected = (cause == "connected")
        embed.add_field(name="👤  Joueur", value=f"**{event.victim_name}**", inline=False)
        if event.victim_pos:
            url = izurvive_url(event.victim_pos[0], event.victim_pos[1], map_name)
            embed.add_field(name="📍  Position", value=f"[{pos_label(event.victim_pos)}]({url})", inline=True)
        if not connected:
            duration = _get_session_duration(event.guild_id, event.victim_name, event.timestamp)
            if duration:
                embed.add_field(name="⏱️  Temps de jeu", value=f"`{duration}`", inline=True)
        icon_file = _attach_fixed_thumbnail(
            embed, ICON_CONNECTED if connected else ICON_DISCONNECTED
        )

    # ── FLAG ──────────────────────────────────────────────────────
    elif kt == KillType.FLAG:
        embed.add_field(name="👤  Joueur", value=f"**{event.victim_name}**", inline=True)
        if cause:
            embed.add_field(name="🚩  Drapeau", value=f"`{FLAG_TRANSLATIONS.get(cause, cause)}`", inline=True)
        if event.victim_pos:
            url = izurvive_url(event.victim_pos[0], event.victim_pos[1], map_name)
            embed.add_field(name="📍  Position", value=f"[{pos_label(event.victim_pos)}]({url})", inline=True)
        icon_file = _attach_flag_thumbnail(embed, cause)

    # ── Fallback ──────────────────────────────────────────────────
    else:
        embed.add_field(name="ℹ️  Détails", value=event.raw_line[:200], inline=False)

    embed.add_field(name=SEP, value="", inline=False)

    footer_parts = ["CodeX KillFeed", server_name, map_name, event.log_time]
    embed.set_footer(text="  ·  ".join(p for p in footer_parts if p))
    embed.timestamp = event.timestamp

    return embed, icon_file


# ─── Embeds utilitaires ───────────────────────────────────────────────────────

def build_setup_embed(
    server_name: str, map_name: str, platform: str, channels: dict[str, str]
) -> discord.Embed:
    from backend.database import CHANNEL_LABELS
    embed = discord.Embed(
        title="✅  KillFeed configuré !",
        description=(
            f"Les événements de **{server_name}** · *{map_name}* "
            "seront remontés automatiquement."
        ),
        color=discord.Color.from_rgb(59, 130, 246),
    )
    embed.add_field(name=SEP, value="", inline=False)
    lines = [f"{CHANNEL_LABELS.get(t, t)}  →  <#{cid}>" for t, cid in channels.items()]
    if lines:
        embed.add_field(name="📡  Salons créés", value="\n".join(lines), inline=False)
    embed.add_field(name="🔄  Polling",    value="`Vérification toutes les 10s`", inline=True)
    embed.add_field(name="🎮  Plateforme", value=f"`{platform.upper()}`",         inline=True)
    embed.set_footer(text="CodeX KillFeed by EpSy  ·  /stop pour arrêter")
    return embed


def build_status_embed(config: ServerConfig, channels: dict[str, str]) -> discord.Embed:
    from backend.database import CHANNEL_LABELS
    embed = discord.Embed(
        title="📡  Statut du KillFeed",
        color=discord.Color.from_rgb(59, 130, 246),
    )
    embed.add_field(name="🖥️  Serveur",    value=f"`{config.server_name}`",      inline=True)
    embed.add_field(name="🗺️  Map",        value=f"`{config.map_name}`",         inline=True)
    embed.add_field(name="🎮  Plateforme", value=f"`{config.platform.upper()}`", inline=True)
    embed.add_field(name=SEP, value="", inline=False)
    lines = [f"{CHANNEL_LABELS.get(t, t)}  →  <#{cid}>" for t, cid in channels.items()]
    if lines:
        embed.add_field(name="📺  Salons actifs", value="\n".join(lines), inline=False)
    embed.set_footer(text="CodeX KillFeed by EpSy")
    return embed
