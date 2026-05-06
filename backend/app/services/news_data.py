import os
from datetime import datetime, timezone

MOCK_NEWS = [
    {
        "title": f"Demo: {sym} reports strong quarterly results",
        "published_at": "2026-05-07T10:00:00Z",
        "source": "Demo News",
        "url": None,
    }
    for sym in ["DEMO"]
]

_MOCK_HEADLINES = [
    "Company reports quarterly earnings beat estimates",
    "Analysts upgrade rating amid strong product demand",
    "New product launch expected to drive revenue growth",
]


def _make_mock(symbol: str) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {"title": f"{symbol}: {h}", "published_at": now, "source": "Demo", "url": None}
        for h in _MOCK_HEADLINES
    ]


async def get_news_data(symbol: str) -> list[dict]:
    api_key = os.getenv("FINNHUB_API_KEY")
    if api_key:
        try:
            import finnhub
            from datetime import date, timedelta

            client = finnhub.Client(api_key=api_key)
            to_date = date.today().isoformat()
            from_date = (date.today() - timedelta(days=7)).isoformat()
            items = client.company_news(symbol, _from=from_date, to=to_date) or []
            result = []
            for item in items[:10]:
                ts = item.get("datetime", 0)
                published = (
                    datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                    if ts else ""
                )
                result.append({
                    "title": item.get("headline", ""),
                    "published_at": published,
                    "source": item.get("source", ""),
                    "url": item.get("url") or None,
                })
            return result if result else _make_mock(symbol)
        except Exception:
            pass

    return _make_mock(symbol)
