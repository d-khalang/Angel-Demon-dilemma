"""State-driven round actions for the Streamlit UI."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import streamlit as st

from angel_demon.dilemmas import validate_dilemma
from angel_demon.flow import (
    decide_round,
    reopen_round,
    revote_round,
    update_round_memory,
)
from angel_demon.llm import LLMError
from angel_demon.logging_config import get_logger
from angel_demon.models import ResponseTarget, Round, UserChoice
from angel_demon.state import SessionStore
from angel_demon.ui import session_state as ui_state
from angel_demon.ui.debate import (
    advance_chat_round,
    choose_dilemma,
    continue_chat_round,
    judge_chat_round,
    primary_action_label,
    start_chat_round,
)

TARGET_LABELS = {
    "both": ResponseTarget.BOTH,
    "Sunny": ResponseTarget.SUNNY,
    "Crowley": ResponseTarget.CROWLEY,
}


def selected_round(session_rounds: list[Round]) -> Round | None:
    if not session_rounds:
        return None
    selected_number = ui_state.get_selected_round_number()
    if selected_number is not None:
        for round_data in session_rounds:
            if round_data.round_number == selected_number:
                return round_data
        ui_state.clear_selected_round_number()
    if ui_state.is_composing_new_round():
        return None
    return session_rounds[-1]


def start_round(session: Any, settings: Any, store: SessionStore, llm: Any) -> None:
    dilemma, submitted = choose_dilemma()
    if not submitted:
        return
    is_valid, validation_error = validate_dilemma(dilemma)
    if not is_valid:
        st.caption(validation_error)
        return

    logger = get_logger("app")
    logger.info(
        "ui_start_debate_clicked session_id=%s dilemma_chars=%d",
        session.session_id,
        len(dilemma),
    )
    with st.chat_message("user"):
        st.write(dilemma)
    try:
        round_data = asyncio.run(start_chat_round(session, dilemma, settings, store, llm))
    except LLMError as exc:
        logger.exception(
            "ui_debate_start_failed session_id=%s error=%s",
            session.session_id,
            exc,
        )
        st.error(
            "The OpenAI request failed before the debate could finish. "
            "Check your API key, model access, and project quota, then try again."
        )
        st.caption(str(exc))
        return

    ui_state.set_selected_round_number(round_data.round_number)
    ui_state.stop_composing_new_round()
    ui_state.request_scroll_to_bottom()
    st.rerun()


def decision_buttons(
    session: Any,
    round_data: Round,
    store: SessionStore,
    *,
    revote: bool,
) -> None:
    col_a, col_b, col_c = st.columns(3)
    choices = (
        (col_a, "Follow Sunny", UserChoice.FOLLOW_SUNNY),
        (col_b, "Follow Crowley", UserChoice.FOLLOW_CROWLEY),
        (col_c, "Undecided", UserChoice.UNDECIDED),
    )
    for column, label, choice in choices:
        disabled = revote and round_data.user_choice == choice
        if column.button(label, use_container_width=True, disabled=disabled):
            get_logger("app").info(
                "ui_user_choice session_id=%s round_number=%d choice=%s revote=%s",
                session.session_id,
                round_data.round_number,
                choice.value,
                revote,
            )
            if revote:
                updated = revote_round(session, round_data, choice, store)
            else:
                updated = decide_round(session, round_data, choice, store)
                ui_state.set_pending_memory_round(round_data.round_number)
            ui_state.set_session_id(updated.session_id)
            ui_state.set_selected_round_number(round_data.round_number)
            ui_state.request_scroll_to_bottom()
            st.rerun()


def render_active_round_controls(
    session: Any,
    round_data: Round,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> None:
    action: str | None = None
    prompt: str | None = None
    selected_target: str | None = "both"
    with st.bottom:
        target_col, spacer_col, continue_col, finalize_col = st.columns(
            [1.45, 1.1, 1.05, 0.85],
            vertical_alignment="bottom",
        )
        with target_col:
            selected_target = st.segmented_control(
                "Reply to",
                options=list(TARGET_LABELS.keys()),
                default="both",
                key=f"reply_target_{round_data.round_number}",
            )
        spacer_col.empty()
        if continue_col.button(
            primary_action_label(round_data),
            type="primary",
            use_container_width=True,
        ):
            action = "advance"
        if finalize_col.button("Finalize", use_container_width=True):
            action = "judge"
        prompt = st.chat_input("Add context or ask a follow-up")

    if action == "advance":
        _continue_agent_debate(session, round_data, settings, store, llm)
    if action == "judge":
        _judge_round(session, round_data, settings, store, llm)
    if prompt:
        _send_followup(session, round_data, prompt, selected_target, settings, store, llm)


def render_reopen_option(session: Any, round_data: Round, store: SessionStore) -> None:
    with st.expander("More options", expanded=False):
        if st.button("Reopen debate", use_container_width=True):
            reopen_round(session, round_data, store)
            ui_state.set_selected_round_number(round_data.round_number)
            ui_state.request_scroll_to_bottom()
            st.rerun()


def maybe_update_pending_memory(
    session: Any,
    round_data: Round,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> None:
    pending_in_ui = ui_state.get_pending_memory_round() == round_data.round_number
    pending_in_store = store.has_pending_memory_update(
        session.session_id,
        round_data.round_number,
    )
    if not pending_in_ui and not pending_in_store:
        return
    if round_data.user_choice is None or round_data.verdict is None:
        ui_state.clear_pending_memory_round()
        return

    start = time.perf_counter()
    with st.spinner("Updating agent memory in the background..."):
        updated = asyncio.run(update_round_memory(session, round_data, llm, store, settings))
    ui_state.clear_pending_memory_round()
    ui_state.set_session_id(updated.session_id)
    get_logger("app").info(
        "ui_memory_updated session_id=%s round_number=%d elapsed_ms=%d",
        session.session_id,
        round_data.round_number,
        int((time.perf_counter() - start) * 1000),
    )


def _continue_agent_debate(
    session: Any,
    round_data: Round,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> None:
    try:
        updated = asyncio.run(advance_chat_round(session, round_data, settings, store, llm))
    except LLMError as exc:
        get_logger("app").exception(
            "ui_conversation_advance_failed session_id=%s error=%s",
            session.session_id,
            exc,
        )
        st.error(
            "The OpenAI request failed before the agents could continue. "
            "Check your API key, model access, and project quota, then try again."
        )
        st.caption(str(exc))
        return
    ui_state.set_selected_round_number(updated.round_number)
    ui_state.request_scroll_to_bottom()
    st.rerun()


def _judge_round(
    session: Any,
    round_data: Round,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> None:
    start = time.perf_counter()
    with st.spinner("The judge is reading the full transcript..."):
        try:
            updated = asyncio.run(judge_chat_round(session, round_data, settings, store, llm))
        except LLMError as exc:
            get_logger("app").exception(
                "ui_conversation_judge_failed session_id=%s error=%s",
                session.session_id,
                exc,
            )
            st.error(
                "The judge request failed. Check your API key, model access, "
                "and project quota, then try again."
            )
            st.caption(str(exc))
            return
    get_logger("app").info(
        "ui_judge_finished session_id=%s round_number=%d elapsed_ms=%d",
        session.session_id,
        updated.round_number,
        int((time.perf_counter() - start) * 1000),
    )
    ui_state.set_selected_round_number(updated.round_number)
    ui_state.request_scroll_to_bottom()
    st.rerun()


def _send_followup(
    session: Any,
    round_data: Round,
    prompt: str,
    selected_target: str | None,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> None:
    target = TARGET_LABELS[str(selected_target or "both")]
    with st.chat_message("user"):
        st.write(prompt)
    try:
        updated = asyncio.run(
            continue_chat_round(session, round_data, prompt, target, settings, store, llm)
        )
    except LLMError as exc:
        get_logger("app").exception(
            "ui_conversation_followup_failed session_id=%s error=%s",
            session.session_id,
            exc,
        )
        st.error(
            "The OpenAI request failed before the agents could respond. "
            "Check your API key, model access, and project quota, then try again."
        )
        st.caption(str(exc))
        return
    ui_state.set_selected_round_number(updated.round_number)
    ui_state.request_scroll_to_bottom()
    st.rerun()
