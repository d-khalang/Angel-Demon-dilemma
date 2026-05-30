"""Debate judging."""

from __future__ import annotations

from angel_demon.llm import LLMError, LLMProvider
from angel_demon.logging_config import get_logger
from angel_demon.models import Character, Opening, Rebuttal, Verdict
from angel_demon.prompts import JUDGE_INSTRUCTIONS, judge_input

logger = get_logger("judge")


def fallback_verdict(round_number: int, reason: str | None = None) -> Verdict:
    winner = Character.SUNNY if round_number % 2 else Character.CROWLEY
    logger.warning("judge_fallback_used round_number=%d winner=%s", round_number, winner.value)
    sunny_score = 6 if winner == Character.SUNNY else 5
    crowley_score = 6 if winner == Character.CROWLEY else 5
    return Verdict(
        winner=winner,
        reason=reason or "Judge evaluation failed; fallback scoring applied.",
        sunny_score=sunny_score,
        crowley_score=crowley_score,
        persuasion_tactics_sunny=["unknown - fallback"],
        persuasion_tactics_crowley=["unknown - fallback"],
        key_moment="Structured judging failed before a key moment could be extracted.",
        is_fallback=True,
    )


async def judge_debate(
    dilemma: str,
    sunny_opening: Opening,
    crowley_opening: Opening,
    sunny_rebuttal: Rebuttal,
    crowley_rebuttal: Rebuttal,
    llm: LLMProvider,
    *,
    round_number: int,
    temperature: float,
) -> Verdict:
    messages = [
        {"role": "system", "content": JUDGE_INSTRUCTIONS},
        {
            "role": "user",
            "content": judge_input(
                dilemma,
                sunny_opening.argument,
                crowley_opening.argument,
                sunny_rebuttal.argument,
                crowley_rebuttal.argument,
            ),
        },
    ]
    try:
        verdict = await llm.complete_json(
            messages,
            Verdict,
            temperature=temperature,
            max_output_tokens=800,
        )
    except LLMError:
        logger.exception("judge_debate_failed round_number=%d", round_number)
        return fallback_verdict(round_number)

    if verdict.sunny_score == verdict.crowley_score:
        logger.warning(
            "judge_equal_scores_adjusted round_number=%d winner=%s score=%d",
            round_number,
            verdict.winner.value,
            verdict.sunny_score,
        )
        if verdict.winner == Character.SUNNY:
            verdict.sunny_score = min(10, verdict.crowley_score + 1)
        else:
            verdict.crowley_score = min(10, verdict.sunny_score + 1)
    logger.info(
        "judge_debate_success round_number=%d winner=%s sunny_score=%d crowley_score=%d",
        round_number,
        verdict.winner.value,
        verdict.sunny_score,
        verdict.crowley_score,
    )
    return verdict
