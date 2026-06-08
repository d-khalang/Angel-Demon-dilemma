"""Debate orchestration."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from angel_demon.agents import (
    build_conversation_turn_messages,
)
from angel_demon.config import Settings
from angel_demon.judge import judge_conversation
from angel_demon.llm import (
    LLMProvider,
    LLMStreamChunk,
    LLMUsage,
    estimate_tokens,
    get_attached_usage,
)
from angel_demon.logging_config import get_logger
from angel_demon.memory import rebuild_session_memory, update_session_memory
from angel_demon.models import (
    Character,
    ConversationMessage,
    ConversationSpeaker,
    Opening,
    Rebuttal,
    ResponseTarget,
    Round,
    RoundStatus,
    SessionState,
    UserChoice,
)
from angel_demon.scoring import (
    calculate_alignment_delta,
    calculate_choice_records,
    calculate_session_alignment,
)
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


def _replace_session_round(session: SessionState, round_data: Round) -> None:
    for index, existing in enumerate(session.rounds):
        if existing.round_number == round_data.round_number:
            session.rounds[index] = round_data
            return
    session.rounds.append(round_data)
    session.rounds.sort(key=lambda item: item.round_number)


def _recent_history(session: SessionState, current_round_number: int) -> list[Round]:
    return [
        round_data
        for round_data in session.rounds
        if round_data.round_number != current_round_number
    ][-3:]


def _derive_round_fields(round_data: Round) -> None:
    sunny_texts = [
        message.content
        for message in round_data.conversation
        if message.speaker == ConversationSpeaker.SUNNY
    ]
    crowley_texts = [
        message.content
        for message in round_data.conversation
        if message.speaker == ConversationSpeaker.CROWLEY
    ]
    if sunny_texts:
        round_data.sunny_opening = Opening(
            character=Character.SUNNY,
            argument=sunny_texts[0],
        )
        round_data.sunny_rebuttal = Rebuttal(
            character=Character.SUNNY,
            argument="\n\n".join(sunny_texts[1:]) or sunny_texts[0],
        )
    if crowley_texts:
        round_data.crowley_opening = Opening(
            character=Character.CROWLEY,
            argument=crowley_texts[0],
        )
        round_data.crowley_rebuttal = Rebuttal(
            character=Character.CROWLEY,
            argument="\n\n".join(crowley_texts[1:]) or crowley_texts[0],
        )


def _normalize_session_scores(session: SessionState) -> None:
    session.alignment_score = calculate_session_alignment(session.rounds)
    sunny_wins, sunny_losses, crowley_wins, crowley_losses = calculate_choice_records(
        session.rounds
    )
    session.sunny_profile.wins = sunny_wins
    session.sunny_profile.losses = sunny_losses
    session.crowley_profile.wins = crowley_wins
    session.crowley_profile.losses = crowley_losses
    session.user_profile.decision_history = [
        round_data.user_choice
        for round_data in session.rounds
        if round_data.user_choice is not None
    ]


def _rebuild_session_memory(session: SessionState) -> None:
    session.user_profile, session.sunny_profile, session.crowley_profile = (
        rebuild_session_memory(session.rounds)
    )
    _normalize_session_scores(session)


async def _append_agent_response(
    round_data: Round,
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
        round_data.dilemma,
        round_data.conversation,
        target,
        session.user_profile,
        _agent_profile_for(session, character),
        _opponent_profile_for(session, character),
        _recent_history(session, round_data.round_number),
    )
    stream = llm.stream(messages, settings.agent_temperature, 550)
    role = character.value
    stream_role = f"{role}:{len(round_data.conversation)}"
    text, latency_ms, usage = await _collect_stream(stream_role, stream, on_chunk)
    usage = _usage_with_fallback(usage, messages, text)
    message = ConversationMessage(
        speaker=_speaker_for(character),
        content=text,
        target=target,
    )
    round_data.conversation.append(message)
    _derive_round_fields(round_data)
    _replace_session_round(session, round_data)
    store.persist_round_transition(
        session,
        round_data,
        messages=[(character.value, text)],
        model_runs=[
            {
                "call_type": f"conversation_{character.value}",
                "model": llm.model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "latency_ms": latency_ms,
                "was_streamed": True,
            }
        ],
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
) -> Round:
    round_data = store.create_round(session, dilemma)
    try:
        for character in _characters_for_target(ResponseTarget.BOTH):
            await _append_agent_response(
                round_data,
                session,
                character,
                ResponseTarget.BOTH,
                llm,
                store,
                settings,
                on_chunk,
            )
        await advance_conversation_round(
            session,
            round_data,
            llm,
            store,
            settings,
            on_chunk=on_chunk,
        )
    except Exception:
        store.discard_round(session, round_data.round_number)
        logger.exception(
            "round_start_failed_discarded session_id=%s round_number=%d",
            session.session_id,
            round_data.round_number,
        )
        raise
    return round_data


async def continue_conversation_round(
    session: SessionState,
    round_data: Round,
    followup: str,
    target: ResponseTarget,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
    *,
    on_chunk: ChunkCallback | None = None,
) -> Round:
    reopen_round(session, round_data, store)
    user_message = ConversationMessage(
        speaker=ConversationSpeaker.USER,
        content=followup,
        target=target,
    )
    round_data.conversation.append(user_message)
    _replace_session_round(session, round_data)
    store.persist_round_transition(
        session,
        round_data,
        messages=[("user", followup)],
    )
    for character in _characters_for_target(target):
        await _append_agent_response(
            round_data,
            session,
            character,
            target,
            llm,
            store,
            settings,
            on_chunk,
        )
    return round_data


async def advance_conversation_round(
    session: SessionState,
    round_data: Round,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
    *,
    on_chunk: ChunkCallback | None = None,
) -> Round:
    reopen_round(session, round_data, store)
    prompt = (
        "Continue the debate. Sunny and Crowley should each deepen their case, respond to the "
        "strongest opposing point so far, and avoid repeating earlier arguments."
    )
    system_message = ConversationMessage(
        speaker=ConversationSpeaker.SYSTEM,
        content=prompt,
        target=ResponseTarget.BOTH,
    )
    round_data.conversation.append(system_message)
    _replace_session_round(session, round_data)
    store.persist_round_transition(
        session,
        round_data,
        messages=[("system", prompt)],
    )
    for character in _characters_for_target(ResponseTarget.BOTH):
        await _append_agent_response(
            round_data,
            session,
            character,
            ResponseTarget.BOTH,
            llm,
            store,
            settings,
            on_chunk,
        )
    return round_data


async def judge_conversation_round(
    session: SessionState,
    round_data: Round,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
) -> Round:
    judge_start = time.perf_counter()
    verdict = await judge_conversation(
        round_data.dilemma,
        round_data.conversation,
        llm,
        round_number=round_data.round_number,
        temperature=settings.judge_temperature,
    )
    judge_usage = get_attached_usage(verdict)
    round_data.verdict = verdict
    round_data.status = RoundStatus.JUDGED
    round_data.user_choice = None
    round_data.alignment_delta = 0
    _derive_round_fields(round_data)
    _replace_session_round(session, round_data)
    _normalize_session_scores(session)
    store.persist_round_transition(
        session,
        round_data,
        messages=[("judge_verdict", verdict.model_dump_json())],
        model_runs=[
            {
                "call_type": "judge_conversation",
                "model": llm.model,
                "input_tokens": judge_usage.input_tokens,
                "output_tokens": judge_usage.output_tokens
                or max(1, len(verdict.model_dump_json()) // 4),
                "latency_ms": int((time.perf_counter() - judge_start) * 1000),
                "was_streamed": False,
                "error": "fallback" if verdict.is_fallback else None,
            }
        ],
    )
    return round_data


def reopen_round(session: SessionState, round_data: Round, store: SessionStore) -> Round:
    if round_data.status != RoundStatus.ACTIVE:
        round_data.status = RoundStatus.ACTIVE
        round_data.verdict = None
        round_data.user_choice = None
        round_data.alignment_delta = 0
        _replace_session_round(session, round_data)
        _rebuild_session_memory(session)
        store.persist_round_transition(session, round_data, memory_job="cancel")
    return round_data


def decide_round(
    session: SessionState,
    current_round: Round,
    choice: UserChoice,
    store: SessionStore,
) -> SessionState:
    if current_round.verdict is None:
        raise ValueError("Cannot choose a side before the judge verdict.")

    current_round.user_choice = choice
    current_round.alignment_delta = calculate_alignment_delta(choice, current_round.verdict)
    current_round.status = RoundStatus.DECIDED
    _replace_session_round(session, current_round)
    session.alignment_score = calculate_session_alignment(session.rounds)

    _normalize_session_scores(session)
    session.updated_at = datetime.now(UTC)
    store.persist_round_transition(
        session,
        current_round,
        messages=[("user_choice", choice.value)],
        memory_job="enqueue",
    )
    logger.info(
        "round_decided session_id=%s round_number=%d choice=%s alignment_after=%d",
        session.session_id,
        current_round.round_number,
        choice.value,
        session.alignment_score,
    )
    return session


async def update_round_memory(
    session: SessionState,
    current_round: Round,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
) -> SessionState:
    if not store.claim_pending_memory_update(
        session.session_id,
        current_round.round_number,
    ):
        return session
    memory_start = time.perf_counter()
    try:
        session.user_profile, session.sunny_profile, session.crowley_profile = (
            await update_session_memory(
                session.user_profile,
                session.sunny_profile,
                session.crowley_profile,
                current_round,
                llm,
                temperature=settings.memory_temperature,
                user_choice_already_recorded=True,
            )
        )
        memory_usage = _combine_usage(
            [
                get_attached_usage(session.user_profile),
                get_attached_usage(session.sunny_profile),
                get_attached_usage(session.crowley_profile),
            ]
        )
        _replace_session_round(session, current_round)
        _normalize_session_scores(session)
        session.updated_at = datetime.now(UTC)
        store.persist_round_transition(
            session,
            current_round,
            model_runs=[
                {
                    "call_type": "memory_updates",
                    "model": llm.model,
                    "input_tokens": memory_usage.input_tokens,
                    "output_tokens": memory_usage.output_tokens,
                    "latency_ms": int((time.perf_counter() - memory_start) * 1000),
                }
            ],
            memory_job="complete",
        )
    except Exception:
        store.requeue_memory_update(
            session.session_id,
            current_round.round_number,
        )
        raise
    logger.info(
        "apply_user_choice_complete session_id=%s round_number=%d sunny_wins=%d "
        "crowley_wins=%d",
        session.session_id,
        current_round.round_number,
        session.sunny_profile.wins,
        session.crowley_profile.wins,
    )
    return session


async def apply_user_choice(
    session: SessionState,
    current_round: Round,
    choice: UserChoice,
    llm: LLMProvider,
    store: SessionStore,
    settings: Settings,
) -> SessionState:
    decide_round(session, current_round, choice, store)
    return await update_round_memory(session, current_round, llm, store, settings)


def revote_round(
    session: SessionState,
    current_round: Round,
    choice: UserChoice,
    store: SessionStore,
) -> SessionState:
    if current_round.verdict is None:
        raise ValueError("Cannot revote before the judge verdict.")

    current_round.user_choice = choice
    current_round.alignment_delta = calculate_alignment_delta(choice, current_round.verdict)
    current_round.status = RoundStatus.DECIDED
    _replace_session_round(session, current_round)
    _rebuild_session_memory(session)
    session.updated_at = datetime.now(UTC)
    store.persist_round_transition(
        session,
        current_round,
        messages=[("user_choice", choice.value)],
        memory_job="enqueue",
    )
    logger.info(
        "round_revoted session_id=%s round_number=%d choice=%s alignment_after=%d",
        session.session_id,
        current_round.round_number,
        choice.value,
        session.alignment_score,
    )
    return session
