"""Debate orchestration."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime

from angel_demon.agents import (
    build_conversation_turn_messages,
    build_opening_messages,
    build_rebuttal_messages,
    make_opening,
    make_rebuttal,
)
from angel_demon.config import Settings
from angel_demon.judge import judge_conversation, judge_debate
from angel_demon.llm import (
    LLMProvider,
    LLMStreamChunk,
    LLMUsage,
    estimate_tokens,
    get_attached_usage,
)
from angel_demon.logging_config import get_logger
from angel_demon.memory import update_agent_profile, update_user_profile
from angel_demon.models import (
    Character,
    ConversationDraft,
    ConversationMessage,
    ConversationSpeaker,
    Opening,
    Rebuttal,
    ResponseTarget,
    Round,
    SessionState,
    UserChoice,
)
from angel_demon.scoring import apply_alignment_delta, calculate_alignment_delta
from angel_demon.state import SessionStore

ChunkCallback = Callable[[str, str], None]
logger = get_logger("flow")


async def _collect_stream(
    role: str,
    stream,
    on_chunk: ChunkCallback | None,
) -> tuple[str, int, LLMUsage]:
    chunks: list[str] = []
    usage = LLMUsage()
    start = time.perf_counter()
    logger.info("stream_collect_start role=%s", role)
    async for chunk in stream:
        if isinstance(chunk, LLMStreamChunk):
            if chunk.usage is not None:
                usage = chunk.usage
            if not chunk.text:
                continue
            text_chunk = chunk.text
        else:
            text_chunk = chunk
        chunks.append(text_chunk)
        if on_chunk:
            on_chunk(role, text_chunk)
    text = "".join(chunks).strip()
    latency_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "stream_collect_complete role=%s latency_ms=%d output_chars=%d",
        role,
        latency_ms,
        len(text),
    )
    return text, latency_ms, usage


def _usage_with_fallback(
    usage: LLMUsage,
    messages: list[dict[str, str]],
    output_text: str,
) -> LLMUsage:
    return LLMUsage(
        input_tokens=usage.input_tokens or estimate_tokens(messages),
        output_tokens=usage.output_tokens or max(1, len(output_text) // 4),
    )


def _combine_usage(usages: list[LLMUsage]) -> LLMUsage:
    input_tokens = sum(usage.input_tokens or 0 for usage in usages)
    output_tokens = sum(usage.output_tokens or 0 for usage in usages)
    return LLMUsage(
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
    )


def _agent_profile_for(session: SessionState, character: Character):
    return session.sunny_profile if character == Character.SUNNY else session.crowley_profile


def _opponent_profile_for(session: SessionState, character: Character):
    return session.crowley_profile if character == Character.SUNNY else session.sunny_profile


def _speaker_for(character: Character) -> ConversationSpeaker:
    return (
        ConversationSpeaker.SUNNY
        if character == Character.SUNNY
        else ConversationSpeaker.CROWLEY
    )


def _characters_for_target(target: ResponseTarget) -> list[Character]:
    if target == ResponseTarget.SUNNY:
        return [Character.SUNNY]
    if target == ResponseTarget.CROWLEY:
        return [Character.CROWLEY]
    return [Character.SUNNY, Character.CROWLEY]


async def _append_agent_response(
    draft: ConversationDraft,
    session: SessionState,
    character: Character,
    target: ResponseTarget,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
    on_chunk: ChunkCallback | None,
) -> ConversationMessage:
    messages = build_conversation_turn_messages(
        character,
        draft.dilemma,
        draft.messages,
        target,
        session.user_profile,
        _agent_profile_for(session, character),
        _opponent_profile_for(session, character),
        session.rounds[-3:],
    )
    stream = llm.stream(messages, settings.agent_temperature, 550)
    role = character.value
    text, latency_ms, usage = await _collect_stream(role, stream, on_chunk)
    usage = _usage_with_fallback(usage, messages, text)
    message = ConversationMessage(
        speaker=_speaker_for(character),
        content=text,
        target=target,
    )
    draft.messages.append(message)
    store.save_message(session.session_id, draft.round_number, character.value, text)
    store.log_model_run(
        session.session_id,
        draft.round_number,
        f"conversation_{character.value}",
        llm.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=latency_ms,
        was_streamed=True,
    )
    return message


async def start_conversation_round(
    session: SessionState,
    dilemma: str,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
    *,
    on_chunk: ChunkCallback | None = None,
) -> ConversationDraft:
    round_number = len(session.rounds) + 1
    draft = ConversationDraft(
        round_number=round_number,
        dilemma=dilemma,
        messages=[
            ConversationMessage(
                speaker=ConversationSpeaker.USER,
                content=dilemma,
                target=ResponseTarget.BOTH,
            )
        ],
    )
    store.save_message(session.session_id, round_number, "user", dilemma)
    for character in _characters_for_target(ResponseTarget.BOTH):
        await _append_agent_response(
            draft,
            session,
            character,
            ResponseTarget.BOTH,
            llm,
            store,
            settings,
            on_chunk,
        )
    return draft


async def continue_conversation_round(
    session: SessionState,
    draft: ConversationDraft,
    followup: str,
    target: ResponseTarget,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
    *,
    on_chunk: ChunkCallback | None = None,
) -> ConversationDraft:
    user_message = ConversationMessage(
        speaker=ConversationSpeaker.USER,
        content=followup,
        target=target,
    )
    draft.messages.append(user_message)
    store.save_message(session.session_id, draft.round_number, "user", followup)
    for character in _characters_for_target(target):
        await _append_agent_response(
            draft,
            session,
            character,
            target,
            llm,
            store,
            settings,
            on_chunk,
        )
    return draft


def _round_from_conversation(draft: ConversationDraft, verdict) -> Round:
    sunny_texts = [
        message.content
        for message in draft.messages
        if message.speaker == ConversationSpeaker.SUNNY
    ]
    crowley_texts = [
        message.content
        for message in draft.messages
        if message.speaker == ConversationSpeaker.CROWLEY
    ]
    sunny_opening = sunny_texts[0] if sunny_texts else "Sunny did not respond."
    crowley_opening = crowley_texts[0] if crowley_texts else "Crowley did not respond."
    sunny_rebuttal = "\n\n".join(sunny_texts[1:]) or sunny_opening
    crowley_rebuttal = "\n\n".join(crowley_texts[1:]) or crowley_opening
    return Round(
        round_number=draft.round_number,
        dilemma=draft.dilemma,
        conversation=draft.messages,
        sunny_opening=Opening(character=Character.SUNNY, argument=sunny_opening),
        crowley_opening=Opening(character=Character.CROWLEY, argument=crowley_opening),
        sunny_rebuttal=Rebuttal(character=Character.SUNNY, argument=sunny_rebuttal),
        crowley_rebuttal=Rebuttal(character=Character.CROWLEY, argument=crowley_rebuttal),
        verdict=verdict,
        timestamp=datetime.now(UTC),
    )


async def judge_conversation_round(
    session: SessionState,
    draft: ConversationDraft,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
) -> Round:
    judge_start = time.perf_counter()
    verdict = await judge_conversation(
        draft.dilemma,
        draft.messages,
        llm,
        round_number=draft.round_number,
        temperature=settings.judge_temperature,
    )
    judge_usage = get_attached_usage(verdict)
    store.log_model_run(
        session.session_id,
        draft.round_number,
        "judge_conversation",
        llm.model,
        input_tokens=judge_usage.input_tokens,
        output_tokens=judge_usage.output_tokens or max(1, len(verdict.model_dump_json()) // 4),
        latency_ms=int((time.perf_counter() - judge_start) * 1000),
        was_streamed=False,
        error="fallback" if verdict.is_fallback else None,
    )
    store.save_message(
        session.session_id,
        draft.round_number,
        "judge_verdict",
        verdict.model_dump_json(),
    )
    return _round_from_conversation(draft, verdict)


async def run_debate_round(
    session: SessionState,
    dilemma: str,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
    *,
    on_chunk: ChunkCallback | None = None,
) -> Round:
    round_number = len(session.rounds) + 1
    history = session.rounds[-3:]
    logger.info(
        "debate_round_start session_id=%s round_number=%d dilemma_chars=%d history_rounds=%d",
        session.session_id,
        round_number,
        len(dilemma),
        len(history),
    )

    sunny_messages = build_opening_messages(
        Character.SUNNY,
        dilemma,
        session.user_profile,
        session.sunny_profile,
        session.crowley_profile,
        history,
    )
    sunny_stream = llm.stream(sunny_messages, settings.agent_temperature, 700)
    sunny_text, sunny_latency, sunny_usage = await _collect_stream(
        "sunny_opening",
        sunny_stream,
        on_chunk,
    )
    sunny_usage = _usage_with_fallback(sunny_usage, sunny_messages, sunny_text)
    sunny_opening = make_opening(Character.SUNNY, sunny_text)
    logger.info("debate_step_complete round_number=%d step=sunny_opening", round_number)
    store.save_message(session.session_id, round_number, "sunny_opening", sunny_text)
    store.log_model_run(
        session.session_id,
        round_number,
        "sunny_opening",
        llm.model,
        input_tokens=sunny_usage.input_tokens,
        output_tokens=sunny_usage.output_tokens,
        latency_ms=sunny_latency,
        was_streamed=True,
    )

    crowley_messages = build_opening_messages(
        Character.CROWLEY,
        dilemma,
        session.user_profile,
        session.crowley_profile,
        session.sunny_profile,
        history,
    )
    crowley_stream = llm.stream(crowley_messages, settings.agent_temperature, 700)
    crowley_text, crowley_latency, crowley_usage = await _collect_stream(
        "crowley_opening",
        crowley_stream,
        on_chunk,
    )
    crowley_usage = _usage_with_fallback(crowley_usage, crowley_messages, crowley_text)
    crowley_opening = make_opening(Character.CROWLEY, crowley_text)
    logger.info("debate_step_complete round_number=%d step=crowley_opening", round_number)
    store.save_message(session.session_id, round_number, "crowley_opening", crowley_text)
    store.log_model_run(
        session.session_id,
        round_number,
        "crowley_opening",
        llm.model,
        input_tokens=crowley_usage.input_tokens,
        output_tokens=crowley_usage.output_tokens,
        latency_ms=crowley_latency,
        was_streamed=True,
    )

    sunny_rebuttal_messages = build_rebuttal_messages(
        Character.SUNNY,
        dilemma,
        sunny_opening,
        crowley_opening,
        session.user_profile,
        session.sunny_profile,
        session.crowley_profile,
    )
    sunny_rebuttal_stream = llm.stream(sunny_rebuttal_messages, settings.agent_temperature, 500)
    sunny_rebuttal_text, sunny_rebuttal_latency, sunny_rebuttal_usage = await _collect_stream(
        "sunny_rebuttal",
        sunny_rebuttal_stream,
        on_chunk,
    )
    sunny_rebuttal_usage = _usage_with_fallback(
        sunny_rebuttal_usage,
        sunny_rebuttal_messages,
        sunny_rebuttal_text,
    )
    sunny_rebuttal = make_rebuttal(Character.SUNNY, sunny_rebuttal_text)
    logger.info("debate_step_complete round_number=%d step=sunny_rebuttal", round_number)
    store.save_message(session.session_id, round_number, "sunny_rebuttal", sunny_rebuttal_text)
    store.log_model_run(
        session.session_id,
        round_number,
        "sunny_rebuttal",
        llm.model,
        input_tokens=sunny_rebuttal_usage.input_tokens,
        output_tokens=sunny_rebuttal_usage.output_tokens,
        latency_ms=sunny_rebuttal_latency,
        was_streamed=True,
    )

    crowley_rebuttal_messages = build_rebuttal_messages(
        Character.CROWLEY,
        dilemma,
        crowley_opening,
        sunny_opening,
        session.user_profile,
        session.crowley_profile,
        session.sunny_profile,
    )
    crowley_rebuttal_stream = llm.stream(crowley_rebuttal_messages, settings.agent_temperature, 500)
    crowley_rebuttal_text, crowley_rebuttal_latency, crowley_rebuttal_usage = await _collect_stream(
        "crowley_rebuttal",
        crowley_rebuttal_stream,
        on_chunk,
    )
    crowley_rebuttal_usage = _usage_with_fallback(
        crowley_rebuttal_usage,
        crowley_rebuttal_messages,
        crowley_rebuttal_text,
    )
    crowley_rebuttal = make_rebuttal(Character.CROWLEY, crowley_rebuttal_text)
    logger.info("debate_step_complete round_number=%d step=crowley_rebuttal", round_number)
    store.save_message(session.session_id, round_number, "crowley_rebuttal", crowley_rebuttal_text)
    store.log_model_run(
        session.session_id,
        round_number,
        "crowley_rebuttal",
        llm.model,
        input_tokens=crowley_rebuttal_usage.input_tokens,
        output_tokens=crowley_rebuttal_usage.output_tokens,
        latency_ms=crowley_rebuttal_latency,
        was_streamed=True,
    )
    judge_start = time.perf_counter()
    verdict = await judge_debate(
        dilemma,
        sunny_opening,
        crowley_opening,
        sunny_rebuttal,
        crowley_rebuttal,
        llm,
        round_number=round_number,
        temperature=settings.judge_temperature,
    )
    judge_usage = get_attached_usage(verdict)
    store.log_model_run(
        session.session_id,
        round_number,
        "judge",
        llm.model,
        input_tokens=judge_usage.input_tokens,
        output_tokens=judge_usage.output_tokens or max(1, len(verdict.model_dump_json()) // 4),
        latency_ms=int((time.perf_counter() - judge_start) * 1000),
        was_streamed=False,
        error="fallback" if verdict.is_fallback else None,
    )
    logger.info(
        "debate_judged session_id=%s round_number=%d winner=%s fallback=%s",
        session.session_id,
        round_number,
        verdict.winner.value,
        verdict.is_fallback,
    )

    round_data = Round(
        round_number=round_number,
        dilemma=dilemma,
        sunny_opening=sunny_opening,
        crowley_opening=crowley_opening,
        sunny_rebuttal=sunny_rebuttal,
        crowley_rebuttal=crowley_rebuttal,
        verdict=verdict,
        timestamp=datetime.now(UTC),
    )
    store.save_message(session.session_id, round_number, "judge_verdict", verdict.model_dump_json())
    logger.info(
        "debate_round_complete session_id=%s round_number=%d",
        session.session_id,
        round_number,
    )
    return round_data


async def apply_user_choice(
    session: SessionState,
    current_round: Round,
    choice: UserChoice,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
) -> SessionState:
    current_round.user_choice = choice
    current_round.alignment_delta = calculate_alignment_delta(choice, current_round.verdict)
    session.alignment_score = apply_alignment_delta(
        session.alignment_score,
        current_round.alignment_delta,
    )

    if choice == UserChoice.FOLLOW_SUNNY:
        session.sunny_profile.wins += 1
        session.crowley_profile.losses += 1
    elif choice == UserChoice.FOLLOW_CROWLEY:
        session.crowley_profile.wins += 1
        session.sunny_profile.losses += 1

    logger.info(
        "apply_user_choice_start session_id=%s round_number=%d choice=%s "
        "alignment_delta=%d alignment_after=%d",
        session.session_id,
        current_round.round_number,
        choice.value,
        current_round.alignment_delta,
        session.alignment_score,
    )
    memory_start = time.perf_counter()
    session.user_profile, session.sunny_profile, session.crowley_profile = await asyncio.gather(
        update_user_profile(
            session.user_profile,
            current_round,
            llm,
            temperature=settings.memory_temperature,
        ),
        update_agent_profile(
            session.sunny_profile,
            current_round,
            session.user_profile,
            llm,
            temperature=settings.memory_temperature,
        ),
        update_agent_profile(
            session.crowley_profile,
            current_round,
            session.user_profile,
            llm,
            temperature=settings.memory_temperature,
        ),
    )
    memory_usage = _combine_usage(
        [
            get_attached_usage(session.user_profile),
            get_attached_usage(session.sunny_profile),
            get_attached_usage(session.crowley_profile),
        ]
    )
    store.log_model_run(
        session.session_id,
        current_round.round_number,
        "memory_updates",
        llm.model,
        input_tokens=memory_usage.input_tokens,
        output_tokens=memory_usage.output_tokens,
        latency_ms=int((time.perf_counter() - memory_start) * 1000),
    )

    session.rounds.append(current_round)
    session.updated_at = datetime.now(UTC)
    store.save_message(
        session.session_id,
        current_round.round_number,
        "user_choice",
        choice.value,
    )
    store.save_round(session.session_id, current_round)
    store.save_session(session)
    logger.info(
        "apply_user_choice_complete session_id=%s round_number=%d sunny_wins=%d "
        "crowley_wins=%d",
        session.session_id,
        current_round.round_number,
        session.sunny_profile.wins,
        session.crowley_profile.wins,
    )
    return session
