"""Run the value-factor forward-return cohort backtest (measurement only, Phase 1).

Tests whether a value/quality factor carries a real forward-return edge on OUR PIT-safe
Taiwan data — annual rebalance, survivorship-corrected (incl. delisted), net of cost.
We do NOT trust external marketing numbers; we reproduce (or fail to reproduce) the
claimed F-Score spread ourselves.

    # F-Score, full study (annual, 2011-2025), survivorship-corrected + cost
    python -m backend.scripts.run_value_cohort --factor fscore --include-delisted --max-staleness-days 10

    # quick smoke (a couple of years)
    python -m backend.scripts.run_value_cohort --factor fscore --start 2019-01-01 --end 2021-12-31
"""
from __future__ import annotations

import argparse
import logging

from backend.scripts._env import load_backend_env
from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
from backend.app.services.strategy.canslim.universe_source import (
    get_all_universe_symbols,
    get_delisted_universe_symbols,
    get_tech_universe_symbols,
)
from backend.app.services.strategy.value.value_cohort import FACTORS, run_value_cohort

logger = logging.getLogger(__name__)


def _resolve_candidates(
    source: str, pit_db: str, max_symbols: int | None, *, include_delisted: bool = False
) -> list[str]:
    """Resolve the candidate pool from fundamentals coverage, optionally restricted to
    a tradable universe and/or merged with already-delisted symbols (survivorship).

    Value investing is breadth-wide (not tech-only), so 'all' is the default. Delisted
    names need OHLCV backfilled (download_delisting) and, ideally, fundamentals; names
    lacking fundamentals simply produce no factor and are skipped. Pair --include-delisted
    with --max-staleness-days so a delisted name leaves the universe on its last bar."""
    covered = fundamentals_covered_symbols(pit_db)
    if source == "tech":
        try:
            tech = set(get_tech_universe_symbols())
        except Exception as exc:
            logger.warning("tech universe fetch failed (%s); using 'all' coverage", exc)
            tech = set()
        if tech:
            covered = [s for s in covered if s in tech]
    elif source == "all_listed":
        try:
            listed = set(get_all_universe_symbols())
        except Exception as exc:
            logger.warning("all-listed fetch failed (%s); using fundamentals coverage", exc)
            listed = set()
        if listed:
            covered = [s for s in covered if s in listed]
    if include_delisted:
        try:
            delisted = get_delisted_universe_symbols()
        except Exception as exc:
            logger.warning("delisted universe fetch failed (%s); continuing without it", exc)
            delisted = []
        merged = list(dict.fromkeys([*covered, *delisted]))
        logger.info("include-delisted: +%d delisted (pre-merge %d -> %d)",
                    len(delisted), len(covered), len(merged))
        covered = merged
    if max_symbols and max_symbols > 0:
        covered = covered[:max_symbols]
    return covered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Value-factor forward-return cohort backtest")
    parser.add_argument("--factor", choices=FACTORS, default="fscore",
                        help="fscore=Piotroski 0-9 (Phase 1 focus); magic=Magic Formula; sy=Shareholder Yield")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--cadence-days", type=int, default=252,
                        help="Trading-day step (≈252 = annual rebalance)")
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    parser.add_argument("--out", default="artifacts/value_cohort")
    parser.add_argument("--turnover-floor", type=float, default=None,
                        help="Per-date liquidity floor in TWD (e.g. 50000000)")
    parser.add_argument("--universe-source", choices=("all", "all_listed", "tech"), default="all",
                        help="all=every fundamentals-covered symbol; all_listed=intersect current listed; "
                             "tech=tech/electronics subset")
    parser.add_argument("--max-symbols", type=int, default=None, help="Cap candidate count (quick run)")
    parser.add_argument("--include-delisted", action="store_true",
                        help="Survivorship correction: merge already-delisted symbols (needs download_delisting; "
                             "pair with --max-staleness-days)")
    parser.add_argument("--max-staleness-days", type=int, default=None,
                        help="Drop a symbol once its last bar on/before each as_of is older than N days "
                             "(makes delisted names fall out on their last trading day; ~10 recommended with "
                             "--include-delisted)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (FinMind token)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_backend_env()

    candidates = _resolve_candidates(
        args.universe_source, args.pit_db, args.max_symbols, include_delisted=args.include_delisted,
    )
    logger.info("factor=%s universe-source=%s include_delisted=%s -> %d candidates",
                args.factor, args.universe_source, args.include_delisted, len(candidates))
    if not candidates:
        logger.error("no candidate symbols resolved (is the PIT DB populated?)")
        return 1
    if args.include_delisted and args.max_staleness_days is None:
        logger.warning("--include-delisted without --max-staleness-days: delisted names keep stale "
                       "last bars and re-introduce survivorship bias. Recommend ~10.")

    report = run_value_cohort(
        factor=args.factor,
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
    logger.info("Done. factor=%s %d rows over %d dates in %.0fs",
                report.factor, report.n_rows, report.n_dates, report.elapsed_seconds)
    logger.info("Report: %s", report.summary_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
