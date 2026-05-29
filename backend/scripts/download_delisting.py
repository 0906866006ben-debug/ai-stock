"""Backfill OHLCV for already-delisted TW stocks (survivorship-bias correction).

FinMind's current TaiwanStockInfo list (used to build the backtest universe)
contains only listed securities, so the backtest never sees companies that later
delisted — an upward survivorship bias. This script pulls TaiwanStockDelisting
(free), then fetches each delisted symbol's historical TaiwanStockPrice (free)
into the same OHLCV store the backtest reads. Once these bars exist, enable the
survivorship-corrected run with AISTOCK_INCLUDE_DELISTED=1 (the per-date
staleness guard in pit_universe then drops each name on its delisting date).

Ban-safe: one request per symbol, rate-limited, no retry. Resumable — symbols
already present in the store are skipped, so re-running continues where it left.

    python -m backend.scripts.download_delisting --rate-limit 1.0
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import date, datetime, timedelta

import httpx

from backend.scripts._env import load_backend_env
from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH
from backend.app.services.strategy.canslim.universe_source import fetch_delisted_stocks, parse_delisted_symbols

logger = logging.getLogger(__name__)

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"


def _delisting_date_map(rows: list[dict]) -> dict[str, str]:
    """symbol -> latest delisting date string (YYYY-MM-DD), common stocks only."""
    out: dict[str, str] = {}
    valid = set(parse_delisted_symbols(rows))
    for row in rows:
        code = str(row.get("stock_id") or row.get("stock_code") or "").strip()
        if code not in valid:
            continue
        d = str(row.get("date") or "")[:10]
        if d and (code not in out or d > out[code]):
            out[code] = d
    return out


def _fetch_price(client: httpx.Client, symbol: str, start_date: str, end_date: str, token: str) -> list[dict]:
    """One ban-safe TaiwanStockPrice request → normalized OHLCV rows for the store."""
    try:
        resp = client.get(FINMIND_BASE, params={
            "dataset": "TaiwanStockPrice", "data_id": symbol,
            "start_date": start_date, "end_date": end_date, "token": token,
        })
        if resp.status_code != 200:
            logger.warning("  %s: HTTP %s — skipping", symbol, resp.status_code)
            return []
        data = resp.json().get("data") or []
    except Exception as exc:
        logger.warning("  %s: fetch failed (%s)", symbol, str(exc)[:120])
        return []

    rows: list[dict] = []
    for c in data:
        d = str(c.get("date") or "")[:10]
        try:
            open_p = float(c.get("open") or 0)
            high = float(c.get("max") or 0)
            low = float(c.get("min") or 0)
            close = float(c.get("close") or 0)
        except (TypeError, ValueError):
            continue
        if not d or min(open_p, high, low, close) <= 0:
            continue
        volume = int(c.get("Trading_Volume") or 0)
        turnover = float(c.get("Trading_money") or 0)
        if turnover <= 0 and close > 0 and volume > 0:
            turnover = close * volume
        rows.append({
            "stock_id": symbol, "date": d, "open": open_p, "high": high,
            "low": low, "close": close, "volume": volume, "turnover": turnover,
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--rate-limit", type=float, default=1.0, help="Sleep seconds between symbols")
    parser.add_argument("--history-years", type=int, default=6, help="Years of price history before each delisting date")
    parser.add_argument("--stocks", nargs="*", help="Override with explicit delisted codes")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if symbol already has bars")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_backend_env()

    import os
    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    if not token:
        logger.error("FINMIND_API_KEY not set — cannot fetch delisting list or prices.")
        return 2

    rows = fetch_delisted_stocks(token)
    delist_dates = _delisting_date_map(rows)
    symbols = args.stocks or sorted(delist_dates)
    if not symbols:
        logger.error("No delisted symbols resolved (check FINMIND_API_KEY / quota).")
        return 2
    logger.info("Backfilling OHLCV for %d delisted symbols -> %s", len(symbols), args.db)

    store = HistoricalDataStore(args.db)
    fetched = skipped = empty = total_rows = 0
    with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for i, symbol in enumerate(symbols, 1):
            if (not args.force) and store.get_latest_date(symbol):
                skipped += 1
                continue
            end_str = delist_dates.get(symbol) or date.today().strftime("%Y-%m-%d")
            try:
                end_dt = datetime.strptime(end_str, "%Y-%m-%d").date()
            except ValueError:
                end_dt = date.today()
            start_str = (end_dt - timedelta(days=int(args.history_years * 365.25))).strftime("%Y-%m-%d")
            price_rows = _fetch_price(client, symbol, start_str, end_str, token)
            if price_rows:
                n = store.upsert_rows(price_rows)
                total_rows += n
                fetched += 1
            else:
                empty += 1
            if i % 50 == 0:
                logger.info("(%d/%d) fetched=%d skipped=%d empty=%d rows=%d", i, len(symbols), fetched, skipped, empty, total_rows)
            time.sleep(max(0.0, args.rate_limit))

    logger.info("Done. fetched=%d skipped=%d empty=%d total_rows=%d", fetched, skipped, empty, total_rows)
    logger.info("Enable survivorship-corrected backtest with AISTOCK_INCLUDE_DELISTED=1 (then re-validate before relying on it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
