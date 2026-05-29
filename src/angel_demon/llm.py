"""LLM provider abstraction and OpenAI Responses API implementation."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from angel_demon.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMParsingError(LLMError):
    pass


class LLMConfigurationError(LLMError):
    pass


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    text = " ".join(message.get("content", "") for message in messages)
    return max(1, len(text) // 4)


def split_instructions(messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, str]]]:
    instructions = "\n\n".join(
        m["content"] for m in messages if m["role"] in {"system", "developer"}
    )
    inputs = [m for m in messages if m["role"] not in {"system", "developer"}]
    return instructions or None, inputs


class LLMProvider:
    model: str

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> str:
        raise NotImplementedError

    def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float = 0.5,
        max_output_tokens: int = 1024,
    ) -> T:
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str | None, model: str) -> None:
        if not api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is required.")
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "The openai package is not installed. Run `uv pip install -e .[dev]`."
            ) from exc

        self.model = model
        self.client = AsyncOpenAI(api_key=api_key)

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> str:
        instructions, input_messages = split_instructions(messages)
        create = cast(Any, self.client.responses.create)
        response = await self._with_retries(
            lambda: create(
                model=self.model,
                instructions=instructions,
                input=input_messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                text={"format": {"type": "text"}},
            )
        )
        return cast(str, response.output_text)

    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        instructions, input_messages = split_instructions(messages)
        create = cast(Any, self.client.responses.create)
        stream = await self._with_retries(
            lambda: create(
                model=self.model,
                instructions=instructions,
                input=input_messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                text={"format": {"type": "text"}},
                stream=True,
            )
        )
        try:
            async for event in stream:
                if getattr(event, "type", None) == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta
        except Exception as exc:
            raise LLMError(str(exc)) from exc

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float = 0.5,
        max_output_tokens: int = 1024,
    ) -> T:
        instructions, input_messages = split_instructions(messages)
        create = cast(Any, self.client.responses.create)
        response = await self._with_retries(
            lambda: create(
                model=self.model,
                instructions=instructions,
                input=input_messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema.__name__,
                        "schema": to_strict_json_schema(schema.model_json_schema()),
                        "strict": True,
                    }
                },
            )
        )
        raw = response.output_text
        try:
            return schema.model_validate_json(raw)
        except Exception:
            try:
                return schema.model_validate(json.loads(raw))
            except Exception as json_exc:
                raise LLMParsingError(f"Could not parse structured output: {raw}") from json_exc

    async def _with_retries(self, call: Any, attempts: int = 3) -> Any:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await call()
            except Exception as exc:  # OpenAI SDK exception classes vary by version.
                last_error = exc
                if attempt == attempts - 1:
                    break
                await asyncio.sleep(2**attempt)
        raise LLMError(str(last_error)) from last_error


class MockLLMProvider(LLMProvider):
    """Deterministic provider for tests and local non-API demos."""

    def __init__(self, responses: list[str] | None = None, model: str = "mock") -> None:
        self._responses = iter(responses or [])
        self.model = model

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> str:
        return next(self._responses)

    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        text = next(self._responses)
        for word in text.split():
            yield word + " "

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float = 0.5,
        max_output_tokens: int = 1024,
    ) -> T:
        raw = next(self._responses)
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:
            raise LLMParsingError(f"Could not parse mock structured output: {raw}") from exc


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai":
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    if settings.llm_provider == "mock":
        return MockLLMProvider()
    raise ValueError(f"Unknown provider: {settings.llm_provider}")


def to_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Adapt Pydantic JSON Schema for OpenAI strict structured outputs."""
    strict_schema = deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            node.pop("title", None)
            if node.get("type") == "object":
                properties = node.get("properties", {})
                node["additionalProperties"] = False
                node["required"] = list(properties.keys())
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(strict_schema)
    return strict_schema


class TimedCall(BaseModel):
    text: str
    latency_ms: int
    input_tokens: int
    output_tokens: int


async def timed_complete(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_output_tokens: int,
) -> TimedCall:
    start = time.perf_counter()
    text = await provider.complete(messages, temperature, max_output_tokens)
    latency_ms = int((time.perf_counter() - start) * 1000)
    return TimedCall(
        text=text,
        latency_ms=latency_ms,
        input_tokens=estimate_tokens(messages),
        output_tokens=max(1, len(text) // 4),
    )
