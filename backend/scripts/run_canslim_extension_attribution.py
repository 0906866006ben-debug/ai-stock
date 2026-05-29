"""Generate CAN SLIM extension attribution from existing tagged OOS trades."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
from backend.app.services.strategy.canslim.extension_attribution import run_extension_attribution


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tagged-trades-csv",
        default="artifacts/canslim_attribution/canslim_real_v1_attribution_tagged_oos_trades.csv",
    )
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-dir", default="artifacts/canslim_attribution")
    parser.add_argument("--output-prefix", default="extension")
    args = parser.parse_args(argv)

    report = run_extension_attribution(
        tagged_trades_csv=Path(args.tagged_trades_csv),
        ohlcv_db_path=Path(args.ohlcv_db),
        output_dir=Path(args.output_dir),
        output_prefix=args.output_prefix,
    )
    print(json.dumps({"artifact_json": report.artifact_json, "artifact_md": report.artifact_md, "enriched_csv": report.enriched_csv}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
