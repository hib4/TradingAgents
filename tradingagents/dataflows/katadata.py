"""Katadata news fetcher for Indonesian stock market sentiment.

Fetches recent Indonesian business and financial news from katadata.co.id's
public RSS feed.  The feed (RSS 2.0) provides article titles, URLs, dates,
categories, and authors.  Articles are filtered to stock-relevant categories
to provide contextual sentiment for Indonesian (.JK) tickers.

The RSS feed has no article body content (``<description>`` is always empty),
so headlines alone drive the sentiment signal — which is sufficient for the
LLM to identify market direction, corporate actions, and macro context.

See: https://katadata.co.id/rss
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_RSS_URL = "https://katadata.co.id/rss"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"

# Categories relevant to Indonesian stock market sentiment.
_STOCK_CATEGORIES = frozenset({"Bursa", "Korporasi", "Makro", "Keuangan"})

# Maximum number of articles to include in the prompt.
_DEFAULT_LIMIT = 30

# Timeout for HTTP requests (seconds).
_TIMEOUT = 10.0

# Sentinel indicating an unavailable source.
_UNAVAILABLE = "<katadata.co.id unavailable: {reason}>"

# XML namespaces used in the RSS feed.
_DC_NS = "http://purl.org/dc/elements/1.1/"


def _find_text(elem: ET.Element, tag: str, namespace: str = "") -> Optional[str]:
    """Extract text from a child element, optionally with a namespace."""
    if namespace:
        child = elem.find(f"{{{namespace}}}{tag}")
        if child is not None and child.text:
            return child.text.strip()
    child = elem.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _parse_rss(limit: int = _DEFAULT_LIMIT, timeout: float = _TIMEOUT) -> list[dict]:
    """Fetch and parse the katadata.co.id RSS feed.

    Returns a list of dicts with keys: ``title``, ``url``, ``date``,
    ``category``, ``author``.  Filtered to stock-relevant categories only.
    """
    req = Request(_RSS_URL, headers={"User-Agent": _UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            xml_bytes = resp.read()
    except (HTTPError, URLError) as exc:
        logger.warning("katadata RSS feed fetch failed: %s", exc)
        return []
    except TimeoutError as exc:
        logger.warning("katadata RSS feed timed out: %s", exc)
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("katadata RSS feed parse failed: %s", exc)
        return []

    entries = []
    for item in root.findall(".//item"):
        category = _find_text(item, "category")
        if category not in _STOCK_CATEGORIES:
            continue

        title = _find_text(item, "title")
        link = _find_text(item, "link")
        pubdate_str = _find_text(item, "pubDate")
        author = _find_text(item, "creator", _DC_NS)

        # Parse date
        date_str = pubdate_str or ""
        if pubdate_str:
            try:
                dt = parsedate_to_datetime(pubdate_str)
                date_str = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        entries.append({
            "title": title or "Unknown",
            "url": link or "",
            "date": date_str,
            "category": category,
            "author": author or "",
        })

        if len(entries) >= limit:
            break

    return entries


def fetch_katadata_news(
    limit: int = _DEFAULT_LIMIT,
    timeout: float = _TIMEOUT,
) -> str:
    """Fetch recent Indonesian business/financial news from katadata.co.id.

    Returns a formatted plaintext block ready for prompt injection,
    or a placeholder string on failure.
    """
    entries = _parse_rss(limit=limit, timeout=timeout)
    if not entries:
        return _UNAVAILABLE.format(reason="no stock-relevant articles found")

    lines = [
        f"Recent Indonesian market news from katadata.co.id ({len(entries)} articles):",
        "",
    ]
    for e in entries:
        author_part = f" by {e['author']}" if e['author'] else ""
        lines.append(f"- [{e['date']}] [{e['category']}] {e['title']}{author_part}")
        if e['url']:
            lines.append(f"  Link: {e['url']}")
        lines.append("")

    return "\n".join(lines)
