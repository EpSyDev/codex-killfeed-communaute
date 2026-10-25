#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# CodeX KillFeed — installation sur Ubuntu (VPS, serveur dédié, Raspberry…)
#
# Usage, depuis le dossier décompressé :
#     sudo bash scripts/install.sh
#
# Rejouable sans risque : ne touche jamais à un .env, une base ou des données
# déjà présents dans /opt/codex-killfeed.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/opt/codex-killfeed"
APP_USER="codex"
SERVICE="codex-killfeed"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

vert()  { printf '\033[1;32m%s\033[0m\n' "$*"; }
jaune() { printf '\033[1;33m%s\033[0m\n' "$*"; }
rouge() { printf '\033[1;31m%s\033[0m\n' "$*"; }
etape() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }

# ── 0. Vérifications ─────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  rouge "Lance ce script avec sudo :  sudo bash scripts/install.sh"
  exit 1
fi
if ! command -v apt-get >/dev/null; then
  rouge "Ce script est prévu pour Ubuntu/Debian (apt). Réinstalle ton VPS avec Ubuntu 24.04 (ou 22.04) depuis l'espace client de ton hébergeur."
  exit 1
fi
if [[ ! -f "$SRC_DIR/main.py" ]]; then
  rouge "main.py introuvable dans $SRC_DIR — lance le script depuis le dossier décompressé."
  exit 1
fi

# ── 1. Paquets système ───────────────────────────────────────────────────────
etape "Installation des paquets système (Python, venv, curl)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates >/dev/null

PYV=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  rouge "Python $PYV détecté — il faut Python 3.10 minimum (Ubuntu 22.04 ou 24.04)."
  exit 1
fi
vert "Python $PYV OK"

# ── 2. Mémoire d'échange (petites VM 1 Go) ──────────────────────────────────
RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ $RAM_MB -lt 2000 ]] && ! swapon --show | grep -q .; then
  etape "Seulement ${RAM_MB} Mo de RAM — création d'un fichier d'échange de 2 Go…"
  # Certains VPS « conteneur » (OpenVZ/LXC) interdisent le swap : on continue sans.
  if { fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none; } \
     && chmod 600 /swapfile && mkswap /swapfile >/dev/null 2>&1 && swapon /swapfile 2>/dev/null; then
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    vert "Swap 2 Go actif"
  else
    rm -f /swapfile
    jaune "Swap refusé par l'hébergeur — on continue sans (le bot tient dans 1 Go)."
  fi
fi

# ── 2.bis Protection SSH (VPS exposés à Internet) ──────────────────────────
# fail2ban bloque les adresses qui enchaînent les mauvais mots de passe SSH.
if ! command -v fail2ban-client >/dev/null; then
  etape "Installation de fail2ban (protection contre les attaques sur SSH)…"
  if apt-get install -y -qq fail2ban >/dev/null 2>&1; then
    systemctl enable --now fail2ban >/dev/null 2>&1 || true
    vert "fail2ban actif"
  else
    jaune "fail2ban non installé (sans gravité, le bot fonctionne sans)."
  fi
fi

# ── 3. Fuseau horaire ───────────────────────────────────────────────────────
if [[ "$(timedatectl show -p Timezone --value 2>/dev/null)" == "Etc/UTC" ]]; then
  timedatectl set-timezone Europe/Paris && vert "Fuseau horaire réglé sur Europe/Paris"
fi

# ── 4. Utilisateur dédié + copie du code ────────────────────────────────────
etape "Copie du bot dans $APP_DIR…"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"
if [[ "$SRC_DIR" != "$APP_DIR" ]]; then
  # Copie le code sans écraser .env / base / données d'une installation existante
  tar -C "$SRC_DIR" --exclude='./.env' --exclude='./data' --exclude='./*.db' \
      --exclude='./venv' --exclude='./.venv' --exclude='__pycache__' -cf - . \
    | tar -C "$APP_DIR" -xf -
  if [[ -f "$SRC_DIR/.env" && ! -f "$APP_DIR/.env" ]]; then
    cp "$SRC_DIR/.env" "$APP_DIR/.env"
  fi
fi

# ── 5. Environnement Python ─────────────────────────────────────────────────
etape "Installation des dépendances Python (1 à 3 minutes)…"
[[ -d "$APP_DIR/venv" ]] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
vert "Dépendances installées"

# ── 6. Configuration (.env) ─────────────────────────────────────────────────
verifier_discord() {
  [[ $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bot $1" \
       https://discord.com/api/v10/users/@me) == "200" ]]
}
verifier_nitrado() {
  [[ $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $1" \
       "https://api.nitrado.net/services/$2/gameservers") == "200" ]]
}

if [[ ! -f "$APP_DIR/.env" ]]; then
  etape "Configuration — colle tes identifiants (clic droit = coller dans la plupart des terminaux)"
  while true; do
    read -rsp "Token du bot Discord (rien ne s'affiche, c'est normal) : " DISCORD_TOKEN; echo
    if verifier_discord "$DISCORD_TOKEN"; then vert "  ✔ Token Discord valide"; break; fi
    rouge "  ✘ Token refusé par Discord — recopie-le (Developer Portal → Bot → Reset Token)."
  done
  while true; do
    read -rsp "Token Nitrado long-life (rien ne s'affiche) : " NITRADO_TOKEN; echo
    read -rp  "ID de service Nitrado (nombre dans l'URL de ton serveur) : " NITRADO_SERVER_ID
    NITRADO_SERVER_ID="${NITRADO_SERVER_ID//[^0-9]/}"
    if verifier_nitrado "$NITRADO_TOKEN" "$NITRADO_SERVER_ID"; then vert "  ✔ Accès Nitrado valide"; break; fi
    rouge "  ✘ Nitrado refuse ce couple token / ID de service — vérifie les deux."
  done
  umask 077
  # printf plutôt que sed : un token ne doit jamais être interprété
  grep -v -E '^(DISCORD_TOKEN|NITRADO_TOKEN|NITRADO_SERVER_ID)=' "$APP_DIR/.env.example" > "$APP_DIR/.env"
  printf '\nDISCORD_TOKEN=%s\nNITRADO_TOKEN=%s\nNITRADO_SERVER_ID=%s\n' \
    "$DISCORD_TOKEN" "$NITRADO_TOKEN" "$NITRADO_SERVER_ID" >> "$APP_DIR/.env"
  umask 022
  vert ".env créé"
else
  jaune ".env déjà présent — conservé tel quel."
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

# ── 7. Service systemd (démarrage auto + redémarrage en cas de crash) ───────
etape "Création du service $SERVICE…"
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=CodeX KillFeed (bot Discord DayZ)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python main.py
Environment=PYTHONUNBUFFERED=1
# Heure française pour les horaires NO PVP et les redémarrages planifiés
# (les VM cloud sont en UTC). À changer si le serveur DayZ vit sur un autre fuseau.
Environment=TZ=Europe/Paris
Restart=always
RestartSec=10

# Durcissement : le bot ne peut écrire que dans son propre dossier
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"
sleep 8

if systemctl is-active --quiet "$SERVICE"; then
  vert "
✅ CodeX KillFeed est en ligne !

Prochaine étape, sur ton Discord :  /setup   puis   /diagnostic

Commandes utiles :
  sudo systemctl status $SERVICE       → état du bot
  sudo journalctl -u $SERVICE -f       → logs en direct (Ctrl+C pour quitter)
  sudo systemctl restart $SERVICE      → redémarrer
  sudo nano $APP_DIR/.env              → modifier la configuration"
else
  rouge "Le service ne tourne pas. Dernières lignes du journal :"
  journalctl -u "$SERVICE" -n 30 --no-pager
  exit 1
fi
