"""Anthropic identity-linked keys need an explicit workspace header."""

from __future__ import annotations

import pytest

from src.ai.client import _resolve_workspace_id
from src.models import AIConfig, AIProvider


def _config(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "provider": AIProvider.ANTHROPIC,
        "model": "claude-sonnet-5",
        "api_key_env": "ANTHROPIC_API_KEY",
    }
    values.update(overrides)
    return AIConfig(**values)


def test_defaults_to_the_conventional_env_var() -> None:
    assert _config().workspace_id_env == "ANTHROPIC_WORKSPACE_ID"


def test_unset_variable_yields_no_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    # An ordinary key rejects the header, so absence must mean "send nothing".
    assert _resolve_workspace_id(_config()) is None


def test_blank_variable_yields_no_header(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI passes an unset secret through as an empty string.
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "   ")
    assert _resolve_workspace_id(_config()) is None


def test_set_variable_is_returned_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "  wrkspc_abc123  ")
    assert _resolve_workspace_id(_config()) == "wrkspc_abc123"


def test_env_var_name_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_WORKSPACE", "wrkspc_xyz")
    assert _resolve_workspace_id(_config(workspace_id_env="MY_WORKSPACE")) == "wrkspc_xyz"


def test_client_sends_the_header_only_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    class _FakeAsyncAnthropic:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.append(kwargs)

    monkeypatch.setattr("src.ai.client.AsyncAnthropic", _FakeAsyncAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    from src.ai.client import AnthropicClient

    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    AnthropicClient(_config())
    assert "default_headers" not in captured[-1]

    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_abc123")
    AnthropicClient(_config())
    assert captured[-1]["default_headers"] == {"anthropic-workspace-id": "wrkspc_abc123"}
