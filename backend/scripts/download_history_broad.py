"""Backfill broad CAN SLIM technology OHLCV plus TAIEX/TPEX indices.

The script is idempotent and resumable via HistoricalDataStore upserts. Re-run
it after interruption; already fetched rows are replaced by primary key. The
candidate pool comes from current FinMind TaiwanStockInfo technology/electronics
categories, so delisted historical names are still absent.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH, HistoricalDataStore
from backend.app.services.strategy.canslim.universe_source import get_tech_universe_symbols
from backend.scripts.download_history import _fetch_one

logger = logging.getLogger(__name__)

INDEX_TICKERS = {"TAIEX": "^TWII", "TPEX": "^TWOII"}


async def download_broad_history(
    *,
    days: int,
    db_path: Path | str,
    rate_limit: float,
    include_indices: bool = True,
    limit: int | None = None,
) -> dict[str, int]:
    store = HistoricalDataStore(db_path)
    symbols = get_tech_universe_symbols()
    if limit is not None:
        symbols = symbols[:limit]
    counts: dict[str, int] = {}
    logger.info("Broad technology candidate symbols: %d", len(symbols))
    for idx, symbol in enumerate(symbols, start=1):
        logger.info("(%d/%d) downloading %s", idx, len(symbols), symbol)
        rows = await _fetch_one(symbol, days)
        counts[symbol] = store.upsert_rows(rows) if rows else 0
        logger.info("  wrote %d rows", counts[symbol])
        await asyncio.sleep(rate_limit)
    if include_indices:
        for symbol, ticker in INDEX_TICKERS.items():
            rows = _fetch_index_rows(symbol, ticker, days)
            counts[symbol] = store.upsert_rows(rows) if rows else 0
            logger.info("Index %s wrote %d rows", symbol, counts[symbol])
    logger.info("DB now contains %d rows", store.row_count())
    return counts


def _fetch_index_rows(symbol: str, ticker: str, days: int) -> list[dict]:
    end = date.today() + timedelta(days=1)
    start = date.today() - timedelta(days=days)
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False, threads=False)
    if df is None or df.empty:
        return []
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    rows: list[dict] = []
    for item in df.to_dict("records"):
        open_price = float(item.get("Open") or 0)
        high = float(item.get("High") or 0)
        low = float(item.get("Low") or 0)
        close = float(item.get("Close") or 0)
        if min(open_price, high, low, close) <= 0:
            continue
        volume = int(item.get("Volume") or 0)
        rows.append(
            {
                "stock_id": symbol,
                "date": pd.Timestamp(item["Date"]).strftime("%Y-%m-%d"),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": close * volume if volume > 0 else 0,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5800, help="Lookback days, 5800 ~= 2010 to today")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--no-indices", action="store_true")
    parser.add_argument("--limit", type=int, help="Debug: only first N broad symbols")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    start = time.time()
    asyncio.run(
        download_broad_history(
            days=args.days,
            db_path=args.db,
            rate_limit=args.rate_limit,
            include_indices=not args.no_indices,
            limit=args.limit,
        )
    )
    logger.info("Done in %.1f seconds", time.time() - start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
