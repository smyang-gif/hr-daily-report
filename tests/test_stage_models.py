"""Tests for per-stage model routing in create_ai_client."""

import pytest

from src.ai.client import _apply_stage_model, create_ai_client
from src.models import AIConfig, AIProvider


def _config(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "provider": AIProvider.ANTHROPIC,
        "model": "big-model",
        "api_key_env": "ANTHROPIC_API_KEY",
    }
    values.update(overrides)
    return AIConfig(**values)


def test_no_stage_keeps_base_model() -> None:
    config = _config(stage_models={"analysis": "small-model"})
    assert _apply_stage_model(config, None).model == "big-model"


def test_stage_without_override_keeps_base_model() -> None:
    config = _config(stage_models={"analysis": "small-model"})
    assert _apply_stage_model(config, "enrichment").model == "big-model"


def test_stage_override_swaps_the_model() -> None:
    config = _config(stage_models={"analysis": "small-model"})
    assert _apply_stage_model(config, "analysis").model == "small-model"


def test_override_does_not_mutate_the_shared_config() -> None:
    config = _config(stage_models={"analysis": "small-model"})

    _apply_stage_model(config, "analysis")

    # The orchestrator reuses one AIConfig across stages; an in-place edit here
    # would leak the cheap model into every later stage.
    assert config.model == "big-model"


def test_override_preserves_unrelated_settings() -> None:
    config = _config(
        stage_models={"analysis": "small-model"},
        temperature=0.7,
        max_tokens=2048,
        languages=["ko"],
    )

    routed = _apply_stage_model(config, "analysis")

    assert routed.temperature == 0.7
    assert routed.max_tokens == 2048
    assert routed.languages == ["ko"]
    assert routed.api_key_env == "ANTHROPIC_API_KEY"


def test_stage_models_defaults_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    assert config.stage_models == {}
    assert _apply_stage_model(config, "analysis").model == "big-model"


def test_create_ai_client_routes_by_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def _fake_single(config):  # type: ignore[no-untyped-def]
        seen.append(config.model)
        return object()

    monkeypatch.setattr("src.ai.client._create_single_client", _fake_single)
    config = _config(stage_models={"analysis": "small-model", "dedup": "small-model"})

    create_ai_client(config, stage="analysis")
    create_ai_client(config, stage="enrichment")
    create_ai_client(config)

    assert seen == ["small-model", "big-model", "big-model"]
