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
    ConversationDraft,
    ConversationSpeaker,
    ResponseTarget,
    Round,
    SessionState,
)
from angel_demon.scoring import get_alignment_zone
from angel_demon.state import SessionStore

AVATAR_DIR = Path("assets/avatars")


@lru_cache(maxsize=4)
def _avatar_bytes(filename: str) -> bytes:
    return (AVATAR_DIR / filename).read_bytes()


def avatar_for(speaker: ConversationSpeaker) -> bytes | None:
    if speaker == ConversationSpeaker.SUNNY:
        return _avatar_bytes("sunny.png")
    if speaker == ConversationSpeaker.CROWLEY:
        return _avatar_bytes("crowley.png")
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
    if round_data.conversation:
        render_conversation(round_data.conversation)
        return
    render_legacy_transcript(round_data)


def render_legacy_transcript(round_data: Round) -> None:
    for speaker, content in (
        (ConversationSpeaker.SUNNY, round_data.sunny_opening.argument),
        (ConversationSpeaker.CROWLEY, round_data.crowley_opening.argument),
        (ConversationSpeaker.SUNNY, round_data.sunny_rebuttal.argument),
        (ConversationSpeaker.CROWLEY, round_data.crowley_rebuttal.argument),
    ):
        render_chat_message(speaker, content)


def render_chat_message(speaker: ConversationSpeaker, content: str) -> None:
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
    with st.chat_message(label, avatar=avatar_for(speaker)):
        st.caption(label)
        st.write(content)


def render_conversation(messages) -> None:
    for message in messages:
        render_chat_message(message.speaker, message.content)


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


def make_stream_placeholders(target: ResponseTarget) -> dict[str, Any]:
    placeholders: dict[str, Any] = {}
    speakers = []
    if target in {ResponseTarget.BOTH, ResponseTarget.SUNNY}:
        speakers.append((ConversationSpeaker.SUNNY, "sunny"))
    if target in {ResponseTarget.BOTH, ResponseTarget.CROWLEY}:
        speakers.append((ConversationSpeaker.CROWLEY, "crowley"))
    for speaker, key in speakers:
        if speaker == ConversationSpeaker.SUNNY:
            with st.chat_message("Sunny", avatar=avatar_for(speaker)):
                st.caption("Sunny")
                placeholders[key] = st.empty()
        else:
            with st.chat_message("Crowley", avatar=avatar_for(speaker)):
                st.caption("Crowley")
                placeholders[key] = st.empty()
    return placeholders


async def start_chat_round(
    session: SessionState,
    dilemma: str,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> ConversationDraft:
    placeholders = make_stream_placeholders(ResponseTarget.BOTH)
    buffers = {role: "" for role in placeholders}

    def on_chunk(role: str, chunk: str) -> None:
        buffers[role] += chunk
        placeholders[role].markdown(buffers[role])

    return await start_conversation_round(
        session,
        dilemma,
        llm,
        store,
        settings,
        on_chunk=on_chunk,
    )


async def continue_chat_round(
    session: SessionState,
    draft: ConversationDraft,
    followup: str,
    target: ResponseTarget,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> ConversationDraft:
    placeholders = make_stream_placeholders(target)
    buffers = {role: "" for role in placeholders}

    def on_chunk(role: str, chunk: str) -> None:
        buffers[role] += chunk
        placeholders[role].markdown(buffers[role])

    return await continue_conversation_round(
        session,
        draft,
        followup,
        target,
        llm,
        store,
        settings,
        on_chunk=on_chunk,
    )


async def advance_chat_round(
    session: SessionState,
    draft: ConversationDraft,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> ConversationDraft:
    placeholders = make_stream_placeholders(ResponseTarget.BOTH)
    buffers = {role: "" for role in placeholders}

    def on_chunk(role: str, chunk: str) -> None:
        buffers[role] += chunk
        placeholders[role].markdown(buffers[role])

    return await advance_conversation_round(
        session,
        draft,
        llm,
        store,
        settings,
        on_chunk=on_chunk,
    )


async def judge_chat_round(
    session: SessionState,
    draft: ConversationDraft,
    settings: Any,
    store: SessionStore,
    llm: Any,
) -> Round:
    return await judge_conversation_round(session, draft, llm, store, settings)
