"""Run the quarterly TW-CANSLIM growth-screen portfolio backtest (measurement only).

Two arms over the same C∩A∩G filter: "ni" (top CANSLIM score, N/I-led) vs "video"
(smallest free-float). Reports annual / CAGR / maxDD / Calmar vs TAIEX.

    # full study (2011-2025), tech universe + delisted (survivorship-corrected)
    python -m backend.scripts.run_canslim_quarterly --include-delisted

    # quick smoke on a short window
    python -m backend.scripts.run_canslim_quarterly --start 2023-01-01 --end 2024-12-31
"""
from __future__ import annotations

import argparse
import logging

from backend.scripts._env import load_backend_env
from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
from backend.app.services.strategy.canslim.quarterly_backtest import run_quarterly_backtest
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
    p.add_argument("--run-id", default="tw_canslim_q")
    p.add_argument("--start", default="2011-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    p.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    p.add_argument("--out", default="artifacts/canslim_quarterly")
    p.add_argument("--universe-source", choices=("all", "tech"), default="tech")
    p.add_argument("--include-delisted", action="store_true", help="Survivorship correction")
    p.add_argument("--basket-size", type=int, default=30)
    p.add_argument("--min-revenue-yoy", type=float, default=0.10)
    p.add_argument("--turnover-floor", type=float, default=100_000_000)
    p.add_argument("--arms", nargs="+", default=["ni", "video"], choices=["ni", "video"])
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (FinMind token)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_backend_env()

    candidates = _resolve_candidates(args.universe_source, args.pit_db, include_delisted=args.include_delisted)
    logger.info("universe=%s include_delisted=%s -> %d candidates", args.universe_source, args.include_delisted, len(candidates))

    report = run_quarterly_backtest(
        run_id=args.run_id, ohlcv_db_path=args.ohlcv_db, pit_db_path=args.pit_db,
        start_date=args.start, end_date=args.end, candidate_symbols=candidates,
        arms=tuple(args.arms), basket_size=args.basket_size,
        min_revenue_yoy=args.min_revenue_yoy, turnover_floor=args.turnover_floor, output_dir=args.out,
    )
    for arm, a in report["arms"].items():
        m = a["metrics"]
        logger.info("arm=%s CAGR=%.1f%% maxDD=%.1f%% Calmar=%.2f", arm, m["cagr"] * 100, m["max_drawdown"] * 100, m["calmar"])
    b = report["benchmark_TAIEX"]["metrics"]
    logger.info("TAIEX CAGR=%.1f%% maxDD=%.1f%%", b["cagr"] * 100, b["max_drawdown"] * 100)
    logger.info("report: %s/quarterly_summary.md", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
