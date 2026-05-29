"""Download external indices (PHLX Semiconductor ^SOX, Nasdaq Composite ^IXIC)
via yfinance into the local OHLCV store, so the CAN SLIM M-4 external-coupling
rule has dated point-in-time data.

Usage:
    python -m backend.scripts.download_external_indices --start 2010-01-01

These indices are stored under their yfinance symbols (^SOX, ^IXIC) in the same
HistoricalDataStore used for TW OHLCV; the regime builder reads them as-of date.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH, HistoricalDataStore

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ("^SOX", "^IXIC")


def fetch_index_rows(symbol: str, start: str) -> list[dict]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    frame = ticker.history(start=start, auto_adjust=False)
    rows: list[dict] = []
    if frame is None or frame.empty:
        return rows
    for index, row in frame.iterrows():
        try:
            date = index.strftime("%Y-%m-%d")
            close = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        if close <= 0:
            continue
        volume = int(row["Volume"]) if not _is_nan(row.get("Volume")) else 0
        rows.append(
            {
                "stock_id": symbol,
                "date": date,
                "open": _f(row.get("Open"), close),
                "high": _f(row.get("High"), close),
                "low": _f(row.get("Low"), close),
                "close": close,
                "volume": volume,
                "turnover": close * volume,
            }
        )
    return rows


def _f(value, fallback: float) -> float:
    try:
        out = float(value)
        return out if out > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _is_nan(value) -> bool:
    try:
        return value != value  # NaN check without importing math
    except Exception:
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2010-01-01", help="Inclusive start date YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    store = HistoricalDataStore(args.db)
    total = 0
    for symbol in args.symbols:
        logger.info("Fetching %s from %s ...", symbol, args.start)
        try:
            rows = fetch_index_rows(symbol, args.start)
        except Exception as exc:  # noqa: BLE001 - report and continue
            logger.warning("Fetch failed for %s: %s", symbol, exc)
            rows = []
        wrote = store.upsert_rows(rows) if rows else 0
        total += wrote
        logger.info("  %s -> %d rows", symbol, wrote)
    logger.info("Done. Wrote %d external-index rows to %s", total, args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
