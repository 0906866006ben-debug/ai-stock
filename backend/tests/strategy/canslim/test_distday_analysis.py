from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.distday_analysis import (
    cohort_comparison,
    distday_state_as_of,
    distribution_day_count,
    run_distday_analysis,
)
from backend.app.services.strategy.canslim.params import load_params


def test_distribution_day_count_and_risk_off_known_answer(tmp_path: Path):
    store = _taiex_store(tmp_path)
    bars = store.get_ohlcv_as_of("TAIEX", "2024-02-10", 30)

    assert distribution_day_count(bars) == 5
    state = distday_state_as_of(store, "2024-02-10", threshold=5)
    assert state["dist_day_count_25"] == 5
    assert state["dist_risk_off"] is True


def test_cohort_reaggregation_known_answers():
    trades = pd.DataFrame(
        [
            {"window": "window_1", "regime_bucket_at_entry": "risk_on", "dist_risk_off": False, "net_return_pct": 0.10},
            {"window": "window_1", "regime_bucket_at_entry": "risk_on", "dist_risk_off": False, "net_return_pct": -0.05},
            {"window": "window_1", "regime_bucket_at_entry": "risk_on", "dist_risk_off": True, "net_return_pct": -0.10},
            {"window": "window_2", "regime_bucket_at_entry": "severe", "dist_risk_off": True, "net_return_pct": 0.03},
        ]
    )

    rows = cohort_comparison(trades)
    window_1 = next(row for row in rows if row["window"] == "window_1")

    assert window_1["plain_risk_on"]["n"] == 3
    assert window_1["plain_risk_on"]["profit_factor"] == 0.6667
    assert window_1["risk_on_not_dist_risk_off"]["n"] == 2
    assert window_1["risk_on_not_dist_risk_off"]["profit_factor"] == 2.0
    assert window_1["removed_count"] == 1


def test_distday_analysis_does_not_mutate_params(tmp_path: Path):
    before = load_params()["backtest"]["canslim"]["regime_entry_gate"]
    store = _taiex_store(tmp_path)
    csv_path = tmp_path / "enriched.csv"
    pd.DataFrame(
        [
            {
                "window": "window_1",
                "regime_bucket_at_entry": "risk_on",
                "entry_date": "2024-02-10",
                "net_return_pct": -0.02,
            }
        ]
    ).to_csv(csv_path, index=False)

    report = run_distday_analysis(
        enriched_trades_csv=csv_path,
        ohlcv_db_path=store.db_path,
        output_dir=tmp_path / "artifacts",
    )
    after = load_params()["backtest"]["canslim"]["regime_entry_gate"]

    assert before is True
    assert after is True
    assert Path(report.artifact_json).exists()


def _taiex_store(tmp_path: Path) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    start = pd.Timestamp("2024-01-01")
    rows = []
    close = 100.0
    volume = 1000
    dist_indexes = {5, 9, 13, 17, 21}
    low_volume_down_indexes = {25}
    for idx in range(30):
        date = (start + pd.Timedelta(days=idx)).strftime("%Y-%m-%d")
        if idx in dist_indexes:
            close *= 0.996
            volume += 200
        elif idx in low_volume_down_indexes:
            close *= 0.996
            volume -= 100
        else:
            close *= 1.003
            volume += 10
        rows.append(
            {
                "stock_id": "TAIEX",
                "date": date,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": volume,
                "turnover": close * volume,
            }
        )
    store.upsert_rows(rows)
    return store
