import os
import httpx
from datetime import date, timedelta

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

# Realistic mock prices for common Taiwan stocks
_MOCK_PRICES = {
    "2330": {"base": 2290, "volume": 50_000_000},    # TSMC
    "0050": {"base": 130, "volume": 5_000_000},      # 0050 ETF
    "0056": {"base": 50, "volume": 8_000_000},       # 0056 ETF
    "2454": {"base": 1180, "volume": 15_000_000},    # MediaTek
    "2317": {"base": 155, "volume": 80_000_000},     # Foxconn
}


def _generate_mock_candles(symbol: str, days: int = 120) -> list[dict]:
    """Generate realistic mock OHLCV data for a given symbol."""
    prices = _MOCK_PRICES.get(symbol, {"base": 100, "volume": 1_000_000})
    base_price = prices["base"]
    base_volume = prices["volume"]

    candles = []
    current_price = base_price

    for i in range(days, 0, -1):
        from datetime import date, timedelta
        trading_date = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")

        # Add realistic daily movement (-2% to +2%)
        daily_change = (i % 13 - 6) * 0.3 / 100  # Cyclical pattern
        open_price = current_price
        close_price = current_price * (1 + daily_change)
        high_price = max(open_price, close_price) * 1.01
        low_price = min(open_price, close_price) * 0.99

        # Add volume variation
        volume = int(base_volume * (0.8 + (i % 7) * 0.05))

        candles.append({
            "time": trading_date,
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })

        current_price = close_price

    return candles


_MOCK_CANDLES = _generate_mock_candles("2330")

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


def _mock_market(symbol: str) -> tuple[dict, bool]:
    """Generate realistic mock market data for a Taiwan stock."""
    candles = _generate_mock_candles(symbol)
    if not candles:
        return _MOCK_RESULT, True

    last = candles[-1]
    prev = candles[-2] if len(candles) > 1 else last
    change = round((last["close"] - prev["close"]) / prev["close"] * 100, 2)

    return {
        "chart_data": candles,
        "current_price": last["close"],
        "price_change_percent": change,
        "volume": last["volume"],
    }, True


async def get_tw_price_history(symbol: str, days: int) -> tuple[list[dict], bool]:
    """Fetch raw daily candles for the past `days` days. Returns (candles, is_mock)."""
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        candles = _generate_mock_candles(symbol, days)
        return candles, True

    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
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
            return _MOCK_CANDLES, True
        rows = sorted(payload["data"], key=lambda r: r["date"])
        candles = [
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
        return (candles, False) if candles else (_MOCK_CANDLES, True)
    except Exception:
        return _MOCK_CANDLES, True


async def get_tw_market_data(symbol: str) -> tuple[dict, bool]:
    """Return (market_dict, is_mock).

    market_dict keys: chart_data (list of CandlePoint dicts), current_price,
    price_change_percent, volume.
    """
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_market(symbol)

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
            return _mock_market(symbol)

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
            return _mock_market(symbol)

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
        return _mock_market(symbol)
