from typing import cast

import pytest
from pydantic import BaseModel

from angel_demon.llm import LLMProvider
from angel_demon.memory import update_user_profile
from angel_demon.models import Round, UserChoice, UserProfile, UserProfileUpdate


class InvalidProfileUpdateLLM(LLMProvider):
    model = "invalid-profile-update"

    async def complete_json[T: BaseModel](
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float = 0.5,
        max_output_tokens: int = 1024,
    ) -> T:
        return cast(
            T,
            UserProfileUpdate.model_construct(
                inferred_values=["novelty"],
                vulnerability_to_sunny=2.0,
                vulnerability_to_crowley=-1.0,
                recent_themes=["risk"],
                notes="Invalid values returned by a provider implementation.",
            ),
        )


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
