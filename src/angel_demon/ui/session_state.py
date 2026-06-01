"""Typed accessors for Streamlit session state keys."""

from __future__ import annotations

import streamlit as st

USER_ID_KEY = "user_id"
SESSION_ID_KEY = "session_id"
SELECTED_ROUND_KEY = "selected_round_number"
COMPOSE_NEW_ROUND_KEY = "compose_new_round"
SCROLL_TO_BOTTOM_KEY = "scroll_to_bottom"
PENDING_MEMORY_ROUND_KEY = "pending_memory_round_number"
CURRENT_ROUND_KEY = "current_round"
CURRENT_DRAFT_KEY = "current_conversation_draft"


def get_user_id() -> str | None:
    value = st.session_state.get(USER_ID_KEY)
    return value if isinstance(value, str) else None


def set_user_id(user_id: str) -> None:
    st.session_state[USER_ID_KEY] = user_id


def get_session_id() -> str | None:
    value = st.session_state.get(SESSION_ID_KEY)
    return value if isinstance(value, str) else None


def set_session_id(session_id: str) -> None:
    st.session_state[SESSION_ID_KEY] = session_id


def clear_session_id() -> None:
    st.session_state.pop(SESSION_ID_KEY, None)


def clear_current_round() -> None:
    st.session_state.pop(CURRENT_ROUND_KEY, None)


def clear_current_draft() -> None:
    st.session_state.pop(CURRENT_DRAFT_KEY, None)


def get_selected_round_number() -> int | None:
    value = st.session_state.get(SELECTED_ROUND_KEY)
    return value if isinstance(value, int) else None


def set_selected_round_number(round_number: int) -> None:
    st.session_state[SELECTED_ROUND_KEY] = round_number
    st.session_state[COMPOSE_NEW_ROUND_KEY] = False


def clear_selected_round_number() -> None:
    st.session_state.pop(SELECTED_ROUND_KEY, None)


def is_composing_new_round() -> bool:
    return bool(st.session_state.get(COMPOSE_NEW_ROUND_KEY))


def compose_new_round() -> None:
    clear_selected_round_number()
    st.session_state[COMPOSE_NEW_ROUND_KEY] = True


def stop_composing_new_round() -> None:
    st.session_state[COMPOSE_NEW_ROUND_KEY] = False


def request_scroll_to_bottom() -> None:
    st.session_state[SCROLL_TO_BOTTOM_KEY] = True


def consume_scroll_to_bottom() -> bool:
    return bool(st.session_state.pop(SCROLL_TO_BOTTOM_KEY, False))


def set_pending_memory_round(round_number: int) -> None:
    st.session_state[PENDING_MEMORY_ROUND_KEY] = round_number


def get_pending_memory_round() -> int | None:
    value = st.session_state.get(PENDING_MEMORY_ROUND_KEY)
    return value if isinstance(value, int) else None


def clear_pending_memory_round() -> None:
    st.session_state.pop(PENDING_MEMORY_ROUND_KEY, None)


def switch_user(user_id: str) -> None:
    set_user_id(user_id)
    clear_session_id()
    clear_selected_round_number()
    stop_composing_new_round()
    clear_pending_memory_round()
    clear_current_round()
    clear_current_draft()


def switch_session(session_id: str) -> None:
    set_session_id(session_id)
    clear_selected_round_number()
    stop_composing_new_round()
    clear_pending_memory_round()
    clear_current_round()
    clear_current_draft()


def clear_active_context() -> None:
    st.session_state.pop(USER_ID_KEY, None)
    clear_session_id()
    clear_selected_round_number()
    stop_composing_new_round()
    clear_pending_memory_round()
    clear_current_round()
    clear_current_draft()
