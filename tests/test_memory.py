from typing import cast

import pytest
from pydantic import BaseModel

from angel_demon.llm import LLMProvider
from angel_demon.memory import update_session_memory, update_user_profile
from angel_demon.models import (
    AgentProfile,
    AgentProfileUpdate,
    Character,
    Round,
    SessionMemoryUpdate,
    UserChoice,
    UserProfile,
    UserProfileUpdate,
    Verdict,
)


class InvalidProfileUpdateLLM(LLMProvider):
    model = "invalid-profile-update"

    async def complete_json[T: BaseModel](
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float = 0.5,
        max_output_tokens: int = 1024,
    ) -> T:
        user_update = UserProfileUpdate.model_construct(
            inferred_values=["novelty"],
            vulnerability_to_sunny=2.0,
            vulnerability_to_crowley=-1.0,
            recent_themes=["risk"],
            notes="Invalid values returned by a provider implementation.",
        )
        if schema is SessionMemoryUpdate:
            return cast(
                T,
                SessionMemoryUpdate.model_construct(
                    user_update=user_update,
                    sunny_update=AgentProfileUpdate.model_construct(
                        successful_tactics=["mercy"],
                        failed_tactics=[],
                        opponent_winning_tactics=[],
                        adaptation_notes="Invalid combined update.",
                    ),
                    crowley_update=AgentProfileUpdate.model_construct(
                        successful_tactics=[],
                        failed_tactics=["status"],
                        opponent_winning_tactics=["mercy"],
                        adaptation_notes="Invalid combined update.",
                    ),
                ),
            )
        return cast(T, user_update)


@pytest.mark.asyncio
async def test_user_memory_falls_back_when_reconstruction_validation_fails() -> None:
    profile = UserProfile()
    round_result = Round(
        round_number=1,
        dilemma="Should I take the generous option?",
        user_choice=UserChoice.FOLLOW_SUNNY,
    )

    updated = await update_user_profile(
        profile,
        round_result,
        InvalidProfileUpdateLLM(),
        temperature=0.3,
    )

    assert updated.decision_history == [UserChoice.FOLLOW_SUNNY]
    assert updated.vulnerability_to_sunny == 1.0
    assert updated.vulnerability_to_crowley == 0.0
    assert updated.notes == "Fallback memory update after round 1."


@pytest.mark.asyncio
async def test_session_memory_falls_back_without_duplicate_recorded_choice() -> None:
    profile = UserProfile(decision_history=[UserChoice.FOLLOW_SUNNY])
    sunny = AgentProfile(character=Character.SUNNY, wins=1)
    crowley = AgentProfile(character=Character.CROWLEY, losses=1)
    round_result = Round(
        round_number=1,
        dilemma="Should I take the generous option?",
        user_choice=UserChoice.FOLLOW_SUNNY,
        verdict=Verdict(
            winner=Character.SUNNY,
            reason="Sunny was more persuasive.",
            sunny_score=8,
            crowley_score=6,
            persuasion_tactics_sunny=["mercy"],
            persuasion_tactics_crowley=["status"],
            key_moment="The user favored generosity.",
        ),
    )

    updated_user, updated_sunny, updated_crowley = await update_session_memory(
        profile,
        sunny,
        crowley,
        round_result,
        InvalidProfileUpdateLLM(),
        temperature=0.3,
        user_choice_already_recorded=True,
    )

    assert updated_user.decision_history == [UserChoice.FOLLOW_SUNNY]
    assert updated_user.vulnerability_to_sunny == 1.0
    assert updated_sunny.successful_tactics == ["mercy"]
    assert updated_crowley.failed_tactics == ["status"]
