"""Backfill TaiwanStockDividendResult (除權息結果, free) for every stock in the
OHLCV store, warming the per-symbol cache used by dividend-adjusted relative
strength (AISTOCK_ADJUSTED_RS=1).

Ban-safe: one request per symbol, rate-limited, no retry on errors. Resumable —
already-cached symbols are skipped, so re-running continues where it left off.

    python -m backend.scripts.download_dividends --rate-limit 1.0
"""
from __future__ import annotations

import argparse
import logging
import time

from backend.scripts._env import load_backend_env
from backend.app.services import file_cache
from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH
from backend.app.services.tw_adjusted_prices import _dividend_results

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--rate-limit", type=float, default=1.0, help="Sleep seconds between symbols")
    parser.add_argument("--stocks", nargs="*", help="Override universe with explicit codes")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if already cached")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (leak FinMind token)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_backend_env()

    stocks = args.stocks or HistoricalDataStore(args.db).list_stocks()
    logger.info("Backfilling dividends for %d symbols -> cache", len(stocks))

    fetched = skipped = empty = 0
    for i, symbol in enumerate(stocks, 1):
        if (not args.force) and isinstance(file_cache.load("dividend_result", symbol), list):
            skipped += 1
            continue
        rows = _dividend_results(symbol)  # fetches + caches (ban-safe, no retry)
        if rows:
            fetched += 1
        else:
            empty += 1
        if i % 100 == 0:
            logger.info("(%d/%d) fetched=%d skipped=%d empty=%d", i, len(stocks), fetched, skipped, empty)
        time.sleep(max(0.0, args.rate_limit))

    logger.info("Done. fetched=%d skipped=%d empty=%d", fetched, skipped, empty)
    logger.info("Enable adjusted RS with AISTOCK_ADJUSTED_RS=1 (then re-validate the backtest before relying on it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
