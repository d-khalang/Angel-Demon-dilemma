import pytest

from angel_demon.judge import judge_debate
from angel_demon.llm import MockLLMProvider
from angel_demon.models import Character, Opening, Rebuttal


@pytest.mark.asyncio
async def test_judge_breaks_equal_scores_from_model() -> None:
    llm = MockLLMProvider(
        [
            """
            {
              "winner": "sunny",
              "reason": "Sunny landed the cleaner argument.",
              "sunny_score": 5,
              "crowley_score": 5,
              "persuasion_tactics_sunny": ["empathy"],
              "persuasion_tactics_crowley": ["self-interest"],
              "key_moment": "Sunny's rebuttal reframed the cost.",
              "safety_notes": null,
              "is_fallback": false
            }
            """
        ]
    )
    verdict = await judge_debate(
        "A dilemma?",
        Opening(character=Character.SUNNY, argument="Be kind."),
        Opening(character=Character.CROWLEY, argument="Be selfish."),
        Rebuttal(character=Character.SUNNY, argument="Kindness lasts."),
        Rebuttal(character=Character.CROWLEY, argument="So does regret."),
        llm,
        round_number=1,
        temperature=0.3,
    )

    assert verdict.winner == Character.SUNNY
    assert verdict.sunny_score > verdict.crowley_score


@pytest.mark.asyncio
async def test_judge_uses_fallback_on_bad_json() -> None:
    llm = MockLLMProvider(["not json"])
    verdict = await judge_debate(
        "A dilemma?",
        Opening(character=Character.SUNNY, argument="Be kind."),
        Opening(character=Character.CROWLEY, argument="Be selfish."),
        Rebuttal(character=Character.SUNNY, argument="Kindness lasts."),
        Rebuttal(character=Character.CROWLEY, argument="So does regret."),
        llm,
        round_number=2,
        temperature=0.3,
    )

    assert verdict.is_fallback is True
    assert verdict.winner == Character.CROWLEY


@pytest.mark.asyncio
async def test_judge_normalizes_scores_that_contradict_the_declared_winner() -> None:
    llm = MockLLMProvider(
        [
            """
            {
              "winner": "sunny",
              "reason": "Sunny landed the cleaner argument.",
              "sunny_score": 4,
              "crowley_score": 9,
              "persuasion_tactics_sunny": ["empathy"],
              "persuasion_tactics_crowley": ["self-interest"],
              "key_moment": "Sunny reframed the cost.",
              "safety_notes": null,
              "is_fallback": false
            }
            """
        ]
    )

    verdict = await judge_debate(
        "A dilemma?",
        Opening(character=Character.SUNNY, argument="Be kind."),
        Opening(character=Character.CROWLEY, argument="Be selfish."),
        Rebuttal(character=Character.SUNNY, argument="Kindness lasts."),
        Rebuttal(character=Character.CROWLEY, argument="So does regret."),
        llm,
        round_number=1,
        temperature=0.3,
    )

    assert verdict.winner == Character.SUNNY
    assert verdict.sunny_score > verdict.crowley_score
