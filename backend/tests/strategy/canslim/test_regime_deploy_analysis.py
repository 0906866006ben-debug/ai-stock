from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.regime_deploy_analysis import (
    aggregate_by,
    riskon_positive_all_windows,
    run_regime_deploy_analysis,
)


def test_regime_cohort_aggregation_known_answers():
    trades = pd.DataFrame(
        [
            {"regime_bucket_at_entry": "risk_on", "net_return_pct": 0.10},
            {"regime_bucket_at_entry": "risk_on", "net_return_pct": -0.05},
            {"regime_bucket_at_entry": "risk_off", "net_return_pct": 0.03},
            {"regime_bucket_at_entry": "risk_off", "net_return_pct": -0.01},
        ]
    )

    rows = aggregate_by(trades, ["regime_bucket_at_entry"])
    risk_on = next(row for row in rows if row["regime_bucket_at_entry"] == "risk_on")
    risk_off = next(row for row in rows if row["regime_bucket_at_entry"] == "risk_off")

    assert risk_on["n"] == 2
    assert risk_on["win_rate"] == 0.5
    assert risk_on["profit_factor"] == 2.0
    assert risk_on["avg_return"] == 0.025
    assert risk_on["sum_return"] == 0.05
    assert risk_off["profit_factor"] == 3.0


def test_risk_on_only_verdict_ignores_no_trade_windows():
    rows = [
        {"window": "window_1", "n": 25, "profit_factor": 1.2},
        {"window": "window_2", "n": 0, "profit_factor": 0.0},
        {"window": "window_3", "n": 30, "profit_factor": 1.5},
    ]

    assert riskon_positive_all_windows(rows, min_window_trades=20) is True

    rows[2]["profit_factor"] = 0.9
    assert riskon_positive_all_windows(rows, min_window_trades=20) is False


def test_analysis_does_not_mutate_params(tmp_path: Path):
    before = load_params()["backtest"]["canslim"]["regime_entry_gate"]
    csv_path = tmp_path / "enriched.csv"
    pd.DataFrame(
        [
            {
                "window": "window_1",
                "regime_bucket_at_entry": "risk_on",
                "pct_from_52w_high": -0.20,
                "net_return_pct": 0.02,
            },
            {
                "window": "window_2",
                "regime_bucket_at_entry": "severe",
                "pct_from_52w_high": -0.20,
                "net_return_pct": -0.01,
            },
        ]
    ).to_csv(csv_path, index=False)

    report = run_regime_deploy_analysis(
        enriched_trades_csv=csv_path,
        output_dir=tmp_path / "artifacts",
        min_window_trades=1,
        min_sleeve_trades=1,
    )
    after = load_params()["backtest"]["canslim"]["regime_entry_gate"]

    assert before is True
    assert after is True
    assert Path(report.artifact_json).exists()
    assert report.by_regime["pooled"]
