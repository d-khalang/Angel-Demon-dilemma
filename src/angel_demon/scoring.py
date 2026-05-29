"""Alignment and promotion scoring."""

from __future__ import annotations

from angel_demon.models import AgentProfile, AlignmentZone, Character, UserChoice, Verdict


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
