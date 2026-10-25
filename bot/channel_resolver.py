"""
bot/channel_resolver.py
Résolution robuste des salons Discord.
Stratégie : ID en cache → fetch API → recherche par nom → mise à jour DB.

Version kit single-tenant : une instance = un guild = un serveur DayZ,
donc plus de risque de collision entre salons homonymes de deux
serveurs DayZ différents dans la même guild — la recherche par nom
porte simplement sur toute la guild (pas de filtrage par catégorie).
"""

import logging
import discord
from backend import database as db

logger = logging.getLogger("killfeed.channel_resolver")


async def resolve_channel(
    bot: discord.Client,
    guild_id: str,
    channel_type: str,
    server_id: str = None,
) -> discord.TextChannel | None:
    """
    Retourne le salon Discord pour un type donné.
    1. Lit le channel_id en DB
    2. Essaie bot.get_channel (cache)
    3. Essaie bot.fetch_channel (API)
    4. Recherche par nom dans la guild (fallback si ID périmé)
    5. Met à jour la DB si un nouveau channel_id est trouvé
    """
    channel_id = db.get_channel(guild_id, channel_type, server_id=server_id)

    # ── Tentative par ID ──────────────────────────────────────────────────────
    if channel_id:
        ch = bot.get_channel(int(channel_id))
        if ch:
            return ch
        try:
            ch = await bot.fetch_channel(int(channel_id))
            return ch
        except (discord.NotFound, discord.Forbidden):
            logger.warning(
                f"[{guild_id}] channel_id {channel_id} ({channel_type}) "
                f"invalide — recherche par nom"
            )
        except Exception as e:
            logger.warning(f"[{guild_id}] fetch_channel {channel_id}: {e}")

    # ── Fallback : recherche par nom dans la guild ────────────────────────────
    guild = bot.get_guild(int(guild_id))
    if not guild:
        try:
            guild = await bot.fetch_guild(int(guild_id))
        except Exception:
            logger.error(f"[{guild_id}] Guild introuvable — impossible de résoudre {channel_type}")
            return None

    cfg       = db.CHANNEL_CONFIG.get(channel_type, {})
    emoji     = cfg.get("emoji", "")
    name_full = f"{emoji}・{channel_type}"         # ex: "💀・morts-pvp"

    # Single-tenant : une seule catégorie CodeX dans la guild, donc recherche
    # par nom directement sur toute la guild (pas de conflit possible).
    found = (discord.utils.get(guild.text_channels, name=name_full)
             or discord.utils.get(guild.text_channels, name=channel_type))

    if found:
        logger.info(
            f"[{guild_id}] Salon '{channel_type}' retrouvé par nom "
            f"(#{found.name}/{found.id}) — MAJ DB"
        )
        db.set_channel(guild_id, channel_type, str(found.id), server_id=server_id or "")
        return found

    logger.debug(f"[{guild_id}] Salon '{channel_type}' introuvable dans la guild")
    return None
