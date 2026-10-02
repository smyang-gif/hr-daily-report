#!/usr/bin/env python3
"""Exercise the collection stage only - no API key, no cost.

Fetches from every configured source and reports what came back, so a broken
feed or a rate-limited source shows up as a number rather than as a quietly
short briefing.

    uv run python scripts/check-sources.py            # uses the config window
    uv run python scripts/check-sources.py --hours 24
    uv run python scripts/check-sources.py --feeds    # only probe RSS URLs
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feedparser  # noqa: E402
import httpx  # noqa: E402

from src.orchestrator import HorizonOrchestrator  # noqa: E402
from src.storage.manager import StorageManager  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (compatible; ai-researcher/1.0)"}


async def probe_feeds(config) -> int:  # type: ignore[no-untyped-def]
    """Check every configured RSS URL resolves and parses."""
    feeds = [(f.name, str(f.url)) for f in config.sources.rss if f.enabled]

    async def one(client, name, url):  # type: ignore[no-untyped-def]
        try:
            r = await client.get(url, follow_redirects=True, headers=UA)
            if r.status_code != 200:
                return name, f"HTTP {r.status_code}", 0
            entries = feedparser.parse(r.text).entries
            return name, ("OK" if entries else "항목 0"), len(entries)
        except Exception as e:
            return name, f"{type(e).__name__}", 0

    async with httpx.AsyncClient(timeout=30) as client:
        results = await asyncio.gather(*[one(client, n, u) for n, u in feeds])

    bad = [r for r in results if r[1] != "OK"]
    print(f"\nRSS 피드 {len(results) - len(bad)}/{len(results)} 정상")
    for name, status, count in sorted(results, key=lambda r: (r[1] != "OK", -r[2])):
        mark = "  OK  " if status == "OK" else "  FAIL"
        print(f"{mark} {name:<24} {count:>4}개  {'' if status == 'OK' else status}")
    return len(bad)


async def run(hours: int | None, feeds_only: bool) -> int:
    storage = StorageManager(data_dir="data")
    config = storage.load_config()

    if feeds_only:
        return 1 if await probe_feeds(config) else 0

    window = hours or config.collection.time_window_hours
    since = datetime.now(timezone.utc) - timedelta(hours=window)
    print(f"최근 {window}시간 수집 중...\n")

    orchestrator = HorizonOrchestrator(config=config, storage=storage)
    items = await orchestrator.fetch_all_sources(since)

    print("\n=== 소스별 ===")
    failures = 0
    for outcome in orchestrator.last_fetch_report.outcomes:
        mark = {"success": "  OK  ", "empty": "  빈  ", "failure": "  FAIL"}[outcome.status]
        note = f"  <- {str(outcome.error)[:56]}" if outcome.error else ""
        print(f"{mark} {outcome.source_name:<16} {len(outcome.items):>4}건{note}")
        if outcome.status == "failure":
            failures += 1

    print(f"\n총 {len(items)}건")
    print("  타입별  :", dict(collections.Counter(i.source_type.value for i in items)))
    print("  프로필별:", dict(collections.Counter(str(i.profile) for i in items)))

    if not items:
        print("\n수집된 항목이 없습니다. 창을 늘려서 다시 확인해 보세요: --hours 48")
        return 1

    print("\n=== 표본 ===")
    for item in items[:8]:
        print(f"  [{item.source_type.value:<11}] {item.title[:70]}")

    # The briefing can only be as good as what arrives here; an empty source
    # class is worth knowing about before blaming the model.
    for label, kinds in (("논문", {"arxiv"}), ("뉴스레터/블로그", {"rss"})):
        if not any(i.source_type.value in kinds for i in items):
            print(f"\n경고: {label} 항목이 하나도 없습니다.")

    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, help="Lookback window override")
    parser.add_argument("--feeds", action="store_true", help="Only probe RSS URLs")
    args = parser.parse_args()

    if not Path("data/config.json").exists():
        print("data/config.json 이 없습니다. 먼저 실행하세요:")
        print("  cp data/config.github.json data/config.json")
        sys.exit(2)

    # The fetch stage never calls the model, but constructing the config
    # validates api_key_env, so give it something to find.
    os.environ.setdefault("ANTHROPIC_API_KEY", "not-used-by-the-fetch-stage")
    sys.exit(asyncio.run(run(args.hours, args.feeds)))


if __name__ == "__main__":
    main()
