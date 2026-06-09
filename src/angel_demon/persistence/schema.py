"""SQLite schema creation and migration helpers."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from angel_demon.logging_config import get_logger

logger = get_logger("state")

DEFAULT_USER_NAME = "Anonymous Player"
SCHEMA_VERSION = 4

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id      TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    alignment       INTEGER NOT NULL DEFAULT 0,
    user_profile    TEXT NOT NULL,
    sunny_profile   TEXT NOT NULL,
    crowley_profile TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rounds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    round_number    INTEGER NOT NULL,
    dilemma         TEXT NOT NULL,
    round_data      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(session_id, round_number)
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    round_number    INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    round_number    INTEGER NOT NULL,
    call_type       TEXT NOT NULL,
    model           TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    was_streamed    INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_jobs (
    session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    round_number    INTEGER NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (session_id, round_number)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_rounds_session ON rounds(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_model_runs_session ON model_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_jobs_status ON memory_jobs(status);
PRAGMA user_version = 4;
"""


def initialize_schema(conn: sqlite3.Connection, db_path: Path) -> None:
    """Bring a database up to the schema version supported by the application."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {version} is newer than supported "
            f"version {SCHEMA_VERSION}."
        )

    if version < 2 and _has_legacy_sessions_table(conn):
        _migrate_legacy_sessions_to_users(conn, db_path)

    conn.executescript(SCHEMA_SQL)
    _recover_interrupted_memory_jobs(conn)


def _recover_interrupted_memory_jobs(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE memory_jobs SET status = 'pending' WHERE status = 'processing'")


def _migrate_legacy_sessions_to_users(
    conn: sqlite3.Connection,
    db_path: Path,
) -> None:
    now = datetime.now(UTC).isoformat()
    default_user_id = str(uuid4())
    logger.warning(
        "migrating_legacy_sqlite_schema db_path=%s target_version=%s",
        db_path,
        SCHEMA_VERSION,
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id      TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO users (user_id, display_name, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (default_user_id, DEFAULT_USER_NAME, now, now),
    )
    conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
    conn.execute(
        "UPDATE sessions SET user_id = ? WHERE user_id IS NULL",
        (default_user_id,),
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
    conn.execute("PRAGMA user_version = 2")


def _has_legacy_sessions_table(conn: sqlite3.Connection) -> bool:
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sessions'"
    ).fetchone()
    if table is None:
        return False
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    return "user_id" not in columns
