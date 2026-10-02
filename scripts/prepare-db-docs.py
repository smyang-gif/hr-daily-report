#!/usr/bin/env python3
"""Turn archived near-miss files into artifact-database documents.

The review page keeps one document per run rather than one per item: the
store caps an artifact at 5,000 documents, and two runs a day of ~25 items
each would reach that in a few months.

    uv run python scripts/prepare-db-docs.py                 # runs not yet synced
    uv run python scripts/prepare-db-docs.py --all           # every archived run
    uv run python scripts/prepare-db-docs.py --since 2026-09-01

Writes one JSON file per run under .sync/db-docs/, ready to hand to the
Artifact tool's write_db, and prints the collection and document id for each.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ARCHIVE = Path("near-misses")
OUT_DIR = Path(".sync/db-docs")
STATE = Path(".sync/synced-runs.json")

RUN_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(morning|evening)\.json$")

# Only what the page renders. `reason` is the model's internal justification
# in English and never reaches the screen, so it stays out of the document.
ITEM_FIELDS = (
    "id",
    "title",
    "url",
    "score",
    "summary",
    "tags",
    "source_type",
    "sub_source",
    "published_at",
)

# Later runs should sort first, and "evening" sorts before "morning"
# alphabetically, so the slot becomes a number.
SLOT_ORDER = {"morning": "1", "evening": "2"}


def load_synced() -> set[str]:
    if not STATE.exists():
        return set()
    try:
        with STATE.open(encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def save_synced(keys: set[str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with STATE.open("w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, indent=2)
        f.write("\n")


def build(path: Path) -> tuple[str, dict] | None:
    match = RUN_NAME.match(path.name)
    if not match:
        return None
    year, month, day, slot = match.groups()
    date = f"{year}-{month}-{day}"
    run_key = f"{date}-{slot}"

    with path.open(encoding="utf-8") as f:
        rows = json.load(f)

    items = []
    for row in rows:
        item = {field: row.get(field) for field in ITEM_FIELDS}
        item["tags"] = list(item.get("tags") or [])
        items.append(item)

    return run_key, {
        "date": date,
        "slot": slot,
        "sort_key": f"{date}-{SLOT_ORDER[slot]}",
        "count": len(items),
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Rebuild every run")
    parser.add_argument("--since", help="Only runs on or after this YYYY-MM-DD")
    args = parser.parse_args()

    if not ARCHIVE.exists():
        print(f"{ARCHIVE}/ 가 없습니다. 브리핑이 한 번은 돌아야 합니다.")
        return 1

    synced = set() if args.all else load_synced()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    prepared: list[str] = []
    for path in sorted(ARCHIVE.rglob("*.json")):
        built = build(path)
        if built is None:
            continue
        run_key, doc = built
        if args.since and doc["date"] < args.since:
            continue
        if run_key in synced:
            continue

        out = OUT_DIR / f"{run_key}.json"
        with out.open("w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")

        size_kb = out.stat().st_size / 1024
        # The store rejects a document over 256 KiB.
        flag = "  ** 256KiB 초과, 분할 필요" if size_kb > 256 else ""
        prepared.append(run_key)
        print(f"  runs/{run_key}  {doc['count']:>3}건  {size_kb:6.1f} KiB  {out}{flag}")

    if not prepared:
        print("새로 준비할 회차가 없습니다. 전부 다시 만들려면 --all 을 쓰세요.")
        return 0

    print(f"\n{len(prepared)}개 회차를 {OUT_DIR}/ 에 준비했습니다.")
    print("각 파일을 write_db 로 collection 'runs', doc_id 는 파일 이름으로 넣으세요.")
    save_synced(synced | set(prepared))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
