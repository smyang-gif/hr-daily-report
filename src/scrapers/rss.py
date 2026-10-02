"""RSS feed scraper implementation."""

import asyncio
import calendar
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin, urlsplit
from email.utils import parsedate_to_datetime
import httpx
import feedparser

from .base import BaseScraper
from ..extractors import ExtractorRegistry
from ..models import ContentItem, SourceType, RSSSourceConfig

logger = logging.getLogger(__name__)

# Per-feed parallelism for link resolution and full-text extraction.
ENTRY_CONCURRENCY = 6


async def resolve_google_news_url(link: str) -> str:
    """Return the publisher URL behind a Google News article link.

    Falls back to the original link on any failure so a decoding outage only
    costs the article body, never the item itself.
    """
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        return link
    try:
        result = await asyncio.to_thread(gnewsdecoder, link, 0)
    except Exception as e:
        logger.debug("Google News decode failed for %s: %s", link, e)
        return link
    decoded = result.get("decoded_url") if isinstance(result, dict) else None
    if result.get("success") and isinstance(decoded, str) and decoded.startswith(("http://", "https://")):
        return decoded
    return link

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


class RSSScraper(BaseScraper):
    """Scraper for RSS/Atom feeds."""

    def __init__(
        self,
        sources: List[RSSSourceConfig],
        http_client: httpx.AsyncClient,
        extractors: Optional[ExtractorRegistry] = None,
    ):
        """Initialize RSS scraper.

        Args:
            sources: List of RSS feed configurations
            http_client: Shared async HTTP client
            extractors: Optional registry of content extractors for full article fetching
        """
        super().__init__({"sources": sources}, http_client)
        self._extractors = extractors

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch RSS feed items.

        Args:
            since: Only fetch items published after this time

        Returns:
            List[ContentItem]: Fetched content items
        """
        items = []
        sources = self.config["sources"]

        for source in sources:
            if not source.enabled:
                continue

            feed_items = await self._fetch_feed(source, since)
            items.extend(feed_items)

        return items

    async def _fetch_feed(
        self, source: RSSSourceConfig, since: datetime
    ) -> List[ContentItem]:
        """Fetch items from a single RSS feed.

        Args:
            source: RSS feed configuration
            since: Only fetch items after this time

        Returns:
            List[ContentItem]: Feed content items
        """
        items = []

        try:
            # Expand environment variables in URL (e.g. ${LWN_TOKEN})
            feed_url = re.sub(
                r"\$\{(\w+)\}",
                lambda m: os.environ.get(m.group(1), m.group(0)).strip(),
                str(source.url),
            )

            # Fetch feed content
            response = await self.client.get(feed_url, follow_redirects=True)
            if response.status_code == 403:
                # Some publishers (e.g. MIT SMR) reject non-browser user agents.
                response = await self.client.get(
                    feed_url, follow_redirects=True, headers=BROWSER_HEADERS
                )
            response.raise_for_status()

            # Parse feed
            feed = feedparser.parse(response.text)

            feed_id = str(source.url).split("//")[1].replace("/", "_")
            extractor = (
                self._extractors.get(source.content_extractor)
                if source.content_extractor and self._extractors
                else None
            )
            semaphore = asyncio.Semaphore(ENTRY_CONCURRENCY)

            async def build(entry) -> Optional[ContentItem]:
                published_at = self._parse_date(entry)
                if not published_at or published_at < since:
                    return None

                # Resolve relative links against the feed URL; one bad entry
                # must not discard the rest of the feed.
                link = urljoin(str(response.url), entry.get("link", "") or "")
                if not link.startswith(("http://", "https://")):
                    return None

                entry_id = entry.get("id", entry.get("link", ""))
                entry_hash = hashlib.sha256(str(entry_id).encode("utf-8")).hexdigest()[:16]
                content = self._extract_content(entry)

                async with semaphore:
                    # Google News search feeds link to a redirect page with no
                    # article text. Resolve the publisher URL so the reader gets
                    # the original link and the extractor gets the real body.
                    if urlsplit(link).hostname == "news.google.com":
                        link = await resolve_google_news_url(link)
                    if extractor:
                        full = await extractor.extract(link, self.client)
                        if full:
                            content = full

                return ContentItem(
                    id=self._generate_id("rss", feed_id, entry_hash),
                    source_type=SourceType.RSS,
                    title=entry.get("title", "Untitled"),
                    url=link,
                    content=content,
                    author=entry.get("author", source.name),
                    published_at=published_at,
                    profile=source.profile,
                    metadata={
                        "feed_name": source.name,
                        "category": source.category,
                        "selection_threshold": source.selection_threshold,
                        "tags": [tag.term for tag in entry.get("tags", [])],
                    },
                )

            async def safe_build(entry) -> Optional[ContentItem]:
                try:
                    return await build(entry)
                except Exception as e:
                    logger.warning("Skipping entry in %s: %s", source.name, e)
                    return None

            built = await asyncio.gather(*(safe_build(e) for e in feed.entries))
            items.extend(item for item in built if item is not None)

        except httpx.HTTPError as e:
            logger.warning("Error fetching RSS feed %s: %s", source.name, e)
        except Exception as e:
            logger.warning("Error parsing RSS feed %s: %s", source.name, e)

        return items

    def _parse_date(self, entry: dict) -> datetime:
        """Parse publication date from feed entry.

        Args:
            entry: Feed entry data

        Returns:
            datetime: Parsed publication date or None
        """
        # Try different date fields
        for field in ["published", "updated", "created"]:
            if field in entry:
                try:
                    # Try parsing structured time first
                    if f"{field}_parsed" in entry and entry[f"{field}_parsed"]:
                        return datetime.fromtimestamp(
                            calendar.timegm(entry[f"{field}_parsed"]), tz=timezone.utc
                        )
                    # Fallback to string parsing
                    date_str = entry[field]
                    return parsedate_to_datetime(date_str)
                except Exception:
                    continue

        return None

    def _extract_content(self, entry: dict) -> str:
        """Extract text content from feed entry.

        Args:
            entry: Feed entry data

        Returns:
            str: Extracted text content
        """
        # Try different content fields
        if "summary" in entry:
            return entry.summary
        if "description" in entry:
            return entry.description
        if "content" in entry and entry.content:
            # content is usually a list
            return entry.content[0].get("value", "")

        return ""
