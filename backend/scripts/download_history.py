"""Download historical OHLCV from FinMind/yfinance into local SQLite cache.

Usage:
    # Download AI Tech whitelist for 2022-2024
    python -m backend.scripts.download_history --start 2022-01-01 --end 2024-12-31

    # Download specific stocks
    python -m backend.scripts.download_history --stocks 2330 2454 6669 --start 2023-01-01

The script is idempotent — re-running fills only missing bars.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from backend.scripts._env import load_backend_env
from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH
from backend.app.services.finmind_market import get_tw_price_history_with_source
from backend.app.services.strategy.canslim.universe_source import get_all_universe_symbols, get_tech_universe_symbols


logger = logging.getLogger(__name__)


def load_ai_tech_codes(json_path: Path) -> list[str]:
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    codes: list[str] = []
    for cat in data.get("categories", {}).values():
        for stock in cat.get("stocks", []):
            code = str(stock.get("code", "")).strip()
            if code:
                codes.append(code)
    return codes


async def _fetch_one(stock_id: str, days: int) -> list[dict]:
    """Fetch via existing finmind_market service. Returns normalized rows."""
    try:
        result = await get_tw_price_history_with_source(stock_id, days)
    except Exception as exc:
        logger.warning("Fetch failed for %s: %s", stock_id, exc)
        return []

    candles = result.candles or []
    rows = []
    for c in candles:
        # Source may use "date" or "time" as the date key
        date_val = c.get("date") or c.get("time")
        if not date_val:
            continue
        close = float(c.get("close", 0) or 0)
        open_price = float(c.get("open", 0) or 0)
        high = float(c.get("high", 0) or 0)
        low = float(c.get("low", 0) or 0)
        if min(open_price, high, low, close) <= 0:
            continue
        volume = int(c.get("volume", 0) or 0)
        turnover = float(c.get("turnover", c.get("turnover_value", 0)) or 0)
        # yfinance fallback for TW stocks doesn't return turnover_value.
        # Compute as close × volume so the liquidity gate works.
        if turnover <= 0 and close > 0 and volume > 0:
            turnover = close * volume
        rows.append({
            "stock_id": stock_id,
            "date": str(date_val)[:10],
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "turnover": turnover,
        })
    return rows


async def download_all(stocks: list[str], days: int, store: HistoricalDataStore, rate_limit_sec: float = 0.5) -> int:
    total = 0
    for i, stock_id in enumerate(stocks):
        logger.info("(%d/%d) downloading %s...", i + 1, len(stocks), stock_id)
        rows = await _fetch_one(stock_id, days)
        if rows:
            n = store.upsert_rows(rows)
            total += n
            logger.info("  → wrote %d rows", n)
        else:
            logger.warning("  → no data for %s", stock_id)
        await asyncio.sleep(rate_limit_sec)   # rate limiting
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=False, help="Inclusive start date YYYY-MM-DD (informational; FinMind uses days lookback)")
    parser.add_argument("--end", required=False, help="Inclusive end date YYYY-MM-DD (informational)")
    parser.add_argument("--days", type=int, default=1500, help="Lookback days from today (default ~4 years)")
    parser.add_argument("--stocks", nargs="*", help="Override universe with explicit stock codes")
    parser.add_argument(
        "--universe-source",
        choices=("file", "broad", "all", "all+etf"),
        default="file",
        help="Universe source when --stocks is not given. file=--universe-file JSON; broad=tech industries; all=every listed common stock; all+etf also includes ETFs (for price-only).",
    )
    parser.add_argument(
        "--universe-file",
        default=str(Path(__file__).resolve().parent.parent / "data" / "sectors" / "ai_tech_tw.json"),
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--rate-limit", type=float, default=0.5, help="Sleep seconds between requests")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    load_backend_env()  # ensure FINMIND_API_KEY is available for universe + price fetches

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    if args.stocks:
        stocks = args.stocks
    elif args.universe_source == "broad":
        stocks = get_tech_universe_symbols()
    elif args.universe_source == "all":
        stocks = get_all_universe_symbols(include_etf=False)
    elif args.universe_source == "all+etf":
        stocks = get_all_universe_symbols(include_etf=True)
    else:
        universe_path = Path(args.universe_file)
        if not universe_path.exists():
            logger.error("Universe file not found: %s", universe_path)
            return 2
        stocks = load_ai_tech_codes(universe_path)

    if not stocks:
        logger.error("Universe resolved to zero stocks (check FINMIND_API_KEY for --universe-source all/broad)")
        return 2

    logger.info("Downloading %d stocks, ~%d days each, to %s", len(stocks), args.days, args.db)

    store = HistoricalDataStore(args.db)
    start_time = time.time()
    total = asyncio.run(download_all(stocks, args.days, store, args.rate_limit))
    elapsed = time.time() - start_time
    logger.info("Done. Wrote %d total rows in %.1f seconds.", total, elapsed)
    logger.info("DB now contains %d rows.", store.row_count())
    return 0


if __name__ == "__main__":
    sys.exit(main())
