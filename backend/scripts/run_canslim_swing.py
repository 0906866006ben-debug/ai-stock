"""Run the CANSLIM swing backtest: enter on the live screen (pass_status==PASS),
exit aligned to the live swing_exit (stop / MA-break / target / max-hold). Fixed
params, by-regime, measurement-only.

    # representative swing run (monthly, tech subset, liquid)
    python -m backend.scripts.run_canslim_swing --universe-source tech --turnover-floor 100000000

    # quick smoke
    python -m backend.scripts.run_canslim_swing --start 2023-01-01 --end 2023-12-31 --max-symbols 100
"""
from __future__ import annotations

import argparse
import logging

from backend.scripts._env import load_backend_env
from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
from backend.app.services.strategy.canslim.swing_backtest import run_swing_backtest
from backend.app.services.strategy.canslim.universe_source import get_tech_universe_symbols

logger = logging.getLogger(__name__)


def _candidates(source: str, pit_db: str, max_symbols: int | None) -> list[str]:
    covered = fundamentals_covered_symbols(pit_db)
    if source == "tech":
        try:
            tech = set(get_tech_universe_symbols())
            if tech:
                covered = [s for s in covered if s in tech]
        except Exception as exc:
            logger.warning("tech universe fetch failed (%s); using full coverage", exc)
    if max_symbols and max_symbols > 0:
        covered = covered[:max_symbols]
    return covered


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="canslim_swing_v1")
    p.add_argument("--start", default="2011-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--cadence-days", type=int, default=21)
    p.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    p.add_argument("--out", default="artifacts/canslim_swing")
    p.add_argument("--universe-source", choices=("all", "tech"), default="all")
    p.add_argument("--max-symbols", type=int, default=None)
    p.add_argument("--turnover-floor", type=float, default=None)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (leak FinMind token)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_backend_env()
    cands = _candidates(args.universe_source, args.pit_db, args.max_symbols)
    logger.info("universe-source=%s -> %d candidates", args.universe_source, len(cands))

    report = run_swing_backtest(
        run_id=args.run_id, ohlcv_db_path=args.ohlcv_db, pit_db_path=args.pit_db,
        start_date=args.start, end_date=args.end, cadence_days=args.cadence_days,
        output_dir=args.out, candidate_symbols=cands, turnover_floor=args.turnover_floor,
    )
    logger.info("Done. %d trades in %.0fs -> %s", report.n_trades, report.elapsed_seconds, report.summary_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
