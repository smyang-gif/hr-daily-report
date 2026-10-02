"""Token tracking retains model detail for credit runway estimates."""

from __future__ import annotations

from datetime import datetime, timezone

from src.ai.costs import build_usage_record
from src.ai.tokens import get_usage_snapshot, record_usage, reset_usage
from src.storage.manager import StorageManager


def setup_function() -> None:
    reset_usage()


def teardown_function() -> None:
    reset_usage()


def test_usage_record_estimates_configured_anthropic_models() -> None:
    record_usage("anthropic", 1_000_000, 100_000, model="claude-haiku-4-5")
    record_usage("anthropic", 500_000, 100_000, model="claude-sonnet-5")

    record = build_usage_record(
        get_usage_snapshot(),
        date="2026-09-12",
        generated_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )

    assert record["input_tokens"] == 1_500_000
    assert record["output_tokens"] == 200_000
    assert record["estimated_cost_usd"] == "3.500000"
    assert record["unknown_price_models"] == []
    assert len(record["models"]) == 2


def test_unknown_model_is_visible_and_excluded_from_estimate() -> None:
    record_usage("anthropic", 10, 5, model="future-model")

    record = build_usage_record(get_usage_snapshot(), date="2026-09-12")

    assert record["estimated_cost_usd"] == "0.000000"
    assert record["unknown_price_models"] == ["anthropic/future-model"]
    assert record["models"][0]["estimated_cost_usd"] is None


def test_storage_saves_usage_record(tmp_path) -> None:
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    record = {"estimated_cost_usd": "0.123456"}

    path = storage.save_usage("2026-09-12", record)

    assert path.name == "horizon-2026-09-12.json"
    assert '"0.123456"' in path.read_text()
