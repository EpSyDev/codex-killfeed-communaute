"""
backend/sqlite_client.py
Shim SQLite reproduisant le sous-ensemble de l'API supabase-py réellement
utilisé par le kit — pour supprimer la dépendance réseau Supabase sans
toucher un seul site d'appel.

CONVENTION SYNCHRONE (vérifiée avant écriture) : aucun `.execute()` du kit
n'est `await`é (`grep -rn "await .*\\.execute()"` → 0 résultat). Le shim est
donc 100 % synchrone et s'appuie sur la stdlib `sqlite3`, pas sur `aiosqlite`.

SOUS-ENSEMBLE SUPPORTÉ (recensé par grep sur backend/*.py + bot/*.py, rien
de plus — ce n'est pas un ORM générique) :

    .table(name)
    .select(cols, count="exact")        cols = "*" | "a" | "a,b,c"
    .insert(payload)                    → .data = [ligne insérée]
    .update(payload)                    → .data = [lignes modifiées]
    .upsert(payload, on_conflict="a,b", ignore_duplicates=False)
    .delete()                           → .data = [lignes supprimées]
    .eq / .gte / .lt / .lte / .ilike / .is_ / .or_
    .limit(n)
    .order(col, desc=True|False)
    .execute()                          → objet avec .data et .count

Non implémenté volontairement (aucun appel dans le kit) : neq, gt, in_, like,
not_, range, single, maybe_single, rpc, storage. Toute tentative lève
NotImplementedError plutôt que de renvoyer un résultat faux.

Détails de fidélité à PostgREST :
  • `.insert()` / `.update()` / `.delete()` renvoient la représentation des
    lignes touchées (le kit s'en sert : `res.data[0]["id"]` après insert,
    `len(res.data)` après delete pour compter les purges).
  • `.upsert(payload, on_conflict=…)` ne met à jour QUE les colonnes présentes
    dans le payload (comme `Prefer: resolution=merge-duplicates`), les autres
    gardent leur valeur — cf. whitelist.upsert_config() qui envoie des champs
    partiels.
  • Les colonnes JSON (questionnaire, questionnaire_answers) sont sérialisées
    à l'écriture et désérialisées à la lecture, comme le ferait `jsonb`.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("killfeed.sqlite")

# Colonnes stockées en TEXT mais manipulées comme du JSON côté Python
# (équivalent des colonnes `jsonb` de l'ancien schéma Postgres).
JSON_COLUMNS: dict[str, set[str]] = {
    "whitelist_config":   {"questionnaire"},
    "whitelist_requests": {"questionnaire_answers"},
}

_IDENT_RE   = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COLUMNS_RE = re.compile(r"^\*$|^[A-Za-z_][A-Za-z0-9_]*(\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*$")


def _check_ident(name: str) -> str:
    if not _IDENT_RE.match(name or ""):
        raise ValueError(f"Identifiant SQL invalide : {name!r}")
    return name


@dataclass
class APIResponse:
    """Réponse minimale — même surface que celle de supabase-py (.data / .count)."""
    data:  list[dict]
    count: Optional[int] = None


class _Query:
    """Builder fluent. Une instance par requête (jamais réutilisée)."""

    def __init__(self, client: "SQLiteClient", table: str):
        self._client  = client
        self._table   = _check_ident(table)
        self._op:      str = "select"
        self._columns: str = "*"
        self._payload: dict[str, Any] = {}
        self._filters: list[tuple[str, list]] = []
        self._order:   Optional[tuple[str, bool]] = None
        self._limit:   Optional[int] = None
        self._count:   Optional[str] = None
        self._on_conflict: Optional[str] = None
        self._ignore_duplicates: bool = False

    # ── Opérations ────────────────────────────────────────────────────────────

    def select(self, *columns: str, count: Optional[str] = None) -> "_Query":
        cols = ",".join(c for c in columns if c) or "*"
        if not _COLUMNS_RE.match(cols.strip()):
            raise ValueError(f"Liste de colonnes invalide : {cols!r}")
        self._op      = "select"
        self._columns = cols
        self._count   = count
        return self

    def insert(self, payload: dict) -> "_Query":
        self._op      = "insert"
        self._payload = dict(payload)
        return self

    def update(self, payload: dict) -> "_Query":
        self._op      = "update"
        self._payload = dict(payload)
        return self

    def upsert(self, payload: dict, on_conflict: Optional[str] = None,
               ignore_duplicates: bool = False) -> "_Query":
        self._op                 = "upsert"
        self._payload            = dict(payload)
        self._on_conflict        = on_conflict
        self._ignore_duplicates  = ignore_duplicates
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    # ── Filtres ───────────────────────────────────────────────────────────────

    def eq(self, column: str, value: Any) -> "_Query":
        col = _check_ident(column)
        if value is None:
            self._filters.append((f"{col} IS NULL", []))
        else:
            self._filters.append((f"{col} = ?", [_adapt(self._table, col, value)]))
        return self

    def gte(self, column: str, value: Any) -> "_Query":
        return self._cmp(column, ">=", value)

    def lt(self, column: str, value: Any) -> "_Query":
        return self._cmp(column, "<", value)

    def lte(self, column: str, value: Any) -> "_Query":
        return self._cmp(column, "<=", value)

    def _cmp(self, column: str, op: str, value: Any) -> "_Query":
        col = _check_ident(column)
        self._filters.append((f"{col} {op} ?", [_adapt(self._table, col, value)]))
        return self

    def ilike(self, column: str, pattern: str) -> "_Query":
        """LIKE SQLite : déjà insensible à la casse sur l'ASCII (= ilike ici)."""
        col = _check_ident(column)
        self._filters.append((f"{col} LIKE ?", [pattern]))
        return self

    def is_(self, column: str, value: Any) -> "_Query":
        col = _check_ident(column)
        norm = str(value).lower() if value is not None else "null"
        if value is None or norm == "null":
            self._filters.append((f"{col} IS NULL", []))
        elif norm in ("true", "false"):
            self._filters.append((f"{col} = ?", [1 if norm == "true" else 0]))
        else:
            raise NotImplementedError(f".is_({column!r}, {value!r}) non supporté")
        return self

    def or_(self, filters: str) -> "_Query":
        """Filtre PostgREST `col.op.valeur,col.op.valeur` joint par OR.

        Seul cas exercé : "server_id.is.null,server_id.eq." dans
        database.heal_generic_channels(). Les opérateurs autres que is/eq
        lèvent NotImplementedError au lieu d'être silencieusement ignorés.
        """
        parts, params = [], []
        for clause in filters.split(","):
            clause = clause.strip()
            if not clause:
                continue
            bits = clause.split(".", 2)
            if len(bits) < 3:
                raise NotImplementedError(f"Clause or_ non supportée : {clause!r}")
            col, op, raw = _check_ident(bits[0]), bits[1], bits[2]
            if op == "is" and raw.lower() == "null":
                parts.append(f"{col} IS NULL")
            elif op == "eq":
                parts.append(f"{col} = ?")
                params.append(raw)
            else:
                raise NotImplementedError(f"Opérateur or_ non supporté : {clause!r}")
        if parts:
            self._filters.append(("(" + " OR ".join(parts) + ")", params))
        return self

    # ── Modificateurs ─────────────────────────────────────────────────────────

    def limit(self, size: int) -> "_Query":
        self._limit = int(size)
        return self

    def order(self, column: str, desc: bool = False) -> "_Query":
        self._order = (_check_ident(column), bool(desc))
        return self

    # ── Méthodes volontairement non implémentées ─────────────────────────────

    def _unsupported(self, name: str):
        def _raise(*_a, **_kw):
            raise NotImplementedError(
                f".{name}() n'est pas implémenté par le shim SQLite "
                "(aucun appel dans le kit — ajouter le support avant de l'utiliser)."
            )
        return _raise

    def __getattr__(self, name: str):
        if name in ("neq", "gt", "in_", "like", "not_", "range",
                    "single", "maybe_single", "match", "contains"):
            return self._unsupported(name)
        raise AttributeError(name)

    # ── Exécution ─────────────────────────────────────────────────────────────

    def _where(self) -> tuple[str, list]:
        if not self._filters:
            return "", []
        sql    = " WHERE " + " AND ".join(f for f, _ in self._filters)
        params = [p for _, ps in self._filters for p in ps]
        return sql, params

    def execute(self) -> APIResponse:
        with self._client._lock:
            handler = {
                "select": self._exec_select,
                "insert": self._exec_insert,
                "update": self._exec_update,
                "upsert": self._exec_upsert,
                "delete": self._exec_delete,
            }[self._op]
            return handler()

    # -- select ---------------------------------------------------------------

    def _exec_select(self) -> APIResponse:
        where, params = self._where()
        sql = f"SELECT {self._columns} FROM {self._table}{where}"
        if self._order:
            sql += f" ORDER BY {self._order[0]} {'DESC' if self._order[1] else 'ASC'}"
        if self._limit is not None:
            sql += f" LIMIT {self._limit}"
        rows  = self._client._fetch(sql, params, self._table)
        total = None
        if self._count:
            cur   = self._client._conn.execute(
                f"SELECT COUNT(*) FROM {self._table}{where}", params)
            total = cur.fetchone()[0]
        return APIResponse(data=rows, count=total)

    # -- insert ---------------------------------------------------------------

    def _exec_insert(self) -> APIResponse:
        payload = self._client._with_generated_pk(self._table, self._payload)
        cols    = [_check_ident(c) for c in payload]
        values  = [_adapt(self._table, c, payload[c]) for c in cols]
        sql = (f"INSERT INTO {self._table} ({', '.join(cols)}) "
               f"VALUES ({', '.join('?' * len(cols))})")
        cur = self._client._conn.execute(sql, values)
        rows = self._client._fetch(
            f"SELECT * FROM {self._table} WHERE rowid = ?", [cur.lastrowid], self._table)
        return APIResponse(data=rows)

    # -- upsert ---------------------------------------------------------------

    def _exec_upsert(self) -> APIResponse:
        conflict = ([_check_ident(c.strip()) for c in self._on_conflict.split(",")]
                    if self._on_conflict else self._client._pk_columns(self._table))
        if not conflict:
            raise ValueError(f"upsert sur {self._table} sans cible de conflit")

        payload = self._client._with_generated_pk(self._table, self._payload)
        cols    = [_check_ident(c) for c in payload]
        values  = [_adapt(self._table, c, payload[c]) for c in cols]
        sql = (f"INSERT INTO {self._table} ({', '.join(cols)}) "
               f"VALUES ({', '.join('?' * len(cols))}) "
               f"ON CONFLICT({', '.join(conflict)}) ")
        updatable = [c for c in cols if c not in conflict]
        if self._ignore_duplicates or not updatable:
            sql += "DO NOTHING"
        else:
            sql += "DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in updatable)
        self._client._conn.execute(sql, values)

        # Relecture par la cible de conflit (fiable même avec DO NOTHING)
        if all(c in payload for c in conflict):
            where  = " AND ".join(f"{c} = ?" for c in conflict)
            params = [_adapt(self._table, c, payload[c]) for c in conflict]
            rows   = self._client._fetch(
                f"SELECT * FROM {self._table} WHERE {where}", params, self._table)
        else:
            rows = []
        return APIResponse(data=rows)

    # -- update ---------------------------------------------------------------

    def _exec_update(self) -> APIResponse:
        where, params = self._where()
        rowids = [r[0] for r in self._client._conn.execute(
            f"SELECT rowid FROM {self._table}{where}", params).fetchall()]
        if not rowids:
            return APIResponse(data=[])
        cols   = [_check_ident(c) for c in self._payload]
        values = [_adapt(self._table, c, self._payload[c]) for c in cols]
        marks  = ", ".join("?" * len(rowids))
        self._client._conn.execute(
            f"UPDATE {self._table} SET {', '.join(f'{c} = ?' for c in cols)} "
            f"WHERE rowid IN ({marks})", values + rowids)
        rows = self._client._fetch(
            f"SELECT * FROM {self._table} WHERE rowid IN ({marks})", rowids, self._table)
        return APIResponse(data=rows)

    # -- delete ---------------------------------------------------------------

    def _exec_delete(self) -> APIResponse:
        where, params = self._where()
        rows = self._client._fetch(
            f"SELECT rowid AS _rowid, * FROM {self._table}{where}", params, self._table)
        if not rows:
            return APIResponse(data=[])
        rowids = [r.pop("_rowid") for r in rows]
        marks  = ", ".join("?" * len(rowids))
        self._client._conn.execute(
            f"DELETE FROM {self._table} WHERE rowid IN ({marks})", rowids)
        return APIResponse(data=rows)


# ─── Conversion de valeurs ────────────────────────────────────────────────────

def _adapt(table: str, column: str, value: Any) -> Any:
    """Python → SQLite. bool → int, dict/list → JSON."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (dict, list)):
        if column not in JSON_COLUMNS.get(table, set()):
            logger.warning(
                f"[SQLite] {table}.{column} reçoit un {type(value).__name__} non "
                "déclaré dans JSON_COLUMNS — sérialisé, mais relu en texte brut."
            )
        return json.dumps(value, ensure_ascii=False)
    return value


def _row_to_dict(table: str, row: sqlite3.Row) -> dict:
    data     = dict(row)
    json_cols = JSON_COLUMNS.get(table, set())
    for col in json_cols & data.keys():
        raw = data[col]
        if isinstance(raw, str) and raw:
            try:
                data[col] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    return data


# ─── Client ───────────────────────────────────────────────────────────────────

class SQLiteClient:
    """Substitut de `supabase.Client` — même point d'accès (`.table(...)`)."""

    def __init__(self, db_path: str | Path, migrations_dir: str | Path | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False : certaines tâches passent par run_in_executor.
        # isolation_level=None : autocommit, comme PostgREST (1 requête = 1 commit).
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False,
                                     isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._pk_cache: dict[str, list[tuple[str, str]]] = {}
        if migrations_dir:
            self.apply_migrations(migrations_dir)

    # ── Surface publique ─────────────────────────────────────────────────────

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def from_(self, name: str) -> _Query:      # alias PostgREST
        return self.table(name)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── Migrations ───────────────────────────────────────────────────────────

    def apply_migrations(self, migrations_dir: str | Path) -> list[str]:
        """Exécute les .sql du dossier dans l'ordre alphabétique (idempotents)."""
        path = Path(migrations_dir)
        if not path.is_dir():
            logger.warning(f"[SQLite] Dossier de migrations introuvable : {path}")
            return []
        applied = []
        with self._lock:
            for sql_file in sorted(path.glob("*.sql")):
                self._conn.executescript(sql_file.read_text(encoding="utf-8"))
                applied.append(sql_file.name)
        self._pk_cache.clear()
        logger.info(f"[SQLite] {self.db_path.name} — migrations appliquées : "
                    f"{', '.join(applied) or 'aucune'}")
        return applied

    # ── Internes ─────────────────────────────────────────────────────────────

    def _fetch(self, sql: str, params: list, table: str) -> list[dict]:
        cur = self._conn.execute(sql, params)
        return [_row_to_dict(table, r) for r in cur.fetchall()]

    def _pk_info(self, table: str) -> list[tuple[str, str]]:
        """[(nom, type)] des colonnes de clé primaire."""
        if table not in self._pk_cache:
            rows = self._conn.execute(f"PRAGMA table_info({_check_ident(table)})").fetchall()
            self._pk_cache[table] = [(r["name"], (r["type"] or "").upper())
                                     for r in rows if r["pk"]]
        return self._pk_cache[table]

    def _pk_columns(self, table: str) -> list[str]:
        return [name for name, _ in self._pk_info(table)]

    def _with_generated_pk(self, table: str, payload: dict) -> dict:
        """Génère un UUID pour une PK TEXT absente du payload.

        Reproduit `default gen_random_uuid()` de l'ancien schéma Postgres pour
        players.id / whitelist_requests.id / servers.server_id, dont le code
        attend la valeur en retour d'insert.
        """
        pk = self._pk_info(table)
        if len(pk) != 1:
            return payload
        name, col_type = pk[0]
        if name in payload or not col_type.startswith("TEXT"):
            return payload
        return {**payload, name: str(uuid.uuid4())}


def create_client(db_path: str | Path,
                  migrations_dir: str | Path | None = None) -> SQLiteClient:
    """Remplaçant de `supabase.create_client` — même rôle, backend local."""
    return SQLiteClient(db_path, migrations_dir)
