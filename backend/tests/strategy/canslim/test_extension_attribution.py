from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.extension_attribution import (
    add_extension_buckets,
    aggregate_by,
    compute_extension_metrics,
    run_extension_attribution,
)
from backend.app.services.strategy.canslim.params import load_params


def test_extension_metrics_are_point_in_time(tmp_path: Path):
    store = _extension_store(tmp_path)

    metrics = compute_extension_metrics(store, "TEST", "2024-03-31")

    assert metrics["close_to_ma20"] == 1.052632
    assert metrics["pct_from_52w_high"] == -0.005236
    assert metrics["return_20d"] == 0.117647
    assert metrics["return_60d"] == 0.461538


def test_extension_bucketing_and_aggregation_known_answers():
    trades = pd.DataFrame(
        [
            {"close_to_ma20": 1.03, "pct_from_52w_high": -0.12, "net_return_pct": 0.10},
            {"close_to_ma20": 1.04, "pct_from_52w_high": -0.11, "net_return_pct": -0.05},
            {"close_to_ma20": 1.10, "pct_from_52w_high": -0.05, "net_return_pct": 0.03},
            {"close_to_ma20": 1.20, "pct_from_52w_high": -0.01, "net_return_pct": -0.03},
        ]
    )

    bucketed = add_extension_buckets(trades)
    rows = aggregate_by(bucketed, ["close_to_ma20_bucket"])
    low = next(row for row in rows if row["close_to_ma20_bucket"] == "low_<1.05")

    assert low["n"] == 2
    assert low["win_rate"] == 0.5
    assert low["profit_factor"] == 2.0
    assert low["avg_return"] == 0.025


def test_extension_analysis_does_not_mutate_params(tmp_path: Path):
    before = load_params()["backtest"]["canslim"]["regime_entry_gate"]
    store = _extension_store(tmp_path)
    csv_path = tmp_path / "tagged.csv"
    pd.DataFrame(
        [
            {
                "window": "window_1",
                "horizon": "swing_term",
                "stock_id": "TEST",
                "signal_date": "2024-03-31",
                "entry_date": "2024-03-31",
                "grade": "B",
                "regime_bucket_at_entry": "risk_on",
                "net_return_pct": 0.02,
                "holding_days": 5,
            }
        ]
    ).to_csv(csv_path, index=False)

    report = run_extension_attribution(
        tagged_trades_csv=csv_path,
        ohlcv_db_path=store.db_path,
        output_dir=tmp_path / "artifacts",
    )
    after = load_params()["backtest"]["canslim"]["regime_entry_gate"]

    assert before is True
    assert after is True
    assert Path(report.artifact_json).exists()
    assert report.pooled["n_trades"] == 1


def _extension_store(tmp_path: Path) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    start = pd.Timestamp("2024-01-01")
    rows = []
    for idx in range(91):
        date = (start + pd.Timedelta(days=idx)).strftime("%Y-%m-%d")
        close = 100 + idx
        rows.append(
            {
                "stock_id": "TEST",
                "date": date,
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
                "turnover": close * 1000,
            }
        )
    store.upsert_rows(rows)
    return store
