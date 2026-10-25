"""
bot/leaderboard.py
Statistiques calculées à partir de la table kills : fiche joueur (/joueur),
classement (/top) et classement hebdomadaire automatique (#statistiques).

Uniquement des comptages d'événements ADM réels — aucun score inventé.
Le temps de jeu additionne les paires connexion → déconnexion (une session
encore ouverte ou sans connexion connue n'est pas comptée).
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

from backend import database as db

MAX_SESSION = timedelta(hours=12)   # garde-fou : déconnexion manquée dans l'ADM
FOOTER      = "CodeX KillFeed by EpSy"


def _ts(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def playtime_by_player(events: list[dict]) -> dict[str, timedelta]:
    """Temps de jeu par joueur (clé en minuscules) à partir des connexions."""
    opened: dict[str, datetime] = {}
    total: dict[str, timedelta] = defaultdict(timedelta)
    for e in sorted(events, key=lambda x: x.get("timestamp") or ""):
        if e.get("kill_type") != "connection" or not e.get("victim_name"):
            continue
        name, ts = e["victim_name"].lower(), _ts(e.get("timestamp") or "")
        if not ts:
            continue
        if e.get("cause") == "connected":
            opened[name] = ts
        elif e.get("cause") == "disconnected" and name in opened:
            delta = ts - opened.pop(name)
            if timedelta(0) < delta <= MAX_SESSION:
                total[name] += delta
    return total


def fmt_duration(d: timedelta) -> str:
    minutes = int(d.total_seconds() // 60)
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d}" if h else f"{m} min"


def _ratio(kills: int, deaths: int) -> str:
    return f"{kills / deaths:.2f}" if deaths else (f"{kills:.2f}" if kills else "0.00")


# ─── Fiche joueur ─────────────────────────────────────────────────────────────

def build_player_embed(guild_id: str, player: str) -> Optional[discord.Embed]:
    events = db.get_player_events(guild_id, player)
    first  = db.get_player_first_seen(guild_id, player)
    if not events and not first:
        return None
    needle = player.lower()
    # Nom tel qu'écrit dans les logs (casse réelle)
    display = next((e["victim_name"] for e in events if (e.get("victim_name") or "").lower() == needle),
                   next((e["killer_name"] for e in events if (e.get("killer_name") or "").lower() == needle), player))

    kills    = [e for e in events if e.get("kill_type") == "pvp" and (e.get("killer_name") or "").lower() == needle]
    deaths   = [e for e in events if e.get("kill_type") in ("pvp", "pve", "suicide")
                and (e.get("victim_name") or "").lower() == needle]
    pvp_d    = sum(1 for e in deaths if e.get("kill_type") == "pvp")
    suicides = sum(1 for e in deaths if e.get("kill_type") == "suicide")
    conns    = [e for e in events if e.get("kill_type") == "connection"
                and (e.get("victim_name") or "").lower() == needle]
    last_seen = max((e["timestamp"] for e in conns), default=None)
    playtime  = playtime_by_player(events).get(needle, timedelta(0))

    victims  = Counter(e.get("victim_name") for e in kills if e.get("victim_name"))
    killers  = Counter(e.get("killer_name") for e in deaths if e.get("kill_type") == "pvp" and e.get("killer_name"))
    weapons  = Counter(e.get("cause") for e in kills if e.get("cause"))
    longest  = max((e.get("distance") or 0 for e in kills), default=0)

    embed = discord.Embed(title=f"🪪 {display}", color=discord.Color.from_rgb(59, 130, 246))
    embed.add_field(
        name="Combat",
        value=(f"⚔️ Kills PVP : **{len(kills)}**\n"
               f"💀 Morts : **{len(deaths)}** (dont PVP {pvp_d}, suicides {suicides})\n"
               f"📈 Ratio K/D PVP : **{_ratio(len(kills), pvp_d)}**"
               + (f"\n🎯 Plus long kill : **{longest:.0f} m**" if longest else "")),
        inline=False,
    )
    seen_lines = []
    if first:
        seen_lines.append(f"Première venue : {first[:10]}")
    if last_seen:
        ts = _ts(last_seen)
        seen_lines.append(f"Dernière connexion : {discord.utils.format_dt(ts, 'R') if ts else last_seen[:16]}")
    seen_lines.append(f"Connexions : {sum(1 for e in conns if e.get('cause') == 'connected')}")
    seen_lines.append(f"Temps de jeu : {fmt_duration(playtime)}")
    embed.add_field(name="Présence", value="\n".join(seen_lines), inline=False)
    if weapons:
        embed.add_field(name="Arme favorite", value=f"{weapons.most_common(1)[0][0]}", inline=True)
    if victims:
        n, c = victims.most_common(1)[0]
        embed.add_field(name="Victime préférée", value=f"{n} ({c}×)", inline=True)
    if killers:
        n, c = killers.most_common(1)[0]
        embed.add_field(name="Bête noire", value=f"{n} ({c}×)", inline=True)
    embed.set_footer(text=f"{FOOTER} · données conservées {db.get_retention(guild_id)} jours")
    return embed


# ─── Classement ───────────────────────────────────────────────────────────────

def build_top_embed(guild_id: str, days: int, title: Optional[str] = None) -> Optional[discord.Embed]:
    since  = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    events = db.get_kills_since(guild_id, since)
    if not events:
        return None

    pvp     = [e for e in events if e.get("kill_type") == "pvp" and e.get("killer_name")
               and e.get("killer_name") != e.get("victim_name")]
    kills   = Counter(e["killer_name"] for e in pvp)
    pvp_d   = Counter(e.get("victim_name") for e in pvp)
    deaths  = Counter(e.get("victim_name") for e in events
                      if e.get("kill_type") in ("pvp", "pve", "suicide") and e.get("victim_name"))
    longest = sorted((e for e in pvp if e.get("distance")), key=lambda e: e["distance"], reverse=True)[:3]
    play    = playtime_by_player(events)
    names   = {e["victim_name"].lower(): e["victim_name"] for e in events
               if e.get("kill_type") == "connection" and e.get("victim_name")}

    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    embed = discord.Embed(
        title=title or f"🏆 Classement — {days} derniers jours",
        color=discord.Color.from_rgb(234, 179, 8),
    )
    if kills:
        embed.add_field(name="⚔️ Kills PVP", inline=True, value="\n".join(
            f"{medals[i]} **{n}** — {c}" for i, (n, c) in enumerate(kills.most_common(5))))
        ratios = sorted(((n, c / max(pvp_d.get(n, 0), 1)) for n, c in kills.items() if c >= 3),
                        key=lambda x: x[1], reverse=True)[:5]
        if ratios:
            embed.add_field(name="📈 Ratio K/D (3 kills min.)", inline=True, value="\n".join(
                f"{medals[i]} **{n}** — {r:.2f}" for i, (n, r) in enumerate(ratios)))
    if longest:
        embed.add_field(name="🎯 Plus longs kills", inline=False, value="\n".join(
            f"{medals[i]} **{e['killer_name']}** → {e.get('victim_name')} — {e['distance']:.0f} m"
            for i, e in enumerate(longest)))
    if play:
        top_play = sorted(play.items(), key=lambda x: x[1], reverse=True)[:5]
        embed.add_field(name="⏱️ Temps de jeu", inline=True, value="\n".join(
            f"{medals[i]} **{names.get(n, n)}** — {fmt_duration(d)}" for i, (n, d) in enumerate(top_play)))
    if deaths:
        embed.add_field(name="💀 Plus souvent morts", inline=True, value="\n".join(
            f"{medals[i]} **{n}** — {c}" for i, (n, c) in enumerate(deaths.most_common(3))))
    if not embed.fields:
        return None
    embed.set_footer(text=FOOTER)
    return embed
