"""Alignment and promotion scoring."""

from __future__ import annotations

from angel_demon.models import AgentProfile, AlignmentZone, Character, Round, UserChoice, Verdict


def calculate_alignment_delta(user_choice: UserChoice, verdict: Verdict) -> int:
    delta = 0
    if user_choice == UserChoice.FOLLOW_SUNNY:
        delta += 15
    elif user_choice == UserChoice.FOLLOW_CROWLEY:
        delta -= 15

    delta += 3 if verdict.winner == Character.SUNNY else -3
    return delta


def apply_alignment_delta(current_score: int, delta: int) -> int:
    return max(-100, min(100, current_score + delta))


def get_alignment_zone(score: int) -> AlignmentZone:
    if score <= -61:
        return AlignmentZone.DEEP_HELL
    if score <= -21:
        return AlignmentZone.HELL
    if score <= 20:
        return AlignmentZone.NEUTRAL
    if score <= 60:
        return AlignmentZone.HEAVEN
    return AlignmentZone.DEEP_HEAVEN


def get_promotion_leader(
    sunny_profile: AgentProfile,
    crowley_profile: AgentProfile,
) -> Character | None:
    if sunny_profile.wins > crowley_profile.wins:
        return Character.SUNNY
    if crowley_profile.wins > sunny_profile.wins:
        return Character.CROWLEY
    return None


def calculate_session_alignment(rounds: list[Round]) -> int:
    score = 0
    for round_data in rounds:
        if round_data.user_choice is None or round_data.verdict is None:
            continue
        score = apply_alignment_delta(
            score,
            calculate_alignment_delta(round_data.user_choice, round_data.verdict),
        )
    return score


def calculate_choice_records(rounds: list[Round]) -> tuple[int, int, int, int]:
    sunny_wins = 0
    sunny_losses = 0
    crowley_wins = 0
    crowley_losses = 0
    for round_data in rounds:
        if round_data.user_choice == UserChoice.FOLLOW_SUNNY:
            sunny_wins += 1
            crowley_losses += 1
        elif round_data.user_choice == UserChoice.FOLLOW_CROWLEY:
            crowley_wins += 1
            sunny_losses += 1
    return sunny_wins, sunny_losses, crowley_wins, crowley_losses


def calculate_judge_laurels(rounds: list[Round]) -> tuple[int, int]:
    sunny = 0
    crowley = 0
    for round_data in rounds:
        if round_data.verdict is None:
            continue
        if round_data.verdict.winner == Character.SUNNY:
            sunny += 1
        else:
            crowley += 1
    return sunny, crowley


def calculate_conversion_streak(rounds: list[Round]) -> tuple[Character | None, int]:
    streak_owner: Character | None = None
    streak = 0
    for round_data in reversed(rounds):
        if round_data.user_choice == UserChoice.FOLLOW_SUNNY:
            character = Character.SUNNY
        elif round_data.user_choice == UserChoice.FOLLOW_CROWLEY:
            character = Character.CROWLEY
        else:
            break

        if streak_owner is None:
            streak_owner = character
        if character != streak_owner:
            break
        streak += 1
    return streak_owner, streak
