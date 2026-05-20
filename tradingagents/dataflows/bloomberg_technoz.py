"""BloombergTechnoz news fetcher for Indonesian stock market sentiment.

Fetches recent Indonesian financial news from bloombergtechnoz.com's
public RSS feed.  The feed provides article titles, URLs, and publication
dates.  Articles are filtered to market-relevant URL path segments to
provide contextual sentiment for Indonesian (.JK) tickers.

Note: bloombergtechnoz.com is operated by Berita Mediatama Indonesia and
is not affiliated with Bloomberg LP.  It publishes daily IHSG analysis,
stock recommendations, macro policy coverage, and energy/commodities news.

See: https://www.bloombergtechnoz.com/rss
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

_RSS_URL = "https://www.bloombergtechnoz.com/rss"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"

# URL path segments that indicate market-relevant articles.
# /pasar-modal    — stock exchange coverage (IHSG, individual stocks)
# /ekonomi-dan-investasi — macro policy, investment analysis
# /detail-news    — individual article pages (we'll catch these via link extraction)
# /finansial      — banking, financial sector (appears in some URLs)
# /energi         — energy/commodities (coal, oil, minerals — relevant for IDX)
_MARKET_PATHS = ("/pasar-modal", "/ekonomi-dan-investasi", "/detail-news", "/finansial", "/energi")

# Maximum number of articles to include in the prompt.
_DEFAULT_LIMIT = 30

# Timeout for HTTP requests (seconds).
_TIMEOUT = 10.0

# Sentinel indicating an unavailable source.
_UNAVAILABLE = "<bloombergtechnoz.com unavailable: {reason}>"

# Indonesian keywords in titles used to infer article category.
_CAT_KEYWORDS = {
    "Market": ["IHSG", "saham", "IDX", "bursa", "LQ45", "emiten", "dividen", "IPO", "right issue", "rekomendasi saham", "analisis teknikal"],
    "Economy": ["APBN", "BI Rate", "inflasi", "PDB", "pertumbuhan ekonomi", "rupiah", "USD/IDR", "nilai tukar", "fiskal", "moneter", "anggaran"],
    "Financial": ["bank", "OJK", "kredit", "asuransi", "BPR", "fintech", "perbankan", "Himbara", "BSI", "BNI", "BRI", "Mandiri"],
    "Energy": ["batubara", "minyak", "gas", "batubara", "nikel", "tambang", "energi", "CPO", "sawit", "komoditas", "pertambangan", "Pertamax"],
    "Global": ["The Fed", "Wall Street", "S&P", "Nasdaq", "Dow Jones", "global", "internasional"],
}


def _is_market_relevant(link: str) -> bool:
    """Return True if the article URL matches a market-relevant path."""
    return any(path in link for path in _MARKET_PATHS) if link else False


def _infer_category(title: str, link: str) -> str:
    """Infer a category from the article title and URL."""
    text = (title + " " + link).lower()
    for category, keywords in _CAT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                return category
    return "News"


def _parse_rss(limit: int = _DEFAULT_LIMIT, timeout: float = _TIMEOUT) -> list[dict]:
    """Fetch and parse the bloombergtechnoz.com RSS feed.

    Returns a list of dicts with keys: ``title``, ``url``, ``date``, ``category``.
    Filtered to market-relevant articles only.
    """
    req = Request(_RSS_URL, headers={"User-Agent": _UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            xml_bytes = resp.read()
    except (HTTPError, URLError) as exc:
        logger.warning("bloombergtechnoz RSS feed fetch failed: %s", exc)
        return []
    except TimeoutError as exc:
        logger.warning("bloombergtechnoz RSS feed timed out: %s", exc)
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("bloombergtechnoz RSS feed parse failed: %s", exc)
        return []

    entries = []
    for item in root.findall(".//item"):
        title_elem = item.find("title")
        link_elem = item.find("link")
        pubdate_elem = item.find("pubDate")

        title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
        link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
        pubdate_str = pubdate_elem.text.strip() if pubdate_elem is not None and pubdate_elem.text else ""

        # Skip non-market articles
        if not _is_market_relevant(link):
            continue

        # Parse date
        date_str = pubdate_str
        if pubdate_str:
            try:
                dt = parsedate_to_datetime(pubdate_str)
                date_str = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        category = _infer_category(title, link)

        entries.append({
            "title": title or "Unknown",
            "url": link or "",
            "date": date_str,
            "category": category,
        })

        if len(entries) >= limit:
            break

    return entries


def fetch_bloomberg_technoz_news(
    limit: int = _DEFAULT_LIMIT,
    timeout: float = _TIMEOUT,
) -> str:
    """Fetch recent Indonesian market/financial news from bloombergtechnoz.com.

    Returns a formatted plaintext block ready for prompt injection,
    or a placeholder string on failure.
    """
    entries = _parse_rss(limit=limit, timeout=timeout)
    if not entries:
        return _UNAVAILABLE.format(reason="no market articles found")

    lines = [
        f"Recent Indonesian market news from bloombergtechnoz.com ({len(entries)} articles):",
        "",
    ]
    for e in entries:
        lines.append(f"- [{e['date']}] [{e['category']}] {e['title']}")
        if e['url']:
            lines.append(f"  Link: {e['url']}")
        lines.append("")

    return "\n".join(lines)
