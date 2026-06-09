"""Low-level SQLite write statements used by SessionStore transactions."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from angel_demon.models import Round, SessionState


def write_session(conn: sqlite3.Connection, session: SessionState) -> None:
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


def write_round(
    conn: sqlite3.Connection,
    session_id: str,
    round_data: Round,
) -> None:
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


def write_message(
    conn: sqlite3.Connection,
    session_id: str,
    round_number: int,
    role: str,
    content: str,
) -> None:
    conn.execute(
        """
        INSERT INTO messages (session_id, round_number, role, content, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, round_number, role, content, _now_iso()),
    )


def write_model_run(
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


def write_memory_job(
    conn: sqlite3.Connection,
    session_id: str,
    round_number: int,
    status: str,
) -> None:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO memory_jobs (
            session_id, round_number, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_id, round_number) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (session_id, round_number, status, now, now),
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
