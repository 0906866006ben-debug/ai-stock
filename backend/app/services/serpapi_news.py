"""SerpAPI google_news fetcher for stock-specific news.

250 free searches/month — usage is guarded by:
  1. 4-hour in-memory cache (same symbol reuses cached result)
  2. Only called when the primary source returns < 3 items
"""
from __future__ import annotations

import os
import time
import re
import httpx
from datetime import date, timedelta

SERPAPI_URL = "https://serpapi.com/search"
_CACHE_TTL = 4 * 3600  # 4 hours in seconds

# {cache_key: (items, fetched_at)}
_cache: dict[str, tuple[list[dict], float]] = {}


def _parse_date(raw: str) -> str:
    """Convert SerpAPI relative/absolute date string to YYYY-MM-DD."""
    raw = raw.strip()
    today = date.today()

    # Already ISO
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw[:10]

    # "X hours/minutes ago" → today
    if re.search(r"hour|minute|分鐘|小時", raw, re.I):
        return today.isoformat()

    # "X days ago"
    m = re.search(r"(\d+)\s*day", raw, re.I)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()

    # "X weeks ago"
    m = re.search(r"(\d+)\s*week", raw, re.I)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).isoformat()

    # "X months ago"
    m = re.search(r"(\d+)\s*month", raw, re.I)
    if m:
        return (today - timedelta(days=int(m.group(1)) * 30)).isoformat()

    # "May 10, 2026" or "2026年5月10日"
    try:
        import dateutil.parser
        return dateutil.parser.parse(raw).strftime("%Y-%m-%d")
    except Exception:
        pass

    return today.isoformat()


async def _fetch_serpapi_news(
    query: str,
    hl: str = "zh-tw",
    gl: str = "tw",
    num: int = 10,
) -> list[dict]:
    """Call SerpAPI google_news. Returns [] on any error."""
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                SERPAPI_URL,
                params={
                    "engine": "google_news",
                    "q": query,
                    "api_key": api_key,
                    "hl": hl,
                    "gl": gl,
                    "num": num,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        results = payload.get("news_results") or []
        items: list[dict] = []
        for r in results:
            title = (r.get("title") or "").strip()
            if not title:
                continue
            source = r.get("source") or {}
            source_name = source.get("name") if isinstance(source, dict) else str(source)
            raw_date = r.get("date") or ""
            items.append({
                "title": title,
                "url": r.get("link") or None,
                "source": source_name or "Google News",
                "published_at": _parse_date(raw_date),
                "snippet": (r.get("snippet") or "").strip(),
            })

        return items

    except Exception:
        return []


def _cache_get(key: str) -> list[dict] | None:
    if key in _cache:
        items, fetched_at = _cache[key]
        if time.time() - fetched_at < _CACHE_TTL:
            return items
        del _cache[key]
    return None


def _cache_set(key: str, items: list[dict]) -> None:
    _cache[key] = (items, time.time())


async def get_tw_stock_news_serpapi(symbol: str, company_name: str = "") -> list[dict]:
    """Fetch TW stock news via SerpAPI google_news (zh-TW).

    Cache key: serpapi:tw:{symbol}
    """
    cache_key = f"serpapi:tw:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Build query: prefer company name if available, fallback to symbol
    query = f"{company_name} {symbol} 股票" if company_name else f"{symbol} 台股 股票"
    items = await _fetch_serpapi_news(query, hl="zh-tw", gl="tw")

    _cache_set(cache_key, items)
    return items


async def get_us_stock_news_serpapi(symbol: str) -> list[dict]:
    """Fetch US stock news via SerpAPI google_news (en).

    Cache key: serpapi:us:{symbol}
    """
    cache_key = f"serpapi:us:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    query = f"{symbol} stock news"
    items = await _fetch_serpapi_news(query, hl="en", gl="us")

    _cache_set(cache_key, items)
    return items
