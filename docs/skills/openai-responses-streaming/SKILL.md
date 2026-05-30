---
name: openai-responses-streaming
description: OpenAI Responses API streaming guidance for Python providers. Use when creating, reviewing, or updating code that calls client.responses.create(..., stream=True), parses Responses streaming events, records token usage from streamed Responses, or compares Responses streaming with Chat Completions streaming.
---

# OpenAI Responses Streaming

Use this skill when working with the OpenAI Responses API streaming surface.

## Core Rules

- For the Responses API, enable streaming with `stream=True` on `client.responses.create(...)`.
- Do not use Chat Completions-only usage options on Responses calls. In particular, do not send `stream_options={"include_usage": True}` to `client.responses.create(...)`.
- If using `stream_options` with Responses, only use Responses-supported properties. As of the checked official docs, the documented property is `include_obfuscation`.
- Read streamed text from `response.output_text.delta` events.
- Capture final token usage from the response object attached to the terminal `response.completed` event.
- Expect early lifecycle events such as `response.created` to have `response.usage == None`.
- Extract Responses usage fields as `usage.input_tokens`, `usage.output_tokens`, and optionally `usage.total_tokens`.
- Keep a local estimate fallback when exact streamed usage is unavailable because SDK versions and failed/incomplete streams may omit final usage.
- If exact telemetry matters, verify the current official OpenAI docs before adding request parameters. The Responses API and Chat Completions streaming shapes differ.

## Python Pattern

```python
stream = await client.responses.create(
    model=model,
    input=input_messages,
    instructions=instructions,
    text={"format": {"type": "text"}},
    stream=True,
)

usage = None
async for event in stream:
    if getattr(event, "type", None) == "response.output_text.delta":
        yield event.delta

    if getattr(event, "type", None) == "response.completed":
        response = getattr(event, "response", None)
        usage = getattr(response, "usage", None)

input_tokens = getattr(usage, "input_tokens", None)
output_tokens = getattr(usage, "output_tokens", None)
```

## Review Checklist

- Is the code using Responses API semantics rather than Chat Completions chunk semantics?
- Does the request avoid unsupported `stream_options.include_usage`?
- Does streamed text handling ignore metadata-only events?
- Does telemetry parsing inspect `event.response.usage` on `response.completed`?
- Does the code fall back to a relevant estimate instead of logging `NULL` or a placeholder `1` token?

## Official References

- Responses streaming guide: https://platform.openai.com/docs/guides/streaming-responses
- Responses streaming events: https://platform.openai.com/docs/api-reference/responses-streaming/response
- Responses API `stream_options`: https://platform.openai.com/docs/api-reference/responses/compact?api-mode=responses
- Chat Completions streaming chunks: https://platform.openai.com/docs/api-reference/chat-streaming
