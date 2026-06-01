from __future__ import annotations

from pathlib import Path

import streamlit as st

from angel_demon.config import load_settings
from angel_demon.llm import LLMConfigurationError, create_llm_provider
from angel_demon.logging_config import get_logger, setup_logging
from angel_demon.state import SessionStore
from angel_demon.ui.round_actions import selected_round, start_round
from angel_demon.ui.round_view import render_round_thread
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
    round_data = selected_round(session.rounds)

    if round_data is None:
        start_round(session, settings, store, llm)
        return

    render_round_thread(session, round_data, settings, store, llm)


if __name__ == "__main__":
    main()
