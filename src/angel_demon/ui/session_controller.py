"""Session and user selection logic for the Streamlit UI."""

from __future__ import annotations

from angel_demon.logging_config import get_logger
from angel_demon.models import SessionState, User
from angel_demon.state import DEFAULT_USER_NAME, SessionStore
from angel_demon.ui import session_state as ui_state

logger = get_logger("ui.session_controller")


def _named_users(store: SessionStore) -> list[User]:
    return [user for user in store.list_users() if user.display_name != DEFAULT_USER_NAME]


def get_active_user(store: SessionStore) -> User:
    named_users = _named_users(store)
    user_id = ui_state.get_user_id()
    if user_id:
        user = store.load_user(user_id)
        if user:
            if user.display_name != DEFAULT_USER_NAME or not named_users:
                return user
            ui_state.clear_active_context()
            logger.info(
                "anonymous_user_hidden user_id=%s replacement_user_id=%s",
                user.user_id,
                named_users[0].user_id,
            )

    if named_users:
        user = named_users[0]
        ui_state.set_user_id(user.user_id)
        logger.info("active_named_user_selected user_id=%s", user.user_id)
        return user

    user = store.get_or_create_default_user()
    ui_state.set_user_id(user.user_id)
    logger.info("active_user_selected user_id=%s", user.user_id)
    return user


def get_active_session(store: SessionStore, user_id: str) -> SessionState:
    session_id = ui_state.get_session_id()
    if session_id:
        loaded = store.load_session(session_id)
        if loaded and loaded.user_id == user_id:
            logger.debug("session_loaded session_id=%s", loaded.session_id)
            return loaded
        ui_state.clear_session_id()

    session_rows = store.list_sessions(user_id)
    if session_rows:
        loaded = store.load_session(str(session_rows[0]["session_id"]))
        if loaded:
            ui_state.set_session_id(loaded.session_id)
            logger.info(
                "latest_session_selected user_id=%s session_id=%s",
                user_id,
                loaded.session_id,
            )
            return loaded

    session = store.create_session(user_id)
    ui_state.set_session_id(session.session_id)
    logger.info(
        "session_created user_id=%s session_id=%s",
        user_id,
        session.session_id,
    )
    return session
