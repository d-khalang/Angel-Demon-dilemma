"""Debate orchestration."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime

from angel_demon.agents import (
    generate_opening_stream,
    generate_rebuttal_stream,
    make_opening,
    make_rebuttal,
)
from angel_demon.config import Settings
from angel_demon.judge import judge_debate
from angel_demon.llm import LLMProvider, estimate_tokens
from angel_demon.memory import update_agent_profile, update_user_profile
from angel_demon.models import Character, Round, SessionState, UserChoice
from angel_demon.scoring import apply_alignment_delta, calculate_alignment_delta
from angel_demon.state import SessionStore

ChunkCallback = Callable[[str, str], None]


async def _collect_stream(
    role: str,
    stream,
    on_chunk: ChunkCallback | None,
) -> tuple[str, int]:
    chunks: list[str] = []
    start = time.perf_counter()
    async for chunk in stream:
        chunks.append(chunk)
        if on_chunk:
            on_chunk(role, chunk)
    return "".join(chunks).strip(), int((time.perf_counter() - start) * 1000)


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

    sunny_stream = generate_opening_stream(
        Character.SUNNY,
        dilemma,
        session.user_profile,
        session.sunny_profile,
        session.crowley_profile,
        history,
        llm,
        temperature=settings.agent_temperature,
    )
    sunny_text, sunny_latency = await _collect_stream("sunny_opening", sunny_stream, on_chunk)
    sunny_opening = make_opening(Character.SUNNY, sunny_text)
    store.save_message(session.session_id, round_number, "sunny_opening", sunny_text)
    store.log_model_run(
        session.session_id,
        round_number,
        "sunny_opening",
        llm.model,
        input_tokens=estimate_tokens([]),
        output_tokens=max(1, len(sunny_text) // 4),
        latency_ms=sunny_latency,
        was_streamed=True,
    )

    crowley_stream = generate_opening_stream(
        Character.CROWLEY,
        dilemma,
        session.user_profile,
        session.crowley_profile,
        session.sunny_profile,
        history,
        llm,
        temperature=settings.agent_temperature,
    )
    crowley_text, crowley_latency = await _collect_stream(
        "crowley_opening",
        crowley_stream,
        on_chunk,
    )
    crowley_opening = make_opening(Character.CROWLEY, crowley_text)
    store.save_message(session.session_id, round_number, "crowley_opening", crowley_text)
    store.log_model_run(
        session.session_id,
        round_number,
        "crowley_opening",
        llm.model,
        output_tokens=max(1, len(crowley_text) // 4),
        latency_ms=crowley_latency,
        was_streamed=True,
    )

    sunny_rebuttal_stream = generate_rebuttal_stream(
        Character.SUNNY,
        dilemma,
        sunny_opening,
        crowley_opening,
        session.user_profile,
        session.sunny_profile,
        session.crowley_profile,
        llm,
        temperature=settings.agent_temperature,
    )
    sunny_rebuttal_text, sunny_rebuttal_latency = await _collect_stream(
        "sunny_rebuttal",
        sunny_rebuttal_stream,
        on_chunk,
    )
    sunny_rebuttal = make_rebuttal(Character.SUNNY, sunny_rebuttal_text)
    store.save_message(session.session_id, round_number, "sunny_rebuttal", sunny_rebuttal_text)
    store.log_model_run(
        session.session_id,
        round_number,
        "sunny_rebuttal",
        llm.model,
        output_tokens=max(1, len(sunny_rebuttal_text) // 4),
        latency_ms=sunny_rebuttal_latency,
        was_streamed=True,
    )

    crowley_rebuttal_stream = generate_rebuttal_stream(
        Character.CROWLEY,
        dilemma,
        crowley_opening,
        sunny_opening,
        session.user_profile,
        session.crowley_profile,
        session.sunny_profile,
        llm,
        temperature=settings.agent_temperature,
    )
    crowley_rebuttal_text, crowley_rebuttal_latency = await _collect_stream(
        "crowley_rebuttal",
        crowley_rebuttal_stream,
        on_chunk,
    )
    crowley_rebuttal = make_rebuttal(Character.CROWLEY, crowley_rebuttal_text)
    store.save_message(session.session_id, round_number, "crowley_rebuttal", crowley_rebuttal_text)
    store.log_model_run(
        session.session_id,
        round_number,
        "crowley_rebuttal",
        llm.model,
        output_tokens=max(1, len(crowley_rebuttal_text) // 4),
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
    store.log_model_run(
        session.session_id,
        round_number,
        "judge",
        llm.model,
        output_tokens=max(1, len(verdict.model_dump_json()) // 4),
        latency_ms=int((time.perf_counter() - judge_start) * 1000),
        was_streamed=False,
        error="fallback" if verdict.is_fallback else None,
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
    store.log_model_run(
        session.session_id,
        current_round.round_number,
        "memory_updates",
        llm.model,
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
    return session
