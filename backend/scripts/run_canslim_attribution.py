"""Run CAN SLIM grade x regime attribution on local PIT data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.attribution import run_real_data_attribution
from backend.scripts.download_history import load_ai_tech_codes

DEFAULT_WINDOWS = [
    ("2018-01-01", "2021-12-31", "2022-01-01", "2022-06-30"),
    ("2018-07-01", "2022-06-30", "2022-07-01", "2022-12-31"),
    ("2019-01-01", "2022-12-31", "2023-01-01", "2023-06-30"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="canslim_real_v1_attribution")
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    parser.add_argument("--universe-file", default="backend/data/sectors/ai_tech_tw.json")
    parser.add_argument("--output-dir", default="artifacts/canslim_attribution")
    args = parser.parse_args(argv)

    universe = load_ai_tech_codes(Path(args.universe_file))
    report = run_real_data_attribution(
        run_id=args.run_id,
        ohlcv_db_path=Path(args.ohlcv_db),
        pit_db_path=Path(args.pit_db),
        stock_universe=universe,
        windows=DEFAULT_WINDOWS,
        params={
            "backtest.canslim.min_entry_grade": "B",
            "backtest.canslim.max_hold_days": 30,
            "scoring.grades.A_signal_min": 55,
            "scoring.grades.B_signal_min": 35,
        },
        output_dir=Path(args.output_dir),
    )
    print(json.dumps({"artifact_json": report.artifact_json, "artifact_md": report.artifact_md, "trades_csv": report.trades_csv}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
