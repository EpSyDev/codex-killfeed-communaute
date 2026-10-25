"""
Commandes ajoutées en v1.1 :
    /joueur, /top                       statistiques (tout le monde)
    /ban, /unban, /bans                 banlist Nitrado (admin)
    /autoban ...                        auto-bans NO PVP / suicide (admin)
    /restart ...                        redémarrages planifiés (admin)
    /maj                                mise à jour depuis GitHub (admin)
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from backend import database as db
from backend import moderation as mod
from backend import nitrado_whitelist as nitrado
from bot.extra_channels import send_alert
from bot.leaderboard import build_player_embed, build_top_embed
from bot.tasks import restarts

logger = logging.getLogger("killfeed.commands_extra")


async def _player_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    try:
        names = db.search_player_names(str(interaction.guild_id), current)
    except Exception:
        return []
    return [app_commands.Choice(name=n, value=n) for n in names]


async def _require_server(interaction: discord.Interaction):
    cfg = db.get_server(str(interaction.guild_id))
    if not cfg:
        await interaction.followup.send("Aucun KillFeed configuré — lance d'abord `/setup`.", ephemeral=True)
    return cfg


def _now_hint() -> str:
    return f"Heure actuelle de la machine du bot : **{datetime.now():%H:%M}**"


class _UpdateConfirmView(discord.ui.View):
    def __init__(self, bot, user_id: int, release: dict, current: str):
        super().__init__(timeout=180)
        self.bot, self.user_id, self.release, self.current = bot, user_id, release, current

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Installer maintenant", style=discord.ButtonStyle.success, emoji="⬆️")
    async def install(self, interaction: discord.Interaction, _button: discord.ui.Button):
        from bot import updater
        self.stop()
        await interaction.response.edit_message(
            content="⏳ Téléchargement et installation… (ne relance pas la commande)", embed=None, view=None)
        try:
            result = await updater.run_update(self.release, self.current,
                                              requested_by=str(interaction.user.id),
                                              channel_id=str(interaction.channel_id))
        except updater.UpdateError as e:
            await interaction.edit_original_response(content=f"❌ {e}\nRien n'a été modifié, le bot continue en **{self.current}**.")
            return
        except Exception as e:
            logger.error(f"[MAJ] Échec inattendu : {e}", exc_info=True)
            await interaction.edit_original_response(
                content=f"❌ Erreur inattendue : {e}\nDétail dans `data/logs/bot.log`. "
                        "Ancienne version sauvegardée dans `data/updates/`.")
            return

        msg = (f"✅ Version **{self.release['tag']}** installée. Le bot redémarre : il revient en ligne "
               "dans 1 à 2 minutes et confirme dans #alertes.")
        if result.get("deps_changed"):
            msg += "\nℹ️ De nouvelles dépendances s'installent au redémarrage : compte quelques minutes de plus."
        if result.get("launcher_changed"):
            msg += ("\n⚠️ Le lanceur Windows a changé : à l'occasion, double-clique sur "
                    "`INSTALLER-WINDOWS` pour l'actualiser (rien n'est perdu).")
        await interaction.edit_original_response(content=msg)
        asyncio.get_running_loop().create_task(_restart_bot(self.bot))

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Mise à jour annulée.", embed=None, view=None)


async def _restart_bot(bot) -> None:
    """Quitte le process : la boucle Windows / systemd relance la nouvelle version."""
    await asyncio.sleep(3)
    logger.info("[MAJ] Redémarrage pour terminer la mise à jour")
    try:
        await asyncio.wait_for(bot.close(), timeout=10)
    finally:
        os._exit(0)


class ExtraCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /joueur ───────────────────────────────────────────────────────────────

    @app_commands.command(name="joueur", description="Fiche d'un joueur : kills, morts, ratio, temps de jeu")
    @app_commands.describe(pseudo="Pseudo en jeu (PSN / Gamertag)")
    @app_commands.autocomplete(pseudo=_player_autocomplete)
    async def joueur(self, interaction: discord.Interaction, pseudo: str):
        await interaction.response.defer(ephemeral=True)
        embed = build_player_embed(str(interaction.guild_id), pseudo.strip())
        if not embed:
            await interaction.followup.send(f"Aucune donnée pour **{pseudo}** sur ce serveur.", ephemeral=True)
            return
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /top ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="top", description="Classement des joueurs sur une période")
    @app_commands.describe(jours="Nombre de jours (1-30, défaut 7)", public="Afficher le classement à tout le salon")
    async def top(self, interaction: discord.Interaction, jours: int = 7, public: bool = False):
        await interaction.response.defer(ephemeral=not public)
        jours = min(max(jours, 1), 30)
        embed = build_top_embed(str(interaction.guild_id), jours)
        if not embed:
            await interaction.followup.send(f"Rien à classer sur les {jours} derniers jours.", ephemeral=True)
            return
        await interaction.followup.send(embed=embed, ephemeral=not public)

    # ── /ban /unban /bans ─────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Bannit un joueur du serveur DayZ (banlist Nitrado)")
    @app_commands.describe(pseudo="Pseudo en jeu exact", raison="Raison (gardée dans #alertes)")
    @app_commands.autocomplete(pseudo=_player_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def ban(self, interaction: discord.Interaction, pseudo: str, raison: str = ""):
        await interaction.response.defer(ephemeral=True)
        cfg = await _require_server(interaction)
        if not cfg:
            return
        pseudo = pseudo.strip()
        ok = await mod.ban_player(cfg.guild_id, pseudo, reason=raison)
        if ok:
            await interaction.followup.send(
                f"✅ **{pseudo}** est banni et retiré de la whitelist.\n"
                "S'il est connecté, il peut rester en jeu jusqu'au prochain redémarrage "
                "(`/restart maintenant` si c'est urgent).",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"⏳ Nitrado ne répond pas : le ban de **{pseudo}** est **mis en attente** et sera "
                "appliqué automatiquement dès que Nitrado répond (essai toutes les 5 minutes). "
                "Il apparaît dans `/bans`.",
                ephemeral=True,
            )
        embed = discord.Embed(title="🔨 Ban manuel" if ok else "⏳ Ban manuel en attente", color=0xEF4444,
                              description=f"**{pseudo}** banni par {interaction.user.mention}")
        if raison:
            embed.add_field(name="Raison", value=raison[:1000], inline=False)
        await send_alert(self.bot, cfg, embed)

    @app_commands.command(name="unban", description="Retire un joueur de la banlist Nitrado")
    @app_commands.describe(pseudo="Pseudo en jeu exact")
    @app_commands.default_permissions(administrator=True)
    async def unban(self, interaction: discord.Interaction, pseudo: str):
        await interaction.response.defer(ephemeral=True)
        cfg = await _require_server(interaction)
        if not cfg:
            return
        found, ok, was_pending = await mod.unban_player(cfg.guild_id, pseudo)
        if not ok:
            await interaction.followup.send(
                ("✅ Ban en attente de **" + pseudo + "** annulé.\n" if was_pending else "")
                + "❌ Nitrado ne répond pas : impossible de vérifier la banlist. Réessaie dans quelques minutes.",
                ephemeral=True)
        elif was_pending and not found:
            await interaction.followup.send(f"✅ Ban en attente de **{pseudo}** annulé (il n'avait pas encore été appliqué).", ephemeral=True)
        elif not found:
            await interaction.followup.send(f"**{pseudo}** n'est pas dans la banlist.", ephemeral=True)
        else:
            await interaction.followup.send(
                f"✅ **{pseudo}** débanni. Pense à le remettre en whitelist si besoin : `/whitelist`.",
                ephemeral=True,
            )
            await send_alert(self.bot, cfg, discord.Embed(
                title="♻️ Déban", color=0x22C55E,
                description=f"**{pseudo}** débanni par {interaction.user.mention}"))

    @unban.autocomplete("pseudo")
    async def _unban_autocomplete(self, interaction: discord.Interaction, current: str):
        pending = [p["name"] for p in mod.get_pending(str(interaction.guild_id))]
        bans = pending + [b for b in await nitrado.read_banlist() if b not in pending]
        cur = current.lower()
        return [app_commands.Choice(name=b, value=b) for b in bans if b.lower().startswith(cur)][:25]

    @app_commands.command(name="bans", description="Liste des joueurs bannis (banlist Nitrado)")
    @app_commands.default_permissions(administrator=True)
    async def bans(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild_id)
        pending = mod.get_pending(gid)
        try:
            bans = await nitrado.read_banlist_strict()
            reachable = True
        except Exception:
            bans, reachable = [], False

        embed = discord.Embed(title=f"🔨 Bannis — {len(bans)}" if reachable else "🔨 Bannis",
                              color=0xEF4444)
        if not reachable:
            embed.description = "⚠️ Nitrado ne répond pas : la banlist ne peut pas être lue pour l'instant."
        elif bans:
            text = "\n".join(f"• {b}" for b in sorted(bans, key=str.lower))
            embed.description = text if len(text) <= 4000 else text[:3990] + "\n…"
        else:
            embed.description = "Aucun joueur banni."
        if pending:
            lines = [f"• **{p['name']}** — depuis le {p.get('since', '?').replace('T', ' à ')}"
                     + (f" ({p['reason'][:60]})" if p.get("reason") else "") for p in pending]
            embed.add_field(name=f"⏳ En attente — {len(pending)} (appliqués dès que Nitrado répond)",
                            value="\n".join(lines)[:1024], inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /autoban ──────────────────────────────────────────────────────────────

    autoban = app_commands.Group(
        name="autoban", description="Bans automatiques NO PVP / suicide",
        default_permissions=discord.Permissions(administrator=True),
    )

    _RULE_CHOICES = [
        app_commands.Choice(name="NO PVP — bannit le tueur à chaque kill PVP", value="nopvp"),
        app_commands.Choice(name="Suicide — bannit le joueur qui se suicide", value="suicide"),
    ]

    @autoban.command(name="activer", description="Active ou désactive une règle d'auto-ban")
    @app_commands.choices(regle=_RULE_CHOICES, etat=[
        app_commands.Choice(name="Activer", value="1"),
        app_commands.Choice(name="Désactiver", value="0"),
    ])
    async def autoban_toggle(self, interaction: discord.Interaction,
                             regle: app_commands.Choice[str], etat: app_commands.Choice[str]):
        gid = str(interaction.guild_id)
        db.set_setting(gid, mod.RULES[regle.value]["toggle"], etat.value)
        msg = f"{'✅ Activé' if etat.value == '1' else '⏸️ Désactivé'} : auto-ban **{mod.RULES[regle.value]['label']}**."
        if regle.value == "nopvp" and etat.value == "1":
            sched = mod.get_schedule(gid)
            msg += ("\nHoraires : " + ("selon `/autoban horaires`" if sched["enabled"] and sched["slots"]
                                       else "**24 h/24** (aucune plage définie)"))
        await interaction.response.send_message(msg, ephemeral=True)

    @autoban.command(name="exception", description="Joueurs jamais bannis par une règle")
    @app_commands.choices(regle=_RULE_CHOICES, action=[
        app_commands.Choice(name="Ajouter", value="add"),
        app_commands.Choice(name="Retirer", value="remove"),
    ])
    @app_commands.autocomplete(pseudo=_player_autocomplete)
    async def autoban_exception(self, interaction: discord.Interaction, regle: app_commands.Choice[str],
                                action: app_commands.Choice[str], pseudo: str):
        gid   = str(interaction.guild_id)
        names = mod.get_exceptions(gid, regle.value)
        lower = [n.lower() for n in names]
        pseudo = pseudo.strip()
        if action.value == "add" and pseudo.lower() not in lower:
            names.append(pseudo)
        elif action.value == "remove":
            names = [n for n in names if n.lower() != pseudo.lower()]
        mod.set_exceptions(gid, regle.value, names)
        await interaction.response.send_message(
            f"Exceptions **{mod.RULES[regle.value]['label']}** : "
            + (", ".join(f"`{n}`" for n in names) if names else "aucune"),
            ephemeral=True,
        )

    @autoban.command(name="horaires", description="Plages horaires du NO PVP (sans plage = 24 h/24)")
    @app_commands.describe(
        jours="tous, semaine, week-end, lun-ven, sam,dim…",
        debut="Heure de début, ex. 08:00",
        fin="Heure de fin, ex. 18:00 ou 24:00 (avant le début = passe minuit)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Ajouter une plage", value="add"),
        app_commands.Choice(name="Tout effacer (retour 24 h/24)", value="clear"),
    ])
    async def autoban_schedule(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                               jours: str = "tous", debut: str = "", fin: str = ""):
        gid   = str(interaction.guild_id)
        sched = mod.get_schedule(gid)
        if action.value == "clear":
            mod.set_schedule(gid, {"enabled": False, "slots": []})
            await interaction.response.send_message("🗑️ Plages effacées : le NO PVP s'applique **24 h/24**.", ephemeral=True)
            return
        days = mod.parse_days(jours)
        start, end = mod.parse_hm(debut), mod.parse_hm(fin, end_of_day=True)
        if days is None or start < 0 or end < 0 or start == end:
            await interaction.response.send_message(
                "❌ Format invalide. Exemple : jours `semaine`, début `08:00`, fin `18:00`.", ephemeral=True)
            return
        sched["slots"].append({"days": days, "start": f"{start // 60:02d}:{start % 60:02d}",
                               "end": f"{end // 60:02d}:{end % 60:02d}"})
        sched["enabled"] = True
        mod.set_schedule(gid, sched)
        await interaction.response.send_message(self._schedule_text(gid), ephemeral=True)

    @autoban.command(name="etat", description="Résumé des règles d'auto-ban")
    async def autoban_status(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        lines = []
        for key, rule in mod.RULES.items():
            on = db.get_setting(gid, rule["toggle"], "0") == "1"
            exc = mod.get_exceptions(gid, key)
            lines.append(f"**{rule['label']}** : {'✅ actif' if on else '⏸️ inactif'}"
                         + (f" — exceptions : {', '.join(exc)}" if exc else ""))
        await interaction.response.send_message("\n".join(lines) + "\n\n" + self._schedule_text(gid), ephemeral=True)

    @staticmethod
    def _schedule_text(gid: str) -> str:
        sched = mod.get_schedule(gid)
        if not sched["enabled"] or not sched["slots"]:
            return f"🕒 NO PVP : **24 h/24**.\n{_now_hint()}"
        slots = "\n".join(f"• {mod.describe_days(s['days'])} de {s['start']} à {s['end']}" for s in sched["slots"])
        active = "actif" if mod.nopvp_active_now(gid) else "inactif"
        return f"🕒 Plages NO PVP :\n{slots}\nEn ce moment : **{active}**. {_now_hint()}"

    # ── /maj ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="maj", description="Installe la dernière version du bot (config et données conservées)")
    @app_commands.default_permissions(administrator=True)
    async def maj(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        from bot import updater
        from bot.tasks import maintenance as mt
        if updater.is_running():
            await interaction.followup.send("⏳ Une mise à jour est déjà en cours.", ephemeral=True)
            return
        if not mt.UPDATE_REPO:
            await interaction.followup.send("La vérification des mises à jour est désactivée sur cette installation.", ephemeral=True)
            return
        await mt.check_version()
        current = mt.current_version()
        rel = mt.update_available()
        if not mt.latest_release.get("tag"):
            await interaction.followup.send("❌ Impossible de joindre GitHub pour l'instant. Réessaie dans quelques minutes.", ephemeral=True)
            return
        if not rel:
            await interaction.followup.send(f"✅ Le bot est à jour (version **{current}**).", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"⬆️ Mise à jour {current} → {rel['tag']}",
            description=((rel.get("notes") or "")[:3000] + f"\n\n[Détail de la version]({rel['url']})"),
            color=0x3B82F6,
        )
        embed.add_field(name="Ce qui va se passer", inline=False, value=(
            "1. téléchargement et vérification du fichier officiel\n"
            "2. sauvegarde de la base et de la version actuelle\n"
            "3. remplacement des fichiers (`.env`, base et données **conservés**)\n"
            "4. redémarrage du bot : **1 à 2 minutes hors ligne**\n"
            "Le résultat est confirmé dans #alertes."))
        await interaction.followup.send(embed=embed, view=_UpdateConfirmView(self.bot, interaction.user.id, rel, current),
                                        ephemeral=True)

    # ── /restart ──────────────────────────────────────────────────────────────

    restart = app_commands.Group(
        name="restart", description="Redémarrages du serveur DayZ",
        default_permissions=discord.Permissions(administrator=True),
    )

    @restart.command(name="planifier", description="Ajoute un redémarrage automatique récurrent")
    @app_commands.describe(heure="Heure du redémarrage, ex. 06:00", jours="tous, semaine, week-end, lun,mer…")
    async def restart_add(self, interaction: discord.Interaction, heure: str, jours: str = "tous"):
        gid = str(interaction.guild_id)
        t, days = mod.parse_hm(heure), mod.parse_days(jours)
        if t < 0 or days is None:
            await interaction.response.send_message("❌ Format invalide. Exemple : heure `06:00`, jours `tous`.", ephemeral=True)
            return
        slot = {"time": f"{t // 60:02d}:{t % 60:02d}", "days": days}
        slots = [s for s in restarts.get_schedule(gid) if s.get("time") != slot["time"]] + [slot]
        restarts.set_schedule(gid, slots)
        await interaction.response.send_message(self._restart_text(gid), ephemeral=True)

    @restart.command(name="retirer", description="Supprime un redémarrage planifié")
    @app_commands.describe(heure="Heure à retirer, ex. 06:00")
    async def restart_remove(self, interaction: discord.Interaction, heure: str):
        gid = str(interaction.guild_id)
        t = mod.parse_hm(heure)
        hm = f"{t // 60:02d}:{t % 60:02d}" if t >= 0 else heure
        slots = restarts.get_schedule(gid)
        kept = [s for s in slots if s.get("time") != hm]
        restarts.set_schedule(gid, kept)
        prefix = "🗑️ Retiré.\n" if len(kept) != len(slots) else f"Aucun redémarrage à {hm}.\n"
        await interaction.response.send_message(prefix + self._restart_text(gid), ephemeral=True)

    @restart.command(name="liste", description="Redémarrages planifiés et prochains passages")
    async def restart_list(self, interaction: discord.Interaction):
        await interaction.response.send_message(self._restart_text(str(interaction.guild_id)), ephemeral=True)

    @restart.command(name="maintenant", description="Redémarre le serveur après un compte à rebours")
    @app_commands.describe(delai="Minutes avant le redémarrage (0-60, défaut 5)")
    async def restart_now(self, interaction: discord.Interaction, delai: int = 5):
        await interaction.response.defer(ephemeral=True)
        cfg = await _require_server(interaction)
        if not cfg:
            return
        delai = min(max(delai, 0), 60)
        when = (datetime.now() + timedelta(minutes=delai)).replace(second=0, microsecond=0)
        if delai == 0:
            when = datetime.now().replace(microsecond=0)
        restarts.schedule_oneoff(cfg.guild_id, when)
        await interaction.followup.send(
            f"✅ Redémarrage prévu à **{when:%H:%M}**"
            + (" (dans quelques secondes)." if delai == 0 else " — annonces dans #annonces.")
            + "\nAnnuler : `/restart annuler`.",
            ephemeral=True,
        )

    @restart.command(name="annuler", description="Annule le redémarrage immédiat en attente")
    async def restart_cancel(self, interaction: discord.Interaction):
        ok = restarts.cancel_oneoff(str(interaction.guild_id))
        await interaction.response.send_message(
            "✅ Redémarrage annulé." if ok else "Aucun redémarrage immédiat en attente "
            "(les redémarrages planifiés se retirent avec `/restart retirer`).",
            ephemeral=True,
        )

    @staticmethod
    def _restart_text(gid: str) -> str:
        slots = restarts.get_schedule(gid)
        lines = [f"• {s['time']} — {mod.describe_days(s.get('days', []))}" for s in slots] or ["• aucun"]
        nxt = restarts.next_restarts(gid)
        txt = "🔄 Redémarrages planifiés :\n" + "\n".join(lines)
        if nxt:
            txt += "\nProchains : " + ", ".join(
                f"{mod.DAY_NAMES[d.weekday()][:3]}. {d:%d/%m %H:%M}" for d in nxt)
        return txt + f"\nAnnonces à -15, -5 et -1 min dans #annonces.\n{_now_hint()}"
