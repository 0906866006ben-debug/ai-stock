"""Run the CANSLIM screening forward-return cohort backtest (measurement only).

Validates the SCREENER: does the stock it surfaces subsequently grow? On each
as_of date it screens the PIT universe, buckets by pass_status / grade / pillar,
and measures forward returns at 1/3/6/12 months vs the universe baseline.

    # full study (monthly, 2011-2025) — ~2-3 hours
    python -m backend.scripts.run_canslim_cohort

    # quick smoke on one year
    python -m backend.scripts.run_canslim_cohort --start 2023-01-01 --end 2023-12-31
"""
from __future__ import annotations

import argparse
import logging

from backend.scripts._env import load_backend_env
from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.cohort_backtest import run_cohort_backtest
from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
from backend.app.services.strategy.canslim.universe_source import get_tech_universe_symbols

logger = logging.getLogger(__name__)


def _resolve_candidates(source: str, pit_db: str, max_symbols: int | None) -> list[str]:
    """Resolve the candidate pool. 'tech' intersects the broad tech/electronics
    universe with fundamentals coverage (where CANSLIM growth names live, and far
    smaller/faster than 'all'); 'all' is every fundamentals-covered symbol."""
    covered = fundamentals_covered_symbols(pit_db)
    if source == "tech":
        try:
            tech = set(get_tech_universe_symbols())
        except Exception as exc:
            logger.warning("tech universe fetch failed (%s); falling back to 'all'", exc)
            tech = set()
        if tech:
            covered = [s for s in covered if s in tech]
        else:
            logger.warning("tech universe empty (no FINMIND token?); using 'all' coverage")
    if max_symbols and max_symbols > 0:
        covered = covered[:max_symbols]
    return covered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="canslim_cohort_v1")
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--cadence-days", type=int, default=21, help="Trading-day step (≈21 = monthly)")
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    parser.add_argument("--out", default="artifacts/canslim_cohort")
    parser.add_argument("--turnover-floor", type=float, default=None, help="Per-date liquidity floor (e.g. 100000000)")
    parser.add_argument("--universe-source", choices=("all", "tech"), default="all",
                        help="all=every fundamentals-covered symbol; tech=tech/electronics subset (faster, growth-focused)")
    parser.add_argument("--max-symbols", type=int, default=None, help="Cap candidate count (for a quick run)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    load_backend_env()

    candidates = _resolve_candidates(args.universe_source, args.pit_db, args.max_symbols)
    logger.info("universe-source=%s -> %d candidate symbols", args.universe_source, len(candidates))

    report = run_cohort_backtest(
        run_id=args.run_id,
        ohlcv_db_path=args.ohlcv_db,
        pit_db_path=args.pit_db,
        start_date=args.start,
        end_date=args.end,
        cadence_days=args.cadence_days,
        output_dir=args.out,
        candidate_symbols=candidates,
        turnover_floor=args.turnover_floor,
    )
    logger.info("Done. %d rows over %d dates in %.0fs", report.n_rows, report.n_dates, report.elapsed_seconds)
    logger.info("Summary: %s", report.summary_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
