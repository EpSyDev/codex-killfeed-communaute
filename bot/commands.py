"""
Commandes Discord — CodeX KillFeed v5
Whitelist unifiée PSN ↔ Discord + embed #logs-whitelist
"""

import discord
from discord.ext import commands
from discord import app_commands
import httpx
import logging
import io
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.models import ServerConfig, CHANNEL_MAP
from backend import database as db
from backend import whitelist as wl
from backend.database import CHANNEL_CONFIG
from bot.config import load_config
from bot.embeds import build_setup_embed, build_status_embed
from backend.manager import PollerManager
from bot.channel_resolver import resolve_channel
from bot.extra_channels import channel_overwrites

logger = logging.getLogger("killfeed.commands")

NITRADO_API = "https://api.nitrado.net"


# ─── Helpers Nitrado ──────────────────────────────────────────────────────────

async def _fetch_dayz_servers(token: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{NITRADO_API}/services",
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        services = r.json().get("data", {}).get("services", [])
        servers  = []
        for s in services:
            details = await client.get(
                f"{NITRADO_API}/services/{s['id']}/gameservers",
                headers={"Authorization": f"Bearer {token}"},
            )
            if details.status_code != 200:
                continue
            gs   = details.json().get("data", {}).get("gameserver", {})
            game = gs.get("game", "").lower()
            if game not in ("dayzps", "dayzxb"):
                continue
            servers.append({
                "id":       s["id"],
                "name":     gs.get("settings", {}).get("config", {}).get("hostname") or f"Serveur {s['id']}",
                "game":     game,
                "map":      gs.get("settings", {}).get("config", {}).get("map", "unknown"),
                "username": gs.get("username", ""),
            })
        return servers


# ─── Views setup ─────────────────────────────────────────────────────────────

class ServerSelectView(discord.ui.View):
    def __init__(self, servers, token, guild, interaction, manager, role_whitelist=None):
        super().__init__(timeout=120)
        self.token          = token
        self.guild          = guild
        self.manager        = manager
        self.role_whitelist = role_whitelist
        options = [
            discord.SelectOption(
                label=s["name"][:90],
                description=f"ID: {s['id']} · {s['game'].upper()} · {s['map']}",
                value=str(s["id"]),
            ) for s in servers[:25]
        ]
        select = discord.ui.Select(placeholder="Sélectionne ton serveur DayZ...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction):
        service_id = interaction.data["values"][0]
        await interaction.response.defer(ephemeral=True)
        await _run_setup(interaction, self.token, service_id, self.guild, self.manager,
                         role_whitelist=self.role_whitelist)


class FilterView(discord.ui.View):
    def __init__(self, guild_id, current_consciousness, current_suicides, current_burials, current_positions_pvp):
        super().__init__(timeout=120)
        for label, key, val, cur, row in [
            ("Activer conscience (PVE)",    "show_consciousness",  "1", current_consciousness,  0),
            ("Désactiver conscience (PVE)", "show_consciousness",  "0", current_consciousness,  0),
            ("Activer suicides",            "show_suicides",       "1", current_suicides,       1),
            ("Désactiver suicides",         "show_suicides",       "0", current_suicides,       1),
            ("Activer enterrements",        "show_burials",        "1", current_burials,         2),
            ("Désactiver enterrements",     "show_burials",        "0", current_burials,         2),
            ("Afficher positions (PVP)",    "show_positions_pvp",  "1", current_positions_pvp,  3),
            ("Masquer positions (PVP)",     "show_positions_pvp",  "0", current_positions_pvp,  3),
        ]:
            style = discord.ButtonStyle.success if val == "1" else discord.ButtonStyle.danger
            self.add_item(_FilterButton(label=label, style=style, setting_key=key,
                                        new_value=val, guild_id=guild_id,
                                        disabled=(cur == val), row=row))


class _FilterButton(discord.ui.Button):
    def __init__(self, setting_key, new_value, guild_id, **kwargs):
        super().__init__(**kwargs)
        self.setting_key = setting_key
        self.new_value   = new_value
        self.guild_id    = guild_id

    async def callback(self, interaction):
        db.set_setting(self.guild_id, self.setting_key, self.new_value)
        await interaction.response.send_message("✅ Paramètre mis à jour.", ephemeral=True)


# ─── View : sélection serveur (réutilisable) ─────────────────────────────────

class _ServerPickView(discord.ui.View):
    """Affiche un select Discord pour choisir parmi plusieurs serveurs configurés."""
    def __init__(self, servers: list):
        super().__init__(timeout=60)
        self.choice = None  # server_id UUID choisi
        options = [
            discord.SelectOption(
                label=s.server_name[:100],
                value=s.server_id,
                description=(s.server_alias or s.map_name or "")[:100],
            )
            for s in servers[:25]
        ]
        select = discord.ui.Select(placeholder="Choisir le serveur…", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        self.choice = interaction.data["values"][0]
        self.stop()
        await interaction.response.defer()


# ─── Setup auto ──────────────────────────────────────────────────────────────

async def _run_setup(interaction, token, service_id, guild, manager,
                     role_whitelist: discord.Role = None):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{NITRADO_API}/services/{service_id}/gameservers",
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            await interaction.followup.send("Erreur récupération infos serveur.", ephemeral=True)
            return
        gs = r.json()["data"]["gameserver"]
        logger.info(f"[Setup] gs keys: {list(gs.keys())}")
        logger.info(f"[Setup] gs name: {gs.get('name')} | settings: {gs.get('settings', {}).get('config', {})}")
        server_name = gs.get("settings", {}).get("config", {}).get("hostname") or f"Serveur {service_id}"
        # Map : dossier mission (FIABLE) d'abord, settings.config.map en secours.
        _mission    = gs.get("settings", {}).get("config", {}).get("mission", "")
        map_name    = (db.map_from_mission(_mission)
                       or gs.get("settings", {}).get("config", {}).get("map")
                       or "unknown")
        platform    = gs.get("game", "dayzps").lower()
        username    = gs.get("username", "")

    # ── Déjà configuré ? → update token uniquement, pas de recréation de salons ──
    existing = db.get_server(str(guild.id), service_id=str(service_id))
    if existing:
        db.save_server(
            guild_id=str(guild.id),
            nitrado_token=token,
            service_id=str(service_id),
            server_name=server_name,
            map_name=map_name,
            platform=platform,
            username=username,
            guild_name=guild.name,
            setup_by_id=str(interaction.user.id),
            setup_by_name=interaction.user.display_name,
        )
        config = db.get_server(str(guild.id), service_id=str(service_id))
        if config:
            await manager.add_server(config)
        await interaction.followup.send(
            embed=discord.Embed(
                title="🔄 Token mis à jour",
                description=(
                    f"**{server_name}** était déjà configuré.\n"
                    "Token actualisé, poller redémarré. Les salons existants sont conservés."
                ),
                color=discord.Color.from_rgb(230, 140, 20),
            ),
            ephemeral=True,
        )
        logger.info(f"[Setup] Guild {guild.id} — {server_name} — re-setup token uniquement")
        return

    # ── Nouveau serveur → création catégorie + salons ─────────────────────────
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            attach_files=True, embed_links=True,
        ),
    }
    if guild.owner:
        overwrites[guild.owner] = discord.PermissionOverwrite(
            view_channel=True, send_messages=False,
        )

    try:
        category = await guild.create_category(
            name=f"📡 CodeX — {server_name}", overwrites=overwrites
        )
    except discord.Forbidden:
        await interaction.followup.send("❌ Permission manquante pour créer des salons.", ephemeral=True)
        return

    BASE_CHANNELS = ["morts-pvp", "morts-pve", "connexions", "logs-adm"]
    # La whitelist publique a besoin de #logs-whitelist pour poster les demandes
    # à valider — on le provisionne dès le setup si un rôle a été fourni.
    if role_whitelist is not None:
        BASE_CHANNELS.append("logs-whitelist")
    created = {}
    for ch_type in BASE_CHANNELS:
        cfg  = CHANNEL_CONFIG.get(ch_type, {"emoji": "📌"})
        name = f"{cfg['emoji']}・{ch_type}"
        try:
            ch = await guild.create_text_channel(name=name, category=category, overwrites=overwrites)
            created[ch_type] = ch.id
        except Exception as e:
            logger.error(f"Erreur création salon {ch_type}: {e}")

    # Salon vocal compteur joueurs — public (visible) mais non-connectable
    voice_overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True),
    }
    try:
        vc = await guild.create_voice_channel(
            name="En-Ligne • 0/?", category=category, overwrites=voice_overwrites
        )
        created["serverstate"] = vc.id
    except Exception as e:
        logger.error(f"Erreur création salon serverstate: {e}")

    # Enregistrement serveur en DB — upsert sur (guild_id, service_id)
    db.save_server(
        guild_id=str(guild.id),
        nitrado_token=token,
        service_id=str(service_id),
        server_name=server_name,
        map_name=map_name,
        platform=platform,
        username=username,
        guild_name=guild.name,
        setup_by_id=str(interaction.user.id),
        setup_by_name=interaction.user.display_name,
    )
    db.set_setting(str(guild.id), "show_suicides",      "1")
    db.set_setting(str(guild.id), "show_burials",       "1")
    db.set_setting(str(guild.id), "show_consciousness", "0")
    db.set_setting(str(guild.id), "show_positions_pvp", "1")

    config    = db.get_server(str(guild.id), service_id=str(service_id))
    server_id = config.server_id if config else ""

    for ch_type, ch_id in created.items():
        db.set_channel(str(guild.id), ch_type, str(ch_id), server_id=server_id)

    if config:
        await manager.add_server(config)

    # ── Whitelist publique (optionnelle) ─────────────────────────────────────
    wl_panel_line = ""
    if role_whitelist is not None:
        from bot.whitelist_request import setup_request_channel
        try:
            cfg_wl = await setup_request_channel(interaction.client, guild, role_whitelist)
            wl_panel_line = f"<#{cfg_wl.get('request_channel_id')}>"
            logger.info(f"[Setup] Guild {guild.id} — salon de demande de whitelist créé")
        except Exception as e:
            logger.error(f"[Setup] Création du salon de whitelist échouée: {e}")
            wl_panel_line = f"⚠️ échec de la création ({e})"

    embed = discord.Embed(
        title="✅  CodeX KillFeed configuré !",
        description=(
            f"**{server_name}** · *{map_name}*\n\n"
            f"Les salons de base ont été créés dans **📡 CodeX — {server_name}**.\n\n"
            "`/filter` pour choisir les événements affichés, "
            "`/diagnostic` pour vérifier que tout fonctionne."
        ),
        color=discord.Color.from_rgb(30, 180, 120),
    )
    embed.add_field(
        name="📡 Salons créés",
        value="\n".join(f"{CHANNEL_CONFIG[t]['emoji']} #{t}" for t in created),
        inline=True,
    )
    if wl_panel_line:
        embed.add_field(
            name="🛡️ Whitelist publique",
            value=f"Salon de demande : {wl_panel_line}",
            inline=False,
        )
    embed.set_footer(text="CodeX KillFeed by EpSy")
    await interaction.followup.send(embed=embed, ephemeral=True)
    logger.info(f"[Setup] Guild {guild.id} — {server_name} — installation automatique")


# ─── Cog principal ────────────────────────────────────────────────────────────

class KillFeedCommands(commands.Cog):
    def __init__(self, bot, manager):
        self.bot     = bot
        self.manager = manager

    # ── /setup ────────────────────────────────────────────────────────────────

    @app_commands.command(name="setup", description="Configure le CodeX KillFeed sur ce serveur")
    @app_commands.describe(
        token="Token API Nitrado — laisser vide pour utiliser NITRADO_TOKEN du .env",
        role_whitelist="Rôle autorisé à voir le salon de demande de whitelist (optionnel)",
    )
    @app_commands.default_permissions(administrator=True)
    async def setup(self, interaction, token: str = None, role_whitelist: discord.Role = None):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Source unique du token : le .env. Le paramètre reste accepté pour
        # un setup ponctuel, mais c'est NITRADO_TOKEN qui sera utilisé ensuite
        # par le poller et la whitelist — ne pas laisser diverger les deux.
        token = (token or "").strip() or load_config().nitrado_token
        if not token:
            await interaction.followup.send(
                "❌ Aucun token Nitrado : renseigne `NITRADO_TOKEN` dans le `.env` "
                "de l'installation, ou passe-le en paramètre.",
                ephemeral=True,
            )
            return

        try:
            servers = await _fetch_dayz_servers(token)
        except httpx.HTTPStatusError as e:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Token invalide",
                    description=f"Nitrado a retourné une erreur HTTP {e.response.status_code}.",
                    color=discord.Color.red()),
                ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"Erreur Nitrado : {e}", ephemeral=True)
            return

        if not servers:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Aucun serveur DayZ trouvé",
                    description="Vérifie que ton token Nitrado est lié à un serveur DayZ PS4/XBOX actif.",
                    color=discord.Color.red()),
                ephemeral=True)
            return

        if len(servers) > 1:
            view = ServerSelectView(servers, token, guild, interaction, self.manager,
                                    role_whitelist=role_whitelist)
            await interaction.followup.send(
                embed=discord.Embed(title="Plusieurs serveurs détectés",
                    description="Lequel configurer ?",
                    color=discord.Color.from_rgb(59, 130, 246)),
                view=view, ephemeral=True)
            return

        await _run_setup(interaction, token, servers[0]["id"], guild, self.manager,
                         role_whitelist=role_whitelist)

    # ── /filter ───────────────────────────────────────────────────────────────

    @app_commands.command(name="filter", description="Configure les événements optionnels du KillFeed")
    @app_commands.default_permissions(administrator=True)
    async def filter(self, interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        config   = db.get_server(guild_id)
        if not config:
            await interaction.followup.send("Aucun KillFeed configuré.", ephemeral=True)
            return
        c = db.get_setting(guild_id, "show_consciousness",  "0")
        s = db.get_setting(guild_id, "show_suicides",       "1")
        b = db.get_setting(guild_id, "show_burials",        "1")
        p = db.get_setting(guild_id, "show_positions_pvp",  "1")
        status_c = "ACTIF" if c == "1" else "INACTIF"
        status_s = "ACTIF" if s == "1" else "INACTIF"
        status_b = "ACTIF" if b == "1" else "INACTIF"
        status_p = "ACTIF" if p == "1" else "INACTIF"
        await interaction.followup.send(
            embed=discord.Embed(
                title="Filtres du KillFeed",
                description=(
                    f"Perte / reprise de conscience : **{status_c}**\n"
                    f"Suicides : **{status_s}**\n"
                    f"Enterrements / déterrements : **{status_b}**\n"
                    f"Positions joueurs (PVP) : **{status_p}**\n\n"
                    "Cliquez pour modifier."
                ),
                color=discord.Color.from_rgb(30, 120, 255),
            ),
            view=FilterView(guild_id, c, s, b, p),
            ephemeral=True,
        )

    # ── /stop ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="salons", description="Active ou désactive un salon optionnel du KillFeed")
    @app_commands.describe(salon="Salon concerné", action="Activer (crée le salon) ou désactiver (le supprime)")
    @app_commands.choices(
        salon=[
            app_commands.Choice(name="🔨 constructions — bases construites/démontées", value="constructions"),
            app_commands.Choice(name="📦 placements — objets posés, enterrés, déterrés",   value="placements"),
            app_commands.Choice(name="🚩 drapeaux — drapeaux hissés/abaissés",         value="drapeaux"),
            app_commands.Choice(name="📋 logs-whitelist — demandes et suivi WL",       value="logs-whitelist"),
            app_commands.Choice(name="🚨 alertes — serveur hors ligne, bans auto (admins)", value="alertes"),
            app_commands.Choice(name="📢 annonces — comptes à rebours des redémarrages",  value="annonces"),
            app_commands.Choice(name="📊 statistiques — classement de la semaine",       value="statistiques"),
        ],
        action=[
            app_commands.Choice(name="Activer",    value="on"),
            app_commands.Choice(name="Désactiver", value="off"),
        ],
    )
    @app_commands.default_permissions(administrator=True)
    async def salons(self, interaction, salon: app_commands.Choice[str], action: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        guild    = interaction.guild
        guild_id = str(guild.id)
        config   = db.get_server(guild_id)
        if not config:
            await interaction.followup.send("Aucun KillFeed configuré — lance d'abord `/setup`.", ephemeral=True)
            return

        ch_type  = salon.value
        existing = await resolve_channel(self.bot, guild_id, ch_type, server_id=config.server_id)

        if action.value == "off":
            if existing:
                try:
                    await existing.delete(reason=f"/salons par {interaction.user}")
                except discord.HTTPException as e:
                    logger.warning(f"[Salons] Suppression #{ch_type} échouée : {e}")
            db.disable_channel(guild_id, ch_type, server_id=config.server_id)
            await interaction.followup.send(f"✅ Salon **{ch_type}** désactivé.", ephemeral=True)
            return

        if existing:
            await interaction.followup.send(f"Le salon {existing.mention} est déjà actif.", ephemeral=True)
            return

        # Même catégorie que les salons de base : les permissions sont héritées
        ref      = await resolve_channel(self.bot, guild_id, "morts-pvp", server_id=config.server_id)
        category = ref.category if ref else None
        name     = f"{CHANNEL_CONFIG[ch_type]['emoji']}・{ch_type}"
        try:
            # Sans overwrites propres, ne rien passer : le salon reste synchronisé
            # avec la catégorie (overwrites={} le rendrait public).
            ow = channel_overwrites(guild, ch_type)
            ch = await guild.create_text_channel(
                name=name, category=category, **({"overwrites": ow} if ow else {}),
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Permission manquante pour créer le salon.", ephemeral=True)
            return
        db.set_channel(guild_id, ch_type, str(ch.id), server_id=config.server_id)
        await interaction.followup.send(f"✅ Salon {ch.mention} créé — les événements y arrivent dès maintenant.", ephemeral=True)

    @app_commands.command(name="stop", description="Désactive le KillFeed sur ce serveur")
    @app_commands.default_permissions(administrator=True)
    async def stop(self, interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        servers  = db.get_all_servers_for_guild(guild_id)
        if not servers:
            await interaction.followup.send("Aucun KillFeed configuré.", ephemeral=True)
            return

        config = servers[0]
        if len(servers) > 1:
            view = _ServerPickView(servers)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Quel serveur stopper ?",
                    description=f"{len(servers)} serveurs configurés sur cette guild.",
                    color=discord.Color.orange(),
                ),
                view=view, ephemeral=True,
            )
            await view.wait()
            if not view.choice:
                return
            config = next((s for s in servers if s.server_id == view.choice), None)
            if not config:
                return

        await self.manager._stop_key(config.server_id)
        db.deactivate_server(guild_id, service_id=config.service_id)
        await interaction.followup.send(
            embed=discord.Embed(
                title="KillFeed arrêté",
                description=f"Polling stoppé pour **{config.server_name}**.",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )

    # ── /purge-guild ──────────────────────────────────────────────────────────

    @app_commands.command(name="purge-guild", description="Supprime définitivement des données KillFeed de ce serveur")
    @app_commands.default_permissions(administrator=True)
    async def purge_guild(self, interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id   = str(interaction.guild_id)
        guild_name = interaction.guild.name if interaction.guild else guild_id

        servers = db.get_all_servers_for_guild(guild_id)
        if not servers:
            await interaction.followup.send("Aucun serveur KillFeed configuré sur cette guild.", ephemeral=True)
            return

        # ── Choix du serveur si plusieurs ────────────────────────────────────
        chosen_server_id: Optional[str] = None   # None = toute la guild
        chosen_label     = "toute la guild"

        if len(servers) > 1:
            class ServerSelectView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=60)
                    self.choice = None   # server_id ou "__all__"

                @discord.ui.select(
                    placeholder="Choisir le serveur à supprimer…",
                    options=[
                        discord.SelectOption(
                            label=s.server_name[:100],
                            value=s.server_id,
                            description=(s.server_alias or s.map_name)[:100],
                        )
                        for s in servers
                    ] + [discord.SelectOption(label="Supprimer TOUTE la guild", value="__all__", description="Efface tous les serveurs + settings", emoji="☠️")],
                )
                async def on_select(self, sel_interaction: discord.Interaction, select):
                    self.choice = select.values[0]
                    self.stop()
                    await sel_interaction.response.defer()

                @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
                async def cancel(self, btn_interaction: discord.Interaction, button):
                    self.stop()
                    await btn_interaction.response.edit_message(content="Annulé.", embed=None, view=None)

            select_view = ServerSelectView()
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🗑️ Purge — choisir le serveur",
                    description=f"**{guild_name}** a **{len(servers)} serveurs** configurés.\nLequel supprimer ?",
                    color=discord.Color.from_rgb(220, 50, 50),
                ),
                view=select_view, ephemeral=True,
            )
            await select_view.wait()

            if select_view.choice is None:
                return   # annulé via bouton

            if select_view.choice == "__all__":
                chosen_server_id = None
                chosen_label     = f"toute la guild **{guild_name}**"
            else:
                chosen_server_id = select_view.choice
                srv = next((s for s in servers if s.server_id == chosen_server_id), None)
                chosen_label = f"le serveur **{srv.server_name}**" if srv else chosen_server_id

        else:
            # Un seul serveur → supprime toute la guild
            chosen_server_id = None
            chosen_label     = f"toute la guild **{guild_name}** (1 serveur)"

        # ── Confirmation finale ───────────────────────────────────────────────
        class ConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                self.confirmed = False

            @discord.ui.button(label="SUPPRIMER DÉFINITIVEMENT", style=discord.ButtonStyle.danger)
            async def confirm(self, btn_interaction: discord.Interaction, button):
                self.confirmed = True
                self.stop()
                await btn_interaction.response.defer()

            @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
            async def cancel(self, btn_interaction: discord.Interaction, button):
                self.stop()
                await btn_interaction.response.edit_message(content="Annulé.", embed=None, view=None)

        confirm_view = ConfirmView()
        scope_detail = (
            "kills · connexions · positions · joueurs · salons · zones d'alerte"
            if chosen_server_id else
            "kills · connexions · positions · joueurs · salons · settings · zones d'alerte · ADM storage"
        )
        confirm_embed = discord.Embed(
            title="⚠️ Confirmation requise",
            description=(
                f"Tu es sur le point de supprimer {chosen_label} :\n\n"
                f"{scope_detail}\n\n"
                "**Cette action est irréversible.**"
            ),
            color=discord.Color.from_rgb(220, 50, 50),
        )
        await interaction.edit_original_response(embed=confirm_embed, view=confirm_view)
        await confirm_view.wait()

        if not confirm_view.confirmed:
            return

        # ── Exécution ─────────────────────────────────────────────────────────
        if chosen_server_id:
            await self.manager._stop_key(chosen_server_id)
            db.delete_server_data(guild_id, chosen_server_id)
            result_msg = f"Le serveur **{chosen_label}** a été supprimé."
        else:
            await self.manager.remove_server(guild_id)
            db.delete_guild_completely(guild_id)
            result_msg = f"Toutes les données de **{guild_name}** ont été effacées."

        await interaction.edit_original_response(
            embed=discord.Embed(
                title="✅ Suppression effectuée",
                description=result_msg,
                color=discord.Color.from_rgb(30, 180, 120),
            ),
            view=None,
        )
        logger.info(f"[Commands] /purge-guild — {chosen_label} supprimé par {interaction.user}")

    # ── /status ───────────────────────────────────────────────────────────────

    @app_commands.command(name="status", description="Affiche le statut du KillFeed")
    async def status(self, interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        servers  = db.get_all_servers_for_guild(guild_id)
        if not servers:
            await interaction.followup.send("Aucun KillFeed configuré.", ephemeral=True)
            return

        config = servers[0]
        if len(servers) > 1:
            view = _ServerPickView(servers)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Statut pour quel serveur ?",
                    color=discord.Color.from_rgb(59, 130, 246),
                ),
                view=view, ephemeral=True,
            )
            await view.wait()
            if not view.choice:
                return
            config = next((s for s in servers if s.server_id == view.choice), None)
            if not config:
                return

        channels = db.get_all_channels(guild_id, server_id=config.server_id)
        await interaction.followup.send(embed=build_status_embed(config, channels), ephemeral=True)

    # ── /kills ────────────────────────────────────────────────────────────────

    @app_commands.command(name="kills", description="Affiche les derniers événements")
    @app_commands.describe(nombre="Nombre d'événements (max 10)")
    async def kills(self, interaction, nombre: int = 5):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        nombre   = min(max(nombre, 1), 10)
        events   = db.get_recent_kills(guild_id, nombre)
        if not events:
            await interaction.followup.send("Aucun événement enregistré.", ephemeral=True)
            return
        lines = []
        for e in events:
            kt = e.get("kill_type", "?")
            v  = e.get("victim_name", "?")
            k  = e.get("killer_name")
            t  = e.get("log_time", "?")
            lines.append(f"`{t}` · **{k}** → **{v}** · `{kt}`" if k else f"`{t}` · **{v}** · `{kt}`")
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"Derniers événements ({nombre})",
                description="\n".join(lines),
                color=discord.Color.from_rgb(59, 130, 246),
            ).set_footer(text="CodeX KillFeed by EpSy"),
            ephemeral=True,
        )

    # ── /whitelist ────────────────────────────────────────────────────────────

    @app_commands.command(name="whitelist", description="Ajoute un joueur à la whitelist (PSN + Discord optionnel)")
    @app_commands.describe(
        psn_id="ID PSN exact du joueur (respecter la casse des logs Nitrado)",
        discord_id="ID Discord numérique du joueur (optionnel)",
        discord_name="Pseudo Discord du joueur (optionnel)",
    )
    @app_commands.default_permissions(administrator=True)
    async def whitelist(self, interaction, psn_id: str, discord_id: str = "", discord_name: str = ""):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        config   = db.get_server(guild_id)
        if not config:
            await interaction.followup.send("Aucun KillFeed configuré.", ephemeral=True)
            return
        try:
            result = await wl.add_player(
                guild_id=guild_id,
                psn_id=psn_id,
                discord_id=discord_id,
                discord_name=discord_name,
                registered_by=str(interaction.user.id),
            )
            color = discord.Color.green() if result.get("success") else discord.Color.red()
            icon  = "✅" if result.get("success") else "❌"
            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"{icon} Whitelist",
                    description=result.get("message", "Erreur inconnue"),
                    color=color,
                ),
                ephemeral=True,
            )
            if result.get("success"):
                from bot.tasks.whitelist_log import send_whitelist_log
                await send_whitelist_log(
                    bot=self.bot, guild_id=guild_id, action="add",
                    psn_id=psn_id, discord_id=discord_id, discord_name=discord_name,
                    done_by=str(interaction.user.id), server_id=config.server_id,
                )
        except Exception as e:
            await interaction.followup.send(f"Erreur : {e}", ephemeral=True)

    # ── /dewhitelist ──────────────────────────────────────────────────────────

    @app_commands.command(name="dewhitelist", description="Retire un joueur de la whitelist du serveur")
    @app_commands.describe(psn_id="ID PSN exact du joueur à retirer")
    @app_commands.default_permissions(administrator=True)
    async def dewhitelist(self, interaction, psn_id: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        config   = db.get_server(guild_id)
        if not config:
            await interaction.followup.send("Aucun KillFeed configuré.", ephemeral=True)
            return
        try:
            result = await wl.remove_player(guild_id, psn_id)
            color = discord.Color.green() if result.get("success") else discord.Color.red()
            icon  = "✅" if result.get("success") else "❌"
            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"{icon} Whitelist",
                    description=result.get("message", "Erreur inconnue"),
                    color=color,
                ),
                ephemeral=True,
            )
            if result.get("success"):
                from bot.tasks.whitelist_log import send_whitelist_log
                await send_whitelist_log(
                    bot=self.bot, guild_id=guild_id, action="remove",
                    psn_id=psn_id, done_by=str(interaction.user.id),
                    server_id=config.server_id,
                )
        except Exception as e:
            await interaction.followup.send(f"Erreur : {e}", ephemeral=True)

    # ── /link ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="link", description="Lie ton PSN/XBOX à ton compte Discord")
    @app_commands.describe(psn_id="Ton pseudo exact tel qu'il apparaît dans les logs du serveur")
    async def link(self, interaction, psn_id: str):
        await interaction.response.defer(ephemeral=True)
        guild_id     = str(interaction.guild_id)
        discord_id   = str(interaction.user.id)
        discord_name = interaction.user.display_name
        config       = db.get_server(guild_id)
        if not config:
            await interaction.followup.send("Aucun KillFeed configuré.", ephemeral=True)
            return
        try:
            result = await wl.add_player(
                guild_id=guild_id,
                psn_id=psn_id.strip(),
                discord_id=discord_id,
                discord_name=discord_name,
                registered_by="self",
            )
            if result.get("success"):
                embed = discord.Embed(
                    title="✅ Compte lié avec succès",
                    description=(
                        f"Ton pseudo **`{psn_id}`** est maintenant lié à ton Discord."
                    ),
                    color=discord.Color.green(),
                )
                embed.set_footer(text="CodeX KillFeed by EpSy")
                await interaction.followup.send(embed=embed, ephemeral=True)
                from bot.tasks.whitelist_log import send_whitelist_log
                await send_whitelist_log(
                    bot=self.bot, guild_id=guild_id, action="add",
                    psn_id=psn_id, discord_id=discord_id, discord_name=discord_name,
                    done_by=discord_id, server_id=config.server_id,
                )
            else:
                embed = discord.Embed(
                    title="❌ Impossible de lier le compte",
                    description=result.get("message", "Erreur inconnue."),
                    color=discord.Color.red(),
                )
                embed.add_field(
                    name="Besoin d'aide ?",
                    value="Vérifie l'orthographe exacte de ton pseudo (casse incluse) ou contacte un admin.",
                    inline=False,
                )
                embed.set_footer(text="CodeX KillFeed by EpSy")
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Erreur : {e}", ephemeral=True)

    # ── /wl ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="wl", description="Affiche la whitelist Nitrado dans le salon logs-whitelist")
    @app_commands.default_permissions(administrator=True)
    async def wl(self, interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        config   = db.get_server(guild_id)
        if not config:
            await interaction.followup.send("Aucun KillFeed configuré.", ephemeral=True)
            return
        try:
            data    = await wl.read_nitrado_whitelist()
            entries = data.get("entries", [])
            count   = data.get("count", len(entries))

            from bot.channel_resolver import resolve_channel
            channel = await resolve_channel(self.bot, guild_id, "logs-whitelist", server_id=config.server_id)
            if not channel:
                await interaction.followup.send("❌ Salon `logs-whitelist` introuvable. Configure-le d'abord.", ephemeral=True)
                return

            # Découpe en chunks de 30 si liste longue
            chunk_size = 30
            chunks = [entries[i:i + chunk_size] for i in range(0, max(len(entries), 1), chunk_size)] if entries else [[]]

            for idx, chunk in enumerate(chunks):
                embed = discord.Embed(
                    title=f"📋 Whitelist Nitrado — {count} joueur{'s' if count != 1 else ''}",
                    description="\n".join(f"🎮 `{p}`" for p in chunk) if chunk else "*Whitelist vide*",
                    color=0x4a8fd4,
                )
                if len(chunks) > 1:
                    embed.set_footer(text=f"Page {idx + 1}/{len(chunks)} · CodeX KillFeed")
                else:
                    embed.set_footer(text=f"Demandé par {interaction.user.display_name} · CodeX KillFeed")
                embed.timestamp = discord.utils.utcnow()
                await channel.send(embed=embed)

            await interaction.followup.send(
                f"✅ Whitelist postée dans <#{channel.id}> — {count} joueur{'s' if count != 1 else ''}.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"Erreur : {e}", ephemeral=True)

    # ── /wl-panel ─────────────────────────────────────────────────────────────

    @app_commands.command(
        name="wl-panel",
        description="Gère le salon public de demande de whitelist (bouton joueur)",
    )
    @app_commands.describe(
        action="installer (crée le salon) · reposter (renvoie le panneau) · retirer (supprime le salon)",
        role="Rôle autorisé à voir le salon — requis pour « installer »",
        role_approuve="Rôle donné au joueur quand sa demande est approuvée (optionnel)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="installer", value="installer"),
        app_commands.Choice(name="reposter",  value="reposter"),
        app_commands.Choice(name="retirer",   value="retirer"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def wl_panel(self, interaction: discord.Interaction,
                       action: app_commands.Choice[str],
                       role: discord.Role = None,
                       role_approuve: discord.Role = None):
        await interaction.response.defer(ephemeral=True)
        from bot.whitelist_request import (
            setup_request_channel, teardown_request_channel, repost_request_message,
        )
        guild = interaction.guild
        # Rôle d'approbation : réglé autrefois par le dashboard SaaS, ici par commande
        if role_approuve is not None and action.value != "retirer":
            if role_approuve >= guild.me.top_role:
                await interaction.followup.send(
                    f"❌ Le rôle {role_approuve.mention} est placé au-dessus du rôle du bot : Discord "
                    "l'empêche de le donner. Dans Paramètres du serveur → Rôles, monte le rôle du bot "
                    "au-dessus, puis relance la commande.", ephemeral=True)
                return
            wl.upsert_config(str(guild.id), approved_role_id=str(role_approuve.id))
            await interaction.followup.send(
                f"✅ Les joueurs approuvés recevront le rôle {role_approuve.mention}.", ephemeral=True)
        try:
            if action.value == "installer":
                if role is None:
                    await interaction.followup.send(
                        "❌ Précise le rôle autorisé à voir le salon : `/wl-panel installer role:@Joueurs`.",
                        ephemeral=True)
                    return
                cfg = await setup_request_channel(self.bot, guild, role)
                await interaction.followup.send(
                    f"✅ Salon de demande créé : <#{cfg.get('request_channel_id')}>\n"
                    "Pense à créer/activer le salon `logs-whitelist` : c'est là que "
                    "les demandes à valider sont postées.",
                    ephemeral=True)
            elif action.value == "reposter":
                cfg = await repost_request_message(guild)
                await interaction.followup.send(
                    f"✅ Panneau reposté dans <#{cfg.get('request_channel_id')}>.", ephemeral=True)
            else:
                await teardown_request_channel(guild)
                await interaction.followup.send(
                    "✅ Salon de demande supprimé, whitelist publique désactivée.", ephemeral=True)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Permissions Discord insuffisantes (gérer les salons).", ephemeral=True)
        except Exception as e:
            logger.error(f"[WLPanel] {action.value} échoué: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)

    # ── /refresh ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="refresh",
        description="Resynchronise le bot avec cette guild (salons, cache, permissions)"
    )
    @app_commands.default_permissions(administrator=True)
    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild    = interaction.guild
        guild_id = str(guild.id)

        servers = db.get_all_active_servers()
        guild_servers = [s for s in servers if s.guild_id == guild_id]

        if not guild_servers:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ Aucun serveur configuré",
                    description="Cette guild n'a pas de KillFeed actif. Utilise `/setup` pour commencer.",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        # ── 1. Vérification des permissions du bot ────────────────────────────
        me = guild.me
        is_admin = me.guild_permissions.administrator
        perm_warn = "" if is_admin else (
            "\n⚠️ **Le bot n'a pas la permission Administrateur** sur cette guild. "
            "C'est la cause probable des erreurs `Missing Access`. "
            "Réinvite le bot avec le scope Administrator ou accorde-lui le rôle manuellement."
        )

        # ── 2. Invalidation du cache channels ────────────────────────────────
        for s in guild_servers:
            db.invalidate_channels_cache(guild_id, s.server_id)
        db.invalidate_channels_cache(guild_id)

        # ── 3. Sync des salons (recréation des supprimés, correction des IDs) ─
        recreated_all: list[str] = []
        sync_errors: list[str]   = []
        for s in guild_servers:
            try:
                recreated = await db.sync_guild_channels(guild, guild_id, server_id=s.server_id)
                recreated_all.extend(recreated)
            except Exception as e:
                sync_errors.append(str(e))

        # ── 4. Audit des permissions par salon ────────────────────────────────
        channels_ok:  list[str] = []
        channels_err: list[str] = []

        all_ch = db.get_all_channels(guild_id)
        for ch_type, ch_id in all_ch.items():
            if not ch_id or ch_type not in db.CHANNEL_CONFIG:
                continue
            ch = guild.get_channel(int(ch_id))
            if ch is None:
                try:
                    ch = await self.bot.fetch_channel(int(ch_id))
                except Exception:
                    channels_err.append(f"`{ch_type}` — salon introuvable (ID périmé ?)")
                    continue
            perms = ch.permissions_for(me)
            missing = []
            if not perms.view_channel:
                missing.append("voir")
            if not perms.send_messages:
                missing.append("envoyer")
            if not perms.attach_files:
                missing.append("fichiers")
            if not perms.embed_links:
                missing.append("embeds")
            if missing:
                channels_err.append(f"`{ch_type}` — accès refusé : {', '.join(missing)}")
            else:
                channels_ok.append(f"`{ch_type}`")

        # ── 5. Construction de l'embed résultat ───────────────────────────────
        color = discord.Color.green() if not channels_err and not sync_errors else discord.Color.orange()
        embed = discord.Embed(
            title="🔄 Refresh terminé",
            color=color,
        )

        embed.add_field(
            name="🤖 Permissions bot",
            value="✅ Administrateur" if is_admin else "❌ Pas Administrateur",
            inline=False,
        )

        if recreated_all:
            embed.add_field(
                name=f"✅ Salons recréés ({len(recreated_all)})",
                value="\n".join(f"• `{c}`" for c in recreated_all),
                inline=False,
            )

        if channels_ok:
            embed.add_field(
                name=f"✅ Salons accessibles ({len(channels_ok)})",
                value=" ".join(channels_ok),
                inline=False,
            )

        if channels_err:
            embed.add_field(
                name=f"❌ Problèmes détectés ({len(channels_err)})",
                value="\n".join(f"• {e}" for e in channels_err),
                inline=False,
            )

        if sync_errors:
            embed.add_field(
                name="⚠️ Erreurs sync",
                value="\n".join(f"• {e}" for e in sync_errors),
                inline=False,
            )

        if not channels_err and not recreated_all and not sync_errors:
            embed.description = "Tout est en ordre. Cache invalidé, aucun salon manquant."
        elif perm_warn:
            embed.description = perm_warn

        logger.info(
            f"[Bot] /refresh guild={guild_id} — "
            f"ok={len(channels_ok)} err={len(channels_err)} recreated={len(recreated_all)}"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /stats ────────────────────────────────────────────────────────────────

    @app_commands.command(name="stats", description="Statistiques de kills sur une période")
    @app_commands.describe(jours="Nombre de jours à analyser (1-30, défaut 7)")
    async def stats(self, interaction: discord.Interaction, jours: int = 7):
        await interaction.response.defer(ephemeral=True)
        jours    = min(max(jours, 1), 30)
        guild_id = str(interaction.guild_id)
        since    = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
        events   = db.get_kills_since(guild_id, since)

        if not events:
            await interaction.followup.send(
                f"Aucun événement enregistré sur les {jours} derniers jours.", ephemeral=True)
            return

        by_type = Counter(e.get("kill_type", "?") for e in events)
        killers = Counter(
            e["killer_name"] for e in events
            if e.get("kill_type") == "pvp" and e.get("killer_name")
        )
        victims = Counter(e.get("victim_name") for e in events if e.get("victim_name"))

        embed = discord.Embed(
            title=f"📊 Statistiques — {jours} derniers jours",
            color=discord.Color.from_rgb(59, 130, 246),
        )
        embed.add_field(
            name="Événements",
            value=(
                f"**{len(events)}** au total\n"
                f"⚔️ PVP : {by_type.get('pvp', 0)}\n"
                f"🐺 PVE : {by_type.get('pve', 0)}\n"
                f"💀 Suicide : {by_type.get('suicide', 0)}"
            ),
            inline=True,
        )
        if killers:
            embed.add_field(
                name="🏆 Top kills PVP",
                value="\n".join(f"**{n}** — {c} kill(s)" for n, c in killers.most_common(5)),
                inline=True,
            )
        if victims:
            embed.add_field(
                name="💀 Plus souvent tués",
                value="\n".join(f"**{n}** — {c}×" for n, c in victims.most_common(3)),
                inline=True,
            )
        embed.set_footer(text="CodeX KillFeed by EpSy")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /diagnostic ───────────────────────────────────────────────────────────
    # Remplace le support humain : chaque ligne doit dire quoi corriger, pas
    # juste "erreur". C'est la commande que l'admin lance avant de nous écrire.

    @app_commands.command(
        name="diagnostic",
        description="Vérifie l'état du bot (Nitrado, base de données, KillFeed)",
    )
    @app_commands.default_permissions(administrator=True)
    async def diagnostic(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        config   = load_config()
        lines: list[str] = []
        all_ok = True

        lines.append("✅ **Discord** — connecté")

        try:
            db.get_all_servers_for_guild(guild_id)
            lines.append("✅ **Base de données** — accessible")
        except Exception as e:
            all_ok = False
            lines.append(f"❌ **Base de données** — {e}")

        if not config.nitrado_token:
            all_ok = False
            lines.append("❌ **Nitrado** — `NITRADO_TOKEN` manquant dans le `.env`")
        else:
            try:
                servers = await _fetch_dayz_servers(config.nitrado_token)
                if servers:
                    lines.append(f"✅ **Nitrado** — token valide ({len(servers)} serveur(s) détecté(s))")
                else:
                    all_ok = False
                    lines.append("⚠️ **Nitrado** — token valide mais aucun serveur DayZ trouvé sur ce compte")
            except httpx.HTTPStatusError as e:
                all_ok = False
                lines.append(f"❌ **Nitrado** — token refusé (HTTP {e.response.status_code})")
            except Exception as e:
                all_ok = False
                lines.append(f"❌ **Nitrado** — injoignable ({e})")

        servers_cfg = [s for s in db.get_all_active_servers() if s.guild_id == guild_id]
        if not servers_cfg:
            lines.append("⚠️ **KillFeed** — aucun serveur configuré (`/setup` pour commencer)")
        else:
            running = sum(1 for s in servers_cfg if self.manager.is_running(s))
            marker  = "✅" if running == len(servers_cfg) else "❌"
            if running != len(servers_cfg):
                all_ok = False
            lines.append(f"{marker} **KillFeed** — {running}/{len(servers_cfg)} poller(s) actif(s)")

        from bot.tasks.maintenance import current_version, update_available, last_backup, UPDATE_REPO
        rel = update_available()
        if rel:
            lines.append(f"⬆️ **Version** — {current_version()} installée, "
                         f"[{rel['tag']} disponible]({rel['url']})")
        else:
            lines.append(f"✅ **Version** — {current_version()}"
                         + ("" if UPDATE_REPO else " (vérification des mises à jour désactivée)"))
        bk = last_backup()
        if bk:
            lines.append(f"✅ **Sauvegarde** — dernière : `{bk.name}` (dossier `data/backups`)")
        else:
            lines.append("⚠️ **Sauvegarde** — aucune pour l'instant (la première se fait dans les 10 min)")
        lines.append(f"🕒 **Horloge de la machine** — {datetime.now():%d/%m %H:%M} "
                     "(référence des horaires NO PVP et redémarrages)")

        embed = discord.Embed(
            title="🩺 Diagnostic",
            description="\n".join(lines),
            color=discord.Color.green() if all_ok else discord.Color.red(),
        )
        embed.set_footer(text="Problème persistant ? Le détail est dans data/logs/bot.log")
        await interaction.followup.send(embed=embed, ephemeral=True)

