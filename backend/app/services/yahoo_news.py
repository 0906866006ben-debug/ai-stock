"""Yahoo Finance news fetcher with 8-category classification."""
import asyncio
import httpx
from datetime import datetime

YAHOO_QUERY_URL = "https://query2.finance.yahoo.com/v1/finance/search"

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
