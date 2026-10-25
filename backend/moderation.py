"""
backend/moderation.py
Bans Nitrado + auto-bans NO PVP / suicide.

Porté depuis codex-killfeed (poller._auto_ban / _nopvp_active_now) : le SaaS
passait par l'API codex-api, le kit écrit directement la banlist Nitrado via
backend/nitrado_whitelist.py (même verrou anti-race que la whitelist).

Réglages (guild_settings) :
    no_pvp_mode                 "1" = tout kill PVP bannit le tueur
    no_pvp_schedule             JSON {"enabled": true, "slots": [{"days": [0..6],
                                "start": "HH:MM", "end": "HH:MM"}]} — sans plage
                                active, le NO PVP s'applique 24 h/24
    no_pvp_exceptions           JSON liste de pseudos jamais bannis
    suicide_autoban             "1" = un suicide bannit le joueur
    suicide_autoban_exceptions  JSON liste de pseudos
    pending_bans                JSON [{"name", "reason", "since"}] — bans pas
                                encore écrits sur Nitrado (injoignable)

Les horaires sont ceux de l'horloge de la machine qui fait tourner le bot.
"""

import json
import logging
from datetime import datetime
from typing import Optional

import discord

from backend import database as db
from backend import nitrado_whitelist as nitrado
from backend.models import KillEvent, ServerConfig

logger = logging.getLogger("killfeed.moderation")

DAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

RULES = {
    "nopvp":   {"toggle": "no_pvp_mode",     "exceptions": "no_pvp_exceptions",          "label": "NO PVP"},
    "suicide": {"toggle": "suicide_autoban", "exceptions": "suicide_autoban_exceptions", "label": "Suicide"},
}


# ─── Réglages ─────────────────────────────────────────────────────────────────

def get_exceptions(guild_id: str, rule: str) -> list[str]:
    try:
        data = json.loads(db.get_setting(guild_id, RULES[rule]["exceptions"], "[]"))
        return [str(x) for x in data] if isinstance(data, list) else []
    except Exception:
        return []


def set_exceptions(guild_id: str, rule: str, names: list[str]) -> None:
    db.set_setting(guild_id, RULES[rule]["exceptions"], json.dumps(names, ensure_ascii=False))


def is_exempt(guild_id: str, rule: str, player: str) -> bool:
    needle = player.strip().lower()
    return any(n.strip().lower() == needle for n in get_exceptions(guild_id, rule))


def get_schedule(guild_id: str) -> dict:
    try:
        sched = json.loads(db.get_setting(guild_id, "no_pvp_schedule", "") or "{}")
        if isinstance(sched, dict):
            sched.setdefault("enabled", False)
            sched.setdefault("slots", [])
            return sched
    except Exception:
        pass
    return {"enabled": False, "slots": []}


def set_schedule(guild_id: str, sched: dict) -> None:
    db.set_setting(guild_id, "no_pvp_schedule", json.dumps(sched))


def parse_hm(value: str, end_of_day: bool = False) -> int:
    """'08:00' → 480 minutes ; -1 si invalide.

    end_of_day : accepte '24:00' (= 1440), pour une fin de plage « jusqu'à minuit ».
    """
    try:
        h, m = value.strip().lower().replace("h", ":").split(":")
        h, m = int(h), int(m or 0)
        if end_of_day and h == 24 and m == 0:
            return 1440
        return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else -1
    except Exception:
        return -1


def parse_days(value: str) -> Optional[list[int]]:
    """'tous', 'semaine', 'week-end', 'lun,mer,ven' ou 'lun-ven' → [0..6]."""
    v = value.strip().lower().replace(" ", "")
    if v in ("tous", "tout", "", "7/7"):
        return list(range(7))
    if v in ("semaine", "lun-ven"):
        return [0, 1, 2, 3, 4]
    if v in ("week-end", "weekend", "we", "sam-dim"):
        return [5, 6]
    prefixes = [d[:3] for d in DAY_NAMES]

    def _idx(token: str) -> int:
        return prefixes.index(token[:3]) if token[:3] in prefixes else -1

    days: set[int] = set()
    for part in v.split(","):
        if "-" in part:
            a, b = (_idx(x) for x in part.split("-", 1))
            if a < 0 or b < 0:
                return None
            i = a
            while True:
                days.add(i)
                if i == b:
                    break
                i = (i + 1) % 7
        else:
            i = _idx(part)
            if i < 0:
                return None
            days.add(i)
    return sorted(days)


def describe_days(days: list[int]) -> str:
    if sorted(days) == list(range(7)):
        return "tous les jours"
    if sorted(days) == [0, 1, 2, 3, 4]:
        return "en semaine"
    if sorted(days) == [5, 6]:
        return "le week-end"
    return ", ".join(DAY_NAMES[d] for d in sorted(days))


def nopvp_active_now(guild_id: str, now: Optional[datetime] = None) -> bool:
    """Le NO PVP s'applique-t-il maintenant ? Sans plage active → 24 h/24.

    Décidé au moment du kill (robuste au redémarrage du bot). Une plage dont
    start > end franchit minuit (ex. 22:00 → 06:00).
    """
    sched = get_schedule(guild_id)
    if not sched.get("enabled") or not sched.get("slots"):
        return True
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    today, yesterday = now.weekday(), (now.weekday() - 1) % 7
    for slot in sched["slots"]:
        days  = slot.get("days") or []
        start = parse_hm(slot.get("start", "00:00"))
        end   = parse_hm(slot.get("end", "00:00"), end_of_day=True)
        if start < 0 or end < 0 or start == end:
            continue
        if start < end:
            if today in days and start <= cur < end:
                return True
        else:
            if today in days and cur >= start:
                return True
            if yesterday in days and cur < end:
                return True
    return False


# ─── Ban Nitrado ──────────────────────────────────────────────────────────────

async def _apply_ban(guild_id: str, player: str) -> bool:
    ok = await nitrado.add_to_banlist(player)
    if not ok:
        return False
    try:
        from backend import whitelist as wl
        await wl.remove_from_nitrado(guild_id, player)
    except Exception as e:
        logger.warning(f"[{guild_id}] Retrait whitelist après ban {player} : {e}")
    return True


async def ban_player(guild_id: str, player: str, reason: str = "") -> bool:
    """Ajoute à la banlist Nitrado et retire de la whitelist (+ table players).

    Un joueur déjà connecté peut rester en jeu jusqu'au redémarrage du serveur
    (Nitrado applique ses réglages au démarrage). Nitrado injoignable → le ban est mis en attente (pending_bans) et retenté
    par retry_pending_bans() ; retourne alors False.
    """
    if await _apply_ban(guild_id, player):
        return True
    add_pending(guild_id, player, reason)
    return False


async def unban_player(guild_id: str, player: str) -> tuple[bool, bool, bool]:
    """(dans_banlist_nitrado, écriture_ok, ban_en_attente_annulé)."""
    was_pending = remove_pending(guild_id, player)
    found, ok = await nitrado.remove_from_banlist(player)
    return found, ok, was_pending


# ─── Bans en attente (Nitrado injoignable) ────────────────────────────────────

def get_pending(guild_id: str) -> list[dict]:
    try:
        data = json.loads(db.get_setting(guild_id, "pending_bans", "[]") or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_pending(guild_id: str, items: list[dict]) -> None:
    db.set_setting(guild_id, "pending_bans", json.dumps(items, ensure_ascii=False))


def add_pending(guild_id: str, player: str, reason: str = "") -> None:
    items = [i for i in get_pending(guild_id) if i.get("name", "").lower() != player.lower()]
    items.append({"name": player, "reason": reason,
                  "since": datetime.now().isoformat(timespec="minutes")})
    _save_pending(guild_id, items)
    logger.warning(f"[{guild_id}] Ban de {player} mis en attente (Nitrado injoignable)")


def remove_pending(guild_id: str, player: str) -> bool:
    items = get_pending(guild_id)
    kept = [i for i in items if i.get("name", "").lower() != player.lower()]
    if len(kept) != len(items):
        _save_pending(guild_id, kept)
        return True
    return False


async def retry_pending_bans(bot, cfg: ServerConfig) -> None:
    """Réessaie les bans en attente ; s'arrête au premier échec (Nitrado encore KO)."""
    for item in get_pending(cfg.guild_id):
        name = item.get("name", "")
        if not await _apply_ban(cfg.guild_id, name):
            return
        remove_pending(cfg.guild_id, name)
        logger.info(f"[{cfg.guild_id}] Ban en attente appliqué : {name}")
        if bot:
            from bot.extra_channels import send_alert
            await send_alert(bot, cfg, discord.Embed(
                title="✅ Ban en attente appliqué",
                description=f"Nitrado répond à nouveau : **{name}** est maintenant banni "
                            f"(demandé le {item.get('since', '?').replace('T', ' à ')}).",
                color=0x22C55E,
            ))


# ─── Auto-ban au fil des événements ADM ───────────────────────────────────────

async def check_auto_ban(bot, cfg: ServerConfig, kill: KillEvent) -> None:
    """Appelé par le poller pour chaque kill PVP / suicide nouvellement enregistré."""
    gid = cfg.guild_id
    try:
        if kill.kill_type.value == "pvp" and kill.killer_name \
                and kill.killer_name != kill.victim_name \
                and db.get_setting(gid, "no_pvp_mode", "0") == "1" \
                and nopvp_active_now(gid) \
                and not is_exempt(gid, "nopvp", kill.killer_name):
            await _auto_ban(bot, cfg, kill.killer_name, "NO PVP", [
                ("Victime", kill.victim_name),
                ("Arme", kill.cause or ""),
            ])
        elif kill.kill_type.value == "suicide" and kill.victim_name \
                and db.get_setting(gid, "suicide_autoban", "0") == "1" \
                and not is_exempt(gid, "suicide", kill.victim_name):
            await _auto_ban(bot, cfg, kill.victim_name, "Suicide", [
                ("Cause", kill.cause or ""),
            ])
    except Exception as e:
        logger.error(f"[{gid}] Auto-ban : {e}")


async def _auto_ban(bot, cfg: ServerConfig, player: str, label: str, fields: list[tuple[str, str]]):
    ok = await ban_player(cfg.guild_id, player, reason=f"Auto-ban {label}")
    logger.info(f"[{cfg.guild_id}] AUTO-BAN {label} — {player} : {'OK' if ok else 'EN ATTENTE'}")
    if not bot:
        return
    from bot.extra_channels import send_alert
    embed = discord.Embed(
        title=f"🚫 Ban automatique — {label}" if ok else f"⏳ Ban automatique en attente — {label}",
        description=(
            f"**{player}** a été ajouté à la banlist Nitrado et retiré de la whitelist."
            if ok else
            f"Nitrado ne répond pas : le ban de **{player}** est mis en attente et "
            "retenté toutes les 5 minutes (visible dans `/bans`)."
        ),
        color=0xEF4444 if ok else 0xF59E0B,
    )
    for name, value in fields:
        if value:
            embed.add_field(name=name, value=f"`{value}`", inline=True)
    embed.add_field(name="Annuler", value=f"`/unban {player}`", inline=False)
    await send_alert(bot, cfg, embed)
