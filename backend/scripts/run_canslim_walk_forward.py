"""Run real-data CANSLIM walk-forward from local OHLCV + PIT stores."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.walk_forward import run_real_data_walk_forward

logger = logging.getLogger(__name__)


def load_ai_tech_codes(json_path: Path) -> list[str]:
    with json_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    codes: list[str] = []
    for category in data.get("categories", {}).values():
        for stock in category.get("stocks", []):
            code = str(stock.get("code", "")).strip()
            if code:
                codes.append(code)
    return codes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="canslim_real_wf")
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    parser.add_argument(
        "--universe-file",
        default=str(Path(__file__).resolve().parent.parent / "data" / "sectors" / "ai_tech_tw.json"),
    )
    parser.add_argument("--stocks", nargs="*", help="Override universe with explicit stock codes")
    parser.add_argument("--output-dir", default="artifacts/canslim_real_walk_forward")
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    if args.stocks:
        universe = [str(stock).strip() for stock in args.stocks if str(stock).strip()]
    else:
        universe = load_ai_tech_codes(Path(args.universe_file))

    params = {
        "backtest.canslim.min_entry_grade": "B",
        "backtest.canslim.max_hold_days": 30,
        "scoring.grades.A_signal_min": 55,
        "scoring.grades.B_signal_min": 35,
    }
    report = run_real_data_walk_forward(
        run_id=args.run_id,
        ohlcv_db_path=args.ohlcv_db,
        pit_db_path=args.pit_db,
        stock_universe=universe,
        windows=[("2018-01-01", "2022-12-31", "2023-01-01", "2026-12-31")],
        params=params,
        output_dir=args.output_dir,
        min_trades=args.min_trades,
    )
    logger.info("Report JSON: %s", report.artifact_json)
    logger.info("Report MD: %s", report.artifact_md)
    logger.info("Accepted: %s", report.accepted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
