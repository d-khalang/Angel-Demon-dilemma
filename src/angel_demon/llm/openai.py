"""OpenAI Responses API adapter."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from pydantic import BaseModel

from angel_demon.llm.core import (
    LLMConfigurationError,
    LLMError,
    LLMParsingError,
    LLMProvider,
    LLMStreamChunk,
    LLMTextResult,
    LLMUsage,
    attach_usage,
    estimate_tokens,
    extract_usage,
    split_instructions,
    to_strict_json_schema,
)
from angel_demon.logging_config import get_logger

logger = get_logger("llm")

OpenAIAsyncClient: Any
try:
    from openai import AsyncOpenAI
except ImportError:
    OpenAIAsyncClient = None
else:
    OpenAIAsyncClient = AsyncOpenAI


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
        if OpenAIAsyncClient is None:
            raise LLMConfigurationError(
                "The openai package is not installed. Run `uv pip install -e .[dev]`."
            )

        self.model = model
        self.log_payloads = log_payloads
        self.client = OpenAIAsyncClient(api_key=api_key)
        logger.info("openai_provider_initialized model=%s", model)

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
                usage = self._event_usage(event, usage)
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

    @staticmethod
    def _event_usage(event: Any, current: LLMUsage) -> LLMUsage:
        event_usage = extract_usage(event)
        if event_usage.input_tokens is not None or event_usage.output_tokens is not None:
            current = event_usage
        response = getattr(event, "response", None)
        if response is None:
            return current
        response_usage = extract_usage(response)
        if (
            response_usage.input_tokens is not None
            or response_usage.output_tokens is not None
        ):
            return response_usage
        return current

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
                raise LLMParsingError(
                    f"Could not parse structured output: {raw}"
                ) from json_exc
        logger.info(
            "llm_complete_json_success model=%s schema=%s latency_ms=%d output_chars=%d",
            self.model,
            schema.__name__,
            int((time.perf_counter() - start) * 1000),
            len(raw),
        )
        if self.log_payloads:
            logger.debug(
                "llm_complete_json_response schema=%s raw=%r",
                schema.__name__,
                raw,
            )
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
                {
                    "role": message.get("role"),
                    "content": message.get("content"),
                }
                for message in messages
            ]
            logger.debug(
                "llm_request_payload type=%s messages=%r",
                call_type,
                safe_messages,
            )
