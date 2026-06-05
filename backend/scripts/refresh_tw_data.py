"""Run scheduled Taiwan data refreshes without full re-downloads.

Recommended cadence:
    daily:    stock master + OHLCV incremental + daily chip/valuation datasets
    monthly:  monthly revenue window
    quarterly financial statements / balance sheet / cash flow window

Examples:
    .venv\\Scripts\\python backend/scripts/refresh_tw_data.py daily --universe-source ohlcv
    .venv\\Scripts\\python backend/scripts/refresh_tw_data.py monthly --universe-source ohlcv
    .venv\\Scripts\\python backend/scripts/refresh_tw_data.py quarterly --universe-source ohlcv
    .venv\\Scripts\\python backend/scripts/refresh_tw_data.py daily --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.scripts._env import load_backend_env
from backend.scripts import download_fundamentals, download_history
from backend.app.services.tw_stocks_list import refresh_stock_master_cache

logger = logging.getLogger(__name__)

DAILY_DATASETS = (
    "TaiwanStockInstitutionalInvestorsBuySell",
    "TaiwanStockMarginPurchaseShortSale",
    "TaiwanStockPER",
)
MONTHLY_DATASETS = ("TaiwanStockMonthRevenue",)
QUARTERLY_DATASETS = (
    "TaiwanStockFinancialStatements",
    "TaiwanStockBalanceSheet",
    "TaiwanStockCashFlowsStatement",
)


def _days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _run_step(name: str, func, argv: list[str], *, dry_run: bool) -> int:
    logger.info("%s: %s", name, " ".join(argv))
    if dry_run:
        return 0
    return int(func(argv))


def _history_args(args: argparse.Namespace) -> list[str]:
    out = [
        "--universe-source",
        args.universe_source,
        "--db",
        args.ohlcv_db,
        "--rate-limit",
        str(args.rate_limit),
        "--incremental",
        "--min-days",
        str(args.price_min_days),
        "--buffer-days",
        str(args.price_buffer_days),
        "--max-days",
        str(args.price_max_days),
    ]
    if args.limit_stocks:
        out.extend(["--stocks", *args.limit_stocks])
    return out


def _fundamental_universe_source(args: argparse.Namespace) -> str:
    if args.fundamental_universe_source:
        return str(args.fundamental_universe_source)
    if args.universe_source == "all+etf":
        return "all"
    if args.universe_source == "file":
        return "ai_tech"
    return str(args.universe_source)


def _fundamental_args(args: argparse.Namespace, datasets: tuple[str, ...], start_date: str) -> list[str]:
    out = [
        "--start",
        start_date,
        "--universe-source",
        _fundamental_universe_source(args),
        "--db",
        args.pit_db,
        "--ohlcv-db",
        args.ohlcv_db,
        "--rate-limit",
        str(args.rate_limit),
        "--datasets",
        *datasets,
        "--max-consecutive-failures",
        str(args.max_consecutive_failures),
        "--no-progress",
    ]
    if args.limit_stocks:
        out.extend(["--stocks", *args.limit_stocks])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Taiwan stock data by cadence.")
    parser.add_argument("cadence", choices=("daily", "monthly", "quarterly", "all"))
    parser.add_argument("--universe-source", choices=("ohlcv", "file", "broad", "all", "all+etf"), default="ohlcv")
    parser.add_argument("--fundamental-universe-source", choices=("ai_tech", "broad", "all", "ohlcv"), default=None)
    parser.add_argument("--ohlcv-db", default=str(download_history.DEFAULT_DB_PATH))
    parser.add_argument("--pit-db", default=str(download_fundamentals.DEFAULT_PIT_DB_PATH))
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--price-min-days", type=int, default=10)
    parser.add_argument("--price-buffer-days", type=int, default=7)
    parser.add_argument("--price-max-days", type=int, default=1500)
    parser.add_argument("--daily-start-days", type=int, default=21)
    parser.add_argument("--monthly-start-days", type=int, default=75)
    parser.add_argument("--quarterly-start-days", type=int, default=500)
    parser.add_argument("--max-consecutive-failures", type=int, default=25)
    parser.add_argument("--limit-stocks", nargs="*", help="Optional explicit stock list for a narrow refresh")
    parser.add_argument("--skip-stock-master", action="store_true")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-fundamentals", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    load_backend_env()

    exit_code = 0
    if not args.skip_stock_master:
        logger.info("stock-master: refresh persistent stock directory cache")
        if not args.dry_run:
            result = asyncio.run(refresh_stock_master_cache())
            logger.info("stock-master result: %s", result)

    if not args.skip_prices:
        exit_code = max(exit_code, _run_step("prices", download_history.main, _history_args(args), dry_run=args.dry_run))

    if args.skip_fundamentals:
        return exit_code

    if args.cadence in {"daily", "all"}:
        exit_code = max(
            exit_code,
            _run_step(
                "fundamentals-daily",
                download_fundamentals.main,
                _fundamental_args(args, DAILY_DATASETS, _days_ago(args.daily_start_days)),
                dry_run=args.dry_run,
            ),
        )
    if args.cadence in {"monthly", "all"}:
        exit_code = max(
            exit_code,
            _run_step(
                "fundamentals-monthly",
                download_fundamentals.main,
                _fundamental_args(args, MONTHLY_DATASETS, _days_ago(args.monthly_start_days)),
                dry_run=args.dry_run,
            ),
        )
    if args.cadence in {"quarterly", "all"}:
        exit_code = max(
            exit_code,
            _run_step(
                "fundamentals-quarterly",
                download_fundamentals.main,
                _fundamental_args(args, QUARTERLY_DATASETS, _days_ago(args.quarterly_start_days)),
                dry_run=args.dry_run,
            ),
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
