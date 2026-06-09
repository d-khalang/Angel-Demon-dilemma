"""SQLite persistence for sessions, rounds, messages, and model run metadata."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from angel_demon.logging_config import get_logger
from angel_demon.models import (
    AgentProfile,
    Character,
    ConversationMessage,
    ConversationSpeaker,
    ResponseTarget,
    Round,
    SessionState,
    User,
    UserProfile,
)
from angel_demon.persistence.records import (
    refresh_session_from_rows,
    session_from_rows,
    user_from_row,
)
from angel_demon.persistence.schema import (
    DEFAULT_USER_NAME,
    initialize_schema,
)
from angel_demon.persistence.schema import (
    SCHEMA_VERSION as SCHEMA_VERSION,
)
from angel_demon.persistence.writes import (
    write_memory_job,
    write_message,
    write_model_run,
    write_round,
    write_session,
)

logger = get_logger("state")


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
        logger.debug("sqlite_connection_opened db_path=%s", self.db_path)
        return conn

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self._open_connection()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            if conn.in_transaction:
                conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
            logger.debug("sqlite_connection_closed db_path=%s", self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            initialize_schema(conn, self.db_path)

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
            return user_from_row(row)
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
        return user_from_row(row)

    def list_users(self) -> list[User]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
        return [user_from_row(row) for row in rows]

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
            self._write_session(conn, session)
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

        session = session_from_rows(row, round_rows)
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
            self._write_round(conn, session_id, round_data)
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
            self._write_message(conn, session_id, round_number, role, content)
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
            self._write_model_run(
                conn,
                session_id,
                round_number,
                call_type,
                model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                was_streamed=was_streamed,
                error=error,
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

    def create_round(self, session: SessionState, dilemma: str) -> Round:
        """Allocate and persist a round number under a SQLite write lock."""
        with self._connect(immediate=True) as conn:
            self._refresh_session(conn, session)
            row = conn.execute(
                "SELECT COALESCE(MAX(round_number), 0) + 1 FROM rounds WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()
            round_number = int(row[0])
            round_data = Round(
                round_number=round_number,
                dilemma=dilemma,
                conversation=[
                    ConversationMessage(
                        speaker=ConversationSpeaker.USER,
                        content=dilemma,
                        target=ResponseTarget.BOTH,
                    )
                ],
            )
            session.rounds.append(round_data)
            session.rounds.sort(key=lambda item: item.round_number)
            session.updated_at = datetime.now(UTC)
            self._write_round(conn, session.session_id, round_data)
            self._write_message(conn, session.session_id, round_number, "user", dilemma)
            self._write_session(conn, session)
        return round_data

    def persist_round_transition(
        self,
        session: SessionState,
        round_data: Round,
        *,
        messages: list[tuple[str, str]] | None = None,
        model_runs: list[dict[str, Any]] | None = None,
        memory_job: Literal["enqueue", "complete", "cancel"] | None = None,
    ) -> None:
        """Persist one workflow transition atomically."""
        session.updated_at = datetime.now(UTC)
        with self._connect(immediate=True) as conn:
            self._write_round(conn, session.session_id, round_data)
            self._write_session(conn, session)
            for role, content in messages or []:
                self._write_message(
                    conn,
                    session.session_id,
                    round_data.round_number,
                    role,
                    content,
                )
            for run in model_runs or []:
                self._write_model_run(
                    conn,
                    session.session_id,
                    round_data.round_number,
                    str(run["call_type"]),
                    str(run["model"]),
                    input_tokens=run.get("input_tokens"),
                    output_tokens=run.get("output_tokens"),
                    latency_ms=run.get("latency_ms"),
                    was_streamed=bool(run.get("was_streamed", False)),
                    error=run.get("error"),
                )
            if memory_job == "enqueue":
                self._write_memory_job(conn, session.session_id, round_data.round_number, "pending")
            elif memory_job == "complete":
                self._write_memory_job(
                    conn,
                    session.session_id,
                    round_data.round_number,
                    "completed",
                )
            elif memory_job == "cancel":
                conn.execute(
                    "DELETE FROM memory_jobs WHERE session_id = ? AND round_number = ?",
                    (session.session_id, round_data.round_number),
                )

    def has_pending_memory_update(self, session_id: str, round_number: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM memory_jobs
                WHERE session_id = ? AND round_number = ? AND status = 'pending'
                """,
                (session_id, round_number),
            ).fetchone()
        return row is not None

    def claim_pending_memory_update(self, session_id: str, round_number: int) -> bool:
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE memory_jobs
                SET status = 'processing', updated_at = ?
                WHERE session_id = ? AND round_number = ? AND status = 'pending'
                """,
                (_now_iso(), session_id, round_number),
            )
        return cursor.rowcount == 1

    def requeue_memory_update(self, session_id: str, round_number: int) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE memory_jobs
                SET status = 'pending', updated_at = ?
                WHERE session_id = ? AND round_number = ? AND status = 'processing'
                """,
                (_now_iso(), session_id, round_number),
            )

    def discard_round(self, session: SessionState, round_number: int) -> None:
        """Remove a round that failed during initial generation."""
        session.rounds = [
            round_data
            for round_data in session.rounds
            if round_data.round_number != round_number
        ]
        session.updated_at = datetime.now(UTC)
        with self._connect(immediate=True) as conn:
            conn.execute(
                "DELETE FROM memory_jobs WHERE session_id = ? AND round_number = ?",
                (session.session_id, round_number),
            )
            conn.execute(
                "DELETE FROM model_runs WHERE session_id = ? AND round_number = ?",
                (session.session_id, round_number),
            )
            conn.execute(
                "DELETE FROM messages WHERE session_id = ? AND round_number = ?",
                (session.session_id, round_number),
            )
            conn.execute(
                "DELETE FROM rounds WHERE session_id = ? AND round_number = ?",
                (session.session_id, round_number),
            )
            self._write_session(conn, session)

    def _write_session(self, conn: sqlite3.Connection, session: SessionState) -> None:
        write_session(conn, session)

    def _refresh_session(
        self,
        conn: sqlite3.Connection,
        session: SessionState,
    ) -> None:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session.session_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown session_id: {session.session_id}")
        round_rows = conn.execute(
            """
            SELECT round_data FROM rounds
            WHERE session_id = ?
            ORDER BY round_number ASC
            """,
            (session.session_id,),
        ).fetchall()
        refresh_session_from_rows(session, row, round_rows)

    def _write_round(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        round_data: Round,
    ) -> None:
        write_round(conn, session_id, round_data)

    def _write_message(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        round_number: int,
        role: str,
        content: str,
    ) -> None:
        write_message(conn, session_id, round_number, role, content)

    def _write_model_run(
        self,
        conn: sqlite3.Connection,
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
        write_model_run(
            conn,
            session_id,
            round_number,
            call_type,
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            was_streamed=was_streamed,
            error=error,
        )

    def _write_memory_job(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        round_number: int,
        status: str,
    ) -> None:
        write_memory_job(conn, session_id, round_number, status)

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
