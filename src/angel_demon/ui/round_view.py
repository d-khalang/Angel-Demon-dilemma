"""Round thread rendering for the Streamlit app."""

from __future__ import annotations

from typing import Any

import streamlit as st

from angel_demon.models import Round, RoundStatus
from angel_demon.state import SessionStore
from angel_demon.ui import session_state as ui_state
from angel_demon.ui.debate import primary_action_label, render_round, render_transcript
from angel_demon.ui.round_actions import (
    decision_buttons,
    maybe_update_pending_memory,
    render_active_round_controls,
    render_reopen_option,
)
from angel_demon.ui.scroll import scroll_to_bottom_if_requested


def render_round_thread(
    session: Any,
    round_data: Round,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> None:
    st.subheader(f"Round {round_data.round_number}")
    render_transcript(round_data, session.alignment_score)
    render_round(round_data)

    if round_data.status == RoundStatus.ACTIVE:
        render_active_round_controls(session, round_data, settings, store, llm)
        scroll_to_bottom_if_requested()
        return

    if round_data.status == RoundStatus.JUDGED:
        st.subheader(primary_action_label(round_data))
        decision_buttons(session, round_data, store, revote=False)
        render_reopen_option(session, round_data, store)
        scroll_to_bottom_if_requested()
        return

    if st.button(primary_action_label(round_data), type="primary", use_container_width=True):
        ui_state.compose_new_round()
        st.rerun()
    with st.expander("Change my choice", expanded=False):
        decision_buttons(session, round_data, store, revote=True)
    render_reopen_option(session, round_data, store)
    scroll_to_bottom_if_requested()
    maybe_update_pending_memory(session, round_data, settings, store, llm)
