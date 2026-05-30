"""Main debate UI rendering."""

from __future__ import annotations

from typing import Any

import streamlit as st

from angel_demon.dilemmas import PRESET_DILEMMAS
from angel_demon.flow import run_debate_round
from angel_demon.models import Character, Round, SessionState
from angel_demon.scoring import get_alignment_zone
from angel_demon.state import SessionStore


def alignment_label(score: int) -> str:
    labels = {
        "deep_hell": "Deep Hell",
        "hell": "Hell",
        "neutral": "Neutral",
        "heaven": "Heaven",
        "deep_heaven": "Deep Heaven",
    }
    return labels[get_alignment_zone(score).value]


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
    settings: Any,
    store: SessionStore,
    llm: Any,
    placeholders: dict[str, Any],
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
