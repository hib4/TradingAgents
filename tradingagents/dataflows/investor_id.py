"""Investor.id news fetcher for Indonesian stock market sentiment.

Fetches the most recent Indonesian financial news from investor.id's
public news sitemap (``/sitemap_news.xml``), which is allowed in the
site's robots.txt.  Articles are filtered to market-relevant categories
(``/market/`` and ``/finance/``) to provide contextual sentiment for
Indonesian (.JK) tickers.

The sitemap returns up to 100 entries with ``<loc>`` (URL) and
``<lastmod>`` (ISO 8601 timestamp) but no title.  Article titles are
approximated from the URL slug (slugified Indonesian text), which is
sufficient for the LLM to understand the topic.

See: https://investor.id/sitemap_news.xml
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_SITEMAP_URL = "https://investor.id/sitemap_news.xml"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"

# URL path segments that indicate market-relevant articles.
_MARKET_CATEGORIES = ("/market/", "/finance/")

# Maximum number of articles to include in the prompt.
_DEFAULT_LIMIT = 30

# Timeout for HTTP requests (seconds).
_TIMEOUT = 10.0

# Sentinel indicating an unavailable source.
_UNAVAILABLE = "<investor.id unavailable: {reason}>"


def _slug_to_title(slug: str) -> str:
    """Convert a URL slug to a human-readable title.

    Investor.id slugs are lowercase Indonesian words separated by hyphens,
    e.g. ``"asing-masuk-saat-ihsg-terpuruk"``.
    """
    # Remove any numeric article ID prefix (e.g. "439685-...")
    slug = re.sub(r"^\d+-", "", slug)
    # Replace hyphens with spaces and title-case
    return slug.replace("-", " ").title()


def _category_from_url(url: str) -> Optional[str]:
    """Extract the category segment from an investor.id article URL.

    URLs follow the pattern ``https://investor.id/{category}/{id}/{slug}``.
    """
    # Match the first path segment after the domain
    m = re.search(r"investor\.id/([^/]+)/", url)
    return m.group(1) if m else None


def _parse_sitemap(limit: int = _DEFAULT_LIMIT, timeout: float = _TIMEOUT) -> list[dict]:
    """Fetch and parse the investor.id news sitemap.

    Returns a list of dicts with keys: ``url``, ``title``, ``date``, ``category``.
    Filtered to market-relevant categories only.
    """
    req = Request(_SITEMAP_URL, headers={"User-Agent": _UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            xml_bytes = resp.read()
    except (HTTPError, URLError) as exc:
        logger.warning("investor.id sitemap fetch failed: %s", exc)
        return []
    except TimeoutError as exc:
        logger.warning("investor.id sitemap timed out: %s", exc)
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("investor.id sitemap parse failed: %s", exc)
        return []

    # Handle both bare <url> elements and namespaced <urlset>/<url>
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    entries = []
    for url_elem in root.findall(f"{ns}url"):
        loc = url_elem.findtext(f"{ns}loc", "")
        lastmod = url_elem.findtext(f"{ns}lastmod", "")

        cat = _category_from_url(loc)
        if cat is None:
            continue

        # Filter to market-relevant categories
        if not any(loc.startswith(f"https://investor.id{cat}") for cat in _MARKET_CATEGORIES):
            continue

        # Extract slug for title approximation
        # URL pattern: https://investor.id/{category}/{id}/{slug}
        parts = loc.rstrip("/").split("/")
        slug = parts[-1] if len(parts) > 1 else ""
        title = _slug_to_title(slug) if slug else "Unknown"

        # Parse date
        date_str = lastmod
        try:
            # Handle ISO 8601 with timezone: 2026-05-20T04:43:50+07:00
            dt = datetime.fromisoformat(lastmod)
            date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

        entries.append({
            "url": loc,
            "title": title,
            "date": date_str,
            "category": cat,
        })

    return entries[:limit]


def fetch_investor_id_news(
    limit: int = _DEFAULT_LIMIT,
    timeout: float = _TIMEOUT,
) -> str:
    """Fetch recent Indonesian market news from investor.id.

    Returns a formatted plaintext block ready for prompt injection,
    or a placeholder string on failure.
    """
    entries = _parse_sitemap(limit=limit, timeout=timeout)
    if not entries:
        return _UNAVAILABLE.format(reason="no market articles found")

    lines = [
        f"Recent Indonesian market news from investor.id ({len(entries)} articles):",
        "",
    ]
    for e in entries:
        lines.append(f"- [{e['date']}] [{e['category'].upper()}] {e['title']}")
        lines.append(f"  Link: {e['url']}")
        lines.append("")

    return "\n".join(lines)
