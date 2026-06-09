"""Memory and adaptation updates."""

from __future__ import annotations

import json

from pydantic import ValidationError

from angel_demon.domain.memory import (
    apply_agent_update,
    apply_user_update,
    enforce_round_outcome,
    heuristic_agent_update,
    heuristic_user_update,
    rebuild_session_memory,
    tactics_for,
)
from angel_demon.llm import LLMError, LLMProvider, attach_usage, get_attached_usage
from angel_demon.logging_config import get_logger
from angel_demon.models import (
    AgentProfile,
    AgentProfileUpdate,
    Round,
    SessionMemoryUpdate,
    UserProfile,
    UserProfileUpdate,
)
from angel_demon.prompts import (
    AGENT_MEMORY_INSTRUCTIONS,
    SESSION_MEMORY_INSTRUCTIONS,
    USER_MEMORY_INSTRUCTIONS,
)

logger = get_logger("memory")

__all__ = [
    "rebuild_session_memory",
    "update_agent_profile",
    "update_session_memory",
    "update_user_profile",
]


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
        updated_user = apply_user_update(
            user_profile,
            round_result,
            update.user_update,
            include_round_choice=not user_choice_already_recorded,
        )
        updated_sunny = apply_agent_update(
            sunny_profile,
            enforce_round_outcome(sunny_profile, round_result, update.sunny_update),
        )
        updated_crowley = apply_agent_update(
            crowley_profile,
            enforce_round_outcome(crowley_profile, round_result, update.crowley_update),
        )
        usage_source = update
    except (LLMError, ValidationError):
        logger.exception(
            "session_memory_update_failed_using_heuristic round_number=%d",
            round_result.round_number,
        )
        updated_user = apply_user_update(
            user_profile,
            round_result,
            heuristic_user_update(
                user_profile,
                round_result,
                include_round_choice=not user_choice_already_recorded,
            ),
            include_round_choice=not user_choice_already_recorded,
        )
        updated_sunny = apply_agent_update(
            sunny_profile,
            heuristic_agent_update(sunny_profile, round_result),
        )
        updated_crowley = apply_agent_update(
            crowley_profile,
            heuristic_agent_update(crowley_profile, round_result),
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
        updated = apply_user_update(
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
        update = heuristic_user_update(profile, round_result, include_round_choice=True)
        updated = apply_user_update(
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

    own_tactics, opponent_tactics = tactics_for(profile, round_result)
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
        updated = apply_agent_update(profile, update)
    except (LLMError, ValidationError):
        logger.exception(
            "agent_profile_update_failed_using_heuristic character=%s round_number=%d",
            profile.character.value,
            round_result.round_number,
        )
        update = heuristic_agent_update(profile, round_result)
        updated = apply_agent_update(profile, update)

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
