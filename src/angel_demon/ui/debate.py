"""Main debate UI rendering."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import streamlit as st

from angel_demon.dilemmas import PRESET_DILEMMAS
from angel_demon.flow import (
    advance_conversation_round,
    continue_conversation_round,
    judge_conversation_round,
    start_conversation_round,
)
from angel_demon.models import (
    Character,
    ConversationSpeaker,
    ResponseTarget,
    Round,
    RoundStatus,
    SessionState,
)
from angel_demon.scoring import get_alignment_zone
from angel_demon.state import SessionStore

AVATAR_DIR = Path("assets/avatars")


@lru_cache(maxsize=8)
def _avatar_bytes(filename: str) -> bytes:
    return (AVATAR_DIR / filename).read_bytes()


def avatar_filename_for(speaker: ConversationSpeaker, alignment_score: int) -> str | None:
    if speaker == ConversationSpeaker.SUNNY:
        if alignment_score <= -30:
            return "sunny-losing.webp"
        if alignment_score >= 30:
            return "sunny-winning.webp"
        return "sunny-neutral.webp"
    if speaker == ConversationSpeaker.CROWLEY:
        if alignment_score <= -30:
            return "crowley-winning.webp"
        if alignment_score >= 30:
            return "crowley-losing.webp"
        return "crowley-neutral.webp"
    return None


def avatar_for(speaker: ConversationSpeaker, alignment_score: int = 0) -> bytes | None:
    filename = avatar_filename_for(speaker, alignment_score)
    if filename is not None:
        return _avatar_bytes(filename)
    return None


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
    if round_data.verdict is None:
        st.subheader(f"Round {round_data.round_number}")
        st.caption("This debate has not been judged yet.")
        return
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


def render_transcript(round_data: Round, alignment_score: int = 0) -> None:
    if round_data.conversation:
        render_conversation(round_data.conversation, alignment_score)
        return
    render_legacy_transcript(round_data, alignment_score)


def render_legacy_transcript(round_data: Round, alignment_score: int = 0) -> None:
    legacy_messages = [
        (ConversationSpeaker.SUNNY, round_data.sunny_opening.argument)
        if round_data.sunny_opening
        else None,
        (ConversationSpeaker.CROWLEY, round_data.crowley_opening.argument)
        if round_data.crowley_opening
        else None,
        (ConversationSpeaker.SUNNY, round_data.sunny_rebuttal.argument)
        if round_data.sunny_rebuttal
        else None,
        (ConversationSpeaker.CROWLEY, round_data.crowley_rebuttal.argument)
        if round_data.crowley_rebuttal
        else None,
    ]
    for item in legacy_messages:
        if item is not None:
            render_chat_message(*item, alignment_score=alignment_score)


def render_chat_message(
    speaker: ConversationSpeaker,
    content: str,
    *,
    alignment_score: int = 0,
) -> None:
    if speaker == ConversationSpeaker.USER:
        with st.chat_message("user"):
            st.write(content)
        return
    if speaker == ConversationSpeaker.SYSTEM:
        st.caption(content)
        return
    label = {
        ConversationSpeaker.SUNNY: "Sunny",
        ConversationSpeaker.CROWLEY: "Crowley",
        ConversationSpeaker.JUDGE: "Judge",
    }[speaker]
    with st.chat_message(label, avatar=avatar_for(speaker, alignment_score)):
        st.caption(label)
        st.markdown(content)


def render_conversation(messages, alignment_score: int = 0) -> None:
    for message in messages:
        render_chat_message(message.speaker, message.content, alignment_score=alignment_score)


def round_status_label(status: RoundStatus) -> str:
    return {
        RoundStatus.ACTIVE: "Active",
        RoundStatus.JUDGED: "Judged",
        RoundStatus.DECIDED: "Decided",
    }[status]


def round_history_label(round_data: Round) -> str:
    preview = " ".join(round_data.dilemma.split())
    if len(preview) > 42:
        preview = f"{preview[:39]}..."
    return f"R{round_data.round_number} | {round_status_label(round_data.status)} | {preview}"


def primary_action_label(round_data: Round) -> str:
    if round_data.status == RoundStatus.ACTIVE:
        return "Continue debate"
    if round_data.status == RoundStatus.JUDGED:
        return "Choose your side"
    return "Start next dilemma"


def choose_dilemma() -> tuple[str, bool]:
    st.subheader("Dilemma")
    preset_titles = ["Custom"] + [item["title"] for item in PRESET_DILEMMAS]
    selected = st.selectbox("Preset", preset_titles, label_visibility="collapsed")
    default_text = ""
    if selected != "Custom":
        default_text = next(
            item["description"] for item in PRESET_DILEMMAS if item["title"] == selected
        )
    with st.form("dilemma_form"):
        dilemma = st.text_area(
            "Enter a dilemma",
            value=default_text,
            height=110,
            placeholder="Should I protect someone I love if it means hurting strangers?",
        )
        submitted = st.form_submit_button("Start debate", type="primary")
    return dilemma, submitted


def _speaker_from_stream_role(role: str) -> ConversationSpeaker:
    speaker_value = role.split(":", maxsplit=1)[0]
    if speaker_value == "sunny":
        return ConversationSpeaker.SUNNY
    if speaker_value == "crowley":
        return ConversationSpeaker.CROWLEY
    return ConversationSpeaker.SYSTEM


def make_stream_callback(alignment_score: int = 0) -> Any:
    placeholders: dict[str, Any] = {}
    buffers: dict[str, str] = {}

    def on_chunk(role: str, chunk: str) -> None:
        if role not in placeholders:
            speaker = _speaker_from_stream_role(role)
            label = "Sunny" if speaker == ConversationSpeaker.SUNNY else "Crowley"
            with st.chat_message(label, avatar=avatar_for(speaker, alignment_score)):
                st.caption(label)
                placeholders[role] = st.empty()
            buffers[role] = ""
        buffers[role] += chunk
        placeholders[role].markdown(buffers[role])

    return on_chunk


async def start_chat_round(
    session: SessionState,
    dilemma: str,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> Round:
    return await start_conversation_round(
        session,
        dilemma,
        llm,
        store,
        settings,
        on_chunk=make_stream_callback(session.alignment_score),
    )


async def continue_chat_round(
    session: SessionState,
    round_data: Round,
    followup: str,
    target: ResponseTarget,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> Round:
    return await continue_conversation_round(
        session,
        round_data,
        followup,
        target,
        llm,
        store,
        settings,
        on_chunk=make_stream_callback(session.alignment_score),
    )


async def advance_chat_round(
    session: SessionState,
    round_data: Round,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> Round:
    return await advance_conversation_round(
        session,
        round_data,
        llm,
        store,
        settings,
        on_chunk=make_stream_callback(session.alignment_score),
    )


async def judge_chat_round(
    session: SessionState,
    round_data: Round,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> Round:
    return await judge_conversation_round(session, round_data, llm, store, settings)
