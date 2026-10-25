"""
Parser ADM v4.0 — DayZ PS4/XBOX uniquement
Patterns construits sur logs Nitrado réels (BADS Z PVE FRANCE, 10/03/2026)

Format PS4/XBOX :
  - Mort    : Player "V" (DEAD) (id=... pos=<x,y,z>) <événement>
  - Vivant  : Player "V" (id=... pos=<x,y,z>) <événement>
  - Connexion : Player "V"(id=...) is connected / has been disconnected

kill_type : pvp / pve / suicide / build / place / connection / flag
cause     : classname brut du log (entité, arme, véhicule...)
detail    : sous-action (vehicle, buried, raised, built with X...)
"""

import re
import logging
from datetime import date, datetime, time
from typing import Optional

from backend.models import KillEvent, KillType

logger = logging.getLogger("killfeed.parser")

# ─── Blocs réutilisables ──────────────────────────────────────────────────────

RE_TIME = r"(\d{1,2}:\d{2}:\d{2})"
RE_NAME = r'"([^"]+)"'
RE_POS  = r"pos=<([\d.]+),\s*([\d.]+),\s*([\d.]+)>"

_DEAD = rf'\s*\(DEAD\)\s*\(id=[^\s)]+\s+{RE_POS}\)'
_LIVE = rf'\s*\(id=[^\s)]+\s+{RE_POS}\)'
_ID   = rf'\s*\([^)]*\)'

# ─── Patterns ─────────────────────────────────────────────────────────────────

PATTERNS = {

    # ══ PVP ══════════════════════════════════════════════════════════════════
    # Distance : ... with M4-A1 from 16.05 meters | Mêlée : ... with (MeleeFist)  (pas de distance)
    "pvp": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}\s*(?:\(DEAD\)\s*)?\(id=[^\s)]+\s+{RE_POS}\)'
        rf'\s+killed by (?:Player\s+)?{RE_NAME}\s*(?:\(DEAD\)\s*)?\(id=[^\s)]+\s+{RE_POS}\)'
        rf'\s+with\s+(.+?)(?:\s+from\s+([\d.]+)\s+meters)?\s*$',
        re.IGNORECASE,
    ),

    # Hit PVP — joueur touché par un autre joueur (vrai format Nitrado console)
    # Distance : Player "V" (id=.. pos=<>)[HP: x] hit by Player "A" (id=.. pos=<>) into Torso(34) for 17.5 damage (Bullet_556x45) with M4-A1 from 21.6 meters
    # Mêlée    : ... into Torso(49) for 4.5 damage (MeleeFist_Heavy)
    # Groupes : t, victim, vx,vy,vz, hp, attacker, ax,ay,az, bodypart, damage, cause, weapon?, dist?
    "pvp_hit": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}\s*(?:\(DEAD\)\s*)?\(id=[^\s)]+\s+{RE_POS}\)'
        rf'\[HP:\s*([\d.]+)\]\s+hit by Player\s+{RE_NAME}\s*(?:\(DEAD\)\s*)?\(id=[^\s)]+\s+{RE_POS}\)'
        rf'\s+into\s+(\w+)\(\d+\)\s+for\s+([\d.]+)\s+damage'
        rf'(?:\s*\(([^)]+)\))?'
        rf'(?:\s+with\s+(\S+)\s+from\s+([\d.]+)\s+meters)?',
        re.IGNORECASE,
    ),

    # ══ PVE ══════════════════════════════════════════════════════════════════
    "pve_killed": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_DEAD}'
        rf'\s+killed by\s+((?!Player\b)[A-Za-z]\S*)',
        re.IGNORECASE,
    ),

    "starvation": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_DEAD}'
        rf'\s+died\.\s+Stats>\s+Water:\s*([\d.]+)\s+Energy:\s*([\d.]+)\s+Bleed\s+sources:\s*(\d+)',
        re.IGNORECASE,
    ),

    "bleedout": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_DEAD}'
        rf'\s+bled out',
        re.IGNORECASE,
    ),

    "unconscious": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s+is unconscious',
        re.IGNORECASE,
    ),

    "regained": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s+regained consciousness',
        re.IGNORECASE,
    ),

    # ══ SUICIDE ══════════════════════════════════════════════════════════════
    # Ligne principale — contient l'arme
    "suicide": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s+performed EmoteSuicide with\s+(\S+)',
        re.IGNORECASE,
    ),
    # Ligne secondaire générée par DayZ après EmoteSuicide — à ignorer si déjà capturé
    "suicide_committed": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_DEAD}'
        rf'\s+committed suicide',
        re.IGNORECASE,
    ),

    # ══ CONNEXION ════════════════════════════════════════════════════════════
    "connected": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_ID}\s*is connected',
        re.IGNORECASE,
    ),

    "disconnected": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_ID}\s*has been disconnected',
        re.IGNORECASE,
    ),

    # ══ BUILD ════════════════════════════════════════════════════════════════
    "build": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s*[Bb]uilt\s+(.+?)\s+(?:on\s+\S+\s+)?with\s+(\S+)',
        re.IGNORECASE,
    ),

    "dismantle": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s*[Dd]ismantled\s+(.+?)\s+from\s+(\S+)\s+with\s+(\S+)',
        re.IGNORECASE,
    ),

    "fold_fence": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s*folded\s+(\S+)',
        re.IGNORECASE,
    ),

    "barbed_wire": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'.*?((?:Un)?[Mm]ounted)\s+BarbedWire\s+(?:on|from)\s+(\S+)',
        re.IGNORECASE,
    ),

    "pack_shelter": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s*packed\s+(.+?)\s+with\s+Hands',
        re.IGNORECASE,
    ),

    # ══ PLACE ════════════════════════════════════════════════════════════════
    "place": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s*placed\s+([^<\n]+?)\s*(?:<([^>]+)>)?\s*$',
        re.IGNORECASE,
    ),

    "dug_in": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'.*?Dug\s+in\s+([A-Za-z0-9_]+)',
        re.IGNORECASE,
    ),

    "dug_out": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'.*?Dug\s+out\s+([A-Za-z0-9_]+)',
        re.IGNORECASE,
    ),

    # ══ FLAG ═════════════════════════════════════════════════════════════════
    "flag_raised": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s*has raised\s+(\S+)',
        re.IGNORECASE,
    ),

    "flag_lowered": re.compile(
        rf'{RE_TIME} \| Player {RE_NAME}{_LIVE}'
        rf'\s*has lowered\s+(\S+)',
        re.IGNORECASE,
    ),

    # ══ PLAYERLIST ═══════════════════════════════════════════════════════════
    "playerlist_entry": re.compile(
        rf'Player {RE_NAME}\s+\(id=[^)]*{RE_POS}\)\s*$',
        re.IGNORECASE,
    ),
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _dt(log_date: date, time_str: str) -> datetime:
    try:
        return datetime.combine(log_date, time.fromisoformat(time_str))
    except Exception:
        return datetime.now()

def _pos(x: str, y: str, z: str) -> tuple[float, float, float]:
    return (float(x), float(y), float(z))

def _starvation_cause(water: float, energy: float, bleed: int) -> str:
    if bleed > 0 and water > 100 and energy > 100:
        return "Hemorrhage"
    if water < 150:
        return "Dehydration"
    if energy < 150:
        return "Starvation"
    return "Unknown"

def _suicide_cause(water: float, energy: float, bleed: int) -> str:
    """Détermine la cause d'un suicide depuis les stats vitales."""
    if bleed > 0:
        return "Hemorrhage"
    if water < 150:
        return "Dehydration"
    if energy < 150:
        return "Starvation"
    return "Unknown cause"

# ─── Parser principal ─────────────────────────────────────────────────────────

def parse_adm_content(
    content:  str,
    log_date: date,
    guild_id: str,
) -> tuple[list[KillEvent], dict[str, tuple[float, float, float]]]:

    events:    list[KillEvent] = []
    positions: dict[str, tuple[float, float, float]] = {}
    ko_buffer:          dict[str, any]       = {}  # datetime | (datetime, attacker, attacker_pos, weapon)
    dead_seen:          dict[str, datetime]  = {}
    suicide_buffer:     dict[str, KillEvent] = {}
    emote_seen:         dict[str, datetime]  = {}  # anti-doublon EmoteSuicide → committed suicide
    pvp_hit_buffer:     dict[str, tuple]     = {}  # victim → (ts, attacker, attacker_pos, weapon) — dernier hit (KO-kill)
    pvp_hits_log:       dict[str, list]      = {}  # victim → [hit dict, ...] — coups encaissés cette vie (embed)

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        m = PATTERNS["playerlist_entry"].search(line)
        if m:
            positions[m.group(1)] = _pos(m.group(2), m.group(3), m.group(4))
            continue

        m = PATTERNS["pvp_hit"].search(line)
        if m:
            (t, victim, vx, vy, vz, hp, attacker, ax, ay, az,
             bodypart, damage, cause, weapon, dist) = m.groups()
            ts  = _dt(log_date, t)
            wpn = (weapon or cause or "").strip()  # mêlée : la cause () = l'arme
            # Dernier hit → KO-kill (inconscience qui finit en mort)
            pvp_hit_buffer[victim] = (ts, attacker, _pos(ax, ay, az), wpn)
            # Coups encaissés vivant → embed (on ignore les hits post-mortem HP=0)
            try:
                if float(hp) > 0:
                    pvp_hits_log.setdefault(victim, []).append({
                        "attacker": attacker, "bodypart": bodypart,
                        "damage":   float(damage), "weapon": wpn,
                    })
            except ValueError:
                pass
            continue

        m = PATTERNS["unconscious"].search(line)
        if m:
            t, name, x, y, z = m.groups()
            ts = _dt(log_date, t)
            hit = pvp_hit_buffer.get(name)
            if hit and abs((ts - hit[0]).total_seconds()) <= 30:
                ko_buffer[name] = (ts, hit[1], hit[2], hit[3])
            else:
                ko_buffer[name] = ts
            events.append(KillEvent(
                guild_id=guild_id, timestamp=ts, log_time=t,
                kill_type=KillType.PVE, cause="Unconscious",
                victim_name=name, victim_pos=_pos(x, y, z),
                raw_line=line,
            ))
            continue

        m = PATTERNS["regained"].search(line)
        if m:
            t, name, x, y, z = m.groups()
            ko_buffer.pop(name, None)
            events.append(KillEvent(
                guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
                kill_type=KillType.PVE, cause="Regained consciousness",
                victim_name=name, victim_pos=_pos(x, y, z),
                raw_line=line,
            ))
            continue

        event = parse_line(line, log_date, guild_id, ko_buffer, dead_seen, suicide_buffer, emote_seen)
        if event:
            v = event.victim_name
            if event.kill_type == KillType.PVP:
                # Attache les coups encaissés (sauf si déjà posés) + reset la vie
                if event.hits_taken is None:
                    event.hits_taken = pvp_hits_log.pop(v, None)
                else:
                    pvp_hits_log.pop(v, None)
            elif event.kill_type in (KillType.PVE, KillType.SUICIDE, KillType.CONNECTION):
                # Mort non-PVP ou (dé)connexion → la vie est terminée, on jette les hits
                pvp_hits_log.pop(v, None)
            events.append(event)

    return events, positions


def parse_line(
    line:           str,
    log_date:       date,
    guild_id:       str,
    ko_buffer:      dict = None,
    dead_seen:      dict = None,
    suicide_buffer: dict = None,
    emote_seen:     dict = None,
) -> Optional[KillEvent]:

    # ── PVP ──────────────────────────────────────────────────────────────────
    m = PATTERNS["pvp"].search(line)
    if m:
        t, victim, vx, vy, vz, killer, kx, ky, kz, weapon, dist = m.groups()
        if dead_seen is not None:
            dead_seen[victim] = _dt(log_date, t)
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.PVP, cause=weapon.strip().strip("()"),  # mêlée : arme entre () → on nettoie
            victim_name=victim, victim_pos=_pos(vx, vy, vz),
            killer_name=killer, killer_pos=_pos(kx, ky, kz),
            distance=float(dist) if dist else None,  # mêlée : pas de distance
            raw_line=line,
        )

    # ── SUICIDE EmoteSuicide — ligne principale avec arme ────────────────────
    m = PATTERNS["suicide"].search(line)
    if m:
        t, victim, vx, vy, vz, weapon = m.groups()
        ts = _dt(log_date, t)
        # Dédoublonner les EmoteSuicide successifs (même joueur, < 60s)
        if emote_seen is not None and victim in emote_seen:
            if abs((ts - emote_seen[victim]).total_seconds()) < 60:
                return None
        if emote_seen is not None:
            emote_seen[victim] = ts
        if dead_seen is not None:
            dead_seen[victim] = ts
        return KillEvent(
            guild_id=guild_id, timestamp=ts, log_time=t,
            kill_type=KillType.SUICIDE, cause=weapon.strip(),
            victim_name=victim, victim_pos=_pos(vx, vy, vz),
            raw_line=line,
        )

    # ── SUICIDE committed — ligne secondaire générée par DayZ ────────────────
    m = PATTERNS["suicide_committed"].search(line)
    if m:
        t, victim, vx, vy, vz = m.groups()
        ts = _dt(log_date, t)
        if emote_seen is not None and victim in emote_seen:
            if abs((ts - emote_seen[victim]).total_seconds()) < 30:
                return None
        if dead_seen is not None and victim in dead_seen:
            if abs((ts - dead_seen[victim]).total_seconds()) < 30:
                return None
        if dead_seen is not None:
            dead_seen[victim] = ts
        return KillEvent(
            guild_id=guild_id, timestamp=ts, log_time=t,
            kill_type=KillType.SUICIDE, cause="Suicide",
            victim_name=victim, victim_pos=_pos(vx, vy, vz),
            raw_line=line,
        )

    # ── PVE starvation (priorité haute — contient les stats) ─────────────────
    m = PATTERNS["starvation"].search(line)
    if m:
        t, victim, vx, vy, vz, water, energy, bleed = m.groups()
        w, e, b = float(water), float(energy), int(bleed)
        ts = _dt(log_date, t)

        # Suicide en attente dans le buffer → enrichir et émettre
        if suicide_buffer and victim in suicide_buffer:
            ev = suicide_buffer.pop(victim)
            ev.cause = _suicide_cause(w, e, b)
            if dead_seen is not None:
                dead_seen[victim] = ts
            return ev

        # Mort déjà émise → la ligne stats est un doublon
        # Fenêtre 30s (était 5s — trop court : EmoteSuicide→stats peut prendre 6-8s)
        if dead_seen and victim in dead_seen:
            if abs((ts - dead_seen[victim]).total_seconds()) < 30:
                return None
        # EmoteSuicide récent → cette ligne stats est la conséquence, on l'ignore
        if emote_seen and victim in emote_seen:
            if abs((ts - emote_seen[victim]).total_seconds()) < 60:
                return None

        cause = _starvation_cause(w, e, b)
        if dead_seen is not None:
            dead_seen[victim] = ts
        ko_info = ko_buffer.pop(victim, None) if ko_buffer else None
        if isinstance(ko_info, tuple):
            _, attacker, attacker_pos, weapon = ko_info
            return KillEvent(
                guild_id=guild_id, timestamp=ts, log_time=t,
                kill_type=KillType.PVP, cause=weapon or cause,
                victim_name=victim, victim_pos=_pos(vx, vy, vz),
                killer_name=attacker, killer_pos=attacker_pos,
                detail="ko",
                raw_line=line,
            )
        return KillEvent(
            guild_id=guild_id, timestamp=ts, log_time=t,
            kill_type=KillType.PVE if cause != "Unknown" else KillType.SUICIDE,
            cause=cause,
            detail=f"water:{w:.0f} energy:{e:.0f} bleed:{b}",
            victim_name=victim, victim_pos=_pos(vx, vy, vz),
            raw_line=line,
        )

    # ── PVE bleedout — dédoublonné si starvation déjà émis ───────────────────
    m = PATTERNS["bleedout"].search(line)
    if m:
        t, victim, vx, vy, vz = m.groups()
        ts = _dt(log_date, t)
        if dead_seen and victim in dead_seen:
            if abs((ts - dead_seen[victim]).total_seconds()) < 3:
                return None
        if dead_seen is not None:
            dead_seen[victim] = ts
        ko_info = ko_buffer.pop(victim, None) if ko_buffer else None
        if isinstance(ko_info, tuple):
            _, attacker, attacker_pos, weapon = ko_info
            return KillEvent(
                guild_id=guild_id, timestamp=ts, log_time=t,
                kill_type=KillType.PVP, cause=weapon or "Bleedout",
                victim_name=victim, victim_pos=_pos(vx, vy, vz),
                killer_name=attacker, killer_pos=attacker_pos,
                detail="ko",
                raw_line=line,
            )
        return KillEvent(
            guild_id=guild_id, timestamp=ts, log_time=t,
            kill_type=KillType.PVE, cause="Bleedout",
            victim_name=victim, victim_pos=_pos(vx, vy, vz),
            raw_line=line,
        )

    # ── PVE killed by entité ──────────────────────────────────────────────────
    m = PATTERNS["pve_killed"].search(line)
    if m:
        t, victim, vx, vy, vz, entity = m.groups()
        ts = _dt(log_date, t)
        if dead_seen is not None:
            dead_seen[victim] = ts
        if ko_buffer:
            ko_buffer.pop(victim, None)
        return KillEvent(
            guild_id=guild_id, timestamp=ts, log_time=t,
            kill_type=KillType.PVE, cause=entity,
            victim_name=victim, victim_pos=_pos(vx, vy, vz),
            raw_line=line,
        )

    # ── CONNEXION ─────────────────────────────────────────────────────────────
    m = PATTERNS["connected"].search(line)
    if m:
        t, name = m.group(1), m.group(2)
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.CONNECTION, cause="connected",
            victim_name=name,
            raw_line=line,
        )

    m = PATTERNS["disconnected"].search(line)
    if m:
        t, name = m.group(1), m.group(2)
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.CONNECTION, cause="disconnected",
            victim_name=name,
            raw_line=line,
        )

    # ── BUILD ─────────────────────────────────────────────────────────────────
    m = PATTERNS["build"].search(line)
    if m:
        t, player, px, py, pz, structure, tool = m.groups()
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.BUILD, cause=structure,
            detail=f"built with {tool}",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    m = PATTERNS["dismantle"].search(line)
    if m:
        t, player, px, py, pz, part, structure, tool = m.groups()
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.BUILD,
            cause=f"{part} from {structure}",
            detail=f"dismantled with {tool}",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    m = PATTERNS["fold_fence"].search(line)
    if m:
        t, player, px, py, pz, structure = m.groups()
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.BUILD, cause=structure, detail="folded",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    m = PATTERNS["barbed_wire"].search(line)
    if m:
        t, player, px, py, pz, action, structure = m.groups()
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.BUILD, cause="BarbedWire",
            detail=f"{'mounted' if 'mount' in action.lower() else 'unmounted'} on {structure}",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    m = PATTERNS["pack_shelter"].search(line)
    if m:
        t, player, px, py, pz, shelter = m.groups()
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.BUILD, cause=shelter.strip(), detail="packed",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    # ── PLACE ─────────────────────────────────────────────────────────────────
    m = PATTERNS["place"].search(line)
    if m:
        t, player, px, py, pz, item, classname = m.groups()
        # Si <classname> absent, normaliser le libellé en classname plausible (ex. "Sea Chest" → "SeaChest")
        cause = (classname or "").strip() or "".join(w for w in item.strip().split())
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.PLACE,
            cause=cause, detail="placed",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    m = PATTERNS["dug_in"].search(line)
    if m:
        t, player, px, py, pz, classname = m.groups()
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.PLACE, cause=classname, detail="buried",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    m = PATTERNS["dug_out"].search(line)
    if m:
        t, player, px, py, pz, classname = m.groups()
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.PLACE, cause=classname, detail="dug out",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    # ── FLAG ──────────────────────────────────────────────────────────────────
    m = PATTERNS["flag_raised"].search(line)
    if m:
        t, player, px, py, pz, flag = m.groups()
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.FLAG, cause=flag.strip(), detail="raised",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    m = PATTERNS["flag_lowered"].search(line)
    if m:
        t, player, px, py, pz, flag = m.groups()
        return KillEvent(
            guild_id=guild_id, timestamp=_dt(log_date, t), log_time=t,
            kill_type=KillType.FLAG, cause=flag.strip(), detail="lowered",
            victim_name=player, victim_pos=_pos(px, py, pz),
            raw_line=line,
        )

    # ── Unmatched — silencieux ────────────────────────────────────────────────
    return None