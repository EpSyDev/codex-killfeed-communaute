"""
bot/config.py
Source unique de vérité pour la configuration du kit.

Tous les secrets et réglages viennent du .env local — plus aucune valeur
sensible en base ni chiffrée (le chiffrement Fernet du token Nitrado protégeait
une base Supabase mutualisée entre clients ; sur une installation single-tenant,
le .env est déjà le périmètre de confiance, comme pour DISCORD_TOKEN).

Consommateurs : main.py (token Discord, log level), backend/database.py
(chemin de la base + token Nitrado injecté dans ServerConfig),
backend/nitrado_whitelist.py (token + service id), bot/tasks/adm_storage.py
(répertoire de données).

NOMS DE VARIABLES (définitifs) :
    DISCORD_TOKEN      token du bot Discord          (obligatoire)
    NITRADO_TOKEN      token API Nitrado long-life   (obligatoire)
    NITRADO_SERVER_ID  ID de SERVICE Nitrado         (obligatoire)
                       (celui des URLs /services/{id}/gameservers)
    LOG_LEVEL          INFO par défaut               (optionnel)
    CODEX_DB_PATH      base SQLite                   (optionnel)
    CODEX_DATA_DIR     données locales (logs ADM)    (optionnel)

`load_config()` ne lève jamais : les appelants valident ce dont ILS ont besoin
(le bot doit pouvoir démarrer pour afficher un message clair, pas planter sur
un KeyError).
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def install_root() -> Path:
    """Racine de l'installation — dossier du projet."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    discord_token:     str
    nitrado_token:     str
    nitrado_server_id: str
    log_level:         str
    db_path:           Path
    data_dir:          Path


def load_config() -> Config:
    root = install_root()
    return Config(
        discord_token     = os.getenv("DISCORD_TOKEN", "").strip(),
        nitrado_token     = os.getenv("NITRADO_TOKEN", "").strip(),
        nitrado_server_id = os.getenv("NITRADO_SERVER_ID", "").strip(),
        log_level         = os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        db_path           = Path(os.getenv("CODEX_DB_PATH") or (root / "codex-kit.db")),
        data_dir          = Path(os.getenv("CODEX_DATA_DIR") or (root / "data")),
    )
