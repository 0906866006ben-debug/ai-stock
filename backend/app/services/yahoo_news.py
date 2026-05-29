"""Yahoo Finance news fetcher with 8-category classification."""
import asyncio
import httpx
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from xml.etree import ElementTree

YAHOO_QUERY_URL = "https://query2.finance.yahoo.com/v1/finance/search"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "market": ["台股", "加權指數", "櫃買", "外資", "成交量", "大盤", "集中市場"],
    "interest": ["FED", "fed", "利率", "升息", "降息", "美債", "殖利率", "CPI", "央行", "聯準會"],
    "fx": ["匯率", "台幣", "美元", "日圓", "人民幣", "升值", "貶值", "外匯"],
    "industry": ["半導體", "AI", "人工智慧", "電子", "產業", "供應鏈", "晶片", "科技"],
    "global": ["Nasdaq", "nasdaq", "S&P", "Dow", "SOX", "NVIDIA", "TSMC", "美股", "道瓊", "那斯達克"],
    "commodity": ["原油", "黃金", "銅", "鋼鐵", "原物料", "石油", "天然氣", "農產品"],
    "geopolitics": ["台海", "中美", "科技戰", "制裁", "戰爭", "地緣", "兩岸", "烏克蘭"],
    "policy": ["政策", "法規", "補助", "電價", "碳費", "ESG", "政府", "財政", "稅"],
}

_MOCK_NEWS: dict[str, list[dict]] = {
    "market": [
        {"title": "台股今日開盤上漲，外資買超逾百億", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "market"},
        {"title": "加權指數站回月線，電子與金融同步回穩", "url": None, "source": "Mock", "published_at": "2026-05-07", "category": "market"},
        {"title": "成交量放大，市場觀望財報與美股走勢", "url": None, "source": "Mock", "published_at": "2026-05-06", "category": "market"},
    ],
    "interest": [
        {"title": "Fed維持利率不變，市場預期年底降息", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "interest"},
        {"title": "美債殖利率回落，成長股評價壓力稍緩", "url": None, "source": "Mock", "published_at": "2026-05-07", "category": "interest"},
        {"title": "央行最新談話偏審慎，資金成本仍受關注", "url": None, "source": "Mock", "published_at": "2026-05-06", "category": "interest"},
    ],
    "fx": [
        {"title": "台幣對美元小幅升值，收32.5元", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "fx"},
        {"title": "美元指數震盪，出口族群關注匯損壓力", "url": None, "source": "Mock", "published_at": "2026-05-07", "category": "fx"},
        {"title": "亞幣走勢分歧，外資匯入力道牽動台股", "url": None, "source": "Mock", "published_at": "2026-05-06", "category": "fx"},
    ],
    "industry": [
        {"title": "AI伺服器需求持續熱絡，半導體族群受惠", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "industry"},
        {"title": "晶片供應鏈拉貨延續，封測與散熱族群受關注", "url": None, "source": "Mock", "published_at": "2026-05-07", "category": "industry"},
        {"title": "電子景氣溫和復甦，法人留意下半年庫存循環", "url": None, "source": "Mock", "published_at": "2026-05-06", "category": "industry"},
    ],
    "global": [
        {"title": "那斯達克指數再創新高，科技股全面上漲", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "global"},
        {"title": "美股財報優於預期，市場風險偏好回升", "url": None, "source": "Mock", "published_at": "2026-05-07", "category": "global"},
        {"title": "歐亞股市震盪整理，投資人觀望通膨數據", "url": None, "source": "Mock", "published_at": "2026-05-06", "category": "global"},
    ],
    "commodity": [
        {"title": "國際油價小幅回落，布蘭特原油約80美元", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "commodity"},
        {"title": "黃金價格高檔整理，避險需求仍在", "url": None, "source": "Mock", "published_at": "2026-05-07", "category": "commodity"},
        {"title": "銅價回升，市場押注製造業需求改善", "url": None, "source": "Mock", "published_at": "2026-05-06", "category": "commodity"},
    ],
    "geopolitics": [
        {"title": "中美科技貿易摩擦持續，台廠密切關注", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "geopolitics"},
        {"title": "地緣政治風險升溫，供應鏈分散布局再受討論", "url": None, "source": "Mock", "published_at": "2026-05-07", "category": "geopolitics"},
        {"title": "區域衝突消息干擾市場情緒，資金偏向防禦板塊", "url": None, "source": "Mock", "published_at": "2026-05-06", "category": "geopolitics"},
    ],
    "policy": [
        {"title": "金管會推動ESG揭露新規，上市公司需遵循", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "policy"},
        {"title": "政府研議產業補助方案，科技投資題材升溫", "url": None, "source": "Mock", "published_at": "2026-05-07", "category": "policy"},
        {"title": "能源與碳費政策調整，市場重新評估成本影響", "url": None, "source": "Mock", "published_at": "2026-05-06", "category": "policy"},
    ],
}

_MIN_NEWS_PER_CATEGORY = 3


def _classify(title: str) -> str:
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in title for kw in keywords):
            return cat
    return "market"


def _top_up_categories(grouped: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Ensure each market-news category has a useful minimum number of items."""
    normalized: dict[str, list[dict]] = {}
    for category in _CATEGORY_KEYWORDS:
        existing = list(grouped.get(category, []))
        seen_titles = {item.get("title", "") for item in existing}
        for mock_item in _MOCK_NEWS.get(category, []):
            if len(existing) >= _MIN_NEWS_PER_CATEGORY:
                break
            title = mock_item.get("title", "")
            if title in seen_titles:
                continue
            existing.append(mock_item)
            seen_titles.add(title)
        normalized[category] = existing
    return normalized


async def _fetch_yahoo_news(query: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                YAHOO_QUERY_URL,
                params={"q": query, "newsCount": 20, "lang": "zh-TW"},
            )
            resp.raise_for_status()
            data = resp.json()

        items = []
        for item in data.get("news", []):
            title = item.get("title", "")
            if not title:
                continue
            pub_ts = item.get("providerPublishTime")
            pub_str = (
                datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d")
                if pub_ts
                else None
            )
            items.append({
                "title": title,
                "url": item.get("link"),
                "source": item.get("publisher"),
                "published_at": pub_str,
                "category": _classify(title),
            })
        return items
    except Exception:
        return []


FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"


async def get_tw_stock_news(symbol: str, company_name: str = "") -> list[dict]:
    """Fetch individual Taiwan stock news from FinMind TaiwanStockNews dataset.

    Returns up to 10 items sorted newest-first.
    Falls back to empty list on error (caller handles fallback).
    """
    import os
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return []

    from datetime import date, timedelta
    start = (date.today() - timedelta(days=14)).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockNews",
                    "data_id": symbol,
                    "start_date": start,
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200 or not payload.get("data"):
            return []

        rows: list[dict] = payload["data"]
        items: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            title = (row.get("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            # date field is "YYYY-MM-DD HH:MM:SS", trim to date part
            raw_date = str(row.get("date") or "")
            pub_date = raw_date[:10] if raw_date else ""
            items.append({
                "title": title,
                "url": row.get("link") or None,
                "source": row.get("source") or "FinMind",
                "published_at": pub_date,
                "category": "stock",
            })

        # Sort newest first
        items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        items = items[:10]

        # Supplement with SerpAPI when FinMind coverage is thin (< 3 items)
        if len(items) < 3:
            from .serpapi_news import get_tw_stock_news_serpapi
            serp = await get_tw_stock_news_serpapi(symbol)
            seen = {n["title"] for n in items}
            for s in serp:
                if s["title"] not in seen:
                    items.append(s)
                    seen.add(s["title"])
            items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
            items = items[:10]

        return items

    except Exception:
        return []


_AI_TECH_NAME_CACHE: dict[str, str] | None = None


def _tw_company_name(symbol: str) -> str:
    """Best-effort symbol→company-name from the AI-tech sector json (free, offline).

    Returns "" when unknown; the caller then searches Yahoo by the bare code,
    which still returns TW news for the ticker.
    """
    global _AI_TECH_NAME_CACHE
    if _AI_TECH_NAME_CACHE is None:
        import json
        from pathlib import Path

        _AI_TECH_NAME_CACHE = {}
        try:
            path = Path(__file__).resolve().parent.parent.parent / "data" / "sectors" / "ai_tech_tw.json"
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            for cat in data.get("categories", {}).values():
                for stock in cat.get("stocks", []):
                    code = str(stock.get("code", "")).strip()
                    name = str(stock.get("name", "")).strip()
                    if code and name:
                        _AI_TECH_NAME_CACHE[code] = name
        except Exception:
            _AI_TECH_NAME_CACHE = {}
    return _AI_TECH_NAME_CACHE.get(str(symbol).strip(), "")


async def _fetch_google_news_rss(query: str) -> list[dict]:
    """Per-stock news via Google News RSS (free, no API key).

    Yahoo's query2 search endpoint no longer returns a `news` array, so this is
    the working free source for per-stock catalysts. Returns rows shaped like
    `_fetch_yahoo_news` ({title, url, published_at, source, category}).
    """
    url = f"{GOOGLE_NEWS_RSS_URL}?q={quote(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            root = ElementTree.fromstring(resp.content)
    except Exception:
        return []

    items: list[dict] = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        pub_raw = (item.findtext("pubDate") or "").strip()
        pub_str: str | None = None
        if pub_raw:
            try:
                pub_str = parsedate_to_datetime(pub_raw).astimezone(timezone.utc).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                pub_str = None
        source_el = item.find("{http://news.google.com/rss}source") or item.find("source")
        source = (source_el.text or "").strip() if source_el is not None and source_el.text else "Google News"
        items.append({
            "title": title,
            "url": link,
            "source": source,
            "published_at": pub_str,
            "category": _classify(title),
        })
    return items


async def _fetch_finmind_news(symbol: str, days: int = 4) -> list[dict]:
    """Per-stock news via FinMind `TaiwanStockNews` (free, structured: title+link+
    date+source). The dataset only returns ONE day per request, so we query the
    last few calendar days. Returns [] when no token / on error (caller falls back
    to Google News RSS). Loop-free per day (cannot trigger an IP ban)."""
    from datetime import date, timedelta

    from backend.app.services.finmind_query import query_finmind

    items: list[dict] = []
    seen: set[str] = set()
    today = date.today()
    for offset in range(days):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        res = await query_finmind("TaiwanStockNews", data_id=symbol, start_date=day)
        if res.get("status") != "ok":
            if res.get("status") in {"no_token", "ip_banned", "rate_limited"}:
                break  # FinMind unusable now → let caller fall back
            continue
        for row in res.get("rows") or []:
            title = str(row.get("title") or "").strip()
            link = str(row.get("link") or "").strip()
            if not title or not link or title in seen:
                continue
            seen.add(title)
            items.append({
                "title": title,
                "url": link,
                "published_at": str(row.get("date") or "")[:10],
                "source": str(row.get("source") or "FinMind"),
                "category": _classify(title),
            })
    items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return items[:10]


async def get_tw_stock_news_yahoo(symbol: str, company_name: str = "") -> list[dict]:
    """Free per-stock news for the CANSLIM N pillar (no key required for the RSS path).

    Primary: FinMind `TaiwanStockNews` (structured title+link+date+source — best fit
    for the N-pillar source contract). Fallback: Google News RSS searched by company
    name + symbol. Returns up to 10 newest items shaped
    {title, url, published_at, source}; [] on total failure (caller handles fallback).
    """
    try:
        finmind_items = await _fetch_finmind_news(symbol)
    except Exception:
        finmind_items = []
    if finmind_items:
        return finmind_items

    name = (company_name or _tw_company_name(symbol)).strip()
    query = f"{name} {symbol}".strip() if name else str(symbol).strip()
    try:
        items = await _fetch_google_news_rss(query)
    except Exception:
        return []
    items = [it for it in items if it.get("title") and it.get("url")]
    items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return items[:10]


async def get_external_news(category: str | None = None) -> dict:
    queries = ["台股", "台灣股市", "美股 科技"]
    tasks = [asyncio.create_task(_fetch_yahoo_news(q)) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge and deduplicate
    seen: set[str] = set()
    all_items: list[dict] = []
    for batch in results:
        if isinstance(batch, list):
            for item in batch:
                title = item.get("title", "")
                if title and title not in seen:
                    seen.add(title)
                    all_items.append(item)

    if not all_items:
        categories = _top_up_categories(_MOCK_NEWS)
        if category:
            categories = {category: categories.get(category, [])}
        total = sum(len(v) for v in categories.values())
        return {"categories": categories, "total": total, "status": "mock"}

    # Group by category
    grouped: dict[str, list[dict]] = {k: [] for k in _CATEGORY_KEYWORDS}
    for item in all_items:
        grouped.setdefault(item["category"], []).append(item)

    grouped = _top_up_categories(grouped)

    if category:
        grouped = {category: grouped.get(category, [])}

    total = sum(len(v) for v in grouped.values())
    return {"categories": grouped, "total": total, "status": "live"}
