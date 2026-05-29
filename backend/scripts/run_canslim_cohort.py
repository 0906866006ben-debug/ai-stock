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
from backend.app.services.strategy.canslim.universe_source import (
    get_delisted_universe_symbols,
    get_tech_universe_symbols,
)

logger = logging.getLogger(__name__)


def _resolve_candidates(
    source: str, pit_db: str, max_symbols: int | None, *, include_delisted: bool = False
) -> list[str]:
    """Resolve the candidate pool. 'tech' intersects the broad tech/electronics
    universe with fundamentals coverage (where CANSLIM growth names live, and far
    smaller/faster than 'all'); 'all' is every fundamentals-covered symbol.

    With include_delisted, already-delisted symbols are merged in (survivorship
    correction). Their OHLCV must be backfilled (download_delisting) and ideally
    their fundamentals too (download_fundamentals --stocks <list>); names lacking
    fundamentals simply screen Insufficient. Pair this with --max-staleness-days
    so a delisted name leaves the universe once it stops trading."""
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
    if include_delisted:
        try:
            delisted = get_delisted_universe_symbols()
        except Exception as exc:
            logger.warning("delisted universe fetch failed (%s); continuing without it", exc)
            delisted = []
        merged = list(dict.fromkeys([*covered, *delisted]))
        logger.info("include-delisted: +%d delisted symbols (pre-merge %d -> %d)",
                    len(delisted), len(covered), len(merged))
        covered = merged
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
    parser.add_argument("--include-delisted", action="store_true",
                        help="Survivorship correction: merge already-delisted symbols into the pool "
                             "(requires download_delisting; pair with --max-staleness-days)")
    parser.add_argument("--max-staleness-days", type=int, default=None,
                        help="Drop a symbol once its latest bar on/before each as_of is older than N "
                             "calendar days (makes delisted names fall out on their last trading day). "
                             "Recommended ~10 with --include-delisted; default off keeps validated runs intact")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (leak FinMind token)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_backend_env()

    candidates = _resolve_candidates(
        args.universe_source, args.pit_db, args.max_symbols, include_delisted=args.include_delisted,
    )
    logger.info("universe-source=%s include_delisted=%s -> %d candidate symbols",
                args.universe_source, args.include_delisted, len(candidates))
    if args.include_delisted and args.max_staleness_days is None:
        logger.warning("--include-delisted without --max-staleness-days: delisted names will keep "
                       "their stale last bars and re-introduce survivorship bias. Recommend ~10.")

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
        max_staleness_days=args.max_staleness_days,
    )
    logger.info("Done. %d rows over %d dates in %.0fs", report.n_rows, report.n_dates, report.elapsed_seconds)
    logger.info("Summary: %s", report.summary_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
