"""Character generation helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator

from angel_demon.llm import LLMProvider, LLMStreamChunk
from angel_demon.models import AgentProfile, Character, Opening, Rebuttal, Round, UserProfile
from angel_demon.prompts import character_instructions, opening_input, rebuttal_input


def _opponent(character: Character) -> Character:
    return Character.CROWLEY if character == Character.SUNNY else Character.SUNNY


def build_opening_messages(
    character: Character,
    dilemma: str,
    user_profile: UserProfile,
    agent_profile: AgentProfile,
    opponent_profile: AgentProfile,
    round_history: list[Round],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": character_instructions(
                character,
                user_profile,
                agent_profile,
                opponent_profile,
            ),
        },
        {"role": "user", "content": opening_input(dilemma, round_history)},
    ]


def build_rebuttal_messages(
    character: Character,
    dilemma: str,
    own_opening: Opening,
    opponent_opening: Opening,
    user_profile: UserProfile,
    agent_profile: AgentProfile,
    opponent_profile: AgentProfile,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": character_instructions(
                character,
                user_profile,
                agent_profile,
                opponent_profile,
            ),
        },
        {
            "role": "user",
            "content": rebuttal_input(
                dilemma,
                own_opening.argument,
                opponent_opening.argument,
            ),
        },
    ]


async def generate_opening_stream(
    character: Character,
    dilemma: str,
    user_profile: UserProfile,
    agent_profile: AgentProfile,
    opponent_profile: AgentProfile,
    round_history: list[Round],
    llm: LLMProvider,
    *,
    temperature: float,
    max_output_tokens: int = 700,
) -> AsyncIterator[str]:
    messages = build_opening_messages(
        character,
        dilemma,
        user_profile,
        agent_profile,
        opponent_profile,
        round_history,
    )
    async for chunk in llm.stream(messages, temperature, max_output_tokens):
        if isinstance(chunk, LLMStreamChunk):
            continue
        yield chunk


async def generate_rebuttal_stream(
    character: Character,
    dilemma: str,
    own_opening: Opening,
    opponent_opening: Opening,
    user_profile: UserProfile,
    agent_profile: AgentProfile,
    opponent_profile: AgentProfile,
    llm: LLMProvider,
    *,
    temperature: float,
    max_output_tokens: int = 500,
) -> AsyncIterator[str]:
    messages = build_rebuttal_messages(
        character,
        dilemma,
        own_opening,
        opponent_opening,
        user_profile,
        agent_profile,
        opponent_profile,
    )
    async for chunk in llm.stream(messages, temperature, max_output_tokens):
        if isinstance(chunk, LLMStreamChunk):
            continue
        yield chunk


def make_opening(character: Character, argument: str) -> Opening:
    return Opening(character=character, argument=argument.strip())


def make_rebuttal(character: Character, argument: str) -> Rebuttal:
    return Rebuttal(character=character, argument=argument.strip())
