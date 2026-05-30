"""LLM provider abstraction and OpenAI Responses API implementation."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel

from angel_demon.config import Settings
from angel_demon.logging_config import get_logger

logger = get_logger("llm")


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


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        log_payloads: bool = False,
    ) -> None:
        if not api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is required.")
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "The openai package is not installed. Run `uv pip install -e .[dev]`."
            ) from exc

        self.model = model
        self.log_payloads = log_payloads
        self.client = AsyncOpenAI(api_key=api_key)
        logger.info("openai_provider_initialized model=%s", model)

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> str:
        return (await self.complete_with_usage(messages, temperature, max_output_tokens)).text

    async def complete_with_usage(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> LLMTextResult:
        instructions, input_messages = split_instructions(messages)
        self._log_request(
            "complete",
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        create = cast(Any, self.client.responses.create)
        start = time.perf_counter()
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
        text = cast(str, response.output_text)
        logger.info(
            "llm_complete_success model=%s latency_ms=%d output_chars=%d",
            self.model,
            int((time.perf_counter() - start) * 1000),
            len(text),
        )
        if self.log_payloads:
            logger.debug("llm_complete_response text=%r", text)
        return LLMTextResult(text=text, usage=extract_usage(response))

    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> AsyncIterator[str | LLMStreamChunk]:
        instructions, input_messages = split_instructions(messages)
        self._log_request(
            "stream",
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        create = cast(Any, self.client.responses.create)
        start = time.perf_counter()
        output_chars = 0
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
            usage = LLMUsage()
            async for event in stream:
                if getattr(event, "type", None) == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        output_chars += len(delta)
                        yield delta
                event_usage = extract_usage(event)
                if event_usage.input_tokens is not None or event_usage.output_tokens is not None:
                    usage = event_usage
                response = getattr(event, "response", None)
                if response is not None:
                    response_usage = extract_usage(response)
                    if (
                        response_usage.input_tokens is not None
                        or response_usage.output_tokens is not None
                    ):
                        usage = response_usage
            if usage.input_tokens is not None or usage.output_tokens is not None:
                yield LLMStreamChunk(usage=usage)
            logger.info(
                "llm_stream_success model=%s latency_ms=%d output_chars=%d",
                self.model,
                int((time.perf_counter() - start) * 1000),
                output_chars,
            )
        except Exception as exc:
            logger.exception("llm_stream_failed model=%s error=%s", self.model, exc)
            raise LLMError(str(exc)) from exc

    async def complete_json[T: BaseModel](
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        temperature: float = 0.5,
        max_output_tokens: int = 1024,
    ) -> T:
        instructions, input_messages = split_instructions(messages)
        self._log_request(
            f"complete_json:{schema.__name__}",
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        create = cast(Any, self.client.responses.create)
        start = time.perf_counter()
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
        usage = extract_usage(response)
        try:
            result = schema.model_validate_json(raw)
        except Exception:
            try:
                result = schema.model_validate(json.loads(raw))
            except Exception as json_exc:
                logger.exception(
                    "llm_complete_json_parse_failed model=%s schema=%s raw=%r",
                    self.model,
                    schema.__name__,
                    raw,
                )
                raise LLMParsingError(f"Could not parse structured output: {raw}") from json_exc
        logger.info(
            "llm_complete_json_success model=%s schema=%s latency_ms=%d output_chars=%d",
            self.model,
            schema.__name__,
            int((time.perf_counter() - start) * 1000),
            len(raw),
        )
        if self.log_payloads:
            logger.debug("llm_complete_json_response schema=%s raw=%r", schema.__name__, raw)
        return attach_usage(result, usage)

    async def _with_retries(self, call: Any, attempts: int = 3) -> Any:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await call()
            except Exception as exc:  # OpenAI SDK exception classes vary by version.
                last_error = exc
                logger.warning(
                    "llm_request_attempt_failed model=%s attempt=%d attempts=%d error=%s",
                    self.model,
                    attempt + 1,
                    attempts,
                    exc,
                )
                if attempt == attempts - 1:
                    break
                await asyncio.sleep(2**attempt)
        logger.error("llm_request_failed model=%s error=%s", self.model, last_error)
        raise LLMError(str(last_error)) from last_error

    def _log_request(
        self,
        call_type: str,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_output_tokens: int,
    ) -> None:
        logger.info(
            "llm_request_start type=%s model=%s input_tokens_estimate=%d "
            "temperature=%.2f max_output_tokens=%d",
            call_type,
            self.model,
            estimate_tokens(messages),
            temperature,
            max_output_tokens,
        )
        if self.log_payloads:
            safe_messages = [
                {"role": message.get("role"), "content": message.get("content")}
                for message in messages
            ]
            logger.debug("llm_request_payload type=%s messages=%r", call_type, safe_messages)


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
        return (await self.complete_with_usage(messages, temperature, max_output_tokens)).text

    async def complete_with_usage(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.8,
        max_output_tokens: int = 1024,
    ) -> LLMTextResult:
        text = next(self._responses)
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
        text = next(self._responses)
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
        raw = next(self._responses)
        try:
            result = schema.model_validate_json(raw)
        except Exception as exc:
            raise LLMParsingError(f"Could not parse mock structured output: {raw}") from exc
        return attach_usage(
            result,
            LLMUsage(
                input_tokens=estimate_tokens(messages),
                output_tokens=max(1, len(raw) // 4),
            ),
        )


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai":
        return OpenAIProvider(
            settings.openai_api_key,
            settings.openai_model,
            log_payloads=settings.log_llm_payloads,
        )
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
    result = await provider.complete_with_usage(messages, temperature, max_output_tokens)
    latency_ms = int((time.perf_counter() - start) * 1000)
    return TimedCall(
        text=result.text,
        latency_ms=latency_ms,
        input_tokens=result.usage.input_tokens or estimate_tokens(messages),
        output_tokens=result.usage.output_tokens or max(1, len(result.text) // 4),
    )
