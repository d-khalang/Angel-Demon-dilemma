"""SQLite persistence for sessions, rounds, messages, and model run metadata."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from angel_demon.logging_config import get_logger
from angel_demon.models import AgentProfile, Character, Round, SessionState, User, UserProfile

logger = get_logger("state")
DEFAULT_USER_NAME = "Anonymous Player"
SCHEMA_VERSION = 2


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SessionStore:
    def __init__(self, db_path: str | Path = "data/state.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("session_store_initialized db_path=%s", self.db_path)

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
        logger.debug("sqlite_connection_opened db_path=%s", self.db_path)
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
            logger.debug("sqlite_connection_closed db_path=%s", self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer than supported "
                    f"version {SCHEMA_VERSION}."
                )

            if version < 2 and self._has_legacy_sessions_table(conn):
                self._migrate_legacy_sessions_to_users(conn)

            self._create_schema(conn)

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
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

            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_rounds_session ON rounds(session_id);
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_model_runs_session ON model_runs(session_id);
            PRAGMA user_version = 2;
            """
        )

    def _migrate_legacy_sessions_to_users(self, conn: sqlite3.Connection) -> None:
        now = _now_iso()
        default_user_id = str(uuid4())
        logger.warning(
            "migrating_legacy_sqlite_schema db_path=%s target_version=%s",
            self.db_path,
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

    def _has_legacy_sessions_table(self, conn: sqlite3.Connection) -> bool:
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

    def create_user(self, display_name: str) -> User:
        now = datetime.now(UTC)
        user = User(
            user_id=str(uuid4()),
            display_name=display_name.strip() or DEFAULT_USER_NAME,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user.user_id,
                    user.display_name,
                    user.created_at.isoformat(),
                    user.updated_at.isoformat(),
                ),
            )
        logger.info("user_created user_id=%s display_name=%s", user.user_id, user.display_name)
        return user

    def get_or_create_default_user(self) -> User:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM users
                WHERE display_name = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (DEFAULT_USER_NAME,),
            ).fetchone()
        if row is not None:
            return User(
                user_id=row["user_id"],
                display_name=row["display_name"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        return self.create_user(DEFAULT_USER_NAME)

    def load_user(self, user_id: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            logger.info("user_load_miss user_id=%s", user_id)
            return None
        return User(
            user_id=row["user_id"],
            display_name=row["display_name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_users(self) -> list[User]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
        return [
            User(
                user_id=row["user_id"],
                display_name=row["display_name"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def create_session(self, user_id: str | None = None) -> SessionState:
        if user_id is None:
            user_id = self.get_or_create_default_user().user_id
        elif self.load_user(user_id) is None:
            raise ValueError(f"Unknown user_id: {user_id}")
        now = datetime.now(UTC)
        session = SessionState(
            session_id=str(uuid4()),
            user_id=user_id,
            user_profile=UserProfile(),
            sunny_profile=AgentProfile(character=Character.SUNNY),
            crowley_profile=AgentProfile(character=Character.CROWLEY),
            created_at=now,
            updated_at=now,
        )
        self.save_session(session)
        logger.info("session_created session_id=%s user_id=%s", session.session_id, user_id)
        return session

    def save_session(self, session: SessionState) -> None:
        session.updated_at = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, alignment, user_profile, sunny_profile, crowley_profile,
                    created_at, updated_at, user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
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
                    session.user_id,
                ),
            )
            conn.execute(
                "UPDATE users SET updated_at = ? WHERE user_id = ?",
                (session.updated_at.isoformat(), session.user_id),
            )
        logger.info(
            "session_saved session_id=%s user_id=%s alignment=%d rounds=%d",
            session.session_id,
            session.user_id,
            session.alignment_score,
            len(session.rounds),
        )

    def claim_anonymous_session(self, session_id: str, user_id: str) -> SessionState | None:
        session = self.load_session(session_id)
        if session is None:
            logger.info("anonymous_session_claim_miss session_id=%s", session_id)
            return None
        current_owner = self.load_user(session.user_id)
        if current_owner is None or current_owner.display_name != DEFAULT_USER_NAME:
            logger.warning(
                "anonymous_session_claim_rejected session_id=%s current_user_id=%s",
                session_id,
                session.user_id,
            )
            return session
        return self._transfer_session(session_id, user_id)

    def _transfer_session(self, session_id: str, user_id: str) -> SessionState | None:
        if self.load_user(user_id) is None:
            raise ValueError(f"Unknown user_id: {user_id}")
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET user_id = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (user_id, now, session_id),
            )
            conn.execute(
                "UPDATE users SET updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
        session = self.load_session(session_id)
        logger.info(
            "anonymous_session_claimed session_id=%s user_id=%s found=%s",
            session_id,
            user_id,
            session is not None,
        )
        return session

    def load_session(self, session_id: str) -> SessionState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                logger.info("session_load_miss session_id=%s", session_id)
                return None

            round_rows = conn.execute(
                """
                SELECT round_data FROM rounds
                WHERE session_id = ?
                ORDER BY round_number ASC
                """,
                (session_id,),
            ).fetchall()

        session = SessionState(
            session_id=row["session_id"],
            user_id=row["user_id"],
            rounds=[Round.model_validate_json(r["round_data"]) for r in round_rows],
            alignment_score=row["alignment"],
            user_profile=UserProfile.model_validate_json(row["user_profile"]),
            sunny_profile=AgentProfile.model_validate_json(row["sunny_profile"]),
            crowley_profile=AgentProfile.model_validate_json(row["crowley_profile"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        logger.info(
            "session_loaded session_id=%s user_id=%s alignment=%d rounds=%d",
            session.session_id,
            session.user_id,
            session.alignment_score,
            len(session.rounds),
        )
        return session

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
        logger.info(
            "round_saved session_id=%s round_number=%d dilemma_chars=%d",
            session_id,
            round_data.round_number,
            len(round_data.dilemma),
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
        logger.info(
            "message_saved session_id=%s round_number=%d role=%s content_chars=%d",
            session_id,
            round_number,
            role,
            len(content),
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
        logger.info(
            "model_run_logged session_id=%s round_number=%d call_type=%s model=%s "
            "latency_ms=%s streamed=%s error=%s",
            session_id,
            round_number,
            call_type,
            model,
            latency_ms,
            was_streamed,
            error,
        )

    def list_sessions(self, user_id: str | None = None) -> list[dict[str, object]]:
        with self._connect() as conn:
            if user_id is None:
                rows = conn.execute(
                    """
                    SELECT s.session_id, s.user_id, s.alignment, s.updated_at,
                           COUNT(r.id) AS round_count
                    FROM sessions s
                    LEFT JOIN rounds r ON r.session_id = s.session_id
                    GROUP BY s.session_id
                    ORDER BY s.updated_at DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.session_id, s.user_id, s.alignment, s.updated_at,
                           COUNT(r.id) AS round_count
                    FROM sessions s
                    LEFT JOIN rounds r ON r.session_id = s.session_id
                    WHERE s.user_id = ?
                    GROUP BY s.session_id
                    ORDER BY s.updated_at DESC
                    """,
                    (user_id,),
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
        logger.info("session_deleted session_id=%s", session_id)

    def delete_user(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        logger.info("user_deleted user_id=%s", user_id)
