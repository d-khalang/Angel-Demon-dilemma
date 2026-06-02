from angel_demon.models import Character, Round, UserChoice, Verdict
from angel_demon.ui.sidebar import _judge_badge, _user_choice_badge


def _verdict(winner: Character) -> Verdict:
    return Verdict(
        winner=winner,
        reason="reason",
        sunny_score=7,
        crowley_score=6,
        key_moment="moment",
    )


def test_user_choice_badge_prioritizes_user_decision() -> None:
    assert (
        _user_choice_badge(
            Round(
                round_number=1,
                dilemma="dilemma",
                verdict=_verdict(Character.CROWLEY),
                user_choice=UserChoice.FOLLOW_SUNNY,
            )
        )
        == "You chose \U0001f47c Sunny"
    )
    assert (
        _user_choice_badge(
            Round(
                round_number=1,
                dilemma="dilemma",
                verdict=_verdict(Character.SUNNY),
                user_choice=UserChoice.FOLLOW_CROWLEY,
            )
        )
        == "You chose \U0001f608 Crowley"
    )
    assert (
        _user_choice_badge(
            Round(
                round_number=1,
                dilemma="dilemma",
                user_choice=UserChoice.UNDECIDED,
            )
        )
        == "You chose \u2696\ufe0f Undecided"
    )


def test_judge_badge_is_secondary_context() -> None:
    assert _judge_badge(Round(round_number=1, dilemma="dilemma")) == "Judge pending"
    assert (
        _judge_badge(
            Round(
                round_number=1,
                dilemma="dilemma",
                verdict=_verdict(Character.SUNNY),
            )
        )
        == "Judge: \U0001f47c Sunny"
    )
