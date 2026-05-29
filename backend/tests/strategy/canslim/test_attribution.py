from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.strategy.canslim.attribution import (
    aggregate_by,
    grade_monotonic_by_pf,
    regime_bucket_at_entry,
    run_real_data_attribution,
)
from backend.app.services.strategy.canslim.params import load_params
from backend.tests.strategy.canslim.test_phase_j2_pit_inputs import AS_OF, _market, _ohlcv_store, _pit_store


def test_attribution_aggregation_metrics_known_answers():
    trades = pd.DataFrame(
        [
            {"grade": "S", "regime_bucket_at_entry": "risk_on", "net_return_pct": 0.10},
            {"grade": "S", "regime_bucket_at_entry": "risk_on", "net_return_pct": -0.05},
            {"grade": "A", "regime_bucket_at_entry": "risk_off", "net_return_pct": 0.03},
            {"grade": "A", "regime_bucket_at_entry": "risk_off", "net_return_pct": -0.03},
            {"grade": "B", "regime_bucket_at_entry": "severe", "net_return_pct": -0.02},
        ]
    )

    by_grade = aggregate_by(trades, ["grade"])
    s_row = next(row for row in by_grade if row["grade"] == "S")
    a_row = next(row for row in by_grade if row["grade"] == "A")
    b_row = next(row for row in by_grade if row["grade"] == "B")

    assert s_row["n"] == 2
    assert s_row["win_rate"] == 0.5
    assert s_row["profit_factor"] == 2.0
    assert s_row["avg_return"] == 0.025
    assert a_row["profit_factor"] == 1.0
    assert b_row["profit_factor"] == 0.0
    assert grade_monotonic_by_pf(by_grade) is True


def test_regime_bucket_at_entry_maps_known_state(tmp_path: Path):
    store = _ohlcv_store(tmp_path)
    params = load_params()

    assert regime_bucket_at_entry(AS_OF, store, ["2330"], params) == "unknown"


def test_analysis_run_disables_gate_without_mutating_live_yaml(tmp_path: Path):
    before = load_params()["backtest"]["canslim"]["regime_entry_gate"]
    ohlcv = _ohlcv_store(tmp_path)
    pit = _pit_store(tmp_path)

    report = run_real_data_attribution(
        run_id="attribution_synthetic",
        ohlcv_db_path=ohlcv.db_path,
        pit_db_path=pit.db_path,
        stock_universe=["2330"],
        windows=[(AS_OF, AS_OF, AS_OF, AS_OF)],
        params={
            "backtest.canslim.min_entry_grade": "B",
            "backtest.canslim.max_hold_days": 30,
            "scoring.grades.A_signal_min": 55,
            "scoring.grades.B_signal_min": 35,
        },
        output_dir=tmp_path / "artifacts",
    )
    after = load_params()["backtest"]["canslim"]["regime_entry_gate"]

    assert before is True
    assert after is True
    assert Path(report.artifact_json).exists()
    assert report.pooled["n_trades"] >= 1
