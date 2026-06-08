from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from angel_demon.config import Settings
from angel_demon.flow import (
    decide_round,
    reopen_round,
    revote_round,
    start_conversation_round,
    update_round_memory,
)
from angel_demon.llm import MockLLMProvider
from angel_demon.models import (
    Character,
    Round,
    RoundStatus,
    UserChoice,
    Verdict,
)
from angel_demon.state import SessionStore


def settings(tmp_path: Path) -> Settings:
    return Settings(
        openai_api_key=None,
        openai_model="mock",
        llm_provider="mock",
        db_path=tmp_path / "state.db",
        log_level="INFO",
        log_file=tmp_path / "test.log",
        log_llm_payloads=False,
        max_rounds_per_session=20,
        agent_temperature=0.8,
        judge_temperature=0.3,
        memory_temperature=0.3,
    )


def decided_round() -> Round:
    return Round(
        round_number=1,
        dilemma="Should I tell the truth or protect a friend?",
        status=RoundStatus.JUDGED,
        verdict=Verdict(
            winner=Character.SUNNY,
            reason="Sunny made the stronger case.",
            sunny_score=8,
            crowley_score=6,
            persuasion_tactics_sunny=["empathy"],
            persuasion_tactics_crowley=["status"],
            key_moment="The cost of deception became clear.",
        ),
    )


@pytest.mark.asyncio
async def test_stale_session_writers_do_not_overwrite_the_same_round(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    first_client = store.load_session(session.session_id)
    second_client = store.load_session(session.session_id)
    assert first_client is not None
    assert second_client is not None

    await start_conversation_round(
        first_client,
        "Should I choose option A or option B?",
        MockLLMProvider(["A1", "A2", "A3", "A4"]),
        store,
        settings(tmp_path),
    )
    await start_conversation_round(
        second_client,
        "Should I choose option C or option D?",
        MockLLMProvider(["B1", "B2", "B3", "B4"]),
        store,
        settings(tmp_path),
    )

    loaded = store.load_session(session.session_id)
    assert loaded is not None
    assert [(item.round_number, item.dilemma) for item in loaded.rounds] == [
        (1, "Should I choose option A or option B?"),
        (2, "Should I choose option C or option D?"),
    ]


def test_concurrent_round_allocation_produces_unique_round_numbers(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    first_client = store.load_session(session.session_id)
    second_client = store.load_session(session.session_id)
    assert first_client is not None
    assert second_client is not None
    barrier = Barrier(2)

    def create_round(client, dilemma: str) -> int:
        barrier.wait()
        return store.create_round(client, dilemma).round_number

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(create_round, first_client, "Choose A or B?")
        second = executor.submit(create_round, second_client, "Choose C or D?")

    assert sorted([first.result(), second.result()]) == [1, 2]
    loaded = store.load_session(session.session_id)
    assert loaded is not None
    assert [round_data.round_number for round_data in loaded.rounds] == [1, 2]


def test_stale_round_creation_preserves_latest_session_profiles(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    stale_client = store.load_session(session.session_id)
    latest = store.load_session(session.session_id)
    assert stale_client is not None
    assert latest is not None
    latest.user_profile.inferred_values = ["latest durable value"]
    store.save_session(latest)

    store.create_round(stale_client, "Should I choose A or B?")

    loaded = store.load_session(session.session_id)
    assert loaded is not None
    assert loaded.user_profile.inferred_values == ["latest durable value"]


@pytest.mark.asyncio
async def test_revote_rebuilds_memory_from_the_new_durable_choice(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    round_data = decided_round()
    session.rounds.append(round_data)
    store.save_round(session.session_id, round_data)

    decide_round(session, round_data, UserChoice.FOLLOW_SUNNY, store)
    await update_round_memory(
        session,
        round_data,
        MockLLMProvider(["not-json"]),
        store,
        settings(tmp_path),
    )
    assert session.sunny_profile.successful_tactics == ["empathy"]

    revote_round(session, round_data, UserChoice.FOLLOW_CROWLEY, store)

    assert session.user_profile.inferred_values == ["self-preservation"]
    assert session.sunny_profile.successful_tactics == []
    assert session.sunny_profile.failed_tactics == ["empathy"]
    assert session.crowley_profile.successful_tactics == ["status"]


@pytest.mark.asyncio
async def test_reopen_removes_memory_derived_from_the_invalidated_decision(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    round_data = decided_round()
    session.rounds.append(round_data)
    store.save_round(session.session_id, round_data)

    decide_round(session, round_data, UserChoice.FOLLOW_SUNNY, store)
    await update_round_memory(
        session,
        round_data,
        MockLLMProvider(["not-json"]),
        store,
        settings(tmp_path),
    )

    reopen_round(session, round_data, store)

    assert session.user_profile.inferred_values == []
    assert session.user_profile.decision_history == []
    assert session.sunny_profile.successful_tactics == []
    assert session.crowley_profile.failed_tactics == []


@pytest.mark.asyncio
async def test_completed_memory_job_is_not_executed_twice(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    round_data = decided_round()
    session.rounds.append(round_data)
    store.save_round(session.session_id, round_data)
    decide_round(session, round_data, UserChoice.FOLLOW_SUNNY, store)

    await update_round_memory(
        session,
        round_data,
        MockLLMProvider(["not-json"]),
        store,
        settings(tmp_path),
    )
    await update_round_memory(
        session,
        round_data,
        MockLLMProvider([]),
        store,
        settings(tmp_path),
    )

    assert not store.has_pending_memory_update(session.session_id, round_data.round_number)


def test_pending_memory_update_survives_store_restart(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    store = SessionStore(db_path)
    session = store.create_session()
    round_data = decided_round()
    session.rounds.append(round_data)
    store.save_round(session.session_id, round_data)

    decide_round(session, round_data, UserChoice.FOLLOW_SUNNY, store)
    assert store.claim_pending_memory_update(session.session_id, round_data.round_number)

    restarted_store = SessionStore(db_path)
    assert restarted_store.has_pending_memory_update(session.session_id, round_data.round_number)


class FailingTransitionStore(SessionStore):
    def _write_model_run(self, *args, **kwargs) -> None:
        raise RuntimeError("injected model-run write failure")


def test_round_transition_rolls_back_all_related_writes(tmp_path) -> None:
    store = FailingTransitionStore(tmp_path / "state.db")
    session = store.create_session()
    round_data = Round(round_number=1, dilemma="Should I choose A or B?")

    with pytest.raises(RuntimeError, match="injected"):
        store.persist_round_transition(
            session,
            round_data,
            messages=[("user", round_data.dilemma)],
            model_runs=[
                {
                    "call_type": "probe",
                    "model": "mock",
                    "was_streamed": False,
                }
            ],
        )

    loaded = store.load_session(session.session_id)
    assert loaded is not None
    assert loaded.rounds == []
    assert store.list_messages(session.session_id) == []
