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
    ],
    "interest": [
        {"title": "Fed維持利率不變，市場預期年底降息", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "interest"},
    ],
    "fx": [
        {"title": "台幣對美元小幅升值，收32.5元", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "fx"},
    ],
    "industry": [
        {"title": "AI伺服器需求持續熱絡，半導體族群受惠", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "industry"},
    ],
    "global": [
        {"title": "那斯達克指數再創新高，科技股全面上漲", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "global"},
    ],
    "commodity": [
        {"title": "國際油價小幅回落，布蘭特原油約80美元", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "commodity"},
    ],
    "geopolitics": [
        {"title": "中美科技貿易摩擦持續，台廠密切關注", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "geopolitics"},
    ],
    "policy": [
        {"title": "金管會推動ESG揭露新規，上市公司需遵循", "url": None, "source": "Mock", "published_at": "2026-05-08", "category": "policy"},
    ],
}


def _classify(title: str) -> str:
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in title for kw in keywords):
            return cat
    return "market"


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
        categories = _MOCK_NEWS
        if category:
            categories = {category: _MOCK_NEWS.get(category, [])}
        total = sum(len(v) for v in categories.values())
        return {"categories": categories, "total": total, "status": "mock"}

    # Group by category
    grouped: dict[str, list[dict]] = {k: [] for k in _CATEGORY_KEYWORDS}
    for item in all_items:
        grouped.setdefault(item["category"], []).append(item)

    if category:
        grouped = {category: grouped.get(category, [])}

    total = sum(len(v) for v in grouped.values())
    return {"categories": grouped, "total": total, "status": "live"}
