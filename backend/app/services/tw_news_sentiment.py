"""
Taiwan stock news and sentiment analysis.

Fetches recent news headlines and classifies sentiment.
Identifies catalysts and macro impacts.
"""
import os

# Mock news data
_MOCK_NEWS = {
    "2330": [
        {
            "title": "台積電Q1營收創新高，EPS達8.83元",
            "source": "經濟日報",
            "date": "2025-05-08",
            "sentiment": "positive",
            "impact": "short_term",
            "relevance": 0.95,
        },
        {
            "title": "美國芯片製造補助法案推進，台積電受惠",
            "source": "中央社",
            "date": "2025-05-06",
            "sentiment": "positive",
            "impact": "long_term",
            "relevance": 0.85,
        },
        {
            "title": "AI芯片需求放緩，業界憂景氣",
            "source": "自由時報",
            "date": "2025-05-03",
            "sentiment": "negative",
            "impact": "long_term",
            "relevance": 0.80,
        },
    ],
    "0050": [
        {
            "title": "台股加權指數突破20000點，ETF受追捧",
            "source": "聯合新聞網",
            "date": "2025-05-08",
            "sentiment": "positive",
            "impact": "short_term",
            "relevance": 0.75,
        },
        {
            "title": "元大0050成分股營收普遍增長",
            "source": "經濟日報",
            "date": "2025-05-05",
            "sentiment": "positive",
            "impact": "long_term",
            "relevance": 0.70,
        },
    ],
}


_POSITIVE_TERMS = (
    "創新高", "新高", "成長", "大漲", "看好", "利多", "突破", "獲利", "訂單", "受惠",
    "強勁", "上修", "飆", "走揚", "回升", "樂觀", "擴產", "增資", "得標", "認列",
)
_NEGATIVE_TERMS = (
    "下跌", "虧損", "看壞", "利空", "衰退", "下修", "疲弱", "賣壓", "示警", "重挫",
    "警示", "跌停", "減資", "違約", "下滑", "保守", "裁員", "停工", "認賠", "降評",
)


def _classify_sentiment(title: str) -> str:
    """Keyword seed sentiment for a headline. The news agent's LLM still does the
    nuanced read; this only seeds the aggregate counts when real news is used."""
    text = title or ""
    pos = sum(1 for kw in _POSITIVE_TERMS if kw in text)
    neg = sum(1 for kw in _NEGATIVE_TERMS if kw in text)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


async def get_tw_news(symbol: str) -> tuple[list[dict], bool]:
    """
    Fetch Taiwan stock news and sentiment.

    Returns: (news_list, is_mock)

    news_list items have keys:
      title, source, date, sentiment (positive|negative|neutral),
      impact (short_term|long_term|both), relevance (0-1), url

    Primary source: real per-stock headlines via Google News RSS (no key needed,
    same free fetcher the CANSLIM N pillar uses). Falls back to mock only when no
    real news is returned, so the news agent runs on real headlines when available.
    """
    rows: list[dict] = []
    if not os.getenv("AISTOCK_DISABLE_LIVE_NEWS"):  # offline/test guard
        try:
            from backend.app.services.yahoo_news import get_tw_stock_news_yahoo
            rows = await get_tw_stock_news_yahoo(symbol)
        except Exception:
            rows = []

    if rows:
        items = [
            {
                "title": r.get("title") or "",
                "source": r.get("source") or "Google News",
                "date": r.get("published_at") or "",
                "sentiment": _classify_sentiment(r.get("title") or ""),
                "impact": "short_term",
                "relevance": 0.6,
                "url": r.get("url"),
            }
            for r in rows
            if r.get("title")
        ]
        if items:
            return items, False

    if symbol in _MOCK_NEWS:
        return _MOCK_NEWS[symbol].copy(), True

    # Generate generic mock for unknown symbols
    generic_news = [
        {
            "title": f"{symbol}最新市場動態",
            "source": "市場新聞",
            "date": "2025-05-08",
            "sentiment": "neutral",
            "impact": "short_term",
            "relevance": 0.50,
        },
    ]

    return generic_news, True


def calculate_sentiment_aggregate(news_list: list[dict]) -> dict:
    """
    Calculate aggregate sentiment from news list.

    Returns: {
        "bullish_count": int,
        "neutral_count": int,
        "bearish_count": int,
        "overall_score": float (0-1),
        "trend": "improving"|"stable"|"deteriorating"
    }
    """
    bullish = sum(1 for n in news_list if n.get("sentiment") == "positive")
    neutral = sum(1 for n in news_list if n.get("sentiment") == "neutral")
    bearish = sum(1 for n in news_list if n.get("sentiment") == "negative")

    total = len(news_list)
    if total == 0:
        return {"bullish_count": 0, "neutral_count": 0, "bearish_count": 0, "overall_score": 0.5, "trend": "stable"}

    # Score: positive is 1.0, neutral is 0.5, negative is 0.0
    total_score = bullish * 1.0 + neutral * 0.5 + bearish * 0.0
    overall_score = total_score / total

    # Trend
    if overall_score > 0.65:
        trend = "improving"
    elif overall_score < 0.35:
        trend = "deteriorating"
    else:
        trend = "stable"

    return {
        "bullish_count": bullish,
        "neutral_count": neutral,
        "bearish_count": bearish,
        "overall_score": overall_score,
        "trend": trend,
    }
