"""
bot/predeps.py
Installe les dépendances d'une mise à jour /maj AU DÉMARRAGE, avant que
main.py importe discord.py & co.

Pourquoi ici : sous Windows, un module compilé (.pyd) déjà chargé par le bot
est verrouillé — pip ne peut pas le remplacer pendant que le bot tourne. À ce
stade, seule la bibliothèque standard est chargée.

Échec de pip → l'ancien code (data/updates/ancienne-version-X) est remis en
place, l'erreur est notée dans data/updates/echec-maj.txt (relayée dans
#alertes par la tâche maintenance) et le process quitte : la boucle de
lancement relance l'ancienne version.

Bibliothèque standard UNIQUEMENT dans ce fichier.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

FLAG_NAME    = "dependances-a-installer.json"
FAILURE_NAME = "echec-maj.txt"


def _note(data_dir: Path, message: str) -> None:
    line = f"{datetime.now():%H:%M:%S} [killfeed.predeps] {message}"
    print(line, flush=True)
    try:
        logs = data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / "bot.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def install_pending_deps(root: Path) -> None:
    data_dir = Path(os.getenv("CODEX_DATA_DIR") or (root / "data"))
    flag = data_dir / "updates" / FLAG_NAME
    if not flag.exists():
        return
    try:
        info = json.loads(flag.read_text(encoding="utf-8"))
    except Exception:
        info = {}
    flag.unlink(missing_ok=True)   # une seule tentative, jamais de boucle

    _note(data_dir, "Mise à jour : installation des nouvelles dépendances (1 à 3 minutes)…")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q",
             "-r", str(root / "requirements.txt")],
            capture_output=True, text=True, timeout=900,
        )
        ok, detail = proc.returncode == 0, (proc.stderr or proc.stdout or "")[-500:]
    except Exception as e:
        ok, detail = False, str(e)

    if ok:
        _note(data_dir, "Dépendances installées ✅")
        return

    _note(data_dir, f"Échec de l'installation des dépendances : {detail}")
    old_dir = Path(info.get("rollback_dir", ""))
    if old_dir.is_dir():
        for src in old_dir.rglob("*"):
            if src.is_file():
                target = root / src.relative_to(old_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
        _note(data_dir, "Ancienne version remise en place — redémarrage")
    (data_dir / "updates" / FAILURE_NAME).write_text(detail or "erreur inconnue", encoding="utf-8")
    sys.exit(1)
