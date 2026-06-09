"""Conversions between SQLite records and domain models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from angel_demon.models import AgentProfile, Round, SessionState, User, UserProfile


def user_from_row(row: Any) -> User:
    return User(
        user_id=row["user_id"],
        display_name=row["display_name"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def session_from_rows(row: Any, round_rows: list[Any]) -> SessionState:
    return SessionState(
        session_id=row["session_id"],
        user_id=row["user_id"],
        rounds=[Round.model_validate_json(item["round_data"]) for item in round_rows],
        alignment_score=row["alignment"],
        user_profile=UserProfile.model_validate_json(row["user_profile"]),
        sunny_profile=AgentProfile.model_validate_json(row["sunny_profile"]),
        crowley_profile=AgentProfile.model_validate_json(row["crowley_profile"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def refresh_session_from_rows(
    session: SessionState,
    row: Any,
    round_rows: list[Any],
) -> None:
    refreshed = session_from_rows(row, round_rows)
    for field_name in SessionState.model_fields:
        setattr(session, field_name, getattr(refreshed, field_name))
