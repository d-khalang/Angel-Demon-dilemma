"""Provider-independent LLM contracts and utilities."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


class LLMError(Exception):
    pass


class LLMParsingError(LLMError):
    pass


class LLMConfigurationError(LLMError):
    pass


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    text = " ".join(message.get("content", "") for message in messages)
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class LLMStreamChunk:
    text: str = ""
    usage: LLMUsage | None = None


@dataclass(frozen=True)
class LLMTextResult:
    text: str
    usage: LLMUsage


def extract_usage(response: Any) -> LLMUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return LLMUsage()
    input_tokens = getattr(usage, "prompt_tokens", None)
    if input_tokens is None:
        input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "completion_tokens", None)
    if output_tokens is None:
        output_tokens = getattr(usage, "output_tokens", None)
    return LLMUsage(input_tokens=input_tokens, output_tokens=output_tokens)


def attach_usage[T: BaseModel](result: T, usage: LLMUsage) -> T:
    object.__setattr__(result, "__llm_usage__", usage)
    return result


def get_attached_usage(result: Any) -> LLMUsage:
    usage = getattr(result, "__llm_usage__", None)
    return usage if isinstance(usage, LLMUsage) else LLMUsage()


def split_instructions(
    messages: list[dict[str, str]],
) -> tuple[str | None, list[dict[str, str]]]:
    instructions = "\n\n".join(
        message["content"]
        for message in messages
        if message["role"] in {"system", "developer"}
    )
    inputs = [
        message
        for message in messages
        if message["role"] not in {"system", "developer"}
    ]
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

    async def complete_with_usage(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> LLMTextResult:
        text = await self.complete(messages, temperature, max_output_tokens)
        return LLMTextResult(
            text=text,
            usage=LLMUsage(
                input_tokens=estimate_tokens(messages),
                output_tokens=max(1, len(text) // 4),
            ),
        )

    def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> AsyncIterator[str | LLMStreamChunk]:
        raise NotImplementedError

    async def complete_json[T: BaseModel](
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float = 0.5,
        max_output_tokens: int = 1024,
    ) -> T:
        raise NotImplementedError


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
    result = await provider.complete_with_usage(
        messages,
        temperature,
        max_output_tokens,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    return TimedCall(
        text=result.text,
        latency_ms=latency_ms,
        input_tokens=result.usage.input_tokens or estimate_tokens(messages),
        output_tokens=result.usage.output_tokens or max(1, len(result.text) // 4),
    )
