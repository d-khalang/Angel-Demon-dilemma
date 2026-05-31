from pathlib import Path

import pytest

from angel_demon.config import Settings
from angel_demon.flow import (
    continue_conversation_round,
    judge_conversation_round,
    start_conversation_round,
)
from angel_demon.llm import MockLLMProvider
from angel_demon.models import Character, ConversationSpeaker, ResponseTarget
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


@pytest.mark.asyncio
async def test_conversation_round_supports_targeted_followup(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    llm = MockLLMProvider(
        [
            "Sunny opening.",
            "Crowley opening.",
            "Sunny targeted reply.",
        ]
    )

    draft = await start_conversation_round(
        session,
        "Should I tell the painful truth?",
        llm,
        store,
        settings(tmp_path),
    )
    draft = await continue_conversation_round(
        session,
        draft,
        "Sunny, what if the truth hurts them?",
        ResponseTarget.SUNNY,
        llm,
        store,
        settings(tmp_path),
    )

    assert [message.speaker for message in draft.messages] == [
        ConversationSpeaker.USER,
        ConversationSpeaker.SUNNY,
        ConversationSpeaker.CROWLEY,
        ConversationSpeaker.USER,
        ConversationSpeaker.SUNNY,
    ]
    assert draft.messages[-1].content == "Sunny targeted reply."


@pytest.mark.asyncio
async def test_judged_conversation_becomes_round(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    llm = MockLLMProvider(
        [
            "Sunny opening.",
            "Crowley opening.",
            """
            {
              "winner": "crowley",
              "reason": "Crowley handled the user's follow-up better.",
              "sunny_score": 6,
              "crowley_score": 7,
              "persuasion_tactics_sunny": ["empathy"],
              "persuasion_tactics_crowley": ["pragmatism"],
              "key_moment": "Crowley answered the personal cost.",
              "safety_notes": null,
              "is_fallback": false
            }
            """,
        ]
    )

    draft = await start_conversation_round(
        session,
        "Should I tell the painful truth?",
        llm,
        store,
        settings(tmp_path),
    )
    round_data = await judge_conversation_round(session, draft, llm, store, settings(tmp_path))

    assert round_data.verdict.winner == Character.CROWLEY
    assert round_data.conversation == draft.messages
    assert round_data.sunny_opening.argument == "Sunny opening."
    assert round_data.crowley_opening.argument == "Crowley opening."
