import yfinance as yf
from datetime import datetime, timedelta
from .tw_indicators import build_indicators, parse_indicator_query

RANGE_CONFIG = {
    "D": ("1d", "5y", 1000),
    "5D": ("1d", "10y", 2000),
    "W": ("1wk", "5y", 260),
    "M": ("1mo", "10y", 120),
    "Y": ("1mo", "20y", 240),
}

def aggregate_candles(candles: list[dict], granularity: str) -> list[dict]:
    """Aggregate daily candles into weekly/monthly/yearly candles."""
    if granularity == "1d" or not candles:
        return candles

    if granularity == "1wk":
        return _aggregate_by_week(candles)
    elif granularity == "1mo":
        return _aggregate_by_month(candles)
    return candles

def _aggregate_by_week(candles: list[dict]) -> list[dict]:
    """Group candles by ISO week."""
    weeks: dict = {}
    for candle in candles:
        date = datetime.strptime(candle["time"], "%Y-%m-%d")
        week_key = date.isocalendar()[1]  # ISO week number
        year = date.year
        key = f"{year}-W{week_key:02d}"

        if key not in weeks:
            weeks[key] = {
                "time": candle["time"],
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
            }
        else:
            weeks[key]["high"] = max(weeks[key]["high"], candle["high"])
            weeks[key]["low"] = min(weeks[key]["low"], candle["low"])
            weeks[key]["close"] = candle["close"]
            weeks[key]["volume"] += candle["volume"]

    return list(weeks.values())

def _aggregate_by_month(candles: list[dict]) -> list[dict]:
    """Group candles by month."""
    months: dict = {}
    for candle in candles:
        date = datetime.strptime(candle["time"], "%Y-%m-%d")
        key = date.strftime("%Y-%m")

        if key not in months:
            months[key] = {
                "time": candle["time"],
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
            }
        else:
            months[key]["high"] = max(months[key]["high"], candle["high"])
            months[key]["low"] = min(months[key]["low"], candle["low"])
            months[key]["close"] = candle["close"]
            months[key]["volume"] += candle["volume"]

    return list(months.values())

async def get_us_price_history(
    symbol: str,
    range: str = "D",
    include_indicators: str | None = None,
) -> dict:
    """Fetch US stock candlestick data with optional indicators."""
    try:
        range = range.upper()
        if range not in RANGE_CONFIG:
            range = "D"

        interval, period, max_candles = RANGE_CONFIG[range]

        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval="1d")

        if hist.empty:
            return {
                "symbol": symbol,
                "range": range,
                "candles": [],
                "indicators": None,
                "is_mock": True,
            }

        candles = []
        for date, row in hist.iterrows():
            try:
                candles.append({
                    "time": date.strftime("%Y-%m-%d"),
                    "open": round(float(row.get("Open", 0)), 2),
                    "high": round(float(row.get("High", 0)), 2),
                    "low": round(float(row.get("Low", 0)), 2),
                    "close": round(float(row.get("Close", 0)), 2),
                    "volume": int(row.get("Volume", 0)),
                })
            except Exception:
                continue

        candles = sorted(candles, key=lambda c: c["time"])

        # Aggregate based on granularity
        if range == "5D":
            granularity = "1d"
        elif range == "W":
            granularity = "1wk"
        elif range == "M":
            granularity = "1mo"
        elif range == "Y":
            granularity = "1mo"
        else:
            granularity = "1d"

        candles = aggregate_candles(candles, granularity)
        candles = candles[-max_candles:] if len(candles) > max_candles else candles

        indicators = None
        if include_indicators and candles:
            requested = parse_indicator_query(include_indicators)
            if requested:
                indicators = build_indicators(candles, requested)

        return {
            "symbol": symbol,
            "range": range,
            "candles": candles,
            "indicators": indicators,
            "is_mock": False,
        }
    except Exception:
        return {
            "symbol": symbol,
            "range": "D",
            "candles": [],
            "indicators": None,
            "is_mock": True,
        }
