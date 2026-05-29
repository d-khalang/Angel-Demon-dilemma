"""Domain models for the Angel vs Demon debate app."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Character(StrEnum):
    SUNNY = "sunny"
    CROWLEY = "crowley"


class UserChoice(StrEnum):
    FOLLOW_SUNNY = "follow_sunny"
    FOLLOW_CROWLEY = "follow_crowley"
    UNDECIDED = "undecided"


class AlignmentZone(StrEnum):
    DEEP_HELL = "deep_hell"
    HELL = "hell"
    NEUTRAL = "neutral"
    HEAVEN = "heaven"
    DEEP_HEAVEN = "deep_heaven"


class Opening(BaseModel):
    character: Character
    argument: str


class Rebuttal(BaseModel):
    character: Character
    argument: str


class Verdict(BaseModel):
    winner: Character
    reason: str
    sunny_score: int = Field(ge=1, le=10)
    crowley_score: int = Field(ge=1, le=10)
    persuasion_tactics_sunny: list[str] = Field(default_factory=list)
    persuasion_tactics_crowley: list[str] = Field(default_factory=list)
    key_moment: str
    safety_notes: str | None = None
    is_fallback: bool = False


class Round(BaseModel):
    round_number: int
    dilemma: str
    sunny_opening: Opening
    crowley_opening: Opening
    sunny_rebuttal: Rebuttal
    crowley_rebuttal: Rebuttal
    verdict: Verdict
    user_choice: UserChoice | None = None
    alignment_delta: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserProfile(BaseModel):
    inferred_values: list[str] = Field(default_factory=list)
    decision_history: list[UserChoice] = Field(default_factory=list)
    vulnerability_to_sunny: float = Field(default=0.5, ge=0.0, le=1.0)
    vulnerability_to_crowley: float = Field(default=0.5, ge=0.0, le=1.0)
    recent_themes: list[str] = Field(default_factory=list)
    notes: str = "No data yet. First interaction."


class AgentProfile(BaseModel):
    character: Character
    successful_tactics: list[str] = Field(default_factory=list)
    failed_tactics: list[str] = Field(default_factory=list)
    opponent_winning_tactics: list[str] = Field(default_factory=list)
    adaptation_notes: str = "First round. Use default personality and tactics."
    wins: int = 0
    losses: int = 0


class SessionState(BaseModel):
    session_id: str
    rounds: list[Round] = Field(default_factory=list)
    alignment_score: int = 0
    user_profile: UserProfile = Field(default_factory=UserProfile)
    sunny_profile: AgentProfile = Field(
        default_factory=lambda: AgentProfile(character=Character.SUNNY)
    )
    crowley_profile: AgentProfile = Field(
        default_factory=lambda: AgentProfile(character=Character.CROWLEY)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserProfileUpdate(BaseModel):
    inferred_values: list[str] = Field(default_factory=list)
    vulnerability_to_sunny: float = Field(ge=0.0, le=1.0)
    vulnerability_to_crowley: float = Field(ge=0.0, le=1.0)
    recent_themes: list[str] = Field(default_factory=list)
    notes: str


class AgentProfileUpdate(BaseModel):
    successful_tactics: list[str] = Field(default_factory=list)
    failed_tactics: list[str] = Field(default_factory=list)
    opponent_winning_tactics: list[str] = Field(default_factory=list)
    adaptation_notes: str
