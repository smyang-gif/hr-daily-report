"""Scored-but-dropped items are recorded so the reader can review them."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from src.orchestrator import HorizonOrchestrator


def _item(item_id: str, score, title="T"):  # type: ignore[no-untyped-def]
    analysis = SimpleNamespace(
        score=score, summary=f"{item_id} 요약", reason="이유", tags=["ai"]
    )
    return SimpleNamespace(
        id=item_id,
        title=title,
        url=f"https://example.com/{item_id}",
        source_type=SimpleNamespace(value="hackernews"),
        author="someone",
        published_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        profile="tech-news",
        processing=SimpleNamespace(analysis=analysis),
    )


def _orchestrator(tmp_path):  # type: ignore[no-untyped-def]
    orchestrator = HorizonOrchestrator.__new__(HorizonOrchestrator)
    saved: dict = {}

    def save(date, rows):  # type: ignore[no-untyped-def]
        path = tmp_path / f"{date}.json"
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        saved["rows"] = rows
        return path

    orchestrator.storage = SimpleNamespace(save_near_misses=save)
    orchestrator.console = SimpleNamespace(print=lambda *a, **k: None)
    orchestrator.icons = {"save": ""}
    orchestrator._sub_source_label = lambda item: "news.ycombinator.com"
    return orchestrator, saved


def test_keeps_only_unselected_items_at_or_above_the_floor(tmp_path) -> None:  # type: ignore[no-untyped-def]
    orchestrator, saved = _orchestrator(tmp_path)
    analyzed = [
        _item("chosen", 8.0),
        _item("near", 6.5),
        _item("exactly-at-floor", 5.0),
        _item("too-low", 4.9),
        _item("unscored", None),
    ]
    selected = [analyzed[0]]

    orchestrator.save_near_misses(analyzed, selected, "2026-09-03")

    ids = [row["id"] for row in saved["rows"]]
    assert ids == ["near", "exactly-at-floor"]


def test_rows_are_ordered_by_score_descending(tmp_path) -> None:  # type: ignore[no-untyped-def]
    orchestrator, saved = _orchestrator(tmp_path)
    analyzed = [_item("a", 5.5), _item("b", 6.9), _item("c", 6.0)]

    orchestrator.save_near_misses(analyzed, [], "2026-09-03")

    assert [row["score"] for row in saved["rows"]] == [6.9, 6.0, 5.5]


def test_rows_carry_what_the_review_page_needs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    orchestrator, saved = _orchestrator(tmp_path)

    orchestrator.save_near_misses([_item("x", 6.0, title="제목")], [], "2026-09-03")

    row = saved["rows"][0]
    for field in ("id", "title", "url", "score", "summary", "tags", "source_type"):
        assert field in row, field
    assert row["title"] == "제목"
    assert row["url"] == "https://example.com/x"


def test_an_empty_result_still_writes_a_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    orchestrator, saved = _orchestrator(tmp_path)

    # A quiet run must leave an empty list, not a missing file the archive
    # step would then treat as "nothing produced".
    orchestrator.save_near_misses([_item("chosen", 9.0)], [_item("chosen", 9.0)], "2026-09-03")

    assert saved["rows"] == []
    assert json.loads((tmp_path / "2026-09-03.json").read_text(encoding="utf-8")) == []
