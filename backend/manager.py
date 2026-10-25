"""
PollerManager v3 — gère N pollers en parallèle, identifiés par server_id UUID.
Supporte plusieurs serveurs DayZ par guild Discord.

Version kit : le Live Embed (édition de l'embed PVP après coup avec des
stats de session) dépendait d'embed_themes.EmbedConfig — retiré avec le
dashboard SaaS, hors périmètre. build_kill_embed n'a plus de paramètre cfg.
"""

import asyncio
import logging
import discord
from typing import Optional
from backend.models import KillEvent, ServerConfig
from backend.poller import ServerPoller
from backend import database as db
from bot.embeds import build_kill_embed
from bot.discord_queue import enqueue

logger = logging.getLogger("killfeed.manager")


class PollerManager:
    def __init__(self, bot: discord.Client):
        self.bot      = bot
        # Clé = server_id UUID (stable même si guild change de config)
        self._pollers: dict[str, ServerPoller] = {}
        self._tasks:   dict[str, asyncio.Task] = {}

    def _key(self, config: ServerConfig) -> str:
        """Identifiant stable du poller — server_id si dispo, sinon guild_id."""
        return config.server_id or config.guild_id

    def get_poller(self, config: ServerConfig) -> Optional[ServerPoller]:
        return self._pollers.get(self._key(config))

    def is_running(self, config: ServerConfig) -> bool:
        task = self._tasks.get(self._key(config))
        return bool(task and not task.done())

    async def _on_kill(self, event: KillEvent, config: ServerConfig, channel_id: str, channel_type: str = ""):
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"[{config.guild_id}] Salon {channel_id} introuvable")
            return

        show_positions_pvp = db.get_setting(config.guild_id, "show_positions_pvp", "1") == "1"
        embed, icon_file = build_kill_embed(
            event, config.server_name, config.map_name,
            show_positions_pvp=show_positions_pvp,
            channel_type=channel_type,
        )

        await enqueue(channel, embed, icon_file)

    async def add_server(self, config: ServerConfig):
        key = self._key(config)
        if key in self._pollers:
            await self._stop_key(key)

        poller = ServerPoller(config, self._on_kill, bot=self.bot)
        self._pollers[key] = poller
        self._tasks[key]   = asyncio.create_task(poller.start())
        logger.info(f"[Manager] Poller ajouté → {config.server_name} "
                    f"(guild={config.guild_id}, server_id={config.server_id})")

    async def _stop_key(self, key: str):
        if key in self._pollers:
            await self._pollers[key].stop()
            del self._pollers[key]
        if key in self._tasks:
            self._tasks[key].cancel()
            del self._tasks[key]

    async def remove_server(self, guild_id: str, service_id: str = None):
        """Arrête le(s) poller(s) d'une guild. Si service_id fourni → un seul serveur."""
        if service_id:
            config = db.get_server(guild_id, service_id=service_id)
            if config:
                await self._stop_key(self._key(config))
        else:
            # Arrêter tous les pollers de cette guild
            to_stop = [k for k, p in self._pollers.items()
                       if p.config.guild_id == guild_id]
            for key in to_stop:
                await self._stop_key(key)

    async def start_all(self):
        servers = db.get_all_active_servers()
        for config in servers:
            await self.add_server(config)
        logger.info(f"[Manager] {len(servers)} poller(s) démarrés")
        return len(servers)
