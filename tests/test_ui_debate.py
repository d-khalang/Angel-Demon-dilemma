from angel_demon.models import Character, Round, RoundStatus, UserChoice, Verdict
from angel_demon.ui.debate import primary_action_label, round_history_label


def verdict() -> Verdict:
    return Verdict(
        winner=Character.SUNNY,
        reason="Clearer.",
        sunny_score=7,
        crowley_score=6,
        persuasion_tactics_sunny=["empathy"],
        persuasion_tactics_crowley=["pragmatism"],
        key_moment="Sunny answered directly.",
    )


def test_round_history_label_includes_status_and_preview() -> None:
    round_data = Round(
        round_number=3,
        dilemma="Should I tell a painful truth to someone I care about?",
        status=RoundStatus.ACTIVE,
    )

    label = round_history_label(round_data)

    assert label.startswith("R3 | Active |")
    assert "painful truth" in label


def test_primary_action_label_follows_round_status() -> None:
    active = Round(round_number=1, dilemma="Dilemma", status=RoundStatus.ACTIVE)
    judged = Round(
        round_number=1,
        dilemma="Dilemma",
        status=RoundStatus.JUDGED,
        verdict=verdict(),
    )
    decided = Round(
        round_number=1,
        dilemma="Dilemma",
        status=RoundStatus.DECIDED,
        verdict=verdict(),
        user_choice=UserChoice.FOLLOW_SUNNY,
    )

    assert primary_action_label(active) == "Continue debate"
    assert primary_action_label(judged) == "Choose your side"
    assert primary_action_label(decided) == "Start next dilemma"
