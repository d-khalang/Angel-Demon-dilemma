"""Memory and adaptation updates."""

from __future__ import annotations

import json

from pydantic import ValidationError

from angel_demon.llm import LLMError, LLMProvider, attach_usage, get_attached_usage
from angel_demon.logging_config import get_logger
from angel_demon.models import (
    AgentProfile,
    AgentProfileUpdate,
    Character,
    Round,
    UserChoice,
    UserProfile,
    UserProfileUpdate,
)
from angel_demon.prompts import AGENT_MEMORY_INSTRUCTIONS, USER_MEMORY_INSTRUCTIONS

logger = get_logger("memory")


def _dedupe(values: list[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(value.strip())
    return result[:limit]


def _truncate(value: str, limit: int = 600) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _memory_round_payload(round_result: Round) -> str:
    verdict = round_result.verdict
    payload = {
        "round_number": round_result.round_number,
        "dilemma": round_result.dilemma,
        "status": round_result.status.value,
        "user_choice": round_result.user_choice.value if round_result.user_choice else None,
        "alignment_delta": round_result.alignment_delta,
        "verdict": None
        if verdict is None
        else {
            "winner": verdict.winner.value,
            "reason": verdict.reason,
            "sunny_score": verdict.sunny_score,
            "crowley_score": verdict.crowley_score,
            "persuasion_tactics_sunny": verdict.persuasion_tactics_sunny,
            "persuasion_tactics_crowley": verdict.persuasion_tactics_crowley,
            "key_moment": verdict.key_moment,
        },
        "transcript_excerpt": [
            {
                "speaker": message.speaker.value,
                "target": getattr(message.target, "value", message.target),
                "content": _truncate(message.content),
            }
            for message in round_result.conversation[-8:]
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


async def update_user_profile(
    profile: UserProfile,
    round_result: Round,
    llm: LLMProvider,
    *,
    temperature: float,
) -> UserProfile:
    messages = [
        {"role": "system", "content": USER_MEMORY_INSTRUCTIONS},
        {
            "role": "user",
            "content": (
                f"Current profile JSON:\n{profile.model_dump_json()}\n\n"
                f"Latest round summary JSON:\n{_memory_round_payload(round_result)}\n\n"
                "Return the updated user profile fields."
            ),
        },
    ]
    try:
        update = await llm.complete_json(
            messages,
            UserProfileUpdate,
            temperature=temperature,
            max_output_tokens=500,
        )
        updated = UserProfile(
            inferred_values=_dedupe(update.inferred_values),
            decision_history=[
                *profile.decision_history,
                round_result.user_choice or UserChoice.UNDECIDED,
            ],
            vulnerability_to_sunny=update.vulnerability_to_sunny,
            vulnerability_to_crowley=update.vulnerability_to_crowley,
            recent_themes=_dedupe(update.recent_themes, limit=5),
            notes=update.notes,
        )
    except (LLMError, ValidationError):
        logger.exception(
            "user_profile_update_failed_using_heuristic round_number=%d",
            round_result.round_number,
        )
        update = _heuristic_user_update(profile, round_result)
        updated = UserProfile(
            inferred_values=_dedupe(update.inferred_values),
            decision_history=[
                *profile.decision_history,
                round_result.user_choice or UserChoice.UNDECIDED,
            ],
            vulnerability_to_sunny=update.vulnerability_to_sunny,
            vulnerability_to_crowley=update.vulnerability_to_crowley,
            recent_themes=_dedupe(update.recent_themes, limit=5),
            notes=update.notes,
        )
    updated = attach_usage(updated, get_attached_usage(update))
    logger.info(
        "user_profile_updated round_number=%d values=%d recent_themes=%d",
        round_result.round_number,
        len(updated.inferred_values),
        len(updated.recent_themes),
    )
    return updated


async def update_agent_profile(
    profile: AgentProfile,
    round_result: Round,
    user_profile: UserProfile,
    llm: LLMProvider,
    *,
    temperature: float,
) -> AgentProfile:
    if round_result.verdict is None:
        raise ValueError("Cannot update agent memory before a round has a verdict.")

    own_tactics = (
        round_result.verdict.persuasion_tactics_sunny
        if profile.character == Character.SUNNY
        else round_result.verdict.persuasion_tactics_crowley
    )
    opponent_tactics = (
        round_result.verdict.persuasion_tactics_crowley
        if profile.character == Character.SUNNY
        else round_result.verdict.persuasion_tactics_sunny
    )
    messages = [
        {"role": "system", "content": AGENT_MEMORY_INSTRUCTIONS},
        {
            "role": "user",
            "content": (
                f"Current profile JSON:\n{profile.model_dump_json()}\n\n"
                f"User profile JSON:\n{user_profile.model_dump_json()}\n\n"
                f"Round summary JSON:\n{_memory_round_payload(round_result)}\n\n"
                f"Own tactics: {own_tactics}\nOpponent tactics: {opponent_tactics}\n"
                "Return the updated agent profile fields."
            ),
        },
    ]
    try:
        update = await llm.complete_json(
            messages,
            AgentProfileUpdate,
            temperature=temperature,
            max_output_tokens=500,
        )
    except LLMError:
        logger.exception(
            "agent_profile_update_failed_using_heuristic character=%s round_number=%d",
            profile.character.value,
            round_result.round_number,
        )
        update = _heuristic_agent_update(profile, round_result)

    updated = AgentProfile(
        character=profile.character,
        successful_tactics=_dedupe(update.successful_tactics),
        failed_tactics=_dedupe(update.failed_tactics),
        opponent_winning_tactics=_dedupe(update.opponent_winning_tactics),
        adaptation_notes=update.adaptation_notes,
        wins=profile.wins,
        losses=profile.losses,
    )
    updated = attach_usage(updated, get_attached_usage(update))
    logger.info(
        "agent_profile_updated character=%s round_number=%d successful_tactics=%d "
        "failed_tactics=%d",
        updated.character.value,
        round_result.round_number,
        len(updated.successful_tactics),
        len(updated.failed_tactics),
    )
    return updated


def _heuristic_user_update(profile: UserProfile, round_result: Round) -> UserProfileUpdate:
    choices = [*profile.decision_history, round_result.user_choice or UserChoice.UNDECIDED]
    sunny_count = choices.count(UserChoice.FOLLOW_SUNNY)
    crowley_count = choices.count(UserChoice.FOLLOW_CROWLEY)
    total = max(1, sunny_count + crowley_count)
    value = (
        "empathy"
        if round_result.user_choice == UserChoice.FOLLOW_SUNNY
        else "self-preservation"
    )
    return UserProfileUpdate(
        inferred_values=_dedupe([*profile.inferred_values, value]),
        vulnerability_to_sunny=sunny_count / total,
        vulnerability_to_crowley=crowley_count / total,
        recent_themes=_dedupe([*profile.recent_themes, "moral tradeoff"], limit=5),
        notes=f"Fallback memory update after round {round_result.round_number}.",
    )


def _heuristic_agent_update(profile: AgentProfile, round_result: Round) -> AgentProfileUpdate:
    if round_result.verdict is None:
        raise ValueError("Cannot update agent memory before a round has a verdict.")

    won = (
        round_result.user_choice == UserChoice.FOLLOW_SUNNY
        if profile.character == Character.SUNNY
        else round_result.user_choice == UserChoice.FOLLOW_CROWLEY
    )
    own_tactics = (
        round_result.verdict.persuasion_tactics_sunny
        if profile.character == Character.SUNNY
        else round_result.verdict.persuasion_tactics_crowley
    )
    opponent_tactics = (
        round_result.verdict.persuasion_tactics_crowley
        if profile.character == Character.SUNNY
        else round_result.verdict.persuasion_tactics_sunny
    )
    return AgentProfileUpdate(
        successful_tactics=_dedupe(
            [*profile.successful_tactics, *(own_tactics if won else [])]
        ),
        failed_tactics=_dedupe([*profile.failed_tactics, *(own_tactics if not won else [])]),
        opponent_winning_tactics=_dedupe(
            [*profile.opponent_winning_tactics, *(opponent_tactics if not won else [])]
        ),
        adaptation_notes=(
            "Repeat the tactics that won this user over."
            if won
            else "Adjust by countering the opponent's most persuasive tactics more directly."
        ),
    )
