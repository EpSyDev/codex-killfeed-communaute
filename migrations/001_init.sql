-- migrations/001_init.sql
-- Schéma complet du kit CodeX self-hosted — dialecte SQLite pur.
--
-- Remplace les deux migrations précédentes (001 squelette SQLite + 002
-- whitelist en dialecte Postgres/Supabase), incompatibles entre elles et
-- jamais déployées nulle part. Source unique désormais.
--
-- Conventions :
--   • uuid Postgres        → TEXT (UUID généré par backend/sqlite_client.py
--                            quand la PK TEXT est absente du payload)
--   • bigserial/serial     → INTEGER PRIMARY KEY AUTOINCREMENT
--   • jsonb                → TEXT (JSON sérialisé, cf. JSON_COLUMNS du shim)
--   • timestamptz          → TEXT ISO8601 UTC
--   • boolean              → INTEGER 0/1
--
-- Les DEFAULT de date produisent EXACTEMENT le format de
-- datetime.now(timezone.utc).isoformat() ("…T12:00:00.123456+00:00") :
-- le code compare les dates en texte (.gte/.lt sur timestamp, first_seen,
-- recorded_at). Un défaut SQLite en "…Z" trierait après un "+00:00" de même
-- instant et ferait échouer silencieusement les purges et les filtres.
--
-- Idempotent : CREATE TABLE/INDEX IF NOT EXISTS uniquement — le fichier est
-- ré-exécuté à chaque démarrage du bot (backend.database.run_migrations()).
--
-- guild_id est conservé sur toutes les tables bien que le kit soit
-- single-tenant : décision actée pour ne pas toucher les .eq("guild_id", …)
-- existants (des dizaines de sites d'appel).
--
-- Les colonnes proviennent STRICTEMENT des select/insert/update/upsert du
-- code (backend/database.py, backend/whitelist.py, backend/poller.py,
-- bot/embeds.py) — rien n'est inventé.

-- ─── servers — un serveur DayZ piloté par le kit ─────────────────────────────
-- Le token Nitrado n'est PLUS stocké ici : il vit en clair dans le .env local
-- (NITRADO_TOKEN) et est injecté dans ServerConfig à la lecture. Fin du
-- chiffrement Fernet, qui ne protégeait qu'une base Supabase mutualisée.
CREATE TABLE IF NOT EXISTS servers (
    server_id     TEXT PRIMARY KEY,              -- UUID généré à l'insert
    guild_id      TEXT NOT NULL,
    service_id    TEXT NOT NULL,                 -- ID de service Nitrado
    server_name   TEXT NOT NULL DEFAULT 'DayZ Server',
    server_alias  TEXT NOT NULL DEFAULT '',
    map_name      TEXT NOT NULL DEFAULT 'chernarus',
    platform      TEXT NOT NULL DEFAULT 'dayzps',
    username      TEXT NOT NULL DEFAULT '',
    active        INTEGER NOT NULL DEFAULT 1,
    guild_name    TEXT NOT NULL DEFAULT '',
    setup_by_id   TEXT NOT NULL DEFAULT '',
    setup_by_name TEXT NOT NULL DEFAULT '',
    retention_days INTEGER NOT NULL DEFAULT 30,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00')
);
CREATE UNIQUE INDEX IF NOT EXISTS servers_guild_service_uidx
    ON servers (guild_id, service_id);

-- ─── channels — salons Discord par serveur ───────────────────────────────────
-- upsert on_conflict="guild_id,server_id,type" → index unique obligatoire.
-- server_id NOT NULL DEFAULT '' : set_channel() écrit '' quand il n'y a pas
-- de serveur résolu, et heal_generic_channels() cible ces lignes 'génériques'.
CREATE TABLE IF NOT EXISTS channels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   TEXT NOT NULL,
    server_id  TEXT NOT NULL DEFAULT '',
    type       TEXT NOT NULL,
    channel_id TEXT NOT NULL DEFAULT '',
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00')
);
CREATE UNIQUE INDEX IF NOT EXISTS channels_guild_server_type_uidx
    ON channels (guild_id, server_id, type);

-- ─── kills — événements parsés dans les logs ADM ─────────────────────────────
CREATE TABLE IF NOT EXISTS kills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    server_id   TEXT,
    timestamp   TEXT NOT NULL,                   -- ISO8601 UTC
    log_time    TEXT,
    kill_type   TEXT NOT NULL,                   -- pvp|pve|suicide|build|place|connection|flag
    cause       TEXT,
    detail      TEXT,
    victim_name TEXT NOT NULL,
    victim_x    INTEGER,
    victim_y    INTEGER,
    victim_z    INTEGER,
    killer_name TEXT,
    killer_x    INTEGER,
    killer_y    INTEGER,
    killer_z    INTEGER,
    distance    REAL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00')
);
CREATE INDEX IF NOT EXISTS kills_guild_ts_idx  ON kills (guild_id, timestamp);
CREATE INDEX IF NOT EXISTS kills_server_ts_idx ON kills (server_id, timestamp);
-- Dédup par clé naturelle (kill_exists_ts)
CREATE INDEX IF NOT EXISTS kills_dedup_idx     ON kills (kill_type, victim_name, timestamp);

-- ─── player_positions — dernière position connue ─────────────────────────────
-- upsert on_conflict="guild_id,player_name"
CREATE TABLE IF NOT EXISTS player_positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    server_id   TEXT,
    player_name TEXT NOT NULL,
    player_id   TEXT,
    x           INTEGER,
    y           INTEGER,
    z           INTEGER,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00')
);
CREATE UNIQUE INDEX IF NOT EXISTS player_positions_guild_player_uidx
    ON player_positions (guild_id, player_name);

-- ─── player_position_history — historique purgé à 7 jours ────────────────────
CREATE TABLE IF NOT EXISTS player_position_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    player_name TEXT NOT NULL,
    x           INTEGER,
    y           INTEGER,
    z           INTEGER,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00')
);
CREATE INDEX IF NOT EXISTS position_history_guild_recorded_idx
    ON player_position_history (guild_id, recorded_at);

-- ─── player_registry — première apparition d'un joueur ───────────────────────
-- upsert on_conflict="guild_id,player_name" + ignore_duplicates
CREATE TABLE IF NOT EXISTS player_registry (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    server_id   TEXT,
    player_name TEXT NOT NULL,
    first_seen  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS player_registry_guild_player_uidx
    ON player_registry (guild_id, player_name);

-- ─── poller_state — position de lecture dans le fichier ADM ──────────────────
-- Pas d'upsert : le code teste l'existence (is_("server_id","null")) puis
-- insert/update. Index simple suffisant.
CREATE TABLE IF NOT EXISTS poller_state (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     TEXT NOT NULL,
    server_id    TEXT,
    log_offset   INTEGER NOT NULL DEFAULT 0,
    current_file TEXT NOT NULL DEFAULT '',
    last_poll    TEXT,
    log_dir      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS poller_state_guild_server_idx
    ON poller_state (guild_id, server_id);

-- ─── guild_settings — réglages clé/valeur (filtres killfeed) ─────────────────
-- upsert on_conflict="guild_id,key"
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL DEFAULT '0',
    PRIMARY KEY (guild_id, key)
);

-- ─── pinned_messages — messages épinglés gérés par le bot ────────────────────
-- upsert on_conflict="guild_id,server_id,msg_type"
CREATE TABLE IF NOT EXISTS pinned_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   TEXT NOT NULL,
    server_id  TEXT NOT NULL DEFAULT '',
    msg_type   TEXT NOT NULL,
    message_id TEXT NOT NULL DEFAULT '',
    channel_id TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS pinned_messages_uidx
    ON pinned_messages (guild_id, server_id, msg_type);

-- ─── bot_heartbeat — ligne unique id=1 (signal de vie) ───────────────────────
CREATE TABLE IF NOT EXISTS bot_heartbeat (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    last_beat      TEXT,
    updated_at     TEXT,
    bot_version    TEXT NOT NULL DEFAULT '',
    guilds_count   INTEGER NOT NULL DEFAULT 0,
    active_servers INTEGER NOT NULL DEFAULT 0
);

-- ─── players — lien PSN ↔ Discord (source de vérité du kit) ──────────────────
-- La whitelist Nitrado reste LA source de vérité du droit de connexion.
-- id en TEXT/UUID : conservé du schéma porté, .eq("id", …) après insert.
CREATE TABLE IF NOT EXISTS players (
    id            TEXT PRIMARY KEY,              -- UUID généré à l'insert
    guild_id      TEXT NOT NULL,
    psn_id        TEXT NOT NULL,
    discord_id    TEXT NOT NULL DEFAULT '',
    discord_name  TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'whitelisted',   -- whitelisted | removed
    staff_notes   TEXT NOT NULL DEFAULT '',
    registered_by TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00')
);
CREATE UNIQUE INDEX IF NOT EXISTS players_guild_psn_uidx
    ON players (guild_id, psn_id);
CREATE INDEX IF NOT EXISTS players_guild_discord_idx
    ON players (guild_id, discord_id);

-- ─── whitelist — miroir local de la whitelist Nitrado ────────────────────────
-- upsert on_conflict="guild_id,player_name"
CREATE TABLE IF NOT EXISTS whitelist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    player_name TEXT NOT NULL,
    added_by    TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    added_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00')
);
CREATE UNIQUE INDEX IF NOT EXISTS whitelist_guild_player_uidx
    ON whitelist (guild_id, player_name);

-- ─── whitelist_requests — demandes du salon public ───────────────────────────
-- id en TEXT/UUID : il transite dans les custom_id Discord (wl_approve:{id})
-- puis revient en .eq("id", request_id).
-- questionnaire_answers : JSON sérialisé (cf. JSON_COLUMNS du shim).
CREATE TABLE IF NOT EXISTS whitelist_requests (
    id                    TEXT PRIMARY KEY,      -- UUID généré à l'insert
    guild_id              TEXT NOT NULL,
    discord_id            TEXT NOT NULL,
    discord_name          TEXT NOT NULL DEFAULT '',
    player_id             TEXT NOT NULL,         -- PSN / Gamertag saisi
    status                TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|refused
    questionnaire_answers TEXT NOT NULL DEFAULT '{}',
    processed_by          TEXT,
    processed_at          TEXT,
    reason                TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00')
);
CREATE INDEX IF NOT EXISTS whitelist_requests_pending_idx
    ON whitelist_requests (guild_id, discord_id, status);

-- ─── whitelist_config — configuration de la whitelist publique ───────────────
-- upsert on_conflict="guild_id" → guild_id est la clé primaire.
-- questionnaire : JSON sérialisé (liste de questions).
CREATE TABLE IF NOT EXISTS whitelist_config (
    guild_id           TEXT PRIMARY KEY,
    enabled            INTEGER NOT NULL DEFAULT 0,
    role_id            TEXT,
    approved_role_id   TEXT,
    request_channel_id TEXT,
    logs_channel_id    TEXT,
    message_id         TEXT,
    questionnaire      TEXT NOT NULL DEFAULT '[]',
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00')
);
