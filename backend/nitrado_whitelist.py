"""
backend/nitrado_whitelist.py
Protocole Nitrado — whitelist & banlist du serveur DayZ (kit single-tenant).

Porté depuis codex-api/modules/unified_whitelist.py (SaaS multi-tenant).
Ce qui change par rapport à la source :
  • Plus de recherche du serveur en base (`_get_server`/`_resolve_sid`) : le kit
    pilote UN serveur, dont les identifiants viennent du .env local
    (NITRADO_TOKEN / NITRADO_SERVER_ID — mêmes variables que bot/config.py).
  • Plus de déchiffrement Fernet (`_decrypt_token`) : le token vit en clair dans
    le .env de la machine du client, comme DISCORD_TOKEN. Le
    chiffrement protégeait une table Supabase partagée entre clients — menace
    qui n'existe plus ici.
  • Appels HTTP passés en async (httpx.AsyncClient) : ils tournent désormais
    dans la boucle d'événements du bot, il ne faut pas la bloquer.

Les endpoints, les catégories/clés de settings et le format des payloads sont
repris À L'IDENTIQUE — c'est un protocole externe, pas de la logique métier.

╔══════════════════════════════════════════════════════════════════════════════╗
║ PROTECTION ANTI-RACE — lire avant toute modification                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ La whitelist et la banlist Nitrado se mettent à jour en READ-MODIFY-WRITE    ║
║ sur la TOTALITÉ du champ (`settings.general.whitelist`). Sans sérialisation, ║
║ deux opérations concurrentes (deux clics « Approuver » quasi simultanés)     ║
║ lisent la même liste et la 2ᵉ écriture écrase la 1ʳᵉ : lost update, le       ║
║ joueur n'arrive jamais dans Nitrado. Bug déjà survenu en production          ║
║ (corrigé le 22/06/2026 côté API).                                           ║
║                                                                              ║
║ Côté API SaaS : un threading.Lock PAR service_id (`_service_lock`), car      ║
║ FastAPI exécutait les endpoints sync dans un threadpool.                     ║
║ Côté kit : un seul process, un seul serveur, tout est asynchrone → un unique ║
║ asyncio.Lock module-level (`_nitrado_lock`) rend le même service.            ║
║                                                                              ║
║ RÈGLE : tout couple lecture→écriture d'une liste Nitrado passe par           ║
║ `_locked_edit()`. Ne jamais appeler write_whitelist()/write_banlist() à      ║
║ partir d'une lecture faite hors du verrou.                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
from typing import Callable, Optional

import httpx

from bot.config import load_config

logger = logging.getLogger("killfeed.nitrado_whitelist")

NITRADO_API = "https://api.nitrado.net"

# Timeouts repris de la source (lecture 15 s, écriture 30 s).
_READ_TIMEOUT  = 15
_WRITE_TIMEOUT = 30

# ─── Verrou anti-race (voir l'encadré en tête de fichier) ─────────────────────
# Un seul serveur DayZ par installation → un seul verrou suffit. Il couvre à la
# fois la whitelist et la banlist : `ban` touche les deux listes d'affilée et
# doit rester atomique vis-à-vis d'une approbation concurrente.
_nitrado_lock = asyncio.Lock()


# ─── Identifiants (.env local — cf. bot/config.py) ────────────────────────────

def _credentials() -> tuple[str, str]:
    """(token, service_id) du serveur Nitrado piloté par ce kit.

    Passe par bot/config.py — source unique de la configuration, partagée avec
    backend/database.py (qui injecte le même token dans ServerConfig).

    NITRADO_SERVER_ID = l'identifiant de SERVICE Nitrado (celui qui apparaît
    dans les URLs /services/{id}/gameservers), pas l'UUID interne du SaaS.
    """
    cfg        = load_config()
    token      = cfg.nitrado_token
    service_id = cfg.nitrado_server_id
    if not token or not service_id:
        raise RuntimeError(
            "NITRADO_TOKEN / NITRADO_SERVER_ID manquants dans le .env — "
            "impossible de joindre la whitelist Nitrado."
        )
    return token, service_id


def _parse_list(raw: str) -> list[str]:
    """Un nom par ligne, CRLF ou LF, lignes vides ignorées (format Nitrado)."""
    if not raw:
        return []
    return [line.strip() for line in raw.replace("\r\n", "\n").splitlines() if line.strip()]


async def _read_setting_strict(key: str) -> list[str]:
    """Lit settings.general.<key> et le découpe en lignes. LÈVE en cas d'échec.

    Indispensable avant toute réécriture : une lecture ratée prise pour une
    liste vide ferait réécrire la liste ENTIÈRE avec un seul nom (whitelist
    ou banlist effacée).
    """
    token, service_id = _credentials()
    async with httpx.AsyncClient(timeout=_READ_TIMEOUT) as client:
        r = await client.get(
            f"{NITRADO_API}/services/{service_id}/gameservers",
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        gs = r.json().get("data", {}).get("gameserver", {})
        general = gs.get("settings", {}).get("general")
        if not isinstance(general, dict):
            raise RuntimeError("réponse Nitrado sans settings.general")
        return _parse_list(general.get(key, ""))


async def _read_setting(key: str) -> list[str]:
    """Lecture tolérante pour l'affichage : [] si Nitrado est indisponible."""
    try:
        return await _read_setting_strict(key)
    except Exception as e:
        logger.warning(f"[Nitrado] Lecture {key} échouée: {e}")
        return []


async def _write_setting(key: str, entries: list[str]) -> bool:
    """Écrit settings.general.<key> via POST /gameservers/settings."""
    token, service_id = _credentials()
    content = "\r\n".join(entries)
    try:
        async with httpx.AsyncClient(timeout=_WRITE_TIMEOUT) as client:
            r = await client.post(
                f"{NITRADO_API}/services/{service_id}/gameservers/settings",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "category": "general",
                    "key":      key,
                    "value":    content,
                },
            )
            r.raise_for_status()
        logger.info(f"[Nitrado] {key} écrite ({len(entries)} entrées)")
        return True
    except httpx.HTTPStatusError as e:
        logger.error(f"[Nitrado] Écriture {key} HTTP {e.response.status_code}: {e.response.text[:300]}")
        return False
    except Exception as e:
        logger.error(f"[Nitrado] Écriture {key} échouée: {e}")
        return False


# ─── Whitelist ────────────────────────────────────────────────────────────────

async def read_whitelist() -> list[str]:
    """Whitelist Nitrado réelle — SOURCE DE VÉRITÉ. [] si Nitrado indisponible."""
    return await _read_setting("whitelist")


async def write_whitelist(entries: list[str]) -> bool:
    """Écriture brute. À n'appeler que sous `_nitrado_lock` (cf. _locked_edit)."""
    return await _write_setting("whitelist", entries)


async def read_banlist() -> list[str]:
    return await _read_setting("bans")


async def read_banlist_strict() -> list[str]:
    """Comme read_banlist, mais lève si Nitrado est injoignable (≠ liste vide)."""
    return await _read_setting_strict("bans")


async def write_banlist(entries: list[str]) -> bool:
    """Écriture brute. À n'appeler que sous `_nitrado_lock` (cf. _locked_edit)."""
    return await _write_setting("bans", entries)


# ─── Read-modify-write sérialisé ──────────────────────────────────────────────

async def _locked_edit(key: str, mutate: Callable[[list[str]], Optional[list[str]]]) -> bool:
    """Lit la liste, applique `mutate`, réécrit — le tout sous le verrou.

    `mutate` reçoit la liste courante et retourne la nouvelle liste, ou None
    pour signifier « rien à faire » (pas d'écriture, succès).
    """
    async with _nitrado_lock:
        try:
            current = await _read_setting_strict(key)
        except Exception as e:
            # Jamais d'écriture sans lecture fiable (cf. _read_setting_strict)
            logger.error(f"[Nitrado] Lecture {key} impossible, modification annulée : {e}")
            return False
        updated = mutate(list(current))
        if updated is None:
            return True
        return await _write_setting(key, updated)


async def add_to_whitelist(psn_id: str) -> bool:
    """Ajoute un joueur (idempotent). Read-modify-write sérialisé."""
    psn_id = psn_id.strip()

    def _mutate(current: list[str]) -> Optional[list[str]]:
        if psn_id in current:
            return current  # réécriture volontaire : confirme l'état Nitrado
        return current + [psn_id]

    return await _locked_edit("whitelist", _mutate)


async def remove_from_whitelist(psn_id: str, ignore_case: bool = False) -> tuple[bool, bool]:
    """Retire un joueur. Retourne (présent_avant, écriture_ok).

    `ignore_case` reproduit la comparaison insensible à la casse de la route
    DELETE /whitelist/nitrado/{player_name} (retrait manuel / départ Discord) ;
    par défaut la comparaison est exacte, comme remove_player() côté API.
    """
    psn_id = psn_id.strip()
    needle = psn_id.lower()
    state  = {"found": False}

    def _mutate(current: list[str]) -> Optional[list[str]]:
        if ignore_case:
            updated = [p for p in current if p.strip().lower() != needle]
        else:
            updated = [p for p in current if p != psn_id]
        state["found"] = len(updated) != len(current)
        if not state["found"]:
            return None  # rien à retirer → pas d'écriture inutile
        return updated

    ok = await _locked_edit("whitelist", _mutate)
    return state["found"], ok


async def add_to_banlist(psn_id: str) -> bool:
    """Ajoute à la banlist persistante Nitrado (idempotent)."""
    psn_id = psn_id.strip()

    def _mutate(current: list[str]) -> Optional[list[str]]:
        if psn_id in current:
            return None
        return current + [psn_id]

    return await _locked_edit("bans", _mutate)


async def remove_from_banlist(psn_id: str) -> tuple[bool, bool]:
    """Retire de la banlist (comparaison insensible à la casse, comme l'API)."""
    needle = psn_id.strip().lower()
    state  = {"found": False}

    def _mutate(current: list[str]) -> Optional[list[str]]:
        updated = [p for p in current if p.strip().lower() != needle]
        state["found"] = len(updated) != len(current)
        return updated if state["found"] else None

    ok = await _locked_edit("bans", _mutate)
    return state["found"], ok


# ─── Lecture de contrôle ──────────────────────────────────────────────────────

async def is_psn_whitelisted(psn_id: str) -> bool:
    """Le PSN/Gamertag est-il dans la whitelist Nitrado réelle ?

    Comparaison insensible à la casse. Fail-open (False) si Nitrado est
    indisponible : on ne bloque pas une demande sur une panne externe —
    comportement identique à is_psn_in_nitrado_whitelist() côté API.
    """
    needle  = psn_id.strip().lower()
    if not needle:
        return False
    current = await read_whitelist()
    return any(entry.strip().lower() == needle for entry in current)
