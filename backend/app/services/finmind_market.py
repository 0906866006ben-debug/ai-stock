import os
import httpx
from datetime import date, timedelta

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

_MOCK_CANDLES = [
    {
        "time": f"2025-{m:02d}-01",
        "open": round(100.0 + i * 2, 2),
        "high": round(103.0 + i * 2, 2),
        "low": round(98.0 + i * 2, 2),
        "close": round(101.0 + i * 2, 2),
        "volume": 1_000_000,
    }
    for i, m in enumerate(range(11, 17))
]

_MOCK_LAST = _MOCK_CANDLES[-1]
_MOCK_PREV = _MOCK_CANDLES[-2]
_MOCK_CHANGE = round(
    (_MOCK_LAST["close"] - _MOCK_PREV["close"]) / _MOCK_PREV["close"] * 100, 2
)

_MOCK_RESULT: dict = {
    "chart_data": _MOCK_CANDLES,
    "current_price": _MOCK_LAST["close"],
    "price_change_percent": _MOCK_CHANGE,
    "volume": _MOCK_LAST["volume"],
}


def _mock_market() -> tuple[dict, bool]:
    return _MOCK_RESULT, True


async def get_tw_market_data(symbol: str) -> tuple[dict, bool]:
    """Return (market_dict, is_mock).

    market_dict keys: chart_data (list of CandlePoint dicts), current_price,
    price_change_percent, volume.
    """
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_market()

    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=180)).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockPrice",
                    "data_id": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200 or not payload.get("data"):
            return _mock_market()

        rows = sorted(payload["data"], key=lambda r: r["date"])
        chart_data = [
            {
                "time": r["date"],
                "open": float(r["open"]),
                "high": float(r["max"]),
                "low": float(r["min"]),
                "close": float(r["close"]),
                "volume": int(r["Trading_Volume"]),
            }
            for r in rows
        ]

        if not chart_data:
            return _mock_market()

        last = chart_data[-1]
        prev_close = chart_data[-2]["close"] if len(chart_data) >= 2 else last["close"]
        price_change = (
            round((last["close"] - prev_close) / prev_close * 100, 2)
            if prev_close
            else 0.0
        )

        return {
            "chart_data": chart_data,
            "current_price": last["close"],
            "price_change_percent": price_change,
            "volume": last["volume"],
        }, False

    except Exception:
        return _mock_market()
