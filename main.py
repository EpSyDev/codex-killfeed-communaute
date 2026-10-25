"""
CodeX KillFeed — Point d'entrée principal (kit single-tenant)

Version kit : retiré tout ce qui dépendait des tâches dashboard SaaS
(cartes, rapports, agrégation, heatmap, monitoring infra) et des
fonctionnalités hors périmètre (panels boutons, demandes par
DM, cache d'icônes CDN). Voir l'historique git avant ce commit pour le
code original de codex-killfeed.

Toute la configuration passe par bot/config.py::load_config() — source
unique de vérité (.env local). Plus de variables lues à la volée ici.
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from bot.config import install_root, load_config
from bot.predeps import install_pending_deps

load_dotenv()
# Avant tout import de discord.py & co : dépendances d'une mise à jour /maj
install_pending_deps(install_root())

import discord
from discord.ext import commands

from bot.discord_queue import run_sender_worker

CONFIG = load_config()

# ─── Logging ──────────────────────────────────────────────────────────────────
# Le fichier fait foi en UTF-8 (c'est lui que le wizard ouvre en cas de souci) ;
# la console d'un cmd.exe par défaut n'est souvent pas en UTF-8 et mangle les
# accents — errors="replace" évite un crash sur l'écriture, pas plus.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s — %(message)s"
_log_dir = CONFIG.data_dir / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, CONFIG.log_level, logging.INFO),
    format=_LOG_FORMAT,
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_dir / "bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("killfeed")

# ─── Imports internes ─────────────────────────────────────────────────────────

from backend import database as db
from backend.manager import PollerManager
from bot.commands import KillFeedCommands
from bot.commands_extra import ExtraCommands
from bot.tasks.server_watch import run_server_watch
from bot.tasks.restarts import run_restart_scheduler
from bot.tasks.maintenance import run_maintenance, current_version
from bot.whitelist_request import WhitelistRequestView, handle_admin_interaction, auto_remove_on_leave

# ─── Bot ──────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members          = True   # Server Members Intent
intents.presences        = False  # Presence Intent inutilisé — économie RAM

bot     = commands.Bot(command_prefix="!", intents=intents)
manager = PollerManager(bot)
bot._codex_manager = manager
_ready_called = False

# ─── Supervision des tâches de fond ──────────────────────────────────────────

async def _supervised(name: str, factory, bot):
    """Lance une tâche et la relance automatiquement si elle crash.
    factory : callable sans argument qui retourne une coroutine."""
    while not bot.is_closed():
        try:
            await factory()
            logger.warning(f"[Supervisor] Tâche '{name}' terminée de façon inattendue — relance dans 10s")
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Supervisor] Tâche '{name}' crashée : {e} — relance dans 30s")
            await asyncio.sleep(30)

# ─── Tâche de purge nocturne ──────────────────────────────────────────────────

async def _nightly_purge():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(86400)
        try:
            total = db.purge_all_guilds()
            logger.info(f"[Bot] Purge nocturne — {total} events supprimés")
        except Exception as e:
            logger.error(f"[Bot] Erreur purge: {e}")

# ─── Heartbeat — signal de vie du bot ─────────────────────────────────────────

BOT_VERSION = current_version()

async def _heartbeat():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            db.write_heartbeat(
                bot_version=BOT_VERSION,
                guilds_count=len(bot.guilds),
                active_servers=len(db.get_all_active_servers()),
            )
        except Exception as e:
            logger.warning(f"[Bot] Heartbeat échec : {e}")
        await asyncio.sleep(30)

# ─── Sync salons au démarrage ─────────────────────────────────────────────────

async def _provision_extra_channels():
    """Provisionne pour les guilds existantes le salon texte 'logs-adm' s'il
    a été ajouté après leur setup initial."""
    active_servers = db.get_all_active_servers()
    by_guild: dict[str, list] = {}
    for cfg in active_servers:
        by_guild.setdefault(cfg.guild_id, []).append(cfg)

    for gid, servers in by_guild.items():
        guild = bot.get_guild(int(gid))
        if not guild:
            continue
        for cfg in servers:
            # Catégorie DU serveur (multi-serveur sûr) — plus de match large sur le 1er '📡 CodeX'
            category = db.find_server_category(guild, getattr(cfg, "server_name", None))
            if not category:
                continue

            # ── Salon texte logs-adm ──────────────────────────────────────────
            # Point 5 : idem, on respecte un logs-adm désactivé volontairement.
            ch_id = db.get_channel(gid, "logs-adm", server_id=cfg.server_id)
            if (not (ch_id and guild.get_channel(int(ch_id)))) \
               and not db.is_channel_explicitly_disabled(gid, "logs-adm", cfg.server_id):
                text_overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    guild.me: discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, attach_files=True, embed_links=True,
                    ),
                }
                try:
                    tc = await guild.create_text_channel(
                        name="📄・logs-adm", category=category, overwrites=text_overwrites
                    )
                    db.set_channel(gid, "logs-adm", str(tc.id), server_id=cfg.server_id or "")
                    logger.info(f"[Bot] Salon logs-adm créé pour guild {gid} ({cfg.server_id})")
                except Exception as e:
                    logger.warning(f"[Bot] Impossible de créer logs-adm pour guild {gid}: {e}")

# ─── Events ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    global _ready_called
    logger.info(f"[Bot] Connecté en tant que {bot.user} (ID: {bot.user.id})")
    if _ready_called:
        logger.info("[Bot] Reconnexion — sync ignorée")
        return
    _ready_called = True

    # 1. Migrations DB
    db.run_migrations()
    logger.info("[Bot] DB à jour ✅")

    # 1.bis Views persistantes
    bot.add_view(WhitelistRequestView())
    logger.info("[Bot] Views persistantes enregistrées ✅")

    # 1.ter Réconciliation des salons par catégorie Discord (source de vérité).
    # Corrige les generic legacy ET les lignes mal attribuées entre serveurs.
    active_servers = db.get_all_active_servers()
    by_guild: dict[str, list] = {}
    for cfg in active_servers:
        by_guild.setdefault(cfg.guild_id, []).append(cfg)
    for gid, gservers in by_guild.items():
        g = bot.get_guild(int(gid))
        if not g:
            continue
        try:
            db.reconcile_channels_to_categories(g, gid, gservers)
        except Exception as e:
            logger.error(f"[Bot] Réconciliation salons {gid}: {e}")

    # 1.quater Provision salons additionnels (serverstate + logs-adm) pour guilds existantes
    try:
        await _provision_extra_channels()
        logger.info("[Bot] Provision salons additionnels ✅")
    except Exception as e:
        logger.warning(f"[Bot] Provision salons additionnels échouée : {e}")

    # 2. Pollers
    if active_servers:
        await manager.start_all()
        logger.info(f"[Bot] {len(active_servers)} serveur(s) relancé(s)")
    else:
        logger.info("[Bot] Aucun serveur en DB — utilise /setup pour commencer")

    # 4. Sync slash commands
    try:
        # Purge les éventuelles commandes guild-spécifiques résiduelles (cause des doublons)
        for guild in bot.guilds:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
        synced = await bot.tree.sync()
        logger.info(f"[Bot] {len(synced)} commandes sync (global), guild-commands purgées")
    except Exception as e:
        logger.warning(f"[Bot] Erreur sync globale : {e}")

    # 5. Tâches de fond supervisées (restart auto si crash)
    _TASKS = [
        ("discord_queue",  lambda: run_sender_worker()),
        ("heartbeat",      lambda: _heartbeat()),
        ("nightly_purge",  lambda: _nightly_purge()),
        ("server_watch",   lambda: run_server_watch(bot, manager)),
        ("restarts",       lambda: run_restart_scheduler(bot)),
        ("maintenance",    lambda: run_maintenance(bot)),
    ]
    for name, factory in _TASKS:
        bot.loop.create_task(_supervised(name, factory, bot))
    # Reset nickname partout où un admin aurait renommé avant la protection
    for guild in bot.guilds:
        me = guild.me
        if me and me.nick is not None:
            try:
                await me.edit(nick=None)
                logger.info(f"[Bot] Nickname réinitialisé dans {guild.name}")
            except discord.Forbidden:
                pass

    logger.info("[Bot] ✅ Prêt — Journal du Survivant v2 actif (récap 22h UTC)")


@bot.event
async def on_member_remove(member: discord.Member):
    """Retire automatiquement un joueur de la whitelist quand il quitte le Discord."""
    guild_id   = str(member.guild.id)
    discord_id = str(member.id)
    try:
        await auto_remove_on_leave(bot, guild_id, discord_id, member.guild, member.display_name)
    except Exception as e:
        logger.error(f"[Bot] on_member_remove error: {e}")


@bot.event
async def on_guild_remove(guild: discord.Guild):
    guild_id = str(guild.id)
    await manager.remove_server(guild_id)
    db.delete_guild_completely(guild_id)
    logger.info(f"[Bot] Retiré de {guild.name} ({guild_id}) → données supprimées")


@bot.event
async def on_interaction(interaction: discord.Interaction):
    """Gère les boutons admin de la whitelist publique (custom_id dynamiques)."""
    try:
        await handle_admin_interaction(interaction)
    except Exception as e:
        logger.error(f"[Bot] on_interaction handler error: {e}")


@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if after.id != bot.user.id:
        return
    if before.nick == after.nick:
        return
    if after.nick is not None:
        try:
            await after.edit(nick=None)
            logger.debug(f"[Bot] Nickname forcé sur None dans {after.guild.name}")
        except discord.Forbidden:
            pass

# ─── Lancement ────────────────────────────────────────────────────────────────

async def main():
    async with bot:
        await bot.add_cog(KillFeedCommands(bot, manager))
        await bot.add_cog(ExtraCommands(bot))
        if not CONFIG.discord_token:
            raise RuntimeError("DISCORD_TOKEN manquant dans le .env")
        await bot.start(CONFIG.discord_token)

if __name__ == "__main__":
    # discord.py/aiohttp laissent parfois un thread non-daemon vivant après un
    # échec de login (compilé en .exe, jamais observé en `python main.py` direct)
    # — le process ne se terminait jamais tout seul, ce qui empêche NSSM de
    # détecter le crash et de redémarrer le service. os._exit() force la sortie
    # une fois qu'il n'y a plus rien à sauver.
    try:
        asyncio.run(main())
    except discord.LoginFailure:
        logger.critical("[Bot] Token Discord invalide — vérifie DISCORD_TOKEN dans le .env")
        os._exit(1)
    except Exception:
        logger.critical("[Bot] Erreur fatale au démarrage", exc_info=True)
        os._exit(1)