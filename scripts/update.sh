#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# CodeX KillFeed — mise à jour vers une nouvelle version
#
# Usage, depuis le dossier de la NOUVELLE version décompressée :
#     sudo bash scripts/update.sh
#
# Conserve .env, base SQLite et données. Sauvegarde la base avant de toucher
# à quoi que ce soit.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/opt/codex-killfeed"
APP_USER="codex"
SERVICE="codex-killfeed"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Lance ce script avec sudo :  sudo bash scripts/update.sh"; exit 1
fi
if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "Aucune installation trouvée dans $APP_DIR — utilise d'abord scripts/install.sh"; exit 1
fi
if [[ "$SRC_DIR" == "$APP_DIR" ]]; then
  echo "Lance ce script depuis le dossier de la nouvelle version, pas depuis $APP_DIR"; exit 1
fi

echo "▶ Arrêt du bot…"
systemctl stop "$SERVICE"

STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$APP_DIR/data/sauvegardes"
for db in "$APP_DIR"/*.db; do
  [[ -f "$db" ]] && cp "$db" "$APP_DIR/data/sauvegardes/$(basename "$db").$STAMP"
done
echo "▶ Base sauvegardée dans $APP_DIR/data/sauvegardes/"

echo "▶ Copie de la nouvelle version…"
tar -C "$SRC_DIR" --exclude='./.env' --exclude='./data' --exclude='./*.db' \
    --exclude='./venv' --exclude='./.venv' --exclude='__pycache__' -cf - . \
  | tar -C "$APP_DIR" -xf -

echo "▶ Mise à jour des dépendances…"
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# v1.1 : fuseau horaire du service (horaires NO PVP / redémarrages planifiés)
UNIT="/etc/systemd/system/$SERVICE.service"
if [[ -f "$UNIT" ]] && ! grep -q '^Environment=TZ=' "$UNIT"; then
  sed -i '/^Environment=PYTHONUNBUFFERED=1/a Environment=TZ=Europe/Paris' "$UNIT"
  systemctl daemon-reload
  echo "▶ Fuseau horaire Europe/Paris ajouté au service"
fi

systemctl start "$SERVICE"
sleep 8
if systemctl is-active --quiet "$SERVICE"; then
  echo "✅ Mise à jour terminée, le bot est en ligne."
else
  echo "⚠️ Le bot ne redémarre pas. Journal :"
  journalctl -u "$SERVICE" -n 30 --no-pager
  exit 1
fi
