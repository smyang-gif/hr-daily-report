"""A wholly failed analysis pass must not look like a quiet news day."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.orchestrator import HorizonOrchestrator


class _Analyzer:
    """Stand-in for ContentAnalyzer with a preset failure tally."""

    def __init__(self, failure_count: int, first_failure: str | None = None):
        self.failure_count = failure_count
        self.first_failure = first_failure

    async def analyze_batch(self, items):  # type: ignore[no-untyped-def]
        return items


def _orchestrator(monkeypatch, analyzer, items):  # type: ignore[no-untyped-def]
    orchestrator = HorizonOrchestrator.__new__(HorizonOrchestrator)
    orchestrator.config = SimpleNamespace(
        ai=SimpleNamespace(
            model="big-model",
            stage_models={"analysis": "small-model"},
            languages=["ko"],
        )
    )
    orchestrator.profiles = SimpleNamespace()
    printed: list[str] = []
    orchestrator.console = SimpleNamespace(print=lambda text="", **_: printed.append(str(text)))
    orchestrator.icons = {"ai": "", "warning": ""}

    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda *a, **k: object())
    monkeypatch.setattr("src.orchestrator.ContentAnalyzer", lambda *a, **k: analyzer)
    return orchestrator, printed


def test_total_failure_raises_rather_than_yielding_an_empty_briefing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    items = [object(), object(), object()]
    orchestrator, _ = _orchestrator(
        monkeypatch, _Analyzer(3, "NotFoundError: model not found"), items
    )

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(orchestrator.analyze_items(items))

    message = str(excinfo.value)
    # The message has to name the model and the underlying error, or the
    # operator is left guessing why the briefing came back empty.
    assert "all 3 items" in message
    assert "small-model" in message
    assert "model not found" in message


def test_partial_failure_warns_but_continues(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    items = [object(), object(), object(), object()]
    orchestrator, printed = _orchestrator(
        monkeypatch, _Analyzer(1, "APIConnectionError: boom"), items
    )

    result = asyncio.run(orchestrator.analyze_items(items))

    assert result == items
    assert any("1/4" in line for line in printed)
    assert any("small-model" in line for line in printed)


def test_clean_run_says_nothing_extra(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    items = [object(), object()]
    orchestrator, printed = _orchestrator(monkeypatch, _Analyzer(0), items)

    result = asyncio.run(orchestrator.analyze_items(items))

    assert result == items
    assert not any("failed" in line.lower() for line in printed)


def test_failure_message_falls_back_to_the_base_model(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    items = [object()]
    orchestrator, _ = _orchestrator(monkeypatch, _Analyzer(1, "boom"), items)
    orchestrator.config.ai.stage_models = {}

    with pytest.raises(RuntimeError, match="big-model"):
        asyncio.run(orchestrator.analyze_items(items))
