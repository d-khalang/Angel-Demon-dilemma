"""Deterministic rules for applying and rebuilding adaptive memory."""

from __future__ import annotations

from angel_demon.models import (
    AgentProfile,
    AgentProfileUpdate,
    Character,
    Round,
    UserChoice,
    UserProfile,
    UserProfileUpdate,
)


def dedupe(values: list[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(value.strip())
    return result[:limit]


def decision_history(
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


def apply_user_update(
    profile: UserProfile,
    round_result: Round,
    update: UserProfileUpdate,
    *,
    include_round_choice: bool,
) -> UserProfile:
    return UserProfile(
        inferred_values=dedupe(update.inferred_values),
        decision_history=decision_history(
            profile,
            round_result,
            include_round_choice=include_round_choice,
        ),
        vulnerability_to_sunny=update.vulnerability_to_sunny,
        vulnerability_to_crowley=update.vulnerability_to_crowley,
        recent_themes=dedupe(update.recent_themes, limit=5),
        notes=update.notes,
    )


def apply_agent_update(
    profile: AgentProfile,
    update: AgentProfileUpdate,
) -> AgentProfile:
    return AgentProfile(
        character=profile.character,
        successful_tactics=dedupe(update.successful_tactics),
        failed_tactics=dedupe(update.failed_tactics),
        opponent_winning_tactics=dedupe(update.opponent_winning_tactics),
        adaptation_notes=update.adaptation_notes,
        wins=profile.wins,
        losses=profile.losses,
    )


def enforce_round_outcome(
    profile: AgentProfile,
    round_result: Round,
    update: AgentProfileUpdate,
) -> AgentProfileUpdate:
    if round_result.verdict is None:
        return update

    own_tactics, opponent_tactics = tactics_for(profile, round_result)
    won = followed_character(profile.character, round_result.user_choice)
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
        successful_tactics=dedupe(successful),
        failed_tactics=dedupe(failed),
        opponent_winning_tactics=dedupe(opponent_winning),
        adaptation_notes=update.adaptation_notes,
    )


def heuristic_user_update(
    profile: UserProfile,
    round_result: Round,
    *,
    include_round_choice: bool,
) -> UserProfileUpdate:
    choices = decision_history(
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
        inferred_values=dedupe([*profile.inferred_values, *new_values]),
        vulnerability_to_sunny=sunny_vulnerability,
        vulnerability_to_crowley=crowley_vulnerability,
        recent_themes=dedupe([*profile.recent_themes, "moral tradeoff"], limit=5),
        notes=f"Fallback memory update after round {round_result.round_number}.",
    )


def heuristic_agent_update(
    profile: AgentProfile,
    round_result: Round,
) -> AgentProfileUpdate:
    if round_result.verdict is None:
        raise ValueError("Cannot update agent memory before a round has a verdict.")

    own_tactics, opponent_tactics = tactics_for(profile, round_result)
    won = followed_character(profile.character, round_result.user_choice)
    return AgentProfileUpdate(
        successful_tactics=dedupe(
            [*profile.successful_tactics, *(own_tactics if won else [])]
        ),
        failed_tactics=dedupe(
            [*profile.failed_tactics, *(own_tactics if not won else [])]
        ),
        opponent_winning_tactics=dedupe(
            [*profile.opponent_winning_tactics, *(opponent_tactics if not won else [])]
        ),
        adaptation_notes=(
            "Repeat the tactics that won this user over."
            if won
            else "Adjust by countering the opponent's most persuasive tactics more directly."
        ),
    )


def tactics_for(
    profile: AgentProfile,
    round_result: Round,
) -> tuple[list[str], list[str]]:
    if round_result.verdict is None:
        raise ValueError("Cannot read tactics before a round has a verdict.")
    if profile.character == Character.SUNNY:
        return (
            round_result.verdict.persuasion_tactics_sunny,
            round_result.verdict.persuasion_tactics_crowley,
        )
    return (
        round_result.verdict.persuasion_tactics_crowley,
        round_result.verdict.persuasion_tactics_sunny,
    )


def followed_character(
    character: Character,
    user_choice: UserChoice | None,
) -> bool:
    if character == Character.SUNNY:
        return user_choice == UserChoice.FOLLOW_SUNNY
    return user_choice == UserChoice.FOLLOW_CROWLEY


def rebuild_session_memory(
    rounds: list[Round],
) -> tuple[UserProfile, AgentProfile, AgentProfile]:
    """Rebuild profiles from durable decisions when a vote changes or is invalidated."""
    user_profile = UserProfile()
    sunny_profile = AgentProfile(character=Character.SUNNY)
    crowley_profile = AgentProfile(character=Character.CROWLEY)
    decided_rounds = [
        round_data
        for round_data in rounds
        if round_data.verdict is not None and round_data.user_choice is not None
    ]
    for round_data in decided_rounds:
        user_profile = apply_user_update(
            user_profile,
            round_data,
            heuristic_user_update(
                user_profile,
                round_data,
                include_round_choice=True,
            ),
            include_round_choice=True,
        )
        sunny_profile = apply_agent_update(
            sunny_profile,
            heuristic_agent_update(sunny_profile, round_data),
        )
        crowley_profile = apply_agent_update(
            crowley_profile,
            heuristic_agent_update(crowley_profile, round_data),
        )
    return user_profile, sunny_profile, crowley_profile
