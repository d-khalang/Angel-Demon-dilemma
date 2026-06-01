from angel_demon.models import AgentProfile, Character, ResponseTarget, UserProfile
from angel_demon.prompts import (
    character_instructions,
    conversation_turn_input,
    opening_input,
    rebuttal_input,
)


def test_character_prompts_have_distinct_value_frames() -> None:
    user_profile = UserProfile()
    sunny_profile = AgentProfile(character=Character.SUNNY)
    crowley_profile = AgentProfile(character=Character.CROWLEY)

    sunny = character_instructions(
        Character.SUNNY,
        user_profile,
        sunny_profile,
        crowley_profile,
    )
    crowley = character_instructions(
        Character.CROWLEY,
        user_profile,
        crowley_profile,
        sunny_profile,
    )

    assert "conscience, sacrifice, mercy, accountability" in sunny
    assert "protects conscience" in sunny
    assert "Do not drift into Crowley's frame" in sunny
    assert "appetite, self-preservation, ambition" in crowley
    assert "maximizes the user" in crowley
    assert "freedom, power, comfort" in crowley
    assert "Do not drift into Sunny's frame" in crowley


def test_prompt_inputs_require_concrete_sides_and_direct_clash() -> None:
    opening = opening_input("Should I expose a friend's lie?", [])
    rebuttal = rebuttal_input("Dilemma", "Own case", "Opponent case")
    turn = conversation_turn_input(
        "Dilemma",
        [],
        Character.SUNNY,
        target=ResponseTarget.BOTH,
        recent_rounds=[],
    )

    assert "Declare the concrete side" in opening
    assert "Do not hedge toward the opponent's answer" in opening
    assert "live clash" in rebuttal
    assert "Keep the rivalry alive" in turn


def test_character_prompts_allow_optional_markdown_and_questions() -> None:
    prompt = character_instructions(
        Character.CROWLEY,
        UserProfile(),
        AgentProfile(character=Character.CROWLEY),
        AgentProfile(character=Character.SUNNY),
    )

    assert "light Markdown emphasis" in prompt
    assert "Decide for yourself when to use it" in prompt
    assert "do not default" in prompt
    assert "bullets, headings, tables" in prompt
    assert "pointed question" in prompt
    assert "opponent currently has more pull" in prompt
    assert "Use questions sparingly" in prompt
