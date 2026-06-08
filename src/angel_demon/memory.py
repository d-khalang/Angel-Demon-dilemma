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
    SessionMemoryUpdate,
    UserChoice,
    UserProfile,
    UserProfileUpdate,
)
from angel_demon.prompts import (
    AGENT_MEMORY_INSTRUCTIONS,
    SESSION_MEMORY_INSTRUCTIONS,
    USER_MEMORY_INSTRUCTIONS,
)

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


def _decision_history(
    profile: UserProfile,
    round_result: Round,
    *,
    include_round_choice: bool,
) -> list[UserChoice]:
    if not include_round_choice:
        return list(profile.decision_history)
    return [
        *profile.decision_history,
        round_result.user_choice or UserChoice.UNDECIDED,
    ]


def _apply_user_update(
    profile: UserProfile,
    round_result: Round,
    update: UserProfileUpdate,
    *,
    include_round_choice: bool,
) -> UserProfile:
    return UserProfile(
        inferred_values=_dedupe(update.inferred_values),
        decision_history=_decision_history(
            profile,
            round_result,
            include_round_choice=include_round_choice,
        ),
        vulnerability_to_sunny=update.vulnerability_to_sunny,
        vulnerability_to_crowley=update.vulnerability_to_crowley,
        recent_themes=_dedupe(update.recent_themes, limit=5),
        notes=update.notes,
    )


def _apply_agent_update(profile: AgentProfile, update: AgentProfileUpdate) -> AgentProfile:
    return AgentProfile(
        character=profile.character,
        successful_tactics=_dedupe(update.successful_tactics),
        failed_tactics=_dedupe(update.failed_tactics),
        opponent_winning_tactics=_dedupe(update.opponent_winning_tactics),
        adaptation_notes=update.adaptation_notes,
        wins=profile.wins,
        losses=profile.losses,
    )


def _enforce_round_outcome(
    profile: AgentProfile,
    round_result: Round,
    update: AgentProfileUpdate,
) -> AgentProfileUpdate:
    if round_result.verdict is None:
        return update
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
    won = (
        round_result.user_choice == UserChoice.FOLLOW_SUNNY
        if profile.character == Character.SUNNY
        else round_result.user_choice == UserChoice.FOLLOW_CROWLEY
    )
    own_keys = {value.strip().lower() for value in own_tactics}
    successful = [
        value
        for value in update.successful_tactics
        if value.strip().lower() not in own_keys or won
    ]
    failed = [
        value
        for value in update.failed_tactics
        if value.strip().lower() not in own_keys or not won
    ]
    if won:
        successful.extend(own_tactics)
    else:
        failed.extend(own_tactics)
    opponent_winning = list(update.opponent_winning_tactics)
    if not won:
        opponent_winning.extend(opponent_tactics)
    return AgentProfileUpdate(
        successful_tactics=_dedupe(successful),
        failed_tactics=_dedupe(failed),
        opponent_winning_tactics=_dedupe(opponent_winning),
        adaptation_notes=update.adaptation_notes,
    )


def _session_memory_messages(
    user_profile: UserProfile,
    sunny_profile: AgentProfile,
    crowley_profile: AgentProfile,
    round_result: Round,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SESSION_MEMORY_INSTRUCTIONS},
        {
            "role": "user",
            "content": (
                f"Current user profile JSON:\n{user_profile.model_dump_json()}\n\n"
                f"Current Sunny profile JSON:\n{sunny_profile.model_dump_json()}\n\n"
                f"Current Crowley profile JSON:\n{crowley_profile.model_dump_json()}\n\n"
                f"Latest round summary JSON:\n{_memory_round_payload(round_result)}\n\n"
                "Return updates for user_update, sunny_update, and crowley_update. "
                "For each character, successful_tactics are tactics that helped that character "
                "win the user's choice this round, failed_tactics are tactics that did not, and "
                "opponent_winning_tactics are the opposing tactics to counter next."
            ),
        },
    ]


async def update_session_memory(
    user_profile: UserProfile,
    sunny_profile: AgentProfile,
    crowley_profile: AgentProfile,
    round_result: Round,
    llm: LLMProvider,
    *,
    temperature: float,
    user_choice_already_recorded: bool = False,
) -> tuple[UserProfile, AgentProfile, AgentProfile]:
    if round_result.verdict is None:
        raise ValueError("Cannot update session memory before a round has a verdict.")

    usage_source: SessionMemoryUpdate | None = None
    try:
        update = await llm.complete_json(
            _session_memory_messages(
                user_profile,
                sunny_profile,
                crowley_profile,
                round_result,
            ),
            SessionMemoryUpdate,
            temperature=temperature,
            max_output_tokens=1200,
        )
        updated_user = _apply_user_update(
            user_profile,
            round_result,
            update.user_update,
            include_round_choice=not user_choice_already_recorded,
        )
        updated_sunny = _apply_agent_update(
            sunny_profile,
            _enforce_round_outcome(sunny_profile, round_result, update.sunny_update),
        )
        updated_crowley = _apply_agent_update(
            crowley_profile,
            _enforce_round_outcome(crowley_profile, round_result, update.crowley_update),
        )
        usage_source = update
    except (LLMError, ValidationError):
        logger.exception(
            "session_memory_update_failed_using_heuristic round_number=%d",
            round_result.round_number,
        )
        updated_user = _apply_user_update(
            user_profile,
            round_result,
            _heuristic_user_update(
                user_profile,
                round_result,
                include_round_choice=not user_choice_already_recorded,
            ),
            include_round_choice=not user_choice_already_recorded,
        )
        updated_sunny = _apply_agent_update(
            sunny_profile,
            _heuristic_agent_update(sunny_profile, round_result),
        )
        updated_crowley = _apply_agent_update(
            crowley_profile,
            _heuristic_agent_update(crowley_profile, round_result),
        )

    updated_user = attach_usage(updated_user, get_attached_usage(usage_source))
    logger.info(
        "session_memory_updated round_number=%d user_values=%d sunny_tactics=%d "
        "crowley_tactics=%d",
        round_result.round_number,
        len(updated_user.inferred_values),
        len(updated_sunny.successful_tactics),
        len(updated_crowley.successful_tactics),
    )
    return updated_user, updated_sunny, updated_crowley


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
        updated = _apply_user_update(
            profile,
            round_result,
            update,
            include_round_choice=True,
        )
    except (LLMError, ValidationError):
        logger.exception(
            "user_profile_update_failed_using_heuristic round_number=%d",
            round_result.round_number,
        )
        update = _heuristic_user_update(profile, round_result, include_round_choice=True)
        updated = _apply_user_update(
            profile,
            round_result,
            update,
            include_round_choice=True,
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
        updated = _apply_agent_update(profile, update)
    except (LLMError, ValidationError):
        logger.exception(
            "agent_profile_update_failed_using_heuristic character=%s round_number=%d",
            profile.character.value,
            round_result.round_number,
        )
        update = _heuristic_agent_update(profile, round_result)
        updated = _apply_agent_update(profile, update)

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


def _heuristic_user_update(
    profile: UserProfile,
    round_result: Round,
    *,
    include_round_choice: bool,
) -> UserProfileUpdate:
    choices = _decision_history(
        profile,
        round_result,
        include_round_choice=include_round_choice,
    )
    sunny_count = choices.count(UserChoice.FOLLOW_SUNNY)
    crowley_count = choices.count(UserChoice.FOLLOW_CROWLEY)
    total = max(1, sunny_count + crowley_count)
    new_values: list[str] = []
    if round_result.user_choice == UserChoice.FOLLOW_SUNNY:
        new_values.append("empathy")
    elif round_result.user_choice == UserChoice.FOLLOW_CROWLEY:
        new_values.append("self-preservation")
    if sunny_count + crowley_count == 0:
        sunny_vulnerability = 0.5
        crowley_vulnerability = 0.5
    else:
        sunny_vulnerability = sunny_count / total
        crowley_vulnerability = crowley_count / total
    return UserProfileUpdate(
        inferred_values=_dedupe([*profile.inferred_values, *new_values]),
        vulnerability_to_sunny=sunny_vulnerability,
        vulnerability_to_crowley=crowley_vulnerability,
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


def rebuild_session_memory(
    rounds: list[Round],
) -> tuple[UserProfile, AgentProfile, AgentProfile]:
    """Rebuild adaptive profiles from durable decided rounds.

    This is used when a decision is changed or invalidated. LLM-derived profile
    snapshots cannot be reversed safely because they combine multiple rounds.
    """
    user_profile = UserProfile()
    sunny_profile = AgentProfile(character=Character.SUNNY)
    crowley_profile = AgentProfile(character=Character.CROWLEY)
    decided_rounds = [
        round_data
        for round_data in rounds
        if round_data.verdict is not None and round_data.user_choice is not None
    ]
    for round_data in decided_rounds:
        user_profile = _apply_user_update(
            user_profile,
            round_data,
            _heuristic_user_update(
                user_profile,
                round_data,
                include_round_choice=True,
            ),
            include_round_choice=True,
        )
        sunny_profile = _apply_agent_update(
            sunny_profile,
            _heuristic_agent_update(sunny_profile, round_data),
        )
        crowley_profile = _apply_agent_update(
            crowley_profile,
            _heuristic_agent_update(crowley_profile, round_data),
        )
    return user_profile, sunny_profile, crowley_profile
