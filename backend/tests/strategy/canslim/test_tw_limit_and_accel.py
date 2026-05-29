"""TW-fit refinements: ±10% price-limit detection + acceleration adjacency."""
from __future__ import annotations

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.features import CanslimFeatures, build_features
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pillar_screening import screen_S
from backend.app.services.strategy.canslim.pit_inputs import _quarterly_eps_yoy_series


def _store_two_bars(tmp_path, prev_close, today_close, today_high, today_low):
    store = HistoricalDataStore(tmp_path / "ohlcv.db")
    rows = [
        {"stock_id": "X", "date": "2025-06-27", "open": prev_close, "high": prev_close,
         "low": prev_close, "close": prev_close, "volume": 1000, "turnover": prev_close * 1000},
        {"stock_id": "X", "date": "2025-06-30", "open": prev_close, "high": today_high,
         "low": today_low, "close": today_close, "volume": 1000, "turnover": today_close * 1000},
    ]
    store.upsert_rows(rows)
    return store


def test_limit_up_detected(tmp_path):
    # +10% and closed at the high -> limit-up lock.
    s = _store_two_bars(tmp_path, 100.0, 110.0, 110.0, 105.0)
    f = build_features("X", "2025-06-30", s)
    assert f.at_limit_up is True
    assert f.at_limit_down is False


def test_limit_down_detected(tmp_path):
    s = _store_two_bars(tmp_path, 100.0, 90.0, 95.0, 90.0)
    f = build_features("X", "2025-06-30", s)
    assert f.at_limit_down is True
    assert f.at_limit_up is False


def test_normal_day_not_limit(tmp_path):
    s = _store_two_bars(tmp_path, 100.0, 103.0, 104.0, 101.0)
    f = build_features("X", "2025-06-30", s)
    assert f.at_limit_up is False and f.at_limit_down is False


def test_limit_up_surfaces_warning_in_s(tmp_path):
    f = CanslimFeatures(symbol="X", as_of_date="2025-06-30", avg_turnover_20=50_000_000,
                        up_down_volume_ratio_10=1.5, volume_ratio_recent_vs_prior_20=1.4,
                        at_limit_up=True)
    v = screen_S(f, {}, load_params())
    assert any("limit-up" in w for w in v.data_warnings)


def test_accel_series_is_contiguous_run_stops_at_gap():
    # Build financials where the 2nd-latest quarter's prior year was a loss (YoY uncomputable);
    # series must NOT bridge across it — it should contain only the latest contiguous run.
    rows = [
        {"period_end": "2023-09-30", "eps": 1.0},  # prior for 2024-09 (ok)
        {"period_end": "2023-12-31", "eps": -1.0},  # prior for 2024-12 is a loss -> 2024-12 uncomputable
        {"period_end": "2024-09-30", "eps": 2.0},
        {"period_end": "2024-12-31", "eps": 3.0},   # latest; prior 2023-12 was loss -> not computable
    ]
    df = pd.DataFrame(rows)
    series = _quarterly_eps_yoy_series(df)
    # latest (2024-12) has loss-base prior -> uncomputable -> run stops immediately -> empty
    assert series == []


def test_accel_series_contiguous_when_all_computable():
    rows = [
        {"period_end": "2023-09-30", "eps": 1.0},
        {"period_end": "2023-12-31", "eps": 1.0},
        {"period_end": "2024-09-30", "eps": 2.0},   # YoY vs 2023-09 = 1.0
        {"period_end": "2024-12-31", "eps": 1.5},   # YoY vs 2023-12 = 0.5
    ]
    df = pd.DataFrame(rows)
    series = _quarterly_eps_yoy_series(df)
    assert series == [1.0, 0.5]
