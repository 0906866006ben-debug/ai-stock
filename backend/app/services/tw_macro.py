"""Macro environment data via yfinance with mock fallback."""
import asyncio
from functools import lru_cache

_TICKERS = {
    "usd_twd": "TWD=X",
    "us_10y_yield": "^TNX",
    "gold_price": "GC=F",
    "oil_wti": "CL=F",
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
}

_MOCK = {
    "usd_twd": 32.5,
    "us_10y_yield": 4.3,
    "gold_price": 2350.0,
    "oil_wti": 78.0,
    "sp500": 5200.0,
    "nasdaq": 16500.0,
    "status": "mock",
}


def _fetch_sync() -> dict:
    try:
        import yfinance as yf
        result: dict = {}
        for key, ticker in _TICKERS.items():
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="1d", auto_adjust=True)
                if not hist.empty:
                    result[key] = round(float(hist["Close"].iloc[-1]), 4)
                else:
                    result[key] = None
            except Exception:
                result[key] = None
        result["status"] = "live"
        return result
    except Exception:
        return dict(_MOCK)


async def get_macro_summary() -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_sync)
