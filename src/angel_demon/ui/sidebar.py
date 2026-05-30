"""Sidebar controls for local users, sessions, and score summaries."""

from __future__ import annotations

import streamlit as st

from angel_demon.logging_config import get_logger
from angel_demon.models import Character, SessionState, User
from angel_demon.scoring import get_promotion_leader
from angel_demon.state import DEFAULT_USER_NAME, SessionStore
from angel_demon.ui import session_state as ui_state
from angel_demon.ui.debate import alignment_label

logger = get_logger("ui.sidebar")


def _session_label(row: dict[str, object]) -> str:
    updated = str(row["updated_at"]).replace("T", " ")[:16]
    round_count = row["round_count"]
    rounds = round_count if isinstance(round_count, int) else int(str(round_count))
    return f"{updated} | {rounds} rounds | alignment {row['alignment']}"


def _render_user_controls(active_user: User, session: SessionState, store: SessionStore) -> None:
    st.title("Users")
    all_users = store.list_users()
    named_users = [user for user in all_users if user.display_name != DEFAULT_USER_NAME]
    users = named_users or all_users
    user_ids = [user.user_id for user in users]
    if active_user.user_id not in user_ids:
        users.insert(0, active_user)
        user_ids.insert(0, active_user.user_id)

    selected_user_id = st.selectbox(
        "Active user",
        options=user_ids,
        format_func=lambda value: next(
            user.display_name for user in users if user.user_id == value
        ),
        index=user_ids.index(active_user.user_id),
    )
    if selected_user_id != active_user.user_id:
        ui_state.switch_user(selected_user_id)
        logger.info("ui_user_switched user_id=%s", selected_user_id)
        st.rerun()

    new_user_name = st.text_input("New user name", placeholder="e.g. Noor")
    if st.button("Create user", use_container_width=True, disabled=not new_user_name.strip()):
        user = store.create_user(new_user_name)
        if active_user.display_name == DEFAULT_USER_NAME:
            claimed_session = store.claim_anonymous_session(session.session_id, user.user_id)
            if claimed_session:
                ui_state.set_session_id(claimed_session.session_id)
        ui_state.set_user_id(user.user_id)
        ui_state.clear_current_round()
        logger.info("ui_user_created user_id=%s", user.user_id)
        st.rerun()


def _render_session_controls(active_user: User, session: SessionState, store: SessionStore) -> None:
    st.title("Sessions")
    session_rows = store.list_sessions(active_user.user_id)
    if session_rows:
        session_ids = [str(row["session_id"]) for row in session_rows]
        selected_session_id = st.selectbox(
            "Active session",
            options=session_ids,
            format_func=lambda value: _session_label(
                next(row for row in session_rows if row["session_id"] == value)
            ),
            index=session_ids.index(session.session_id),
        )
        if selected_session_id != session.session_id:
            ui_state.switch_session(selected_session_id)
            logger.info(
                "ui_session_switched user_id=%s session_id=%s",
                active_user.user_id,
                selected_session_id,
            )
            st.rerun()
    else:
        st.caption("No sessions yet.")

    if st.button("Start new session", use_container_width=True):
        new_session = store.create_session(active_user.user_id)
        ui_state.switch_session(new_session.session_id)
        logger.info(
            "ui_session_created user_id=%s session_id=%s",
            active_user.user_id,
            new_session.session_id,
        )
        st.rerun()


def _render_delete_controls(active_user: User, session: SessionState, store: SessionStore) -> None:
    with st.expander("Delete", expanded=False):
        confirm_session = st.checkbox("Confirm current session deletion")
        if st.button(
            "Delete current session",
            use_container_width=True,
            disabled=not confirm_session,
        ):
            store.delete_session(session.session_id)
            ui_state.clear_session_id()
            ui_state.clear_current_round()
            logger.info(
                "ui_session_deleted user_id=%s session_id=%s",
                active_user.user_id,
                session.session_id,
            )
            st.rerun()

        confirm_user = st.checkbox("Confirm active user deletion")
        if st.button(
            "Delete active user",
            use_container_width=True,
            disabled=not confirm_user,
        ):
            store.delete_user(active_user.user_id)
            ui_state.clear_active_context()
            logger.info("ui_user_deleted user_id=%s", active_user.user_id)
            st.rerun()


def _render_score_controls(session: SessionState) -> None:
    st.title("Promotion Race")
    leader = get_promotion_leader(session.sunny_profile, session.crowley_profile)
    leader_text = (
        "Tied" if leader is None else ("Sunny" if leader == Character.SUNNY else "Crowley")
    )
    col_a, col_b = st.columns(2)
    col_a.metric("Sunny", session.sunny_profile.wins)
    col_b.metric("Crowley", session.crowley_profile.wins)
    st.caption(f"Leader: {leader_text}")

    st.divider()
    st.title("Alignment")
    normalized = (session.alignment_score + 100) / 200
    st.progress(normalized)
    st.metric(alignment_label(session.alignment_score), session.alignment_score)


def _render_history(session: SessionState) -> None:
    st.title("History")
    if not session.rounds:
        st.caption("No rounds yet.")
    for round_data in reversed(session.rounds[-8:]):
        label = f"Round {round_data.round_number}: {round_data.verdict.winner.value} won"
        with st.expander(label):
            st.write(round_data.dilemma)
            if round_data.user_choice:
                st.caption(f"User chose: {round_data.user_choice.value}")
            st.caption(round_data.verdict.reason)


def render_sidebar(active_user: User, session: SessionState, store: SessionStore) -> None:
    with st.sidebar:
        _render_user_controls(active_user, session, store)
        st.divider()
        _render_session_controls(active_user, session, store)
        st.divider()
        _render_delete_controls(active_user, session, store)
        st.divider()
        _render_score_controls(session)
        st.divider()
        _render_history(session)
