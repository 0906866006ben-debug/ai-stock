"""Generate CAN SLIM risk-on deployability report from enriched trades."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.services.strategy.canslim.regime_deploy_analysis import run_regime_deploy_analysis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enriched-trades-csv", default="artifacts/canslim_attribution/extension_enriched_trades.csv")
    parser.add_argument("--output-dir", default="artifacts/canslim_attribution")
    parser.add_argument("--output-prefix", default="riskon_deploy")
    parser.add_argument("--min-window-trades", type=int, default=20)
    parser.add_argument("--min-sleeve-trades", type=int, default=20)
    args = parser.parse_args(argv)

    report = run_regime_deploy_analysis(
        enriched_trades_csv=Path(args.enriched_trades_csv),
        output_dir=Path(args.output_dir),
        output_prefix=args.output_prefix,
        min_window_trades=args.min_window_trades,
        min_sleeve_trades=args.min_sleeve_trades,
    )
    print(json.dumps({"artifact_json": report.artifact_json, "artifact_md": report.artifact_md}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
