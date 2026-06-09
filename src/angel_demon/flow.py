"""Debate orchestration."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from angel_demon.agents import (
    build_conversation_turn_messages,
)
from angel_demon.config import Settings
from angel_demon.domain.rounds import (
    agent_profile_for,
    characters_for_target,
    derive_round_fields,
    normalize_session_scores,
    opponent_profile_for,
    rebuild_adaptive_state,
    recent_history,
    replace_session_round,
    speaker_for,
)
from angel_demon.judge import judge_conversation
from angel_demon.llm import (
    LLMProvider,
    get_attached_usage,
)
from angel_demon.llm.streaming import (
    ChunkCallback,
    collect_stream,
    combine_usage,
    usage_with_fallback,
)
from angel_demon.logging_config import get_logger
from angel_demon.memory import update_session_memory
from angel_demon.models import (
    Character,
    ConversationMessage,
    ConversationSpeaker,
    ResponseTarget,
    Round,
    RoundStatus,
    SessionState,
    UserChoice,
)
from angel_demon.scoring import (
    calculate_alignment_delta,
    calculate_session_alignment,
)
from angel_demon.state import SessionStore

logger = get_logger("flow")


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
        agent_profile_for(session, character),
        opponent_profile_for(session, character),
        recent_history(session, round_data.round_number),
    )
    stream = llm.stream(messages, settings.agent_temperature, 550)
    role = character.value
    stream_role = f"{role}:{len(round_data.conversation)}"
    text, latency_ms, usage = await collect_stream(stream_role, stream, on_chunk)
    usage = usage_with_fallback(usage, messages, text)
    message = ConversationMessage(
        speaker=speaker_for(character),
        content=text,
        target=target,
    )
    round_data.conversation.append(message)
    derive_round_fields(round_data)
    replace_session_round(session, round_data)
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
        for character in characters_for_target(ResponseTarget.BOTH):
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
    replace_session_round(session, round_data)
    store.persist_round_transition(
        session,
        round_data,
        messages=[("user", followup)],
    )
    for character in characters_for_target(target):
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
    replace_session_round(session, round_data)
    store.persist_round_transition(
        session,
        round_data,
        messages=[("system", prompt)],
    )
    for character in characters_for_target(ResponseTarget.BOTH):
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
    derive_round_fields(round_data)
    replace_session_round(session, round_data)
    normalize_session_scores(session)
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
        replace_session_round(session, round_data)
        rebuild_adaptive_state(session)
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
    replace_session_round(session, current_round)
    session.alignment_score = calculate_session_alignment(session.rounds)

    normalize_session_scores(session)
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
        memory_usage = combine_usage(
            [
                get_attached_usage(session.user_profile),
                get_attached_usage(session.sunny_profile),
                get_attached_usage(session.crowley_profile),
            ]
        )
        replace_session_round(session, current_round)
        normalize_session_scores(session)
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
    replace_session_round(session, current_round)
    rebuild_adaptive_state(session)
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
