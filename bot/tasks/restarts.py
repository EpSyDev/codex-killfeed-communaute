"""
bot/tasks/restarts.py
Redémarrages planifiés du serveur DayZ via l'API Nitrado, avec compte à rebours
dans #annonces (15 min, 5 min, 1 min, puis « redémarrage en cours »).

Réglages (guild_settings) :
    restart_schedule   JSON [{"time": "06:00", "days": [0..6]}, ...]
    restart_last       clé "AAAAMMJJHHMM" du dernier redémarrage exécuté
                       (persistée : un bot relancé pile à l'heure ne
                       redémarre pas le serveur deux fois)
    restart_last_ts    horodatage du dernier redémarrage lancé par le bot
                       (lu par server_watch pour taire ses alertes)

Les heures sont celles de l'horloge de la machine qui fait tourner le bot.
Un redémarrage immédiat (/restart maintenant) est gardé en mémoire seulement.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import discord
import httpx

from backend import database as db
from backend.models import ServerConfig
from bot.extra_channels import ensure_channel, send_alert

logger = logging.getLogger("killfeed.restarts")

NITRADO_API = "https://api.nitrado.net"
WARN_STAGES = (15, 5, 1)    # minutes avant le redémarrage
TICK        = 20            # secondes entre deux vérifications
WINDOW      = 120           # tolérance si la boucle a pris du retard

# Redémarrages ponctuels en attente : {guild_id: datetime}
_oneoff: dict[str, datetime] = {}
# Annonces déjà envoyées : {"guild:AAAAMMJJHHMM:stage"}
_fired: set[str] = set()


# ─── Réglages ─────────────────────────────────────────────────────────────────

def get_schedule(guild_id: str) -> list[dict]:
    try:
        data = json.loads(db.get_setting(guild_id, "restart_schedule", "[]") or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def set_schedule(guild_id: str, slots: list[dict]) -> None:
    slots = sorted(slots, key=lambda s: s.get("time", ""))
    db.set_setting(guild_id, "restart_schedule", json.dumps(slots))


def schedule_oneoff(guild_id: str, when: datetime) -> None:
    _oneoff[guild_id] = when


def cancel_oneoff(guild_id: str) -> bool:
    return _oneoff.pop(guild_id, None) is not None


def next_restarts(guild_id: str, now: Optional[datetime] = None, limit: int = 3) -> list[datetime]:
    now = now or datetime.now()
    out = []
    if guild_id in _oneoff:
        out.append(_oneoff[guild_id])
    for day in range(8):
        base = (now + timedelta(days=day)).date()
        for slot in get_schedule(guild_id):
            try:
                h, m = (int(x) for x in slot["time"].split(":"))
            except Exception:
                continue
            target = datetime(base.year, base.month, base.day, h, m)
            if target > now and target.weekday() in slot.get("days", []):
                out.append(target)
    return sorted(set(out))[:limit]


# ─── Nitrado ──────────────────────────────────────────────────────────────────

async def nitrado_restart(cfg: ServerConfig) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{NITRADO_API}/services/{cfg.service_id}/gameservers/restart",
                headers={"Authorization": f"Bearer {cfg.nitrado_token}"},
                data={"message": "Redémarrage planifié (CodeX KillFeed)"},
            )
        if r.status_code == 200:
            return True, ""
        return False, f"HTTP {r.status_code} — {r.text[:200]}"
    except Exception as e:
        return False, str(e)


# ─── Boucle ───────────────────────────────────────────────────────────────────

def _pending_targets(guild_id: str, now: datetime) -> list[datetime]:
    """Redémarrages dans les 16 prochaines minutes (ou tout juste passés)."""
    horizon = now + timedelta(minutes=max(WARN_STAGES) + 1)
    targets = [t for t in next_restarts(guild_id, now - timedelta(seconds=WINDOW), limit=10)
               if t <= horizon]
    return targets


async def _announce(bot, cfg: ServerConfig, embed: discord.Embed) -> None:
    from bot.discord_queue import enqueue
    ch = await ensure_channel(bot, cfg, "annonces")
    if ch:
        await enqueue(ch, embed)


async def _tick(bot, cfg: ServerConfig) -> None:
    gid = cfg.guild_id
    now = datetime.now()
    # Ponctuel raté (bot arrêté à l'heure prévue) : on l'oublie
    if gid in _oneoff and _oneoff[gid] < now - timedelta(seconds=WINDOW):
        _oneoff.pop(gid, None)
    for target in _pending_targets(gid, now):
        key = target.strftime("%Y%m%d%H%M")
        for stage in WARN_STAGES:
            moment = target - timedelta(minutes=stage)
            fkey = f"{gid}:{key}:{stage}"
            if moment <= now < moment + timedelta(seconds=WINDOW) and fkey not in _fired:
                _fired.add(fkey)
                await _announce(bot, cfg, discord.Embed(
                    title=f"⏳ Redémarrage du serveur dans {stage} minute{'s' if stage > 1 else ''}",
                    description=f"**{cfg.server_name}** redémarre à **{target:%H:%M}**. "
                                "Mets-toi à l'abri et déconnecte-toi proprement.",
                    color=0xF59E0B if stage > 1 else 0xEF4444,
                ))

        if target <= now < target + timedelta(seconds=WINDOW) \
                and db.get_setting(gid, "restart_last", "") != key:
            db.set_setting(gid, "restart_last", key)
            db.set_setting(gid, "restart_last_ts", str(time.time()))
            if _oneoff.get(gid) == target:
                _oneoff.pop(gid, None)
            ok, err = await nitrado_restart(cfg)
            logger.info(f"[{gid}] Redémarrage {key} : {'OK' if ok else err}")
            if ok:
                await _announce(bot, cfg, discord.Embed(
                    title="🔄 Redémarrage en cours",
                    description="Le serveur revient dans quelques minutes.",
                    color=0x3B82F6,
                ))
            else:
                await send_alert(bot, cfg, discord.Embed(
                    title="⚠️ Redémarrage planifié échoué",
                    description=f"Nitrado a refusé le redémarrage de {target:%H:%M} : {err}",
                    color=0xF59E0B,
                ))

    # Ménage des annonces vieilles de plus d'un jour
    if len(_fired) > 200:
        cutoff = (now - timedelta(days=1)).strftime("%Y%m%d%H%M")
        for k in [k for k in _fired if k.split(":")[1] < cutoff]:
            _fired.discard(k)


async def run_restart_scheduler(bot) -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        for cfg in db.get_all_active_servers():
            try:
                await _tick(bot, cfg)
            except Exception as e:
                logger.error(f"[{cfg.guild_id}] Planificateur redémarrages : {e}")
        await asyncio.sleep(TICK)
