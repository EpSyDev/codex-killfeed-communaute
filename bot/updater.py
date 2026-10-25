"""
bot/updater.py
Mise à jour en place depuis la dernière release GitHub (commande /maj).

Étapes, chacune bloquante en cas d'échec (rien n'est touché avant l'étape 5) :
  1. téléchargement du zip de la release (UPDATE_REPO, HTTPS uniquement) ;
  2. contrôle de l'empreinte SHA-256 publiée par GitHub pour ce fichier ;
  3. contrôle du contenu : un seul dossier racine, aucun chemin qui sort du
     dossier, main.py + VERSION présents, VERSION = numéro de la release ;
  4. sauvegarde : base (data/backups/avant-maj-*.db) + code actuel
     (data/updates/ancienne-version-X/) ;
  5. remplacement des fichiers — jamais .env, data/, *.db, venv/, ni
     scripts/windows/lancer-bot.bat (en cours d'exécution : cmd lit un .bat au
     fil de l'eau, le remplacer ferait exécuter n'importe quoi) ;
  6. dépendances (pip) seulement si requirements.txt a changé, au démarrage
     suivant (bot/predeps.py) — en cas d'échec, le code précédent est remis
     en place ;
  7. le bot quitte : la boucle Windows (30 s) ou systemd (10 s) le relance.

Après le redémarrage, maintenance.py confirme l'installation dans #alertes
(réglage maj_pending).
"""

import asyncio
import hashlib
import io
import json
import logging
import shutil
import zipfile
from pathlib import Path, PurePosixPath

import httpx

from backend import database as db
from bot.config import install_root, load_config

logger = logging.getLogger("killfeed.updater")

MAX_ZIP_SIZE = 60 * 1024 * 1024
PROTECTED_TOP = {".env", "data", "venv", ".venv", ".git", "__pycache__"}
PROTECTED_FILES = {"scripts/windows/lancer-bot.bat", "scripts/windows/lancer-bot.vbs"}
DEPS_FLAG = "dependances-a-installer.json"   # lu par bot/predeps.py

_lock = asyncio.Lock()


class UpdateError(Exception):
    """Message destiné à l'admin (français, actionnable)."""


def is_running() -> bool:
    return _lock.locked()


def _updates_dir() -> Path:
    d = load_config().data_dir / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _protected(rel: PurePosixPath) -> bool:
    return (rel.parts[0] in PROTECTED_TOP
            or rel.as_posix() in PROTECTED_FILES
            or rel.suffix in (".db", ".pyc")
            or "__pycache__" in rel.parts)


# ─── 1-3. Téléchargement et contrôles ─────────────────────────────────────────

async def _download(url: str) -> bytes:
    if not url.startswith("https://github.com/"):
        raise UpdateError("Adresse de téléchargement inattendue : mise à jour annulée.")
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", url, headers={"User-Agent": "CodeX-KillFeed"}) as r:
                r.raise_for_status()
                buf = io.BytesIO()
                async for chunk in r.aiter_bytes():
                    buf.write(chunk)
                    if buf.tell() > MAX_ZIP_SIZE:
                        raise UpdateError("Fichier de mise à jour anormalement gros : annulé.")
                return buf.getvalue()
    except httpx.HTTPError as e:
        raise UpdateError(f"Téléchargement impossible ({e}). Vérifie la connexion Internet, puis réessaie.")


def _check_digest(data: bytes, digest: str) -> None:
    if not digest:
        logger.warning("[MAJ] GitHub ne fournit pas d'empreinte pour ce fichier — contrôle sauté")
        return
    algo, _, expected = digest.partition(":")
    if algo.lower() != "sha256" or hashlib.sha256(data).hexdigest() != expected.lower():
        raise UpdateError("Le fichier téléchargé est corrompu (empreinte différente) : mise à jour annulée.")


def _extract(data: bytes, expected_version: str, dest: Path) -> Path:
    """Extrait dans dest après contrôle ; retourne le dossier racine extrait."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise UpdateError("Le fichier téléchargé n'est pas un zip valide : mise à jour annulée.")
    names = [n for n in zf.namelist() if not n.endswith("/")]
    roots = {PurePosixPath(n).parts[0] for n in names}
    if len(roots) != 1:
        raise UpdateError("Contenu du zip inattendu : mise à jour annulée.")
    root = roots.pop()
    for n in names:
        p = PurePosixPath(n)
        if p.is_absolute() or ".." in p.parts or "\\" in n or ":" in n:
            raise UpdateError("Le zip contient un chemin dangereux : mise à jour annulée.")
    for required in ("main.py", "VERSION"):
        if f"{root}/{required}" not in names:
            raise UpdateError(f"Le zip ne contient pas {required} : mise à jour annulée.")
    version = zf.read(f"{root}/VERSION").decode("utf-8", "replace").strip()
    if version.lstrip("vV") != expected_version.lstrip("vV"):
        raise UpdateError(f"Le zip annonce la version {version} au lieu de {expected_version} : annulé.")
    if dest.exists():
        shutil.rmtree(dest)
    zf.extractall(dest)
    return dest / root


# ─── 4-6. Sauvegarde, remplacement, dépendances ───────────────────────────────

def _code_files(base: Path) -> list[PurePosixPath]:
    out = []
    for p in base.rglob("*"):
        if p.is_file():
            rel = PurePosixPath(p.relative_to(base).as_posix())
            if not _protected(rel):
                out.append(rel)
    return out


def _copy_tree(src: Path, dst: Path, files: list[PurePosixPath]) -> None:
    for rel in files:
        target = dst / Path(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / Path(*rel.parts), target)


def _apply(new_root: Path, current: str, target: str) -> dict:
    """Partie synchrone (exécutée hors de la boucle Discord)."""
    root = install_root()
    upd = _updates_dir()

    # 4. Sauvegardes
    backup_db = load_config().data_dir / "backups" / f"avant-maj-{target}.db"
    backup_db.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3
    dst = sqlite3.connect(str(backup_db))
    try:
        db.get_client()._conn.backup(dst)
    finally:
        dst.close()
    old_dir = upd / f"ancienne-version-{current}"
    for previous in upd.glob("ancienne-version-*"):   # une seule copie gardée
        shutil.rmtree(previous, ignore_errors=True)
    old_files = _code_files(root)
    _copy_tree(root, old_dir, old_files)

    old_req = (root / "requirements.txt").read_bytes() if (root / "requirements.txt").exists() else b""
    new_req = (new_root / "requirements.txt").read_bytes() if (new_root / "requirements.txt").exists() else b""

    # 5. Remplacement
    new_files = _code_files(new_root)
    _copy_tree(new_root, root, new_files)
    launcher_changed = any(
        (new_root / f).exists() and (root / f).exists()
        and (new_root / f).read_bytes() != (root / f).read_bytes()
        for f in ("scripts/windows/lancer-bot.bat",)
    )

    # 6. Dépendances : installées au prochain démarrage par bot/predeps.py,
    # AVANT que le bot charge ses modules (sous Windows, un module compilé déjà
    # chargé est verrouillé et pip ne pourrait pas le remplacer).
    if new_req != old_req:
        (upd / DEPS_FLAG).write_text(json.dumps({"rollback_dir": str(old_dir)}), encoding="utf-8")
    return {"launcher_changed": launcher_changed, "deps_changed": new_req != old_req}


async def run_update(release: dict, current: str, requested_by: str, channel_id: str) -> dict:
    """Télécharge, contrôle et installe la release. Lève UpdateError."""
    if _lock.locked():
        raise UpdateError("Une mise à jour est déjà en cours.")
    async with _lock:
        if not release.get("zip_url"):
            raise UpdateError("Cette version n'a pas de fichier zip à télécharger : mise à jour impossible.")
        data = await _download(release["zip_url"])
        _check_digest(data, release.get("digest", ""))
        staging = _updates_dir() / "nouvelle-version"
        loop = asyncio.get_running_loop()
        new_root = await loop.run_in_executor(None, _extract, data, release["tag"], staging)
        result = await loop.run_in_executor(None, _apply, new_root, current, release["tag"].lstrip("vV"))
        shutil.rmtree(staging, ignore_errors=True)
        db.set_setting("global", "maj_pending", json.dumps({
            "from": current, "to": release["tag"].lstrip("vV"),
            "by": requested_by, "channel_id": channel_id,
        }))
        logger.info(f"[MAJ] {current} → {release['tag']} installée, redémarrage")
        return result


def pop_pending() -> dict:
    """Mise à jour en attente de confirmation (lue une fois au démarrage)."""
    raw = db.get_setting("global", "maj_pending", "")
    if not raw:
        return {}
    db.set_setting("global", "maj_pending", "")
    try:
        return json.loads(raw)
    except Exception:
        return {}
