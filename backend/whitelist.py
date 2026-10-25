"""
backend/whitelist.py
Logique métier whitelist — en process, single-tenant.

Porté depuis codex-api (SaaS) :
  • modules/unified_whitelist.py  → add_player / remove_player / registre joueurs
  • modules/whitelist_request.py  → config, demandes, anti-spam, validation
  • main.py (routes /killfeed/{guild}/whitelist-request/*) → l'ORCHESTRATION
    (submit_request / approve_request / refuse_request), qui vivait dans les
    endpoints FastAPI et n'existait donc nulle part ailleurs.

Le bot n'appelle plus d'API HTTP : tout tourne dans le même process.

Ce qui a été retiré volontairement (décisions de portage) :
  • server_id / service_id / _resolve_sid / _get_server : le kit pilote UN
    serveur DayZ, décrit par le .env (cf. backend/nitrado_whitelist.py).
  • _decrypt_token : plus de chiffrement du token Nitrado (voir nitrado_whitelist).
  • get_guilds_for_player / unlink_player_discord / get_guild_members /
    get_guild_roles : fonctions du dashboard SaaS, aucun rôle dans le flux
    demande → approbation (les rôles Discord sont résolus par discord.py
    directement dans bot/whitelist_request.py).
  • ban_player : chaînait un RCON #ban issu des systèmes de modération
    (NO-PVP / auto-ban suicide) élagués à la passe précédente. Les primitives
    banlist Nitrado restent disponibles dans backend/nitrado_whitelist.py.

`guild_id` est conservé : c'est l'axe de toutes les tables du kit
(channels, players, whitelist…) et le bot le tient de l'interaction Discord.

Répartition des responsabilités :
  • Nitrado (source de vérité + verrou anti-race) → backend/nitrado_whitelist.py
  • Discord (salons, embeds, boutons)             → bot/whitelist_request.py
  • Ici                                           → DB + enchaînement métier
"""

import logging
import re
from datetime import datetime, timezone

from backend import database as db
from backend import nitrado_whitelist as nitrado

logger = logging.getLogger("killfeed.whitelist")

# Validation ID joueur : 3-20 chars, alphanumérique + _ - .
ID_REGEX = re.compile(r"^[A-Za-z0-9._-]{3,20}$")


def _sb():
    return db.get_client()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Validation ───────────────────────────────────────────────────────────────

def validate_id(player_id: str) -> tuple[bool, str]:
    pid = (player_id or "").strip()
    if not ID_REGEX.match(pid):
        return False, "Format invalide. 3-20 caractères, lettres/chiffres/_-. uniquement."
    return True, pid


# ─── Config de la whitelist publique ──────────────────────────────────────────

def get_config(guild_id: str) -> dict:
    res = _sb().table("whitelist_config").select("*").eq("guild_id", guild_id).limit(1).execute()
    if res.data:
        return res.data[0]
    return {
        "guild_id":           guild_id,
        "enabled":            False,
        "role_id":            None,
        "approved_role_id":   None,
        "request_channel_id": None,
        "logs_channel_id":    None,
        "message_id":         None,
        "questionnaire":      [],
    }


def upsert_config(guild_id: str, **fields) -> dict:
    _sb().table("whitelist_config").upsert({
        "guild_id":   guild_id,
        **fields,
        "updated_at": _now(),
    }, on_conflict="guild_id").execute()
    return get_config(guild_id)


# ─── Registre joueurs (table players — lien PSN ↔ Discord) ───────────────────

def get_players(guild_id: str) -> list[dict]:
    res = _sb().table("players").select("*") \
        .eq("guild_id", guild_id) \
        .order("registered_at", desc=True).execute()
    return res.data or []


def get_players_by_discord(guild_id: str, discord_id: str) -> list[dict]:
    """Joueurs whitelistés liés à ce compte Discord (auto-remove au départ)."""
    res = _sb().table("players").select("*") \
        .eq("guild_id", guild_id) \
        .eq("discord_id", discord_id) \
        .eq("status", "whitelisted").execute()
    return res.data or []


async def add_player(
    guild_id:      str,
    psn_id:        str,
    discord_id:    str = "",
    discord_name:  str = "",
    registered_by: str = "bot",
    staff_notes:   str = "",
) -> dict:
    """Whiteliste un joueur : players → Nitrado → cache `whitelist`.

    Nitrado est la source de vérité : si une ligne `players` existe mais que le
    PSN n'est PAS réellement dans la whitelist Nitrado (WL vidée par un admin),
    l'entrée est considérée obsolète et réactivée au lieu d'être rejetée.
    Si l'écriture Nitrado échoue, la ligne `players` est annulée (rollback) —
    jamais de joueur « enregistré » qui ne peut pas se connecter.
    """
    sb     = _sb()
    psn_id = psn_id.strip()

    # ── 1. Doublons ───────────────────────────────────────────────────────────
    existing = None

    dup_psn = sb.table("players").select("id,psn_id,discord_id,status") \
        .eq("guild_id", guild_id).eq("psn_id", psn_id).limit(1).execute()
    if dup_psn.data:
        existing = dup_psn.data[0]
        if await nitrado.is_psn_whitelisted(psn_id):
            return {
                "success": False,
                "message": f"PSN '{psn_id}' déjà enregistré "
                           f"(lié à Discord {existing['discord_id'] or 'aucun'}, statut: {existing['status']})",
            }

    if existing is None and discord_id:
        dup_dc = sb.table("players").select("id,psn_id,discord_id,status") \
            .eq("guild_id", guild_id).eq("discord_id", discord_id).limit(1).execute()
        if dup_dc.data:
            existing = dup_dc.data[0]
            old_psn  = (existing.get("psn_id") or "").strip()
            if old_psn and old_psn.lower() != psn_id.lower() \
               and await nitrado.is_psn_whitelisted(old_psn):
                return {
                    "success": False,
                    "message": f"Discord ID '{discord_id}' déjà lié au PSN '{old_psn}'",
                }

    # ── 2. Écriture players — insert ou réactivation ──────────────────────────
    reactivated = existing is not None
    try:
        payload = {
            "guild_id":      guild_id,
            "psn_id":        psn_id,
            "discord_id":    discord_id,
            "discord_name":  discord_name,
            "status":        "whitelisted",
            "staff_notes":   staff_notes,
            "registered_by": registered_by,
        }
        if reactivated:
            upd        = sb.table("players").update(payload).eq("id", existing["id"]).execute()
            player_row = upd.data[0] if upd.data else None
            player_id  = existing["id"]
            logger.info(f"[Whitelist] Ligne {player_id} réactivée (WL Nitrado obsolète)")
        else:
            ins        = sb.table("players").insert(payload).execute()
            player_row = ins.data[0] if ins.data else None
            player_id  = player_row["id"] if player_row else None
    except Exception as e:
        return {"success": False, "message": f"Erreur DB players: {e}"}

    # ── 3. Nitrado (read-modify-write sérialisé — cf. nitrado_whitelist) ──────
    nitrado_ok = await nitrado.add_to_whitelist(psn_id)

    if not nitrado_ok:
        logger.error(f"[Whitelist] Rollback player {psn_id} — Nitrado KO")
        try:
            if reactivated:
                sb.table("players").update({"status": "removed"}).eq("id", player_id).execute()
            else:
                sb.table("players").delete().eq("id", player_id).execute()
        except Exception as re_:
            logger.error(f"[Whitelist] Rollback échoué: {re_}")
        return {
            "success": False,
            "message": "Erreur écriture whitelist Nitrado — aucune modification enregistrée.",
        }

    # ── 4. Cache/registre interne `whitelist` ─────────────────────────────────
    try:
        sb.table("whitelist").upsert({
            "guild_id":    guild_id,
            "player_name": psn_id,
            "added_by":    registered_by,
            "note":        f"Discord: {discord_name} ({discord_id})" if discord_id else staff_notes,
        }, on_conflict="guild_id,player_name").execute()
    except Exception as e:
        logger.warning(f"[Whitelist] Cache whitelist non mis à jour: {e}")

    logger.info(f"[Whitelist] {psn_id} ↔ {discord_id or '—'} ajouté")
    return {
        "success": True,
        "message": f"✅ {psn_id} whitelisté — lien PSN↔Discord établi",
        "player":  player_row,
        "nitrado": nitrado_ok,
    }


async def remove_player(guild_id: str, psn_id: str) -> dict:
    """Retire un joueur enregistré : DB (players + whitelist) puis Nitrado."""
    sb     = _sb()
    psn_id = psn_id.strip()

    exists = sb.table("players").select("id") \
        .eq("guild_id", guild_id).eq("psn_id", psn_id).limit(1).execute()
    if not exists.data:
        return {"success": False, "message": f"PSN '{psn_id}' introuvable"}

    try:
        sb.table("players").delete().eq("guild_id", guild_id).eq("psn_id", psn_id).execute()
        sb.table("whitelist").delete().eq("guild_id", guild_id).eq("player_name", psn_id).execute()
    except Exception as e:
        return {"success": False, "message": f"Erreur DB: {e}"}

    _, nitrado_ok = await nitrado.remove_from_whitelist(psn_id)

    msg = f"✅ {psn_id} retiré de la whitelist"
    if not nitrado_ok:
        msg += " (DB uniquement — Nitrado indisponible)"
    logger.info(f"[Whitelist] {psn_id} retiré")
    return {"success": True, "message": msg}


async def remove_from_nitrado(guild_id: str, player_name: str) -> dict:
    """Retrait par le nom Nitrado (casse ignorée) + nettoyage DB si présent.

    Port de DELETE /killfeed/{guild}/whitelist/nitrado/{player_name} : utilisé
    quand on part de la whitelist Nitrado (départ Discord, retrait manuel) et
    non d'une ligne `players`.
    """
    found, ok = await nitrado.remove_from_whitelist(player_name, ignore_case=True)
    if not found:
        return {"success": False, "message": f"{player_name} non trouvé dans la whitelist Nitrado"}
    if not ok:
        return {"success": False, "message": "Erreur lors de l'écriture sur Nitrado"}

    sb = _sb()
    try:
        sb.table("players").delete().eq("guild_id", guild_id).ilike("psn_id", player_name).execute()
        sb.table("whitelist").delete().eq("guild_id", guild_id).ilike("player_name", player_name).execute()
    except Exception as e:
        logger.warning(f"[Whitelist] Nettoyage DB après retrait Nitrado: {e}")

    return {"success": True, "message": f"{player_name} retiré de la whitelist"}


# ─── Demandes — anti-spam ─────────────────────────────────────────────────────

def has_pending_request(guild_id: str, discord_id: str) -> bool:
    res = _sb().table("whitelist_requests").select("id") \
        .eq("guild_id", guild_id) \
        .eq("discord_id", discord_id) \
        .eq("status", "pending").limit(1).execute()
    return bool(res.data)


async def is_already_whitelisted(guild_id: str, discord_id: str) -> bool:
    """Le compte Discord est-il déjà whitelisté ? Nitrado fait foi.

    Une ligne `players` sans contrepartie dans la whitelist Nitrado est une
    entrée périmée : on la marque `removed` et on répond False (sinon le joueur
    reste bloqué « déjà whitelisté » alors qu'il ne peut pas se connecter).
    Si Nitrado est injoignable, on retombe sur la DB pour ne pas tout bloquer.
    """
    res = _sb().table("players").select("id,status,psn_id") \
        .eq("guild_id", guild_id) \
        .eq("discord_id", discord_id) \
        .eq("status", "whitelisted").limit(1).execute()
    if not res.data:
        return False

    player = res.data[0]
    psn_id = (player.get("psn_id") or "").strip()
    if not psn_id:
        return False

    try:
        in_nitrado = await nitrado.is_psn_whitelisted(psn_id)
    except Exception as e:
        logger.warning(f"[Whitelist] Cross-check Nitrado indispo, fallback DB: {e}")
        return True

    if not in_nitrado:
        try:
            _sb().table("players").update({"status": "removed"}).eq("id", player["id"]).execute()
            logger.info(f"[Whitelist] Entrée périmée nettoyée: {psn_id} (discord={discord_id})")
        except Exception as e:
            logger.warning(f"[Whitelist] Nettoyage entrée périmée échoué: {e}")

    return in_nitrado


async def check_request(guild_id: str, discord_id: str) -> dict:
    """Pré-check du bouton public : peut-on ouvrir le formulaire ?"""
    return {
        "pending":     has_pending_request(guild_id, discord_id),
        "whitelisted": await is_already_whitelisted(guild_id, discord_id),
    }


# ─── Demandes — CRUD ──────────────────────────────────────────────────────────

def create_request(guild_id: str, discord_id: str, discord_name: str, player_id: str,
                   questionnaire_answers: dict | None = None) -> dict:
    ins = _sb().table("whitelist_requests").insert({
        "guild_id":              guild_id,
        "discord_id":            discord_id,
        "discord_name":          discord_name,
        "player_id":             player_id,
        "status":                "pending",
        "questionnaire_answers": questionnaire_answers or {},
    }).execute()
    return ins.data[0] if ins.data else {}


def get_request(request_id: str) -> dict | None:
    res = _sb().table("whitelist_requests").select("*") \
        .eq("id", request_id).limit(1).execute()
    return res.data[0] if res.data else None


def mark_request(request_id: str, status: str, processed_by: str, reason: str = "") -> dict:
    _sb().table("whitelist_requests").update({
        "status":       status,
        "processed_by": processed_by,
        "processed_at": _now(),
        "reason":       reason,
    }).eq("id", request_id).execute()
    return get_request(request_id) or {}


# ─── Orchestration (ex-endpoints FastAPI) ─────────────────────────────────────

async def submit_request(guild_id: str, discord_id: str, discord_name: str, player_id: str,
                         questionnaire_answers: dict | None = None) -> dict:
    """Enregistre une demande après validation — port de POST /whitelist-request."""
    ok, payload = validate_id(player_id)
    if not ok:
        return {"success": False, "message": payload}
    if has_pending_request(guild_id, discord_id):
        return {"success": False, "message": "Tu as déjà une demande en attente."}
    if await is_already_whitelisted(guild_id, discord_id):
        return {"success": False, "message": "Tu es déjà whitelisté sur ce serveur."}
    if await nitrado.is_psn_whitelisted(payload):
        return {
            "success": False,
            "message": f"Le PSN/Gamertag `{payload}` est déjà whitelisté sur ce serveur — "
                       "aucune demande nécessaire.",
        }
    row = create_request(guild_id, discord_id, discord_name, payload, questionnaire_answers or {})
    return {"success": True, "request": row}


async def approve_request(guild_id: str, request_id: str, processed_by: str) -> dict:
    """Approuve : whiteliste sur Nitrado PUIS marque la demande.

    Ordre volontaire : `mark_request` n'est fait qu'après un add_player réussi,
    sinon une demande marquée « approved » pourrait ne jamais atterrir dans
    Nitrado. Le self-heal ci-dessous rattrape les cas historiques : demande déjà
    marquée approved mais joueur absent de la whitelist réelle → on ré-ajoute.
    """
    request = get_request(request_id)
    if not request or request.get("guild_id") != guild_id:
        return {"success": False, "message": "Demande introuvable."}

    status = request.get("status")
    if status == "refused":
        return {"success": False, "message": "Demande déjà refusée."}
    if status == "approved":
        if await nitrado.is_psn_whitelisted(request["player_id"]):
            return {"success": True, "message": "Déjà whitelisté ✅", "request": request}
        # absent de Nitrado malgré 'approved' → on retombe sur add_player

    result = await add_player(
        guild_id=guild_id,
        psn_id=request["player_id"],
        discord_id=request.get("discord_id", ""),
        discord_name=request.get("discord_name", ""),
        registered_by=f"wl_request:{processed_by}",
    )
    if not result.get("success"):
        return result

    mark_request(request_id, "approved", processed_by, "")
    return {
        "success": True,
        "message": result.get("message", "Approuvé"),
        "request": get_request(request_id),
    }


def refuse_request(guild_id: str, request_id: str, processed_by: str, reason: str = "") -> dict:
    request = get_request(request_id)
    if not request or request.get("guild_id") != guild_id:
        return {"success": False, "message": "Demande introuvable."}
    if request.get("status") != "pending":
        return {"success": False, "message": f"Demande déjà traitée ({request.get('status')})"}
    mark_request(request_id, "refused", processed_by, reason or "")
    return {"success": True, "request": get_request(request_id)}


# ─── Lecture Nitrado (commande /wl) ───────────────────────────────────────────

async def read_nitrado_whitelist() -> dict:
    entries = await nitrado.read_whitelist()
    return {"count": len(entries), "entries": entries}
