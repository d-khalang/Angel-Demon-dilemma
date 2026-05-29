from angel_demon.models import Character, UserChoice, Verdict
from angel_demon.scoring import apply_alignment_delta, calculate_alignment_delta, get_alignment_zone


def verdict(winner: Character) -> Verdict:
    return Verdict(
        winner=winner,
        reason="Strong argument.",
        sunny_score=6 if winner == Character.SUNNY else 5,
        crowley_score=6 if winner == Character.CROWLEY else 5,
        persuasion_tactics_sunny=["empathy"],
        persuasion_tactics_crowley=["self-interest"],
        key_moment="The rebuttal landed.",
    )


def test_calculate_alignment_delta_user_and_judge_agree() -> None:
    assert calculate_alignment_delta(UserChoice.FOLLOW_SUNNY, verdict(Character.SUNNY)) == 18
    assert calculate_alignment_delta(UserChoice.FOLLOW_CROWLEY, verdict(Character.CROWLEY)) == -18


def test_calculate_alignment_delta_user_and_judge_disagree() -> None:
    assert calculate_alignment_delta(UserChoice.FOLLOW_CROWLEY, verdict(Character.SUNNY)) == -12
    assert calculate_alignment_delta(UserChoice.UNDECIDED, verdict(Character.CROWLEY)) == -3


def test_apply_alignment_delta_clamps() -> None:
    assert apply_alignment_delta(95, 18) == 100
    assert apply_alignment_delta(-95, -18) == -100


def test_alignment_zones() -> None:
    assert get_alignment_zone(-80).value == "deep_hell"
    assert get_alignment_zone(-40).value == "hell"
    assert get_alignment_zone(0).value == "neutral"
    assert get_alignment_zone(40).value == "heaven"
    assert get_alignment_zone(80).value == "deep_heaven"
