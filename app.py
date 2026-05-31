from __future__ import annotations

import asyncio
from pathlib import Path

import streamlit as st

from angel_demon.config import load_settings
from angel_demon.dilemmas import validate_dilemma
from angel_demon.flow import apply_user_choice
from angel_demon.llm import LLMConfigurationError, LLMError, create_llm_provider
from angel_demon.logging_config import get_logger, setup_logging
from angel_demon.models import ResponseTarget, UserChoice
from angel_demon.state import SessionStore
from angel_demon.ui import session_state as ui_state
from angel_demon.ui.debate import (
    advance_chat_round,
    choose_dilemma,
    continue_chat_round,
    judge_chat_round,
    render_conversation,
    render_round,
    render_transcript,
    start_chat_round,
)
from angel_demon.ui.session_controller import get_active_session, get_active_user
from angel_demon.ui.sidebar import render_sidebar

st.set_page_config(
    page_title="Angel vs Demon - Moral Dilemma Debate",
    page_icon="AD",
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_css() -> None:
    css_path = Path("assets/style.css")
    if css_path.exists():
        st.markdown(
            f"<style>{css_path.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )


@st.cache_resource
def get_resources():
    settings = load_settings()
    setup_logging(settings)
    logger = get_logger("app")
    logger.info(
        "app_resources_loading provider=%s model=%s db_path=%s",
        settings.llm_provider,
        settings.openai_model,
        settings.db_path,
    )
    store = SessionStore(settings.db_path)
    llm = create_llm_provider(settings)
    logger.info("app_resources_loaded")
    return settings, store, llm


TARGET_LABELS = {
    "Both": ResponseTarget.BOTH,
    "Sunny": ResponseTarget.SUNNY,
    "Crowley": ResponseTarget.CROWLEY,
}


def main() -> None:
    load_css()
    st.title("Angel vs Demon")
    st.caption("Sunny and Crowley compete for your soul, one dilemma at a time.")

    try:
        settings, store, llm = get_resources()
    except LLMConfigurationError as exc:
        st.error(str(exc))
        st.info("Create a .env file from .env.example and set OPENAI_API_KEY.")
        return

    active_user = get_active_user(store)
    session = get_active_session(store, active_user.user_id)
    render_sidebar(active_user, session, store)

    draft = ui_state.get_current_draft()
    round_data = ui_state.get_current_round()

    if draft is None and round_data is None:
        dilemma, submitted = choose_dilemma()

        if submitted:
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
            ui_state.clear_current_round()
            ui_state.clear_current_draft()
            with st.chat_message("user"):
                st.write(dilemma)
            try:
                draft = asyncio.run(
                    start_chat_round(session, dilemma, settings, store, llm)
                )
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
            ui_state.set_current_draft(draft)
            st.rerun()

    if draft is not None:
        render_conversation(draft.messages)
        with st.bottom:
            selected_target = st.segmented_control(
                "Reply to",
                options=list(TARGET_LABELS.keys()),
                default="Both",
                key="reply_target",
            )
            st.caption(
                "Final judgment ends the debate and moves you to the decision step. "
                "Use Continue debate if you are not convinced yet."
            )
            col_a, col_b, col_c = st.columns([1, 1, 2])
            if col_a.button("Continue debate", use_container_width=True):
                with st.status("Continuing the debate...", expanded=False):
                    try:
                        draft = asyncio.run(
                            advance_chat_round(session, draft, settings, store, llm)
                        )
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
                ui_state.set_current_draft(draft)
                st.rerun()
            if col_b.button("Finalize with judge", type="primary", use_container_width=True):
                with st.status("Judging the debate...", expanded=False):
                    try:
                        round_data = asyncio.run(
                            judge_chat_round(session, draft, settings, store, llm)
                        )
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
                ui_state.set_current_round(round_data)
                ui_state.clear_current_draft()
                st.rerun()
            col_c.caption("Add context, challenge an agent, or ask one side directly.")
            prompt = st.chat_input("Add a follow-up or question")
        if prompt:
            target = TARGET_LABELS[str(selected_target or "Both")]
            with st.chat_message("user"):
                st.write(prompt)
            try:
                draft = asyncio.run(
                    continue_chat_round(session, draft, prompt, target, settings, store, llm)
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
            ui_state.set_current_draft(draft)
            st.rerun()

    if round_data and not round_data.user_choice:
        render_transcript(round_data)
        render_round(round_data)
        st.info("This debate has been finalized by the judge. Choose a side to complete the round.")
        st.subheader("Your decision")
        col_a, col_b, col_c = st.columns(3)
        choices = (
            (col_a, "Follow Sunny", UserChoice.FOLLOW_SUNNY),
            (col_b, "Follow Crowley", UserChoice.FOLLOW_CROWLEY),
            (col_c, "Undecided", UserChoice.UNDECIDED),
        )
        for column, label, choice in choices:
            if column.button(label, use_container_width=True):
                get_logger("app").info(
                    "ui_user_choice session_id=%s round_number=%d choice=%s",
                    session.session_id,
                    round_data.round_number,
                    choice.value,
                )
                updated = asyncio.run(
                    apply_user_choice(
                        session,
                        round_data,
                        choice,
                        llm,
                        store,
                        settings,
                    )
                )
                ui_state.set_session_id(updated.session_id)
                ui_state.clear_current_round()
                ui_state.clear_current_draft()
                st.rerun()

    if session.rounds and draft is None and round_data is None:
        st.subheader("Latest completed round")
        render_round(session.rounds[-1])


if __name__ == "__main__":
    main()
