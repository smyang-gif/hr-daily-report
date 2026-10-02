"""Topic dedup must collapse overlapping groups returned by the model."""

import asyncio
from types import SimpleNamespace

from src.models import AIConfig, Config, DigestConfig, SourcesConfig
from src.orchestrator import HorizonOrchestrator

from tests.test_balanced_digest import make_item


class _FakeClient:
    def __init__(self, response: str):
        self.response = response

    async def complete(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self.response


def _orchestrator() -> HorizonOrchestrator:
    config = Config(
        ai=AIConfig(provider="openai", model="test", api_key_env="TEST_API_KEY"),
        sources=SourcesConfig(),
        digest=DigestConfig(),
    )
    return HorizonOrchestrator(config, SimpleNamespace(save_near_misses=lambda d, r: None))


def _run(monkeypatch, response: str, n: int) -> list[str]:
    import src.orchestrator as module

    monkeypatch.setattr(module, "create_ai_client", lambda *a, **k: _FakeClient(response))
    items = [make_item(f"i{i}", 10 - i * 0.1, None) for i in range(n)]
    kept = asyncio.run(_orchestrator().merge_topic_duplicates(items, log=False))
    return [item.id for item in kept]


def test_overlapping_groups_keep_one_item(monkeypatch) -> None:
    # Observed in production: [[4, 10], [12, 10]] kept both 4 and 12.
    kept = _run(monkeypatch, '{"duplicates": [[4, 10], [12, 10]]}', 13)
    assert "i4" in kept
    assert "i10" not in kept and "i12" not in kept


def test_lower_scored_primary_does_not_win(monkeypatch) -> None:
    # Observed in production: [[17, 3]] would drop the higher-scored item 3.
    kept = _run(monkeypatch, '{"duplicates": [[17, 3]]}', 18)
    assert "i3" in kept and "i17" not in kept


def test_unrelated_items_are_untouched(monkeypatch) -> None:
    kept = _run(monkeypatch, '{"duplicates": [[0, 2]]}', 4)
    assert kept == ["i0", "i1", "i3"]
