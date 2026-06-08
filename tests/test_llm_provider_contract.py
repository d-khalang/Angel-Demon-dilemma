from types import SimpleNamespace
from typing import Any

import pytest

from angel_demon.llm import LLMStreamChunk, OpenAIProvider
from angel_demon.models import Verdict


class FakeResponses:
    def __init__(self, results: list[Any]) -> None:
        self.results = iter(results)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


class FakeStream:
    def __init__(self, events: list[Any]) -> None:
        self.events = events

    def __aiter__(self):
        async def iterate():
            for event in self.events:
                yield event

        return iterate()


def response(text: str, input_tokens: int = 11, output_tokens: int = 7) -> Any:
    return SimpleNamespace(
        output_text=text,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


@pytest.mark.asyncio
async def test_openai_text_request_contract_separates_instructions_and_usage() -> None:
    provider = OpenAIProvider("test-key", "test-model")
    fake = FakeResponses([response("completed")])
    provider.client = SimpleNamespace(responses=fake)

    result = await provider.complete_with_usage(
        [
            {"role": "system", "content": "System contract."},
            {"role": "user", "content": "User input."},
        ],
        temperature=0.2,
        max_output_tokens=123,
    )

    assert result.text == "completed"
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7
    assert fake.calls == [
        {
            "model": "test-model",
            "instructions": "System contract.",
            "input": [{"role": "user", "content": "User input."}],
            "temperature": 0.2,
            "max_output_tokens": 123,
            "text": {"format": {"type": "text"}},
        }
    ]


@pytest.mark.asyncio
async def test_openai_stream_contract_emits_text_and_completed_usage() -> None:
    provider = OpenAIProvider("test-key", "test-model")
    stream = FakeStream(
        [
            SimpleNamespace(type="response.output_text.delta", delta="Hello "),
            SimpleNamespace(type="response.output_text.delta", delta="world"),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=13, output_tokens=2)
                ),
            ),
        ]
    )
    fake = FakeResponses([stream])
    provider.client = SimpleNamespace(responses=fake)

    chunks = [
        chunk
        async for chunk in provider.stream(
            [{"role": "user", "content": "Say hello."}],
            temperature=0.4,
            max_output_tokens=20,
        )
    ]

    assert chunks[:2] == ["Hello ", "world"]
    assert isinstance(chunks[-1], LLMStreamChunk)
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.input_tokens == 13
    assert chunks[-1].usage.output_tokens == 2
    assert fake.calls[0]["stream"] is True


@pytest.mark.asyncio
async def test_openai_structured_output_contract_uses_strict_schema() -> None:
    provider = OpenAIProvider("test-key", "test-model")
    fake = FakeResponses(
        [
            response(
                """
                {
                  "winner": "sunny",
                  "reason": "Clearer.",
                  "sunny_score": 8,
                  "crowley_score": 7,
                  "persuasion_tactics_sunny": ["empathy"],
                  "persuasion_tactics_crowley": ["status"],
                  "key_moment": "The rebuttal.",
                  "safety_notes": null,
                  "is_fallback": false
                }
                """
            )
        ]
    )
    provider.client = SimpleNamespace(responses=fake)

    verdict = await provider.complete_json(
        [{"role": "user", "content": "Judge this."}],
        Verdict,
    )

    output_format = fake.calls[0]["text"]["format"]
    assert verdict.sunny_score == 8
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    assert output_format["schema"]["additionalProperties"] is False
    assert set(output_format["schema"]["required"]) == set(
        output_format["schema"]["properties"]
    )


@pytest.mark.asyncio
async def test_openai_provider_retries_transient_request_failures(monkeypatch) -> None:
    provider = OpenAIProvider("test-key", "test-model")
    fake = FakeResponses(
        [
            RuntimeError("temporary one"),
            RuntimeError("temporary two"),
            response("recovered"),
        ]
    )
    provider.client = SimpleNamespace(responses=fake)

    async def no_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("angel_demon.llm.asyncio.sleep", no_sleep)

    assert await provider.complete([{"role": "user", "content": "Retry."}]) == "recovered"
    assert len(fake.calls) == 3
