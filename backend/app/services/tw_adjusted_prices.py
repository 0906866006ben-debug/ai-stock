"""Self-computed dividend/split-adjusted (還原) close prices — free-tier.

FinMind's adjusted-price dataset (TaiwanStockPriceAdj) is PAID. On the free tier
we reconstruct back-adjusted prices ourselves from TaiwanStockDividendResult,
which ships the official 除權息前後參考價 (`before_price` / `after_price`). Each
ex-date contributes a ratio = after_price / before_price (< 1 for a payout); a
historical bar's adjustment factor is the product of the ratios of every ex-date
that comes AFTER it, so old prices are scaled to be comparable with today.

This module is standalone and read-only: it does NOT feed the validated CANSLIM
RS/feature pipeline (that would require a full adjusted-price backfill + re-test).
It powers a single-stock adjusted-price view/endpoint.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import httpx

from backend.app.services import file_cache
from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"


def event_ratios(dividend_rows: list[dict]) -> list[tuple[str, float]]:
    """(ex_date, after/before) ratios, ascending by date. Skips bad/empty rows."""
    out: list[tuple[str, float]] = []
    for row in dividend_rows:
        try:
            before = float(row.get("before_price"))
            after = float(row.get("after_price"))
        except (TypeError, ValueError):
            continue
        if before > 0 and after > 0:
            out.append((str(row.get("date"))[:10], after / before))
    out.sort()
    return out


def adjust_closes(price_rows: list[dict], dividend_rows: list[dict]) -> list[dict]:
    """Return price rows with an added `adj_close` (back-adjusted). Pure function."""
    ratios = event_ratios(dividend_rows)
    out: list[dict] = []
    for row in price_rows:
        d = str(row.get("date"))[:10]
        close = row.get("close")
        factor = 1.0
        for ex_date, ratio in ratios:
            if ex_date > d:
                factor *= ratio
        adj = round(close * factor, 4) if isinstance(close, (int, float)) else None
        out.append({"date": d, "close": close, "adj_close": adj})
    return out


def cached_event_ratios(symbol: str) -> list[tuple[str, float]]:
    """Dividend (ex_date, after/before) ratios from cache ONLY — no network.

    Used in the relative-strength hot loop, so it must never fetch. Returns [] when
    the symbol's dividends were not backfilled (→ adjustment becomes a no-op)."""
    cached = file_cache.load("dividend_result", symbol)
    return event_ratios(cached) if isinstance(cached, list) else []


def dividend_window_factor(symbol: str, start_date: str, end_date: str) -> float:
    """Product of dividend ratios with ex-date in (start_date, end_date] (cache-only).
    A window return is back-adjusted by DIVIDING the raw price ratio by this factor."""
    s, e = str(start_date)[:10], str(end_date)[:10]
    factor = 1.0
    for ex_date, ratio in cached_event_ratios(symbol):
        if s < ex_date <= e:
            factor *= ratio
    return factor


def _dividend_results(symbol: str) -> list[dict]:
    """Fetch TaiwanStockDividendResult (free). Cached persistently (rarely changes).
    Single request, no retry → ban-safe. Returns [] on no token / error / quota."""
    cached = file_cache.load("dividend_result", symbol)
    if isinstance(cached, list):
        return cached
    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    if not token:
        return []
    start = (date.today() - timedelta(days=4000)).strftime("%Y-%m-%d")
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(FINMIND_BASE, params={
                "dataset": "TaiwanStockDividendResult", "data_id": symbol,
                "start_date": start, "token": token,
            })
        if resp.status_code != 200:
            return []
        rows = resp.json().get("data") or []
    except Exception:
        return []
    if rows:
        file_cache.save("dividend_result", symbol, rows)
    return rows


def get_adjusted_prices(symbol: str, days: int = 250, store: HistoricalDataStore | None = None) -> dict:
    """Adjusted close series for one stock from the local OHLCV store + dividends."""
    store = store or HistoricalDataStore(DEFAULT_DB_PATH)
    start = (date.today() - timedelta(days=int(days * 1.6) + 10)).strftime("%Y-%m-%d")
    end = date.today().strftime("%Y-%m-%d")
    try:
        df = store.get_ohlcv(symbol, start, end)
    except Exception:
        df = None
    if df is None or df.empty:
        return {"symbol": symbol, "status": "no_data", "rows": [], "events": 0}

    price_rows = [{"date": str(r["date"])[:10], "close": float(r["close"])} for _, r in df.iterrows() if r.get("close") is not None]
    dividends = _dividend_results(symbol)
    rows = adjust_closes(price_rows, dividends)[-days:]
    return {
        "symbol": symbol,
        "status": "ok" if rows else "no_data",
        "events": len(event_ratios(dividends)),
        "rows": rows,
    }
