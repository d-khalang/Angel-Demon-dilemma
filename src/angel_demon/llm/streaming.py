"""Streaming collection and usage accounting for workflow orchestration."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable

from angel_demon.llm.core import LLMStreamChunk, LLMUsage, estimate_tokens
from angel_demon.logging_config import get_logger

ChunkCallback = Callable[[str, str], None]
logger = get_logger("flow")


async def collect_stream(
    role: str,
    stream: AsyncIterator[str | LLMStreamChunk],
    on_chunk: ChunkCallback | None,
) -> tuple[str, int, LLMUsage]:
    chunks: list[str] = []
    usage = LLMUsage()
    start = time.perf_counter()
    logger.info("stream_collect_start role=%s", role)
    async for chunk in stream:
        if isinstance(chunk, LLMStreamChunk):
            if chunk.usage is not None:
                usage = chunk.usage
            if not chunk.text:
                continue
            text_chunk = chunk.text
        else:
            text_chunk = chunk
        chunks.append(text_chunk)
        if on_chunk:
            on_chunk(role, text_chunk)
    text = "".join(chunks).strip()
    latency_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "stream_collect_complete role=%s latency_ms=%d output_chars=%d",
        role,
        latency_ms,
        len(text),
    )
    return text, latency_ms, usage


def usage_with_fallback(
    usage: LLMUsage,
    messages: list[dict[str, str]],
    output_text: str,
) -> LLMUsage:
    return LLMUsage(
        input_tokens=usage.input_tokens or estimate_tokens(messages),
        output_tokens=usage.output_tokens or max(1, len(output_text) // 4),
    )


def combine_usage(usages: list[LLMUsage]) -> LLMUsage:
    input_tokens = sum(usage.input_tokens or 0 for usage in usages)
    output_tokens = sum(usage.output_tokens or 0 for usage in usages)
    return LLMUsage(
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
    )
