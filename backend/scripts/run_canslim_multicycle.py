"""Run the Phase M3 fixed-param CAN SLIM multi-cycle backtest."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.multicycle_backtest import run_multicycle_backtest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="canslim_multicycle_v1")
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--cadence-days", type=int, default=5)
    parser.add_argument("--output-dir", default="artifacts/canslim_multicycle")
    parser.add_argument("--turnover-floor", type=float, default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    report = run_multicycle_backtest(
        run_id=args.run_id,
        ohlcv_db_path=Path(args.ohlcv_db),
        pit_db_path=Path(args.pit_db),
        start_date=args.start,
        end_date=args.end,
        cadence_days=args.cadence_days,
        output_dir=Path(args.output_dir),
        turnover_floor=args.turnover_floor,
        resume=not bool(args.no_resume),
    )
    print(
        json.dumps(
            {
                "tagged_trades_csv": report.tagged_trades_csv,
                "summary_json": report.summary_json,
                "summary_md": report.summary_md,
                "n_trades": report.summary.get("n_trades", 0),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
