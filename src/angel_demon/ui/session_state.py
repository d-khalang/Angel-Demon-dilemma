"""Typed accessors for Streamlit session state keys."""

from __future__ import annotations

import streamlit as st

from angel_demon.models import ConversationDraft, Round

USER_ID_KEY = "user_id"
SESSION_ID_KEY = "session_id"
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


def has_current_round() -> bool:
    return CURRENT_ROUND_KEY in st.session_state


def get_current_round() -> Round | None:
    value = st.session_state.get(CURRENT_ROUND_KEY)
    if not isinstance(value, str):
        return None
    return Round.model_validate_json(value)


def set_current_round(round_data: Round) -> None:
    st.session_state[CURRENT_ROUND_KEY] = round_data.model_dump_json()


def clear_current_round() -> None:
    st.session_state.pop(CURRENT_ROUND_KEY, None)


def has_current_draft() -> bool:
    return CURRENT_DRAFT_KEY in st.session_state


def get_current_draft() -> ConversationDraft | None:
    value = st.session_state.get(CURRENT_DRAFT_KEY)
    if not isinstance(value, str):
        return None
    return ConversationDraft.model_validate_json(value)


def set_current_draft(draft: ConversationDraft) -> None:
    st.session_state[CURRENT_DRAFT_KEY] = draft.model_dump_json()


def clear_current_draft() -> None:
    st.session_state.pop(CURRENT_DRAFT_KEY, None)


def switch_user(user_id: str) -> None:
    set_user_id(user_id)
    clear_session_id()
    clear_current_round()
    clear_current_draft()


def switch_session(session_id: str) -> None:
    set_session_id(session_id)
    clear_current_round()
    clear_current_draft()


def clear_active_context() -> None:
    st.session_state.pop(USER_ID_KEY, None)
    clear_session_id()
    clear_current_round()
    clear_current_draft()
