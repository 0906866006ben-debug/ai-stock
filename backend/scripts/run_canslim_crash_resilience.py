"""Run the crash-resilience cohort (Path B validation, measurement only).

Across 5 TW crashes (2011/2015/2018/2020/2022), sort the survivorship universe by pre-crash
Composite Durability Score into quintiles and measure drawdown / recovery / delisting per
quintile. Tests: does Q1 (durable) beat Q5 (junk)?

    # survivorship-corrected (include delisted — needed for the delisting-rate metric)
    python -m backend.scripts.run_canslim_crash_resilience --include-delisted
"""
from __future__ import annotations

import argparse
import logging

from backend.scripts._env import load_backend_env
from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.crash_resilience import run_crash_resilience
from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
from backend.app.services.strategy.canslim.universe_source import (
    get_delisted_universe_symbols,
    get_tech_universe_symbols,
)

logger = logging.getLogger(__name__)


def _resolve_candidates(source: str, pit_db: str, *, include_delisted: bool) -> list[str]:
    covered = fundamentals_covered_symbols(pit_db)
    if source == "tech":
        try:
            tech = set(get_tech_universe_symbols())
        except Exception as exc:
            logger.warning("tech universe fetch failed (%s); using 'all'", exc)
            tech = set()
        if tech:
            covered = [s for s in covered if s in tech]
    if include_delisted:
        try:
            delisted = get_delisted_universe_symbols()
        except Exception as exc:
            logger.warning("delisted fetch failed (%s); continuing without", exc)
            delisted = []
        covered = list(dict.fromkeys([*covered, *delisted]))
    return covered


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="crash_resilience")
    p.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    p.add_argument("--out", default="artifacts/canslim_crash_resilience")
    p.add_argument("--universe-source", choices=("all", "tech"), default="tech")
    p.add_argument("--include-delisted", action="store_true", help="Survivorship correction (needed for delisting rate)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (FinMind token)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_backend_env()

    candidates = _resolve_candidates(args.universe_source, args.pit_db, include_delisted=args.include_delisted)
    if not args.include_delisted:
        logger.warning("running WITHOUT delisted names -> delisting-rate metric is meaningless; pass --include-delisted")
    logger.info("universe=%s include_delisted=%s -> %d candidates", args.universe_source, args.include_delisted, len(candidates))

    report = run_crash_resilience(
        run_id=args.run_id, ohlcv_db_path=args.ohlcv_db, pit_db_path=args.pit_db,
        candidate_symbols=candidates, output_dir=args.out,
    )
    for name, summ in report.get("events", {}).items():
        vs = summ.get("Q1_vs_Q5", {})
        logger.info("event %s: Q1-Q5 drawdown_gap=%s recovered_gap=%s impairment_gap=%s",
                    name, vs.get("drawdown_gap"), vs.get("recovered_gap"), vs.get("impairment_gap"))
    logger.info("report: %s/crash_summary.md", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
