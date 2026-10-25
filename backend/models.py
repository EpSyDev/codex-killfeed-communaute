from pydantic import BaseModel
from datetime import datetime
from enum import Enum
from typing import Optional


class KillType(str, Enum):
    # ── Morts ────────────────────────────────────────────────────
    PVP          = "pvp"        # tué par joueur ou véhicule conduit par joueur
    PVE          = "pve"        # tué par entité monde (zombie, animal, env, faim...)
    SUICIDE      = "suicide"    # mort volontaire
    # ── Activité base ────────────────────────────────────────────
    BUILD        = "build"      # construction / déconstruction / barbelés / abri
    PLACE        = "place"      # placement / enterrement / déterrement
    CONNECTION   = "connection" # connexion / déconnexion
    # ── Drapeaux ─────────────────────────────────────────────────
    FLAG         = "flag"       # levé / baissé


# Mapping type → salon Discord
CHANNEL_MAP = {
    KillType.PVP:        "morts-pvp",
    KillType.PVE:        "morts-pve",
    KillType.SUICIDE:    "morts-pve",
    KillType.BUILD:      "constructions",
    KillType.PLACE:      "placements",
    KillType.CONNECTION: "connexions",
    KillType.FLAG:       "drapeaux",
}

# Canal dédié aux alertes intrusion (hors KillEvent — envoi direct depuis poller)
CHANNEL_ALERT_INTRUSION = "alerte-intrusion"


class ServerConfig(BaseModel):
    id:            Optional[int] = None
    server_id:     Optional[str] = None   # UUID stable — identifiant unique du serveur DayZ
    guild_id:      str
    nitrado_token: str
    service_id:    str
    server_name:   str  = "DayZ Server"
    server_alias:  str  = ""              # Nom court choisi par l'admin ("PVP", "PVE"...)
    map_name:      str  = "Chernarus"
    platform:      str  = "dayzps"
    username:      str  = ""
    active:        bool = True
    created_at:    Optional[datetime] = None


class KillEvent(BaseModel):
    id:           Optional[int]   = None
    guild_id:     str
    server_id:    Optional[str]   = None  # UUID du serveur DayZ source
    timestamp:    datetime
    log_time:     str
    kill_type:    KillType

    # Cause brute depuis le log (classname, entity, weapon...)
    cause:        Optional[str]   = None

    # Victime
    victim_name:  str
    victim_pos:   Optional[tuple[float, float, float]] = None

    # Tueur (PVP uniquement)
    killer_name:  Optional[str]   = None
    killer_pos:   Optional[tuple[float, float, float]] = None
    distance:     Optional[float] = None

    # Détail activité (build, place, flag...)
    detail:       Optional[str]   = None

    # Coups encaissés avant la mort (PVP) — transient, non persisté en DB
    # Liste de dicts : {attacker, bodypart, damage, weapon}
    hits_taken:   Optional[list]  = None

    raw_line:     Optional[str]   = None
