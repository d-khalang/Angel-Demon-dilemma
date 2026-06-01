from pathlib import Path

import pytest

from angel_demon.config import Settings
from angel_demon.flow import (
    advance_conversation_round,
    apply_user_choice,
    continue_conversation_round,
    judge_conversation_round,
    reopen_round,
    revote_round,
    start_conversation_round,
)
from angel_demon.llm import MockLLMProvider
from angel_demon.models import (
    Character,
    ConversationSpeaker,
    ResponseTarget,
    RoundStatus,
    UserChoice,
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


@pytest.mark.asyncio
async def test_conversation_round_supports_targeted_followup(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    llm = MockLLMProvider(
        [
            "Sunny opening.",
            "Crowley opening.",
            "Sunny first clash.",
            "Crowley first clash.",
            "Sunny targeted reply.",
        ]
    )

    round_data = await start_conversation_round(
        session,
        "Should I tell the painful truth?",
        llm,
        store,
        settings(tmp_path),
    )
    round_data = await continue_conversation_round(
        session,
        round_data,
        "Sunny, what if the truth hurts them?",
        ResponseTarget.SUNNY,
        llm,
        store,
        settings(tmp_path),
    )

    assert [message.speaker for message in round_data.conversation] == [
        ConversationSpeaker.USER,
        ConversationSpeaker.SUNNY,
        ConversationSpeaker.CROWLEY,
        ConversationSpeaker.SYSTEM,
        ConversationSpeaker.SUNNY,
        ConversationSpeaker.CROWLEY,
        ConversationSpeaker.USER,
        ConversationSpeaker.SUNNY,
    ]
    assert round_data.status == RoundStatus.ACTIVE
    assert round_data.conversation[-1].content == "Sunny targeted reply."


@pytest.mark.asyncio
async def test_conversation_round_can_advance_without_user_followup(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    llm = MockLLMProvider(
        [
            "Sunny opening.",
            "Crowley opening.",
            "Sunny first clash.",
            "Crowley first clash.",
            "Sunny continues.",
            "Crowley continues.",
        ]
    )

    round_data = await start_conversation_round(
        session,
        "Should I tell the painful truth?",
        llm,
        store,
        settings(tmp_path),
    )
    round_data = await advance_conversation_round(
        session,
        round_data,
        llm,
        store,
        settings(tmp_path),
    )

    assert [message.speaker for message in round_data.conversation] == [
        ConversationSpeaker.USER,
        ConversationSpeaker.SUNNY,
        ConversationSpeaker.CROWLEY,
        ConversationSpeaker.SYSTEM,
        ConversationSpeaker.SUNNY,
        ConversationSpeaker.CROWLEY,
        ConversationSpeaker.SYSTEM,
        ConversationSpeaker.SUNNY,
        ConversationSpeaker.CROWLEY,
    ]
    assert round_data.conversation[-2].content == "Sunny continues."
    assert round_data.conversation[-1].content == "Crowley continues."


@pytest.mark.asyncio
async def test_judged_conversation_becomes_round(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    llm = MockLLMProvider(
        [
            "Sunny opening.",
            "Crowley opening.",
            "Sunny first clash.",
            "Crowley first clash.",
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

    round_data = await start_conversation_round(
        session,
        "Should I tell the painful truth?",
        llm,
        store,
        settings(tmp_path),
    )
    judged = await judge_conversation_round(session, round_data, llm, store, settings(tmp_path))

    assert judged.verdict is not None
    assert judged.verdict.winner == Character.CROWLEY
    assert judged.status == RoundStatus.JUDGED
    assert judged.conversation == round_data.conversation
    assert judged.sunny_opening.argument == "Sunny opening."
    assert judged.crowley_opening.argument == "Crowley opening."


@pytest.mark.asyncio
async def test_judged_round_can_be_reopened_and_rejudged(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    llm = MockLLMProvider(
        [
            "Sunny opening.",
            "Crowley opening.",
            "Sunny first clash.",
            "Crowley first clash.",
            """
            {
              "winner": "sunny",
              "reason": "Sunny was clearer.",
              "sunny_score": 7,
              "crowley_score": 6,
              "persuasion_tactics_sunny": ["empathy"],
              "persuasion_tactics_crowley": ["pragmatism"],
              "key_moment": "Sunny answered the fear.",
              "safety_notes": null,
              "is_fallback": false
            }
            """,
            "Crowley adds context.",
            """
            {
              "winner": "crowley",
              "reason": "Crowley used the new context better.",
              "sunny_score": 6,
              "crowley_score": 8,
              "persuasion_tactics_sunny": ["empathy"],
              "persuasion_tactics_crowley": ["personal cost"],
              "key_moment": "Crowley reframed the consequence.",
              "safety_notes": null,
              "is_fallback": false
            }
            """,
        ]
    )

    round_data = await start_conversation_round(
        session,
        "Should I tell the painful truth?",
        llm,
        store,
        settings(tmp_path),
    )
    round_data = await judge_conversation_round(session, round_data, llm, store, settings(tmp_path))
    original_length = len(round_data.conversation)

    reopen_round(session, round_data, store)
    round_data = await continue_conversation_round(
        session,
        round_data,
        "Crowley, answer the emotional cost.",
        ResponseTarget.CROWLEY,
        llm,
        store,
        settings(tmp_path),
    )
    round_data = await judge_conversation_round(session, round_data, llm, store, settings(tmp_path))

    assert round_data.status == RoundStatus.JUDGED
    assert round_data.verdict is not None
    assert round_data.verdict.winner == Character.CROWLEY
    assert len(round_data.conversation) == original_length + 2


@pytest.mark.asyncio
async def test_choice_and_revote_recalculate_session_totals(tmp_path) -> None:
    store = SessionStore(tmp_path / "state.db")
    session = store.create_session()
    llm = MockLLMProvider(
        [
            "Sunny opening.",
            "Crowley opening.",
            "Sunny first clash.",
            "Crowley first clash.",
            """
            {
              "winner": "sunny",
              "reason": "Sunny was clearer.",
              "sunny_score": 7,
              "crowley_score": 6,
              "persuasion_tactics_sunny": ["empathy"],
              "persuasion_tactics_crowley": ["pragmatism"],
              "key_moment": "Sunny answered the fear.",
              "safety_notes": null,
              "is_fallback": false
            }
            """,
            """
            {
              "inferred_values": ["honesty"],
              "vulnerability_to_sunny": 1.0,
              "vulnerability_to_crowley": 0.0,
              "recent_themes": ["truth"],
              "notes": "Values honesty."
            }
            """,
            """
            {
              "successful_tactics": ["empathy"],
              "failed_tactics": [],
              "opponent_winning_tactics": [],
              "adaptation_notes": "Use empathy."
            }
            """,
            """
            {
              "successful_tactics": [],
              "failed_tactics": ["pragmatism"],
              "opponent_winning_tactics": ["empathy"],
              "adaptation_notes": "Counter empathy."
            }
            """,
        ]
    )

    round_data = await start_conversation_round(
        session,
        "Should I tell the painful truth?",
        llm,
        store,
        settings(tmp_path),
    )
    round_data = await judge_conversation_round(session, round_data, llm, store, settings(tmp_path))
    session = await apply_user_choice(
        session,
        round_data,
        UserChoice.FOLLOW_SUNNY,
        llm,
        store,
        settings(tmp_path),
    )

    assert session.alignment_score == 18
    assert session.sunny_profile.wins == 1
    assert session.crowley_profile.wins == 0

    session = revote_round(session, round_data, UserChoice.FOLLOW_CROWLEY, store)

    assert session.alignment_score == -12
    assert session.sunny_profile.wins == 0
    assert session.crowley_profile.wins == 1
