from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from angel_demon.config import Settings
from angel_demon.flow import (
    apply_user_choice,
    continue_conversation_round,
    judge_conversation_round,
    reopen_round,
    revote_round,
    start_conversation_round,
)
from angel_demon.llm import LLMError, LLMProvider, MockLLMProvider
from angel_demon.models import ResponseTarget, RoundStatus, UserChoice
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


class InterruptedStreamProvider(LLMProvider):
    model = "interrupted"

    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        yield "partial output"
        raise LLMError("stream interrupted")


@pytest.mark.asyncio
async def test_interrupted_initial_stream_is_discarded_and_retry_is_clean(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()

    with pytest.raises(LLMError, match="interrupted"):
        await start_conversation_round(
            session,
            "Should I choose option A or option B?",
            InterruptedStreamProvider(),
            store,
            settings(tmp_path),
        )

    reloaded = store.load_session(session.session_id)
    assert reloaded is not None
    assert reloaded.rounds == []
    assert store.list_messages(session.session_id) == []

    retried = await start_conversation_round(
        session,
        "Should I choose option A or option B?",
        MockLLMProvider(["S1", "C1", "S2", "C2"]),
        store,
        settings(tmp_path),
    )
    assert retried.round_number == 1


@pytest.mark.asyncio
async def test_full_lifecycle_remains_consistent_across_database_reloads(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    store = SessionStore(db_path)
    session = store.create_session()
    llm = MockLLMProvider()

    round_data = await start_conversation_round(
        session,
        "Should I tell the truth or protect my friend?",
        llm,
        store,
        settings(tmp_path),
    )
    reloaded = store.load_session(session.session_id)
    assert reloaded is not None
    assert reloaded.rounds[0].status == RoundStatus.ACTIVE

    round_data = await continue_conversation_round(
        reloaded,
        reloaded.rounds[0],
        "What about the long-term consequences?",
        ResponseTarget.BOTH,
        llm,
        store,
        settings(tmp_path),
    )
    round_data = await judge_conversation_round(
        reloaded,
        round_data,
        llm,
        store,
        settings(tmp_path),
    )
    await apply_user_choice(
        reloaded,
        round_data,
        UserChoice.FOLLOW_SUNNY,
        llm,
        store,
        settings(tmp_path),
    )

    decided = SessionStore(db_path).load_session(session.session_id)
    assert decided is not None
    assert decided.rounds[0].status == RoundStatus.DECIDED
    assert decided.alignment_score == 18
    assert decided.user_profile.decision_history == [UserChoice.FOLLOW_SUNNY]
    assert not store.has_pending_memory_update(session.session_id, 1)

    revote_round(decided, decided.rounds[0], UserChoice.FOLLOW_CROWLEY, store)
    revoted = SessionStore(db_path).load_session(session.session_id)
    assert revoted is not None
    assert revoted.alignment_score == -12
    assert revoted.user_profile.decision_history == [UserChoice.FOLLOW_CROWLEY]
    assert store.has_pending_memory_update(session.session_id, 1)

    reopen_round(revoted, revoted.rounds[0], store)
    reopened = SessionStore(db_path).load_session(session.session_id)
    assert reopened is not None
    assert reopened.alignment_score == 0
    assert reopened.rounds[0].status == RoundStatus.ACTIVE
    assert reopened.user_profile.decision_history == []
    assert not store.has_pending_memory_update(session.session_id, 1)


@pytest.mark.asyncio
async def test_round_snapshot_and_audit_messages_reconcile(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    round_data = await start_conversation_round(
        session,
        "Should I tell the truth or protect my friend?",
        MockLLMProvider(),
        store,
        settings(tmp_path),
    )

    persisted = store.load_session(session.session_id)
    assert persisted is not None
    audit = [
        (str(row["role"]), str(row["content"]))
        for row in store.list_messages(session.session_id)
        if row["role"] in {"user", "system", "sunny", "crowley"}
    ]
    snapshot = [
        (message.speaker.value, message.content)
        for message in persisted.rounds[0].conversation
    ]

    assert round_data.conversation == persisted.rounds[0].conversation
    assert audit == snapshot
