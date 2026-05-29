"""Score & rank the whole market by CANSLIM (one as-of snapshot).

Every data-bearing stock gets overall_score (0-100), grade (S/A/B/C/D), 7 factor
scores, regime, structure_status — sorted high to low. Independent of pass_status.

    # whole market, latest date
    python -m backend.scripts.run_canslim_ranking

    # specific date / tech only / liquid only
    python -m backend.scripts.run_canslim_ranking --as-of 2025-06-30 --universe-source tech --turnover-floor 50000000
"""
from __future__ import annotations

import argparse
import logging

from backend.scripts._env import load_backend_env
from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.canslim_ranking import run_ranking
from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
from backend.app.services.strategy.canslim.universe_source import get_tech_universe_symbols

logger = logging.getLogger(__name__)


def _candidates(source: str, pit_db: str) -> list[str]:
    covered = fundamentals_covered_symbols(pit_db)
    if source == "tech":
        try:
            tech = set(get_tech_universe_symbols())
            if tech:
                covered = [s for s in covered if s in tech]
        except Exception as exc:
            logger.warning("tech universe fetch failed (%s); using full coverage", exc)
    return covered


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="canslim_ranking_v1")
    p.add_argument("--as-of", default=None, help="YYYY-MM-DD; default = latest in store")
    p.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    p.add_argument("--out", default="artifacts/canslim_ranking")
    p.add_argument("--universe-source", choices=("all", "tech"), default="all")
    p.add_argument("--turnover-floor", type=float, default=None)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (leak FinMind token)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_backend_env()
    cands = _candidates(args.universe_source, args.pit_db)
    logger.info("universe-source=%s -> %d candidates", args.universe_source, len(cands))

    report = run_ranking(
        run_id=args.run_id, as_of_date=args.as_of, ohlcv_db_path=args.ohlcv_db, pit_db_path=args.pit_db,
        output_dir=args.out, candidate_symbols=cands, turnover_floor=args.turnover_floor,
    )
    logger.info("Done. %d stocks scored as of %s in %.0fs", report.n_ranked, report.as_of_date, report.elapsed_seconds)
    logger.info("grade dist: %s", report.grade_distribution)
    logger.info("CSV: %s", report.ranked_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
