"""
bot/tasks/adm_storage.py
Archivage local des fichiers ADM (ex-Supabase Storage).

- Déclenché quand le poller détecte un nouveau fichier ADM
- Stocke dans {CODEX_DATA_DIR}/adm/{guild_id}/{filename}
- Purge automatique des fichiers > 72h

Le bucket `adm-logs` a disparu avec la dépendance Supabase : un kit
self-hosted archive sur son propre disque. L'URL signée qui servait à
contourner la limite d'upload Discord (25 Mo) n'a plus d'équivalent —
elle est remplacée par le chemin local du fichier, que l'admin lit sur
la machine où tourne le bot (cf. get_adm_file_path / poller._post_adm_to_logs).
"""

import logging
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bot.config import load_config

logger = logging.getLogger("killfeed.adm_storage")

MAX_AGE_HOURS = 72


def _guild_dir(guild_id: str) -> Path:
    """{CODEX_DATA_DIR}/adm/{guild_id} — créé à la volée."""
    path = load_config().data_dir / "adm" / str(guild_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def save_adm_to_storage(guild_id: str, filename: str, content: str) -> bool:
    """Archive un fichier ADM sur le disque local. Écrase si déjà présent."""
    try:
        target = _guild_dir(guild_id) / Path(filename).name
        # newline="" : pas de traduction \n → \r\n sous Windows, sinon les
        # CRLF déjà présents dans les ADM Nitrado deviendraient des \r\r\n.
        target.write_text(content, encoding="utf-8", newline="")
        logger.info(f"[ADMStorage] {guild_id} — {filename} archivé "
                    f"({target.stat().st_size} bytes)")
        return True
    except Exception as e:
        logger.error(f"[ADMStorage] Erreur sauvegarde {filename}: {e}")
        return False


def purge_old_adm(guild_id: str) -> int:
    """Supprime les archives ADM de plus de 72h. Retourne le nb supprimé."""
    try:
        cutoff  = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)).timestamp()
        deleted = 0
        for f in _guild_dir(guild_id).iterdir():
            if not f.is_file():
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
                    logger.info(f"[ADMStorage] {guild_id} — {f.name} supprimé (>{MAX_AGE_HOURS}h)")
            except OSError:
                continue
        return deleted
    except Exception as e:
        logger.error(f"[ADMStorage] Erreur purge {guild_id}: {e}")
        return 0


def list_adm_files(guild_id: str) -> list[dict]:
    """[{name, size, updated_at}] triés par date décroissante."""
    try:
        result = []
        for f in _guild_dir(guild_id).iterdir():
            if not f.is_file() or not f.name.upper().endswith(".ADM"):
                continue
            stat = f.stat()
            result.append({
                "name":       f.name,
                "size":       stat.st_size,
                "updated_at": _iso(stat.st_mtime),
            })
        result.sort(key=lambda x: x["updated_at"], reverse=True)
        return result
    except Exception as e:
        logger.error(f"[ADMStorage] Erreur liste {guild_id}: {e}")
        return []


def get_adm_file_path(guild_id: str, filename: str) -> str | None:
    """Chemin absolu de l'archive locale, ou None si absente.

    Remplace l'ancienne URL signée (1h) du bucket Supabase : il n'y a plus de
    serveur pour la servir. Le bot affiche ce chemin dans #logs-adm quand le
    fichier dépasse la limite d'upload Discord.
    """
    try:
        path = _guild_dir(guild_id) / Path(filename).name
        return str(path) if path.is_file() else None
    except Exception as e:
        logger.error(f"[ADMStorage] Erreur chemin {filename}: {e}")
        return None


def delete_guild_adm(guild_id: str) -> bool:
    """Supprime tout le dossier d'archives d'une guild (départ du bot)."""
    try:
        shutil.rmtree(load_config().data_dir / "adm" / str(guild_id), ignore_errors=True)
        return True
    except Exception as e:
        logger.error(f"[ADMStorage] Erreur suppression {guild_id}: {e}")
        return False
