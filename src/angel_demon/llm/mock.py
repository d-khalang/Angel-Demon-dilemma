"""Deterministic LLM provider for tests and local demos."""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import BaseModel

from angel_demon.llm.core import (
    LLMParsingError,
    LLMProvider,
    LLMStreamChunk,
    LLMTextResult,
    LLMUsage,
    attach_usage,
    estimate_tokens,
    split_instructions,
)


class MockLLMProvider(LLMProvider):
    def __init__(
        self,
        responses: list[str] | None = None,
        model: str = "mock",
    ) -> None:
        self._responses = iter(responses) if responses is not None else None
        self.model = model

    def _next_text(self, messages: list[dict[str, str]]) -> str:
        if self._responses is not None:
            return next(self._responses)
        instructions, _ = split_instructions(messages)
        if instructions and "You are Crowley" in instructions:
            return "Crowley argues for self-interest, leverage, and the practical advantage."
        if instructions and "You are Sunny" in instructions:
            return "Sunny argues for empathy, accountability, and the long-term good."
        return "A deterministic mock response."

    def _default_structured_result[T: BaseModel](
        self,
        schema: type[T],
        messages: list[dict[str, str]],
    ) -> T:
        if schema.__name__ == "Verdict":
            return schema.model_validate(
                {
                    "winner": "sunny",
                    "reason": "Sunny made the more coherent case.",
                    "sunny_score": 8,
                    "crowley_score": 7,
                    "persuasion_tactics_sunny": ["empathy"],
                    "persuasion_tactics_crowley": ["pragmatism"],
                    "key_moment": "Sunny connected the choice to its long-term consequences.",
                    "safety_notes": None,
                    "is_fallback": False,
                }
            )
        if schema.__name__ == "SessionMemoryUpdate":
            prompt = "\n".join(message.get("content", "") for message in messages)
            followed_crowley = '"user_choice": "follow_crowley"' in prompt
            user_value = "self-preservation" if followed_crowley else "empathy"
            sunny_vulnerability = 0.4 if followed_crowley else 0.6
            crowley_vulnerability = 0.6 if followed_crowley else 0.4
            return schema.model_validate(
                {
                    "user_update": {
                        "inferred_values": [user_value],
                        "vulnerability_to_sunny": sunny_vulnerability,
                        "vulnerability_to_crowley": crowley_vulnerability,
                        "recent_themes": ["moral tradeoff"],
                        "notes": "Deterministic mock memory.",
                    },
                    "sunny_update": {
                        "successful_tactics": ["empathy"],
                        "failed_tactics": [],
                        "opponent_winning_tactics": [],
                        "adaptation_notes": "Continue connecting choices to consequences.",
                    },
                    "crowley_update": {
                        "successful_tactics": [],
                        "failed_tactics": ["pragmatism"],
                        "opponent_winning_tactics": ["empathy"],
                        "adaptation_notes": "Counter the user's concern for consequences.",
                    },
                }
            )
        raise LLMParsingError(
            f"No default mock response for schema: {schema.__name__}"
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> str:
        result = await self.complete_with_usage(
            messages,
            temperature,
            max_output_tokens,
        )
        return result.text

    async def complete_with_usage(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> LLMTextResult:
        text = self._next_text(messages)
        return LLMTextResult(
            text=text,
            usage=LLMUsage(
                input_tokens=estimate_tokens(messages),
                output_tokens=max(1, len(text) // 4),
            ),
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> AsyncIterator[str | LLMStreamChunk]:
        text = self._next_text(messages)
        for word in text.split():
            yield word + " "
        yield LLMStreamChunk(
            usage=LLMUsage(
                input_tokens=estimate_tokens(messages),
                output_tokens=max(1, len(text) // 4),
            )
        )

    async def complete_json[T: BaseModel](
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float = 0.5,
        max_output_tokens: int = 1024,
    ) -> T:
        if self._responses is None:
            result = self._default_structured_result(schema, messages)
            raw = result.model_dump_json()
        else:
            raw = next(self._responses)
            try:
                result = schema.model_validate_json(raw)
            except Exception as exc:
                raise LLMParsingError(
                    f"Could not parse mock structured output: {raw}"
                ) from exc
        return attach_usage(
            result,
            LLMUsage(
                input_tokens=estimate_tokens(messages),
                output_tokens=max(1, len(raw) // 4),
            ),
        )
