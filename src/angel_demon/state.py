"""SQLite persistence for sessions, rounds, messages, and model run metadata."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from angel_demon.models import AgentProfile, Character, Round, SessionState, UserProfile


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SessionStore:
    def __init__(self, db_path: str | Path = "data/state.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=10.0,
            autocommit=True,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        if self.db_path.name != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        conn.autocommit = False
        return conn

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._open_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id      TEXT PRIMARY KEY,
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

                CREATE INDEX IF NOT EXISTS idx_rounds_session ON rounds(session_id);
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_model_runs_session ON model_runs(session_id);
                """
            )

    def create_session(self) -> SessionState:
        now = datetime.now(UTC)
        session = SessionState(
            session_id=str(uuid4()),
            user_profile=UserProfile(),
            sunny_profile=AgentProfile(character=Character.SUNNY),
            crowley_profile=AgentProfile(character=Character.CROWLEY),
            created_at=now,
            updated_at=now,
        )
        self.save_session(session)
        return session

    def save_session(self, session: SessionState) -> None:
        session.updated_at = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, alignment, user_profile, sunny_profile, crowley_profile,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    alignment = excluded.alignment,
                    user_profile = excluded.user_profile,
                    sunny_profile = excluded.sunny_profile,
                    crowley_profile = excluded.crowley_profile,
                    updated_at = excluded.updated_at
                """,
                (
                    session.session_id,
                    session.alignment_score,
                    session.user_profile.model_dump_json(),
                    session.sunny_profile.model_dump_json(),
                    session.crowley_profile.model_dump_json(),
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )

    def load_session(self, session_id: str) -> SessionState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None

            round_rows = conn.execute(
                """
                SELECT round_data FROM rounds
                WHERE session_id = ?
                ORDER BY round_number ASC
                """,
                (session_id,),
            ).fetchall()

        return SessionState(
            session_id=row["session_id"],
            rounds=[Round.model_validate_json(r["round_data"]) for r in round_rows],
            alignment_score=row["alignment"],
            user_profile=UserProfile.model_validate_json(row["user_profile"]),
            sunny_profile=AgentProfile.model_validate_json(row["sunny_profile"]),
            crowley_profile=AgentProfile.model_validate_json(row["crowley_profile"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def save_round(self, session_id: str, round_data: Round) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rounds (session_id, round_number, dilemma, round_data, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, round_number) DO UPDATE SET
                    dilemma = excluded.dilemma,
                    round_data = excluded.round_data
                """,
                (
                    session_id,
                    round_data.round_number,
                    round_data.dilemma,
                    round_data.model_dump_json(),
                    round_data.timestamp.isoformat(),
                ),
            )

    def save_message(
        self,
        session_id: str,
        round_number: int,
        role: str,
        content: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (session_id, round_number, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, round_number, role, content, _now_iso()),
            )

    def log_model_run(
        self,
        session_id: str,
        round_number: int,
        call_type: str,
        model: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        was_streamed: bool = False,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_runs (
                    session_id, round_number, call_type, model, input_tokens, output_tokens,
                    latency_ms, was_streamed, error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    round_number,
                    call_type,
                    model,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    1 if was_streamed else 0,
                    error,
                    _now_iso(),
                ),
            )

    def list_sessions(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.session_id, s.alignment, s.updated_at, COUNT(r.id) AS round_count
                FROM sessions s
                LEFT JOIN rounds r ON r.session_id = s.session_id
                GROUP BY s.session_id
                ORDER BY s.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_messages(self, session_id: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT round_number, role, content, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
