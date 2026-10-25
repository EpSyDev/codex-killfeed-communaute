"""
bot/tasks/maintenance.py
Tâches lentes, vérifiées toutes les 10 minutes :

  • sauvegarde quotidienne de la base SQLite dans data/backups/
    (API backup de SQLite : copie cohérente même pendant l'écriture),
    7 dernières conservées ;
  • vérification de version : compare le fichier VERSION à la dernière
    release GitHub de UPDATE_REPO, une fois par jour, et prévient #alertes
    une seule fois par nouvelle version ;
  • classement hebdomadaire publié le dimanche à 20 h (heure de la machine)
    dans #statistiques.
"""

import asyncio
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord
import httpx

from backend import database as db
from bot.config import install_root, load_config
from bot.extra_channels import ensure_channel, send_alert
from bot.leaderboard import build_top_embed

logger = logging.getLogger("killfeed.maintenance")

# Dépôt GitHub qui publie les versions (« propriétaire/dépôt »).
# Vide = vérification désactivée.
UPDATE_REPO   = "EpSyDev/codex-killfeed-communaute"
BACKUP_KEEP   = 7
WEEKLY_DAY    = 6      # dimanche
WEEKLY_HOUR   = 20
TICK          = 600

# Dernier résultat de la vérification, lu par /diagnostic
latest_release: dict = {}


# ─── Version ──────────────────────────────────────────────────────────────────

def current_version() -> str:
    try:
        return (install_root() / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "inconnue"


def _vtuple(v: str) -> tuple:
    parts = []
    for p in v.lstrip("vV").split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def update_available() -> Optional[dict]:
    tag = latest_release.get("tag")
    if tag and current_version() != "inconnue" and _vtuple(tag) > _vtuple(current_version()):
        return latest_release
    return None


async def check_version() -> None:
    if not UPDATE_REPO:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json",
                         "User-Agent": "CodeX-KillFeed"},
            )
        if r.status_code != 200:
            logger.debug(f"[Version] GitHub HTTP {r.status_code}")
            return
        data = r.json()
        latest_release.update({
            "tag":     data.get("tag_name", ""),
            "url":     data.get("html_url", ""),
            "notes":   (data.get("body") or "")[:900],
            "checked": datetime.now().isoformat(timespec="minutes"),
        })
    except Exception as e:
        logger.debug(f"[Version] Vérification impossible : {e}")


async def _notify_update(bot) -> None:
    rel = update_available()
    if not rel:
        return
    for cfg in db.get_all_active_servers():
        if db.get_setting(cfg.guild_id, "update_notified", "") == rel["tag"]:
            continue
        db.set_setting(cfg.guild_id, "update_notified", rel["tag"])
        embed = discord.Embed(
            title=f"⬆️ Nouvelle version disponible : {rel['tag']}",
            description=(f"Version installée : **{current_version()}**\n"
                         f"[Télécharger la nouvelle version]({rel['url']})\n\n"
                         + (rel["notes"] or "")),
            color=0x3B82F6,
        )
        await send_alert(bot, cfg, embed)


# ─── Sauvegarde ───────────────────────────────────────────────────────────────

def backup_dir() -> Path:
    return load_config().data_dir / "backups"


def last_backup() -> Optional[Path]:
    files = sorted(backup_dir().glob("codex-kit-*.db"))
    return files[-1] if files else None


def backup_database() -> Optional[Path]:
    """Sauvegarde du jour si absente. Retourne le fichier créé, sinon None."""
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"codex-kit-{datetime.now():%Y-%m-%d}.db"
    if target.exists():
        return None
    tmp = target.with_suffix(".tmp")
    dst = sqlite3.connect(str(tmp))
    try:
        db.get_client()._conn.backup(dst)
    finally:
        dst.close()
    tmp.replace(target)
    for old in sorted(folder.glob("codex-kit-*.db"))[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)
    logger.info(f"[Sauvegarde] Base copiée : {target.name}")
    return target


# ─── Classement hebdomadaire ──────────────────────────────────────────────────

async def _weekly_top(bot) -> None:
    now = datetime.now()
    if now.weekday() != WEEKLY_DAY or now.hour < WEEKLY_HOUR:
        return
    week = now.strftime("%G-%V")
    from bot.discord_queue import enqueue
    for cfg in db.get_all_active_servers():
        if db.get_setting(cfg.guild_id, "weekly_top_last", "") == week:
            continue
        db.set_setting(cfg.guild_id, "weekly_top_last", week)
        embed = build_top_embed(cfg.guild_id, 7, title=f"🏆 Classement de la semaine — {cfg.server_name}")
        if not embed:
            continue
        ch = await ensure_channel(bot, cfg, "statistiques")
        if ch:
            await enqueue(ch, embed)


# ─── Boucle ───────────────────────────────────────────────────────────────────

async def run_maintenance(bot) -> None:
    await bot.wait_until_ready()
    last_version_check: Optional[str] = None
    while not bot.is_closed():
        try:
            backup_database()
        except Exception as e:
            logger.error(f"[Sauvegarde] Échec : {e}")

        today = datetime.now().strftime("%Y-%m-%d")
        if last_version_check != today:
            last_version_check = today
            await check_version()
            try:
                await _notify_update(bot)
            except Exception as e:
                logger.error(f"[Version] Notification : {e}")

        try:
            await _weekly_top(bot)
        except Exception as e:
            logger.error(f"[Classement] Publication : {e}")

        await asyncio.sleep(TICK)
