"""Run the 優質長期持有 quality long-term-hold screener (三大面) on the canonical stores.

Grades every name in the PIT liquidity universe at one as_of date across 基本面 /
籌碼面 / 技術面 and writes a ranked watchlist (CSV + markdown). Research/watchlist
tooling only — no trade instructions; factor edge pending the run_value_cohort
2011-2025 validation.

    # screen today's universe (currently-listed, fundamentals-covered, liquid)
    python -m backend.scripts.run_value_screen

    # a specific date / looser liquidity floor / more rows in the report
    python -m backend.scripts.run_value_screen --as-of 2025-06-30 --turnover-floor 30000000 --top 100
"""
from __future__ import annotations

import argparse
import logging

from backend.scripts._env import load_backend_env
from backend.scripts.run_value_cohort import _resolve_candidates
from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.value.value_screener import run_value_screen

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="優質長期持有股票篩選器 (三大面)")
    parser.add_argument("--as-of", default=None,
                        help="Screen date YYYY-MM-DD (default: latest TAIEX bar in the store)")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    parser.add_argument("--out", default="artifacts/value_screen")
    parser.add_argument("--turnover-floor", type=float, default=50_000_000,
                        help="Per-date liquidity floor in TWD (junk filter; default 50M)")
    parser.add_argument("--max-staleness-days", type=int, default=10,
                        help="Drop names whose last bar is older than N days (suspended/delisted filter)")
    parser.add_argument("--universe-source", choices=("all", "all_listed", "tech"), default="all_listed",
                        help="all=every fundamentals-covered symbol; all_listed=intersect currently listed "
                             "(default for a live watchlist); tech=tech/electronics subset")
    parser.add_argument("--max-symbols", type=int, default=None, help="Cap candidate count (quick run)")
    parser.add_argument("--top", type=int, default=50, help="Rows shown in the markdown report")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (FinMind token)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_backend_env()

    candidates = _resolve_candidates(args.universe_source, args.pit_db, args.max_symbols)
    logger.info("universe-source=%s -> %d candidates", args.universe_source, len(candidates))
    if not candidates:
        logger.error("no candidate symbols resolved (is the PIT DB populated?)")
        return 1

    report = run_value_screen(
        as_of=args.as_of,
        run_id=args.run_id,
        ohlcv_db_path=args.ohlcv_db,
        pit_db_path=args.pit_db,
        output_dir=args.out,
        candidate_symbols=candidates,
        turnover_floor=args.turnover_floor,
        max_staleness_days=args.max_staleness_days,
        top_n=args.top,
    )
    logger.info("Done. as_of=%s universe=%d rows=%d grades=%s in %.0fs",
                report.as_of, report.universe_size, report.n_rows,
                report.grade_counts, report.elapsed_seconds)
    logger.info("Report: %s", report.report_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
