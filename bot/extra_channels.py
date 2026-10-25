"""
bot/extra_channels.py
Salons créés à la demande par les fonctions automatiques (pas par /setup) :

    alertes       privé (admins)     serveur hors ligne, logs figés, bans auto,
                                     nouvelle version disponible
    annonces      public, lecture    comptes à rebours des redémarrages
    statistiques  public, lecture    classement hebdomadaire

« Public » volontairement : la catégorie /setup est masquée à @everyone, mais
des overwrites propres au salon le détachent de la catégorie — les joueurs
voient les annonces sans que l'admin ait à ouvrir quoi que ce soit.

Créés dans la catégorie du serveur au premier besoin. Un salon désactivé
via /salons (enabled=0) n'est jamais recréé automatiquement.
"""

import logging
from typing import Optional

import discord

from backend import database as db
from backend.database import CHANNEL_CONFIG
from backend.models import ServerConfig
from bot.channel_resolver import resolve_channel

logger = logging.getLogger("killfeed.extra_channels")

PRIVATE_CHANNELS   = {"alertes"}
READ_ONLY_CHANNELS = {"annonces", "statistiques"}


def channel_overwrites(guild: discord.Guild, ch_type: str) -> dict:
    """Permissions selon le type ; {} = héritées de la catégorie."""
    me = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                     embed_links=True, attach_files=True)
    if ch_type in PRIVATE_CHANNELS:
        return {guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: me}
    if ch_type in READ_ONLY_CHANNELS:
        return {guild.default_role: discord.PermissionOverwrite(send_messages=False), guild.me: me}
    return {}


async def ensure_channel(bot: discord.Client, cfg: ServerConfig, ch_type: str) -> Optional[discord.TextChannel]:
    """Salon existant, ou créé à la volée. None si désactivé ou impossible."""
    gid = cfg.guild_id
    existing = await resolve_channel(bot, gid, ch_type, server_id=cfg.server_id)
    if existing:
        return existing
    if db.is_channel_explicitly_disabled(gid, ch_type, cfg.server_id):
        return None

    guild = bot.get_guild(int(gid))
    if not guild:
        return None
    category = db.find_server_category(guild, cfg.server_name)
    ow = channel_overwrites(guild, ch_type)
    try:
        ch = await guild.create_text_channel(
            name=f"{CHANNEL_CONFIG[ch_type]['emoji']}・{ch_type}",
            category=category,
            **({"overwrites": ow} if ow else {}),   # {} rendrait le salon public
        )
    except discord.HTTPException as e:
        logger.warning(f"[{gid}] Création salon {ch_type} impossible : {e}")
        return None
    db.set_channel(gid, ch_type, str(ch.id), server_id=cfg.server_id or "")
    logger.info(f"[{gid}] Salon {ch_type} créé")
    return ch


async def send_alert(bot: discord.Client, cfg: ServerConfig, embed: discord.Embed) -> None:
    """Envoie un embed dans #alertes (créé au besoin). Silencieux si désactivé."""
    from bot.discord_queue import enqueue
    ch = await ensure_channel(bot, cfg, "alertes")
    if ch:
        embed.set_footer(text="CodeX KillFeed — /salons pour désactiver ce salon")
        await enqueue(ch, embed)
