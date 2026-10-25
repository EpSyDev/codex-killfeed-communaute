"""
Queue centralisée pour les posts Discord.
Évite les rate limits (429) quand plusieurs pollers postent simultanément.
Supporte un Future optionnel pour récupérer le message envoyé (Live Embed).
"""
import asyncio
import logging
from typing import Optional

import discord

logger = logging.getLogger("killfeed.queue")

_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
_SEND_DELAY = 0.3  # ~3 msg/s — sous la limite Discord (50 req/s global, 5/5s par channel)


async def enqueue(
    channel: discord.TextChannel,
    embed: discord.Embed,
    file: Optional[discord.File] = None,
    result_future: Optional[asyncio.Future] = None,
) -> None:
    if _queue.full():
        logger.warning(
            f"[Queue] File pleine (500 items) — message ignoré (channel={channel.id})"
        )
        if result_future and not result_future.done():
            result_future.set_result(None)
        return
    await _queue.put((channel, embed, file, result_future))


async def run_sender_worker() -> None:
    """Worker unique qui consomme la queue et poste sur Discord à débit contrôlé."""
    logger.info("[Queue] Worker démarré")
    while True:
        channel, embed, file, result_future = await _queue.get()
        message = None
        try:
            if file:
                message = await channel.send(embed=embed, file=file)
            else:
                message = await channel.send(embed=embed)
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, "retry_after", 1.0)
                logger.warning(
                    f"[Queue] Rate limit 429 — pause {retry_after:.1f}s (channel={channel.id})"
                )
                await asyncio.sleep(retry_after)
            else:
                logger.error(f"[Queue] Erreur Discord {e.status}: {e.text}")
        except Exception as e:
            logger.error(f"[Queue] Erreur inattendue: {e}")
        finally:
            _queue.task_done()
            if result_future and not result_future.done():
                result_future.set_result(message)
        await asyncio.sleep(_SEND_DELAY)
