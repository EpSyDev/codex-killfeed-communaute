"""
bot/whitelist_request.py
Whitelist publique — couche Discord (salon public, modals, boutons admin).

Kit single-tenant : plus aucun appel HTTP vers l'API SaaS. Toute la logique
métier (anti-spam, Nitrado, stockage, verrou anti-race) vit dans
backend/whitelist.py et backend/nitrado_whitelist.py, appelés directement.

Flux :
1. Joueur clique « 📝 Demander la whitelist » → pré-check → Modal de saisie ID
2. (optionnel) questionnaire admin → Modal dynamique
3. La demande est enregistrée puis annoncée dans #logs-whitelist avec les
   boutons ✅ Approuver / ❌ Refuser
4. Approbation → écriture Nitrado (sous verrou) + rôle « whitelisté » + DM joueur

La création/suppression du salon public (ex-endpoints /whitelist-request/setup)
se fait ici avec discord.py — le bot est dans la guild, plus besoin de passer
par l'API REST Discord avec un token.
"""

import logging
from datetime import datetime

import discord
from discord import ui

from backend import whitelist as wl

logger = logging.getLogger("killfeed.wl_request")

# Custom IDs des Views persistantes
CID_REQUEST_BUTTON       = "wl_request"
CID_APPROVE_PREFIX       = "wl_approve:"
CID_REFUSE_PREFIX        = "wl_refuse:"
CID_QUESTIONNAIRE_PREFIX = "wl_questionnaire:"

REQUEST_CHANNEL_NAME = "demande-whitelist"


async def _resolve_logs_channel(bot: discord.Client, guild_id: str):
    """Salon #logs-whitelist de la guild (un seul serveur DayZ par installation)."""
    from bot.channel_resolver import resolve_channel
    return await resolve_channel(bot, guild_id, "logs-whitelist")


# ─── Embed + View du salon public ─────────────────────────────────────────────

def build_request_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🛡️  Demande de whitelist",
        description=(
            "Pour rejoindre le serveur, clique sur le bouton ci-dessous et indique "
            "ton **ID PSN** ou **Gamertag Xbox** exact (tel qu'il apparaît en jeu).\n\n"
            "Un administrateur examinera ta demande dans les plus brefs délais.\n\n"
            "⚠️ Ta demande est privée — toi seul vois ta saisie."
        ),
        color=0x4a8fd4,
    )
    embed.set_footer(text="CodeX KillFeed · Whitelist publique")
    return embed


class WhitelistRequestView(ui.View):
    """View permanente — le bouton « Demander la whitelist » du salon public."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="📝 Demander la whitelist",
               style=discord.ButtonStyle.primary,
               custom_id=CID_REQUEST_BUTTON)
    async def on_request(self, interaction: discord.Interaction, _button: ui.Button):
        await _precheck_then_modal(interaction,
                                   str(interaction.guild_id),
                                   str(interaction.user.id))


# ─── Setup / teardown du salon public (ex-endpoints API) ─────────────────────

async def setup_request_channel(bot: discord.Client, guild: discord.Guild,
                                role: discord.Role) -> dict:
    """Crée le salon `demande-whitelist`, y poste le panneau, sauvegarde la config.

    Un salon déjà configuré est supprimé d'abord (clean restart), comme le
    faisait setup_channel() côté API.
    """
    guild_id = str(guild.id)
    cfg      = wl.get_config(guild_id)

    old_id = cfg.get("request_channel_id")
    if old_id:
        await _delete_channel(guild, old_id)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role:               discord.PermissionOverwrite(view_channel=True, send_messages=False),
        guild.me:           discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            embed_links=True, manage_messages=True, read_message_history=True,
        ),
    }
    channel = await guild.create_text_channel(
        name=REQUEST_CHANNEL_NAME,
        topic="Demandez votre whitelist en cliquant sur le bouton.",
        overwrites=overwrites,
    )
    message = await channel.send(embed=build_request_embed(), view=WhitelistRequestView())

    # Mémorise le salon de logs courant (informatif — la résolution réelle
    # passe toujours par channel_resolver au moment d'écrire).
    try:
        logs = await _resolve_logs_channel(bot, guild_id)
    except Exception:
        logs = None

    return wl.upsert_config(
        guild_id,
        enabled=True,
        role_id=str(role.id),
        request_channel_id=str(channel.id),
        logs_channel_id=str(logs.id) if logs else None,
        message_id=str(message.id),
    )


async def teardown_request_channel(guild: discord.Guild) -> dict:
    guild_id = str(guild.id)
    cfg      = wl.get_config(guild_id)
    if cfg.get("request_channel_id"):
        await _delete_channel(guild, cfg["request_channel_id"])
    return wl.upsert_config(
        guild_id,
        enabled=False,
        request_channel_id=None,
        message_id=None,
    )


async def repost_request_message(guild: discord.Guild) -> dict:
    """Repost le panneau dans le salon existant (message supprimé par erreur)."""
    guild_id = str(guild.id)
    cfg      = wl.get_config(guild_id)
    channel_id = cfg.get("request_channel_id")
    if not channel_id:
        raise ValueError("Aucun salon de demande configuré.")
    channel = guild.get_channel(int(channel_id)) or await guild.fetch_channel(int(channel_id))
    message = await channel.send(embed=build_request_embed(), view=WhitelistRequestView())
    return wl.upsert_config(guild_id, message_id=str(message.id))


async def _delete_channel(guild: discord.Guild, channel_id: str) -> None:
    try:
        channel = guild.get_channel(int(channel_id)) or await guild.fetch_channel(int(channel_id))
        if channel:
            await channel.delete(reason="Whitelist publique — reconfiguration")
    except Exception as e:
        logger.warning(f"[WLRequest] Suppression salon {channel_id} échouée: {e}")


# ─── Embed admin ──────────────────────────────────────────────────────────────

def _build_admin_embed(discord_id: str, discord_name: str, player_id: str,
                       answers: dict | None = None, questions: list | None = None) -> discord.Embed:
    embed = discord.Embed(title="🆕  Nouvelle demande de whitelist", color=0x4a8fd4)
    embed.add_field(name="💬 Discord", value=f"<@{discord_id}>\n`{discord_name or discord_id}`", inline=True)
    embed.add_field(name="🎮 ID saisi", value=f"`{player_id}`", inline=True)
    if answers and questions:
        embed.add_field(name="​", value="​", inline=False)  # séparateur
        for q in questions:
            qid   = str(q.get("id", ""))
            label = q.get("label", f"Question {qid}")
            reply = answers.get(qid, "*(sans réponse)*")
            embed.add_field(name=f"❓ {label}", value=reply[:1024] or "*(vide)*", inline=False)
    embed.set_footer(text="Demande en attente — valide ou refuse ci-dessous.")
    embed.timestamp = datetime.utcnow()
    return embed


def _admin_view(request_id: str) -> ui.View:
    view = ui.View(timeout=None)
    view.add_item(ui.Button(
        label="✅ Approuver",
        style=discord.ButtonStyle.success,
        custom_id=f"{CID_APPROVE_PREFIX}{request_id}",
    ))
    view.add_item(ui.Button(
        label="❌ Refuser",
        style=discord.ButtonStyle.danger,
        custom_id=f"{CID_REFUSE_PREFIX}{request_id}",
    ))
    return view


# ─── Création de la demande + annonce admin ───────────────────────────────────

async def _post_request_and_notify(
    interaction: discord.Interaction,
    guild_id: str,
    discord_id: str,
    discord_name: str,
    pid: str,
    answers: dict | None,
    questions: list | None,
) -> None:
    try:
        result = await wl.submit_request(guild_id, discord_id, discord_name, pid, answers)
    except Exception as e:
        logger.error(f"[WLRequest] submit_request: {e}", exc_info=True)
        await interaction.followup.send("❌ Erreur serveur, réessaie plus tard.", ephemeral=True)
        return

    if not result.get("success"):
        await interaction.followup.send(f"❌ {result.get('message', 'Erreur inconnue')}", ephemeral=True)
        return

    request    = result.get("request", {})
    request_id = str(request.get("id", ""))

    channel = await _resolve_logs_channel(interaction.client, guild_id)
    if not channel:
        await interaction.followup.send(
            "✅ Demande enregistrée — mais le salon `logs-whitelist` est introuvable. "
            "Préviens un admin de configurer le KillFeed.",
            ephemeral=True,
        )
        return

    try:
        await channel.send(
            embed=_build_admin_embed(discord_id, discord_name, pid, answers, questions),
            view=_admin_view(request_id),
        )
    except Exception as e:
        logger.error(f"[WLRequest] Envoi embed admin échoué: {e}")

    await interaction.followup.send(
        "✅ Ta demande a été envoyée. Tu recevras une notification dès qu'un admin l'aura traitée.",
        ephemeral=True,
    )


# ─── Modals ───────────────────────────────────────────────────────────────────

class _QuestionnaireModal(ui.Modal, title="Questionnaire de whitelist"):
    """Modal dynamique — jusqu'à 5 questions définies par l'admin."""

    def __init__(self, questions: list, guild_id: str, discord_id: str,
                 discord_name: str, player_id: str):
        super().__init__()
        self._questions    = questions
        self._guild_id     = guild_id
        self._discord_id   = discord_id
        self._discord_name = discord_name
        self._player_id    = player_id
        self._inputs: list[ui.TextInput] = []
        for i, q in enumerate(questions[:5]):
            inp = ui.TextInput(
                label=q.get("label", f"Question {i+1}")[:45],
                style=discord.TextStyle.paragraph,
                required=False,
                max_length=500,
                custom_id=str(q.get("id", i)),
            )
            self.add_item(inp)
            self._inputs.append(inp)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        answers = {str(q.get("id", i)): (self._inputs[i].value or "").strip()
                   for i, q in enumerate(self._questions[:5])}
        await _post_request_and_notify(
            interaction, self._guild_id, self._discord_id, self._discord_name,
            self._player_id, answers, self._questions,
        )


class _RequestModal(ui.Modal, title="Demande de whitelist"):
    player_id = ui.TextInput(
        label="Ton ID PSN ou Gamertag Xbox",
        placeholder="ex: maximus91600",
        min_length=3, max_length=20, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild_id     = str(interaction.guild_id)
        discord_id   = str(interaction.user.id)
        discord_name = interaction.user.display_name
        pid          = self.player_id.value.strip()

        ok, payload = wl.validate_id(pid)
        if not ok:
            await interaction.response.send_message(f"❌ {payload}", ephemeral=True)
            return
        pid = payload

        try:
            cfg = wl.get_config(guild_id)
        except Exception:
            cfg = {}
        questions = cfg.get("questionnaire") or []

        if questions:
            # Étape 2 : message éphémère + bouton questionnaire.
            # custom_id : wl_questionnaire:{guild}:{discord}:{pid}
            # (pid ne contient jamais ':' — la regex d'ID l'interdit)
            custom_id = f"{CID_QUESTIONNAIRE_PREFIX}{guild_id}:{discord_id}:{pid}"
            view = ui.View(timeout=300)
            view.add_item(ui.Button(
                label="📋 Répondre au questionnaire",
                style=discord.ButtonStyle.primary,
                custom_id=custom_id,
            ))
            await interaction.response.send_message(
                "✅ ID enregistré ! **Étape 2/2** — réponds maintenant au questionnaire "
                "pour finaliser ta demande.",
                view=view,
                ephemeral=True,
            )
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
            await _post_request_and_notify(interaction, guild_id, discord_id,
                                           discord_name, pid, None, None)


class _RefuseReasonModal(ui.Modal, title="Refuser la demande"):
    reason = ui.TextInput(
        label="Raison (facultatif)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
        placeholder="Visible par le joueur en DM",
    )

    def __init__(self, request_id: str, original_message: discord.Message):
        super().__init__()
        self.request_id       = request_id
        self.original_message = original_message

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = str(interaction.guild_id)
        try:
            result = wl.refuse_request(guild_id, self.request_id,
                                       str(interaction.user.id), self.reason.value or "")
        except Exception as e:
            logger.error(f"[WLRequest] refuse_request: {e}", exc_info=True)
            await interaction.followup.send("❌ Erreur interne.", ephemeral=True)
            return

        if not result.get("success"):
            await interaction.followup.send(f"❌ {result.get('message', 'Erreur')}", ephemeral=True)
            return

        request = result.get("request", {}) or {}
        await _finalize_admin_message(
            self.original_message, "refused", interaction.user, request, self.reason.value or "",
        )
        server_name = interaction.guild.name if interaction.guild else ""
        await _notify_player(interaction.client, request, "refused", self.reason.value or "", server_name)
        await interaction.followup.send("✅ Demande refusée.", ephemeral=True)


# ─── Update embed admin + DM joueur ───────────────────────────────────────────

async def _finalize_admin_message(message: discord.Message, status: str,
                                  admin: discord.User, request: dict, reason: str):
    """Édite l'embed admin pour montrer le statut + retire les boutons."""
    if not message:
        return
    try:
        embed = message.embeds[0] if message.embeds else discord.Embed()
        if status == "approved":
            embed.title = "✅  Demande approuvée"
            embed.color = discord.Color.from_rgb(52, 211, 153)
            embed.add_field(name="👤 Approuvée par", value=f"<@{admin.id}>", inline=False)
        else:
            embed.title = "❌  Demande refusée"
            embed.color = discord.Color.from_rgb(239, 68, 68)
            embed.add_field(name="👤 Refusée par", value=f"<@{admin.id}>", inline=False)
            if reason:
                embed.add_field(name="📝 Raison", value=reason[:1024], inline=False)
        await message.edit(embed=embed, view=None)
    except Exception as e:
        logger.warning(f"[WLRequest] Edit admin message échoué: {e}")


async def _notify_player(bot: discord.Client, request: dict, status: str,
                         reason: str, server_name: str = ""):
    discord_id = request.get("discord_id")
    if not discord_id:
        return
    try:
        user = await bot.fetch_user(int(discord_id))
        server_suffix = f" sur **{server_name}**" if server_name else ""
        if status == "approved":
            text = (
                f"✅ Ta demande de whitelist (`{request.get('player_id', '')}`){server_suffix} "
                "a été **approuvée**.\nTu peux te connecter au serveur."
            )
        else:
            text = f"❌ Ta demande de whitelist (`{request.get('player_id', '')}`){server_suffix} a été **refusée**."
            if reason:
                text += f"\n**Raison :** {reason}"
        await user.send(text)
    except Exception as e:
        logger.info(f"[WLRequest] DM joueur {discord_id} impossible: {e}")


# ─── Pré-check avant ouverture du modal ───────────────────────────────────────

async def _precheck_then_modal(interaction: discord.Interaction,
                               guild_id: str, discord_id: str) -> None:
    """Pré-check (déjà whitelisté / demande en attente) PUIS ouverture du modal.

    Doit être la 1ʳᵉ réponse à l'interaction (send_message OU send_modal).
    """
    try:
        check = await wl.check_request(guild_id, discord_id)
    except Exception as e:
        logger.error(f"[WLRequest] check échoué: {e}", exc_info=True)
        await interaction.response.send_message(
            "❌ Service indisponible, réessaie plus tard.", ephemeral=True)
        return

    if check.get("whitelisted"):
        await interaction.response.send_message(
            "✅ Tu es déjà whitelisté sur ce serveur — aucune demande nécessaire.", ephemeral=True)
        return
    if check.get("pending"):
        await interaction.response.send_message(
            "⏳ Tu as déjà une demande en attente de validation. Patiente !", ephemeral=True)
        return

    await interaction.response.send_modal(_RequestModal())


# ─── Attribution du rôle « whitelisté » ───────────────────────────────────────

async def _grant_approved_role(interaction: discord.Interaction, request: dict) -> None:
    """Donne le rôle configuré (`approved_role_id`) au joueur approuvé.

    Best-effort : ne fait jamais échouer l'approbation. Rappel : le bot ne peut
    attribuer qu'un rôle situé SOUS lui dans la hiérarchie Discord (sinon 403).
    """
    try:
        cfg = wl.get_config(str(interaction.guild_id))
        approved_role_id = cfg.get("approved_role_id")
        if not approved_role_id:
            return
        if not interaction.guild:
            logger.warning("[WLRequest] interaction.guild est None — rôle non attribué")
            return

        discord_id = request.get("discord_id")
        if not discord_id:
            logger.warning("[WLRequest] discord_id absent de la demande — skip rôle")
            return

        member = interaction.guild.get_member(int(discord_id))
        if member is None:
            try:
                member = await interaction.guild.fetch_member(int(discord_id))
            except discord.NotFound:
                logger.warning(f"[WLRequest] Membre {discord_id} introuvable dans la guild")
                return
            except Exception as fe:
                logger.warning(f"[WLRequest] fetch_member échoué: {fe}")
                return

        role = interaction.guild.get_role(int(approved_role_id)) \
            or discord.utils.get(interaction.guild.roles, id=int(approved_role_id))
        if role is None:
            logger.warning(f"[WLRequest] Rôle {approved_role_id} introuvable dans la guild")
            return

        await member.add_roles(role, reason="Whitelist approuvée")
        logger.info(f"[WLRequest] ✅ Rôle '{role.name}' attribué à {member.display_name}")
    except discord.Forbidden as e:
        logger.error(
            f"[WLRequest] Permission refusée pour attribuer le rôle "
            f"(bot trop bas dans la hiérarchie ?): {e}"
        )
    except Exception as e:
        logger.warning(f"[WLRequest] Attribution rôle échouée: {e}", exc_info=True)


# ─── Listener des boutons (custom_id dynamiques) ──────────────────────────────

async def handle_admin_interaction(interaction: discord.Interaction) -> bool:
    """À appeler depuis on_interaction. True si l'interaction a été gérée."""
    if interaction.type != discord.InteractionType.component:
        return False
    cid = interaction.data.get("custom_id", "") if interaction.data else ""

    # ── Bouton « Répondre au questionnaire » (éphémère, étape 2 joueur) ──
    if cid.startswith(CID_QUESTIONNAIRE_PREFIX):
        parts = cid[len(CID_QUESTIONNAIRE_PREFIX):].split(":")
        if len(parts) < 3:
            await interaction.response.send_message("❌ Lien invalide.", ephemeral=True)
            return True
        guild_id_q, discord_id_q, player_id_q = parts[0], parts[1], parts[2]
        if str(interaction.user.id) != discord_id_q:
            await interaction.response.send_message("❌ Ce bouton ne t'appartient pas.", ephemeral=True)
            return True
        try:
            cfg = wl.get_config(guild_id_q)
        except Exception:
            await interaction.response.send_message("❌ Erreur de configuration.", ephemeral=True)
            return True
        questions = cfg.get("questionnaire") or []
        if not questions:
            await interaction.response.send_message("❌ Questionnaire introuvable.", ephemeral=True)
            return True
        await interaction.response.send_modal(_QuestionnaireModal(
            questions=questions,
            guild_id=guild_id_q,
            discord_id=discord_id_q,
            discord_name=interaction.user.display_name,
            player_id=player_id_q,
        ))
        return True

    if not (cid.startswith(CID_APPROVE_PREFIX) or cid.startswith(CID_REFUSE_PREFIX)):
        return False

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Seuls les administrateurs peuvent traiter les demandes.", ephemeral=True)
        return True

    guild_id   = str(interaction.guild_id)
    is_approve = cid.startswith(CID_APPROVE_PREFIX)
    request_id = cid.split(":", 1)[1] if ":" in cid else ""
    if not request_id:
        await interaction.response.send_message("❌ ID de demande invalide.", ephemeral=True)
        return True

    if is_approve:
        # defer immédiat : approve_request enchaîne lecture + écriture Nitrado
        # (et peut attendre le verrou anti-race si une autre approbation est en
        # cours) — bien au-delà des 3 s de réponse initiale imposées par Discord.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await wl.approve_request(guild_id, request_id, str(interaction.user.id))
        except Exception as e:
            logger.error(f"[WLRequest] approve_request: {e}", exc_info=True)
            await interaction.followup.send("❌ Erreur interne.", ephemeral=True)
            return True

        if not result.get("success"):
            await interaction.followup.send(f"❌ {result.get('message', 'Erreur')}", ephemeral=True)
            return True

        request = result.get("request", {}) or {}
        await _finalize_admin_message(interaction.message, "approved", interaction.user, request, "")
        server_name = interaction.guild.name if interaction.guild else ""
        await _notify_player(interaction.client, request, "approved", "", server_name)
        await _grant_approved_role(interaction, request)

        await interaction.followup.send("✅ Joueur whitelisté.", ephemeral=True)
        return True

    # Refus → modal raison
    await interaction.response.send_modal(
        _RefuseReasonModal(request_id=request_id, original_message=interaction.message))
    return True


# ─── Auto-remove quand un membre quitte le Discord ────────────────────────────

async def auto_remove_on_leave(bot: discord.Client, guild_id: str, discord_id: str,
                               guild: discord.Guild, display_name: str) -> None:
    """on_member_remove : retire de la whitelist Nitrado le joueur qui s'en va."""
    try:
        players = wl.get_players_by_discord(guild_id, discord_id)
    except Exception as e:
        logger.warning(f"[WLRequest] auto_remove: lookup joueur échoué ({e})")
        return
    if not players:
        return

    removed: list[str] = []
    for player in players:
        psn_id = player.get("psn_id")
        if not psn_id:
            continue
        try:
            result = await wl.remove_from_nitrado(guild_id, psn_id)
            if result.get("success"):
                removed.append(psn_id)
                logger.info(f"[WLRequest] {psn_id} retiré auto (départ Discord: {display_name})")
            else:
                logger.warning(f"[WLRequest] Retrait auto {psn_id}: {result.get('message')}")
        except Exception as e:
            logger.warning(f"[WLRequest] Retrait auto {psn_id} échoué: {e}")

    if not removed:
        return

    try:
        channel = await _resolve_logs_channel(bot, guild_id)
        if channel:
            embed = discord.Embed(
                title="🚪 Départ Discord — Whitelist retirée automatiquement",
                color=0xef4444,
                description=(
                    f"**{display_name}** (`{discord_id}`) a quitté le Discord.\n"
                    f"`{'`, `'.join(removed)}` retiré(s) de la whitelist Nitrado."
                ),
            )
            embed.timestamp = datetime.utcnow()
            await channel.send(embed=embed)
    except Exception as e:
        logger.warning(f"[WLRequest] Notif départ Discord échouée: {e}")
