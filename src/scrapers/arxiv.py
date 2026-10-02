"""arXiv preprint scraper implementation."""

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from typing import List, Optional
import calendar

import httpx
import feedparser

from .base import BaseScraper
from ..models import ContentItem, SourceType, ArxivConfig

logger = logging.getLogger(__name__)

API_URL = "https://export.arxiv.org/api/query"

# arXiv answers bursts with 429 and occasionally drops the connection outright.
# Both are transient, and a category lost to one is a whole subject area missing
# from the briefing, so retry before giving up.
MAX_ATTEMPTS = 4


class _Transient(Exception):
    """A failure worth retrying, as opposed to a malformed query."""

# "http://arxiv.org/abs/2401.12345v2" -> "2401.12345". Dropping the version
# suffix collapses the same paper fetched under several categories into one item.
_ABS_ID = re.compile(r"/abs/(?P<id>[^v\s]+?)(?:v\d+)?$")


class ArxivScraper(BaseScraper):
    """Scraper for arXiv preprints via the public Atom API."""

    def __init__(self, config: ArxivConfig, http_client: httpx.AsyncClient):
        """Initialize arXiv scraper.

        Args:
            config: arXiv source configuration
            http_client: Shared async HTTP client
        """
        super().__init__({"source": config}, http_client)
        self.source = config
        self._keywords = [k.lower() for k in config.boost_keywords]

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch arXiv preprints submitted since the given time.

        One request per category, spaced by `request_delay_sec`. arXiv rejects
        a combined `cat:A OR cat:B` query outright with a 429 regardless of
        pacing, so batching is not an option; categories are not redundant
        either - measured against a 150-row page, cs.AI alone covers about a
        fifth of what the configured set returns.

        Args:
            since: Only fetch papers published after this time

        Returns:
            List[ContentItem]: Fetched content items, deduplicated by arXiv ID
        """
        if not self.source.enabled or not self.source.categories:
            return []

        # The same paper is often cross-listed; keep the first occurrence.
        seen: dict[str, ContentItem] = {}

        for index, category in enumerate(self.source.categories):
            if index > 0 and self.source.request_delay_sec > 0:
                # arXiv asks for no more than one request every three seconds.
                await asyncio.sleep(self.source.request_delay_sec)

            for item in await self._fetch_category(category, since):
                existing = seen.get(item.id)
                if existing is None:
                    seen[item.id] = item
                else:
                    # Record the cross-listing rather than dropping it silently.
                    others = existing.metadata.setdefault("also_in", [])
                    if category not in others:
                        others.append(category)

        return list(seen.values())

    async def _fetch_category(
        self, category: str, since: datetime
    ) -> List[ContentItem]:
        """Fetch the newest preprints for a single arXiv category.

        Args:
            category: arXiv category token, e.g. "cs.AI"
            since: Only fetch papers published after this time

        Returns:
            List[ContentItem]: Papers in this category newer than `since`
        """
        items: List[ContentItem] = []

        try:
            body = await self._get_with_retry(category)
        except Exception as e:
            # A non-retryable failure in one category must not cost the others.
            logger.warning(
                "arXiv category %s failed: %s: %s", category, type(e).__name__, e
            )
            return items
        if body is None:
            return items

        try:
            for entry in feedparser.parse(body).entries:
                published_at = self._parse_date(entry)
                if not published_at:
                    continue
                # Results are newest-first, so the first old paper ends the page.
                if published_at < since:
                    break

                item = self._build_item(entry, category, published_at)
                if item:
                    items.append(item)
        except Exception as e:
            logger.warning(
                "Error parsing arXiv category %s: %s: %s",
                category, type(e).__name__, e,
            )

        return items

    async def _get_with_retry(self, category: str) -> Optional[str]:
        """Fetch one category page, retrying transient failures.

        Args:
            category: arXiv category token

        Returns:
            Optional[str]: The Atom body, or None once the retries are spent.
        """
        params = {
            "search_query": f"cat:{category}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": self.source.max_results_per_category,
        }

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self.client.get(
                    API_URL, params=params, follow_redirects=True
                )
                # Only rate limiting and server faults are worth another try.
                # A 4xx other than 429 means the query itself is wrong, so let
                # raise_for_status surface it to the caller immediately.
                if response.status_code == 429 or response.status_code >= 500:
                    raise _Transient(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response.text
            except (_Transient, httpx.TransportError) as e:
                if attempt == MAX_ATTEMPTS:
                    logger.warning(
                        "arXiv category %s failed after %d attempts: %s: %s",
                        category, MAX_ATTEMPTS, type(e).__name__, e,
                    )
                    return None
                # Exponential backoff from the configured delay, jittered so
                # concurrent categories do not retry in lockstep.
                base = max(self.source.request_delay_sec, 1.0)
                delay = base * (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.info(
                    "arXiv category %s attempt %d/%d failed (%s); retrying in %.1fs",
                    category, attempt, MAX_ATTEMPTS, type(e).__name__, delay,
                )
                await asyncio.sleep(delay)

        return None

    def _build_item(
        self, entry: dict, category: str, published_at: datetime
    ) -> Optional[ContentItem]:
        """Convert one Atom entry into a ContentItem.

        Args:
            entry: Feed entry data
            category: Category this entry was fetched under
            published_at: Parsed submission time

        Returns:
            Optional[ContentItem]: None when the entry carries no usable arXiv ID
        """
        raw_id = entry.get("id", "")
        match = _ABS_ID.search(str(raw_id))
        if not match:
            return None
        arxiv_id = match.group("id")

        title = _collapse(entry.get("title", "Untitled"))
        abstract = _collapse(entry.get("summary", ""))
        authors = [a.get("name", "") for a in entry.get("authors", []) if a.get("name")]

        tags = [t.term for t in entry.get("tags", []) if getattr(t, "term", None)]
        primary = entry.get("arxiv_primary_category", {}).get("term") or category

        haystack = f"{title}\n{abstract}".lower()
        matched = [k for k in self._keywords if k in haystack]

        return ContentItem(
            id=self._generate_id("arxiv", "paper", arxiv_id),
            source_type=SourceType.ARXIV,
            title=title,
            url=f"https://arxiv.org/abs/{arxiv_id}",
            content=abstract,
            author=", ".join(authors[:5]) or None,
            published_at=published_at,
            profile=self.source.profile,
            metadata={
                "feed_name": f"arXiv {primary}",
                "category": self.source.category,
                "arxiv_id": arxiv_id,
                "primary_category": primary,
                "authors": authors,
                "author_count": len(authors),
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                # Surfaced for AI scoring; deliberately not a hard filter.
                "matched_keywords": matched,
                "tags": tags,
            },
        )

    def _parse_date(self, entry: dict) -> Optional[datetime]:
        """Parse the submission date from an Atom entry.

        Args:
            entry: Feed entry data

        Returns:
            Optional[datetime]: Parsed submission time in UTC, or None
        """
        for field in ["published", "updated"]:
            parsed = entry.get(f"{field}_parsed")
            if parsed:
                try:
                    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
                except Exception:
                    continue
        return None


def _collapse(text: str) -> str:
    """Flatten the hard-wrapped whitespace arXiv uses in titles and abstracts."""
    return re.sub(r"\s+", " ", text or "").strip()
