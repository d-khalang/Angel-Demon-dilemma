from __future__ import annotations

import asyncio
from pathlib import Path

import streamlit as st

from angel_demon.config import load_settings
from angel_demon.dilemmas import PRESET_DILEMMAS, validate_dilemma
from angel_demon.flow import apply_user_choice, run_debate_round
from angel_demon.llm import LLMConfigurationError, LLMError, create_llm_provider
from angel_demon.logging_config import get_logger, setup_logging
from angel_demon.models import Character, Round, SessionState, User, UserChoice
from angel_demon.scoring import get_alignment_zone, get_promotion_leader
from angel_demon.state import SessionStore

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


def get_active_user(store: SessionStore) -> User:
    user_id = st.session_state.get("user_id")
    if user_id:
        user = store.load_user(user_id)
        if user:
            return user

    user = store.get_or_create_default_user()
    st.session_state.user_id = user.user_id
    get_logger("app").info("active_user_selected user_id=%s", user.user_id)
    return user


def get_session(store: SessionStore, user_id: str) -> SessionState:
    session_id = st.session_state.get("session_id")
    if session_id:
        loaded = store.load_session(session_id)
        if loaded and loaded.user_id == user_id:
            get_logger("app").debug("session_loaded session_id=%s", loaded.session_id)
            return loaded
        st.session_state.pop("session_id", None)

    session_rows = store.list_sessions(user_id)
    if session_rows:
        loaded = store.load_session(str(session_rows[0]["session_id"]))
        if loaded:
            st.session_state.session_id = loaded.session_id
            get_logger("app").info(
                "latest_session_selected user_id=%s session_id=%s",
                user_id,
                loaded.session_id,
            )
            return loaded

    session = store.create_session(user_id)
    st.session_state.session_id = session.session_id
    get_logger("app").info(
        "session_created user_id=%s session_id=%s",
        user_id,
        session.session_id,
    )
    return session


def alignment_label(score: int) -> str:
    labels = {
        "deep_hell": "Deep Hell",
        "hell": "Hell",
        "neutral": "Neutral",
        "heaven": "Heaven",
        "deep_heaven": "Deep Heaven",
    }
    return labels[get_alignment_zone(score).value]


def _session_label(row: dict[str, object]) -> str:
    updated = str(row["updated_at"]).replace("T", " ")[:16]
    rounds = int(row["round_count"])
    return f"{updated} | {rounds} rounds | alignment {row['alignment']}"


def render_sidebar(active_user: User, session: SessionState, store: SessionStore) -> None:
    with st.sidebar:
        st.title("Users")
        users = store.list_users()
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
            st.session_state.user_id = selected_user_id
            st.session_state.pop("session_id", None)
            st.session_state.pop("current_round", None)
            get_logger("app").info("ui_user_switched user_id=%s", selected_user_id)
            st.rerun()

        new_user_name = st.text_input("New user name", placeholder="e.g. Noor")
        if st.button("Create user", use_container_width=True, disabled=not new_user_name.strip()):
            user = store.create_user(new_user_name)
            if active_user.display_name == "Anonymous Player":
                claimed_session = store.transfer_session(session.session_id, user.user_id)
                if claimed_session:
                    st.session_state.session_id = claimed_session.session_id
            st.session_state.user_id = user.user_id
            st.session_state.pop("current_round", None)
            get_logger("app").info("ui_user_created user_id=%s", user.user_id)
            st.rerun()

        st.divider()
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
                st.session_state.session_id = selected_session_id
                st.session_state.pop("current_round", None)
                get_logger("app").info(
                    "ui_session_switched user_id=%s session_id=%s",
                    active_user.user_id,
                    selected_session_id,
                )
                st.rerun()
        else:
            st.caption("No sessions yet.")

        if st.button("Start new session", use_container_width=True):
            new_session = store.create_session(active_user.user_id)
            st.session_state.session_id = new_session.session_id
            st.session_state.pop("current_round", None)
            get_logger("app").info(
                "ui_session_created user_id=%s session_id=%s",
                active_user.user_id,
                new_session.session_id,
            )
            st.rerun()

        st.divider()
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

        st.divider()
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

def render_round(round_data: Round) -> None:
    st.subheader(f"Round {round_data.round_number} Verdict")
    winner = "Sunny" if round_data.verdict.winner == Character.SUNNY else "Crowley"
    st.markdown(f"**Winner:** {winner}")
    st.write(round_data.verdict.reason)
    cols = st.columns(2)
    cols[0].metric("Sunny score", round_data.verdict.sunny_score)
    cols[1].metric("Crowley score", round_data.verdict.crowley_score)
    st.caption(f"Key moment: {round_data.verdict.key_moment}")
    if round_data.verdict.is_fallback:
        st.warning("Fallback judging was used for this round.")


def render_transcript(round_data: Round) -> None:
    st.subheader("Debate transcript")
    with st.expander("Sunny opening", expanded=True):
        st.write(round_data.sunny_opening.argument)
    with st.expander("Crowley opening", expanded=True):
        st.write(round_data.crowley_opening.argument)
    with st.expander("Sunny rebuttal", expanded=False):
        st.write(round_data.sunny_rebuttal.argument)
    with st.expander("Crowley rebuttal", expanded=False):
        st.write(round_data.crowley_rebuttal.argument)


def choose_dilemma() -> str:
    st.subheader("Dilemma")
    preset_titles = ["Custom"] + [item["title"] for item in PRESET_DILEMMAS]
    selected = st.selectbox("Preset", preset_titles, label_visibility="collapsed")
    default_text = ""
    if selected != "Custom":
        default_text = next(
            item["description"] for item in PRESET_DILEMMAS if item["title"] == selected
        )
    return st.text_area(
        "Enter a dilemma",
        value=default_text,
        height=110,
        placeholder="Should I protect someone I love if it means hurting strangers?",
    )


async def generate_round(
    session: SessionState,
    dilemma: str,
    settings,
    store: SessionStore,
    llm,
    placeholders,
) -> Round:
    buffers = {role: "" for role in placeholders}

    def on_chunk(role: str, chunk: str) -> None:
        buffers[role] += chunk
        placeholders[role].markdown(buffers[role])

    return await run_debate_round(
        session,
        dilemma,
        llm,
        store,
        settings,
        on_chunk=on_chunk,
    )


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
    session = get_session(store, active_user.user_id)
    render_sidebar(active_user, session, store)

    dilemma = choose_dilemma()
    is_valid, validation_error = validate_dilemma(dilemma)
    can_start = is_valid and "current_round" not in st.session_state

    if not is_valid:
        st.caption(validation_error)

    if st.button("Start debate", type="primary", disabled=not can_start):
        logger = get_logger("app")
        logger.info(
            "ui_start_debate_clicked session_id=%s dilemma_chars=%d",
            session.session_id,
            len(dilemma),
        )
        st.session_state.pop("current_round", None)
        st.subheader("Debate")
        st.markdown("#### Sunny opening")
        sunny_opening_box = st.empty()
        st.markdown("#### Crowley opening")
        crowley_opening_box = st.empty()
        st.markdown("#### Sunny rebuttal")
        sunny_rebuttal_box = st.empty()
        st.markdown("#### Crowley rebuttal")
        crowley_rebuttal_box = st.empty()
        placeholders = {
            "sunny_opening": sunny_opening_box,
            "crowley_opening": crowley_opening_box,
            "sunny_rebuttal": sunny_rebuttal_box,
            "crowley_rebuttal": crowley_rebuttal_box,
        }
        with st.spinner("Sunny and Crowley are preparing their arguments..."):
            try:
                round_data = asyncio.run(
                    generate_round(session, dilemma, settings, store, llm, placeholders)
                )
            except LLMError as exc:
                logger.exception(
                    "ui_debate_generation_failed session_id=%s error=%s",
                    session.session_id,
                    exc,
                )
                st.error(
                    "The OpenAI request failed before the debate could finish. "
                    "Check your API key, model access, and project quota, then try again."
                )
                st.caption(str(exc))
                return
        st.session_state.current_round = round_data.model_dump_json()
        logger.info(
            "ui_debate_generation_completed session_id=%s round_number=%d winner=%s",
            session.session_id,
            round_data.round_number,
            round_data.verdict.winner.value,
        )

    if "current_round" in st.session_state:
        round_data = Round.model_validate_json(st.session_state.current_round)
        if not round_data.user_choice:
            render_transcript(round_data)
            render_round(round_data)
            st.subheader("Your decision")
            col_a, col_b, col_c = st.columns(3)
            if col_a.button("Follow Sunny", use_container_width=True):
                get_logger("app").info(
                    "ui_user_choice session_id=%s round_number=%d choice=%s",
                    session.session_id,
                    round_data.round_number,
                    UserChoice.FOLLOW_SUNNY.value,
                )
                updated = asyncio.run(
                    apply_user_choice(
                        session,
                        round_data,
                        UserChoice.FOLLOW_SUNNY,
                        llm,
                        store,
                        settings,
                    )
                )
                st.session_state.session_id = updated.session_id
                st.session_state.pop("current_round", None)
                st.rerun()
            if col_b.button("Follow Crowley", use_container_width=True):
                get_logger("app").info(
                    "ui_user_choice session_id=%s round_number=%d choice=%s",
                    session.session_id,
                    round_data.round_number,
                    UserChoice.FOLLOW_CROWLEY.value,
                )
                updated = asyncio.run(
                    apply_user_choice(
                        session,
                        round_data,
                        UserChoice.FOLLOW_CROWLEY,
                        llm,
                        store,
                        settings,
                    )
                )
                st.session_state.session_id = updated.session_id
                st.session_state.pop("current_round", None)
                st.rerun()
            if col_c.button("Undecided", use_container_width=True):
                get_logger("app").info(
                    "ui_user_choice session_id=%s round_number=%d choice=%s",
                    session.session_id,
                    round_data.round_number,
                    UserChoice.UNDECIDED.value,
                )
                updated = asyncio.run(
                    apply_user_choice(
                        session,
                        round_data,
                        UserChoice.UNDECIDED,
                        llm,
                        store,
                        settings,
                    )
                )
                st.session_state.session_id = updated.session_id
                st.session_state.pop("current_round", None)
                st.rerun()

    if session.rounds:
        st.subheader("Latest completed round")
        render_round(session.rounds[-1])


if __name__ == "__main__":
    main()
