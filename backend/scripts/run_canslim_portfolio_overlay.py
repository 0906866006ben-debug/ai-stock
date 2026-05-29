"""Run Phase N CAN SLIM portfolio overlay measurement report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.strategy.canslim.portfolio_sim import run_overlay_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tagged-trades-csv", default="artifacts/canslim_multicycle/multicycle_tagged_trades.csv")
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-dir", default="artifacts/canslim_portfolio_overlay")
    parser.add_argument("--max-concurrent", type=int, default=10)
    parser.add_argument("--initial-capital", type=float, default=1.0)
    args = parser.parse_args(argv)

    report = run_overlay_report(
        tagged_trades_csv=Path(args.tagged_trades_csv),
        ohlcv_db_path=Path(args.ohlcv_db),
        output_dir=Path(args.output_dir),
        max_concurrent=args.max_concurrent,
        initial_capital=args.initial_capital,
    )
    print(json.dumps({"artifact_json": report["artifact_json"], "artifact_md": report["artifact_md"], "verdict": report["verdict"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
