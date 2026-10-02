from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.models import ArxivConfig, SourceType
from src.scrapers.arxiv import ArxivScraper


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entry(
    arxiv_id: str,
    title: str = "A Title",
    summary: str = "An abstract.",
    published: str | None = None,
    authors: tuple[str, ...] = ("Ada Lovelace", "Alan Turing"),
    version: str = "v1",
    primary: str = "cs.AI",
) -> str:
    published = published or (_now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    author_tags = "".join(f"<author><name>{a}</name></author>" for a in authors)
    return f"""
      <entry>
        <id>http://arxiv.org/abs/{arxiv_id}{version}</id>
        <updated>{published}</updated>
        <published>{published}</published>
        <title>{title}</title>
        <summary>{summary}</summary>
        {author_tags}
        <link href="http://arxiv.org/abs/{arxiv_id}{version}" rel="alternate" type="text/html"/>
        <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="{primary}"/>
        <category term="{primary}" scheme="http://arxiv.org/schemas/atom"/>
      </entry>
    """


def _feed(entries_xml: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>ArXiv Query</title>
      {entries_xml}
    </feed>
    """


def _response(text: str, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.status_code = status_code
    response.raise_for_status.return_value = None
    return response


def _mock_client(*texts: str) -> AsyncMock:
    """Client returning one feed body per successive call."""
    client = AsyncMock()
    client.get.side_effect = [_response(t) for t in texts]
    return client


def _config(**overrides) -> ArxivConfig:  # type: ignore[no-untyped-def]
    values = {
        "enabled": True,
        "categories": ["cs.AI"],
        "max_results_per_category": 10,
        "request_delay_sec": 0.0,  # keep tests fast
    }
    values.update(overrides)
    return ArxivConfig(**values)


def test_disabled_source_fetches_nothing() -> None:
    client = _mock_client(_feed(_entry("2601.00001")))
    scraper = ArxivScraper(_config(enabled=False), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert items == []
    client.get.assert_not_called()


def test_parses_entry_into_content_item() -> None:
    client = _mock_client(
        _feed(_entry("2601.00001", title="Scaling  Laws\n  Revisited", authors=("Ada Lovelace",)))
    )
    scraper = ArxivScraper(_config(), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert len(items) == 1
    item = items[0]
    assert item.source_type == SourceType.ARXIV
    # arXiv hard-wraps titles and abstracts; whitespace must be collapsed.
    assert item.title == "Scaling Laws Revisited"
    assert str(item.url) == "https://arxiv.org/abs/2601.00001"
    assert item.metadata["arxiv_id"] == "2601.00001"
    assert item.metadata["pdf_url"] == "https://arxiv.org/pdf/2601.00001"
    assert item.author == "Ada Lovelace"
    assert item.metadata["author_count"] == 1


def test_id_excludes_version_and_category_so_cross_listings_merge() -> None:
    # Same paper returned under two categories, at different version suffixes.
    client = _mock_client(
        _feed(_entry("2601.00001", version="v1", primary="cs.AI")),
        _feed(_entry("2601.00001", version="v3", primary="cs.AI")),
    )
    scraper = ArxivScraper(_config(categories=["cs.AI", "cs.CL"]), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert len(items) == 1
    assert items[0].id == "arxiv:paper:2601.00001"
    assert items[0].metadata["also_in"] == ["cs.CL"]


def test_queries_one_category_at_a_time() -> None:
    # arXiv answers a combined "cat:A OR cat:B" query with an immediate 429
    # no matter how the requests are paced, so each category must go out as
    # its own plain cat: query.
    client = _mock_client(*[_feed(_entry(f"2601.0000{i}")) for i in range(1, 4)])
    scraper = ArxivScraper(
        _config(categories=["cs.AI", "cs.CL", "cs.LG"]), client
    )

    asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert client.get.await_count == 3
    queries = [c.kwargs["params"]["search_query"] for c in client.get.await_args_list]
    assert queries == ["cat:cs.AI", "cat:cs.CL", "cat:cs.LG"]
    assert not any(" OR " in q for q in queries)


def test_primary_category_prefers_the_entry_over_the_queried_category() -> None:
    client = _mock_client(_feed(_entry("2601.00001", primary="cs.LG")))
    scraper = ArxivScraper(_config(categories=["cs.AI"]), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert items[0].metadata["primary_category"] == "cs.LG"
    assert items[0].metadata["feed_name"] == "arXiv cs.LG"


def test_a_failed_category_does_not_cost_the_others(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _skip_backoff(monkeypatch)
    client = AsyncMock()
    client.get.side_effect = [
        RuntimeError("arxiv is down"),
        _response(_feed(_entry("2601.00002"))),
    ]
    scraper = ArxivScraper(_config(categories=["cs.AI", "cs.CL"]), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert [i.metadata["arxiv_id"] for i in items] == ["2601.00002"]


def test_no_categories_means_no_request() -> None:
    client = _mock_client(_feed(_entry("2601.00001")))
    scraper = ArxivScraper(_config(categories=[]), client)

    assert asyncio.run(scraper.fetch(_now() - timedelta(hours=24))) == []
    client.get.assert_not_called()


def test_stops_at_first_item_older_than_since() -> None:
    fresh = (_now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = (_now() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = _mock_client(
        _feed(_entry("2601.00001", published=fresh) + _entry("2601.00002", published=stale))
    )
    scraper = ArxivScraper(_config(), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert [i.metadata["arxiv_id"] for i in items] == ["2601.00001"]


def test_boost_keywords_are_recorded_not_filtered() -> None:
    client = _mock_client(
        _feed(
            _entry("2601.00001", title="An Agent Benchmark")
            + _entry("2601.00002", title="Unrelated Topic", summary="Nothing to see.")
        )
    )
    scraper = ArxivScraper(_config(boost_keywords=["agent", "diffusion"]), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    # Both survive; keywords only annotate for downstream scoring.
    assert len(items) == 2
    by_id = {i.metadata["arxiv_id"]: i for i in items}
    assert by_id["2601.00001"].metadata["matched_keywords"] == ["agent"]
    assert by_id["2601.00002"].metadata["matched_keywords"] == []


def test_malformed_feed_yields_no_items_rather_than_raising() -> None:
    client = _mock_client("<not xml at all")
    scraper = ArxivScraper(_config(), client)

    assert asyncio.run(scraper.fetch(_now() - timedelta(hours=24))) == []


def _skip_backoff(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Make retry sleeps instant so the tests stay fast."""

    async def _no_sleep(_seconds):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr("src.scrapers.arxiv.asyncio.sleep", _no_sleep)


def test_retries_a_429_then_succeeds(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _skip_backoff(monkeypatch)
    client = AsyncMock()
    # arXiv rate-limits bursts; a category lost to a 429 is a whole subject
    # area missing from the briefing, so it must be retried.
    client.get.side_effect = [
        _response("", status_code=429),
        _response(_feed(_entry("2601.00001"))),
    ]
    scraper = ArxivScraper(_config(), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert [i.metadata["arxiv_id"] for i in items] == ["2601.00001"]
    assert client.get.await_count == 2


def test_gives_up_after_max_attempts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from src.scrapers.arxiv import MAX_ATTEMPTS

    _skip_backoff(monkeypatch)
    client = AsyncMock()
    client.get.side_effect = [_response("", status_code=429)] * (MAX_ATTEMPTS + 2)
    scraper = ArxivScraper(_config(), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert items == []
    assert client.get.await_count == MAX_ATTEMPTS


def test_retries_a_server_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _skip_backoff(monkeypatch)
    client = AsyncMock()
    client.get.side_effect = [
        _response("", status_code=503),
        _response(_feed(_entry("2601.00001"))),
    ]
    scraper = ArxivScraper(_config(), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    assert [i.metadata["arxiv_id"] for i in items] == ["2601.00001"]


def test_does_not_retry_a_client_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _skip_backoff(monkeypatch)
    bad = _response("", status_code=400)
    bad.raise_for_status.side_effect = httpx.HTTPStatusError(
        "400", request=MagicMock(), response=bad
    )
    client = AsyncMock()
    client.get.side_effect = [bad, _response(_feed(_entry("2601.00001")))]
    scraper = ArxivScraper(_config(), client)

    items = asyncio.run(scraper.fetch(_now() - timedelta(hours=24)))

    # A 400 means the query itself is wrong; retrying it just wastes time.
    assert items == []
    assert client.get.await_count == 1


def test_rejects_non_category_tokens() -> None:
    import pytest

    with pytest.raises(ValueError, match="invalid arXiv category"):
        ArxivConfig(categories=["../../etc/passwd"])
