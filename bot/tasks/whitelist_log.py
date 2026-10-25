"""
bot/tasks/whitelist_log.py
Envoie un embed dans le salon #logs-whitelist à chaque action whitelist.
Le salon est créé automatiquement s'il n'existe pas dans CHANNEL_CONFIG.
"""

import discord
import logging
from datetime import datetime
from bot.channel_resolver import resolve_channel

logger = logging.getLogger("killfeed.whitelist_log")

CHANNEL_TYPE = "logs-whitelist"


async def send_whitelist_log(
    bot:          discord.Client,
    guild_id:     str,
    action:       str,          # "add" | "remove" | "ban"
    psn_id:       str,
    discord_id:   str  = "",
    discord_name: str  = "",
    done_by:      str  = "",
    reason:       str  = "",
    server_id:    str  = None,
):
    """
    Envoie un embed dans le #logs-whitelist DU SERVEUR (server_id).
    Appelé depuis l'API via une tâche asyncio ou depuis le bot directement.
    """
    channel = await resolve_channel(bot, guild_id, CHANNEL_TYPE, server_id=server_id)
    if not channel:
        return

    if action == "add":
        color = 0x34d399  # vert
        title = "✅ Joueur whitelisté"
        desc  = f"Lien PSN ↔ Discord établi — joueur autorisé sur le serveur."
    elif action == "remove":
        color = 0xfbbf24  # jaune
        title = "🔓 Joueur retiré"
        desc  = f"Le joueur a été retiré de la whitelist."
    elif action == "ban":
        color = 0xef4444  # rouge
        title = "🚫 Joueur banni"
        desc  = reason or "Aucune raison précisée."
    else:
        return

    embed = discord.Embed(title=title, description=desc, color=color)
    embed.add_field(name="🎮 PSN ID",      value=f"`{psn_id}`",    inline=True)
    if discord_id:
        dc_display = f"{discord_name} (`{discord_id}`)" if discord_name else f"`{discord_id}`"
        embed.add_field(name="💬 Discord", value=dc_display,        inline=True)
    if done_by:
        embed.add_field(name="👤 Par",     value=f"<@{done_by}>",   inline=True)
    embed.set_footer(text="CodeX KillFeed · Whitelist unifiée")
    embed.timestamp = datetime.utcnow()

    try:
        await channel.send(embed=embed)
    except Exception as e:
        logger.error(f"[WhitelistLog] Erreur envoi embed: {e}")
