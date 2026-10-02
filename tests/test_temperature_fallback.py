"""Newer Claude models reject `temperature`; the client must adapt, not fail."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.ai.client import AnthropicClient, _is_temperature_deprecated
from src.models import AIConfig, AIProvider

DEPRECATED = "Error code: 400 - {'message': '`temperature` is deprecated for this model.'}"


def _config(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "provider": AIProvider.ANTHROPIC,
        "model": "claude-sonnet-5",
        "api_key_env": "ANTHROPIC_API_KEY",
        "temperature": 0.3,
    }
    values.update(overrides)
    return AIConfig(**values)


def _client(monkeypatch, create):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    monkeypatch.setattr(
        "src.ai.client.AsyncAnthropic",
        lambda **_: SimpleNamespace(messages=SimpleNamespace(create=create)),
    )
    return AnthropicClient(_config())


def _message(text: str = "ok"):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=2),
    )


def test_detects_the_deprecation_message() -> None:
    assert _is_temperature_deprecated(DEPRECATED)
    assert _is_temperature_deprecated("temperature is not supported")
    assert not _is_temperature_deprecated("overloaded_error")
    # Must not swallow an unrelated 400.
    assert not _is_temperature_deprecated("max_tokens is deprecated")


def test_retries_without_temperature_and_remembers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict] = []

    async def create(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        if "temperature" in kwargs:
            raise RuntimeError(DEPRECATED)
        return _message()

    client = _client(monkeypatch, create)

    assert asyncio.run(client.complete(system="s", user="u")) == "ok"
    assert len(calls) == 2
    assert "temperature" in calls[0] and "temperature" not in calls[1]

    # The second call must not repeat the doomed attempt.
    assert asyncio.run(client.complete(system="s", user="u")) == "ok"
    assert len(calls) == 3
    assert "temperature" not in calls[2]


def test_concurrent_requests_each_retry_without_temperature(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict] = []
    all_initial_requests_started = asyncio.Event()
    initial_request_count = 0

    async def create(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal initial_request_count
        calls.append(kwargs)
        if "temperature" in kwargs:
            initial_request_count += 1
            if initial_request_count == 3:
                all_initial_requests_started.set()
            await all_initial_requests_started.wait()
            raise RuntimeError(DEPRECATED)
        return _message()

    client = _client(monkeypatch, create)

    async def complete_all() -> list[str]:
        return await asyncio.gather(
            client.complete(system="s", user="one"),
            client.complete(system="s", user="two"),
            client.complete(system="s", user="three"),
        )

    assert asyncio.run(complete_all()) == ["ok", "ok", "ok"]
    assert len(calls) == 6
    assert sum("temperature" in call for call in calls) == 3
    assert client._supports_temperature is False


def test_unrelated_errors_still_propagate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def create(**_):  # type: ignore[no-untyped-def]
        raise RuntimeError("Error code: 529 - overloaded_error")

    client = _client(monkeypatch, create)

    with pytest.raises(RuntimeError, match="overloaded"):
        asyncio.run(client.complete(system="s", user="u"))


def test_models_that_accept_temperature_keep_sending_it(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict] = []

    async def create(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        return _message()

    client = _client(monkeypatch, create)
    asyncio.run(client.complete(system="s", user="u"))
    asyncio.run(client.complete(system="s", user="u"))

    assert all("temperature" in c for c in calls)


def test_skips_thinking_blocks(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def create(**_):  # type: ignore[no-untyped-def]
        # Sonnet 5 and the Opus 5 family think by default, so the first block
        # is a ThinkingBlock with no `.text`.
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="pondering"),
                SimpleNamespace(type="text", text='{"score": 8}'),
            ],
            usage=SimpleNamespace(input_tokens=10, output_tokens=2),
            stop_reason="end_turn",
        )

    client = _client(monkeypatch, create)

    assert asyncio.run(client.complete(system="s", user="u")) == '{"score": 8}'


def test_joins_multiple_text_blocks(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def create(**_):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="..."),
                SimpleNamespace(type="text", text="part one "),
                SimpleNamespace(type="text", text="part two"),
            ],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )

    client = _client(monkeypatch, create)

    assert asyncio.run(client.complete(system="s", user="u")) == "part one part two"


def test_a_textless_response_raises_with_the_stop_reason(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def create(**_):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking="...")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason="refusal",
        )

    client = _client(monkeypatch, create)

    with pytest.raises(ValueError, match="refusal"):
        asyncio.run(client.complete(system="s", user="u"))
