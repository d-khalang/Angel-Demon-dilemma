"""Stable public facade for LLM contracts and provider implementations."""

from __future__ import annotations

# Kept public for compatibility with tests that replace asyncio.sleep during retries.
import asyncio as asyncio

from angel_demon.config import Settings, normalize_llm_provider
from angel_demon.llm.core import (
    LLMConfigurationError,
    LLMError,
    LLMParsingError,
    LLMProvider,
    LLMStreamChunk,
    LLMTextResult,
    LLMUsage,
    TimedCall,
    attach_usage,
    estimate_tokens,
    extract_usage,
    get_attached_usage,
    split_instructions,
    timed_complete,
    to_strict_json_schema,
)
from angel_demon.llm.mock import MockLLMProvider
from angel_demon.llm.openai import OpenAIProvider

__all__ = [
    "LLMConfigurationError",
    "LLMError",
    "LLMParsingError",
    "LLMProvider",
    "LLMStreamChunk",
    "LLMTextResult",
    "LLMUsage",
    "MockLLMProvider",
    "OpenAIProvider",
    "TimedCall",
    "attach_usage",
    "create_llm_provider",
    "estimate_tokens",
    "extract_usage",
    "get_attached_usage",
    "split_instructions",
    "timed_complete",
    "to_strict_json_schema",
]


def create_llm_provider(settings: Settings) -> LLMProvider:
    provider_name = normalize_llm_provider(settings.llm_provider)
    if provider_name == "openai":
        return OpenAIProvider(
            settings.openai_api_key,
            settings.openai_model,
            log_payloads=settings.log_llm_payloads,
        )
    if provider_name == "mock":
        return MockLLMProvider()
    raise ValueError(f"Unknown provider: {provider_name!r}")
