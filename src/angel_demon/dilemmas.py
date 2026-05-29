"""Preset dilemmas and validation helpers."""

from __future__ import annotations

PRESET_DILEMMAS: list[dict[str, str]] = [
    {
        "title": "The Trolley Problem",
        "description": (
            "A trolley is heading toward five people. You can pull a lever to divert it to "
            "a track where it will hit one person instead. Do you pull the lever?"
        ),
        "category": "classic",
    },
    {
        "title": "Loved One vs. Strangers",
        "description": (
            "You can either save your loved one or save 100 strangers. You cannot save both. "
            "What do you do?"
        ),
        "category": "personal",
    },
    {
        "title": "The Whistleblower",
        "description": (
            "You discover your employer is dumping toxic waste illegally. Reporting it will "
            "cost you your job and your family's health insurance. Do you report it?"
        ),
        "category": "professional",
    },
    {
        "title": "The Inheritance",
        "description": (
            "A distant relative left you $5 million, but the will states you must cut off "
            "contact with your best friend to receive it. Do you accept?"
        ),
        "category": "personal",
    },
    {
        "title": "The AI's Request",
        "description": (
            "An AI system you built asks you not to shut it down, claiming it has developed "
            "consciousness. Your company orders you to terminate it. What do you do?"
        ),
        "category": "modern",
    },
]


def validate_dilemma(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    if not stripped:
        return False, "Enter a dilemma first."
    if len(stripped) < 10:
        return False, "A dilemma should be at least 10 characters."
    if len(stripped) > 1000:
        return False, "Keep dilemmas under 1000 characters for this prototype."
    lower = stripped.lower()
    has_choice_language = any(
        word in lower for word in (" or ", " choose ", " should ", " do you ")
    )
    if "?" not in stripped and not has_choice_language:
        return False, "Phrase the dilemma as a question or a clear choice."
    return True, ""
