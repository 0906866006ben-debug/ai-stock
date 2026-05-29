from datetime import date, timedelta

import pytest

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.features import CanslimFeatures, build_features


def _store_with_rows(tmp_path, *, n: int = 260) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "canslim_features.db")
    start = date(2024, 1, 1)
    rows = []
    previous_close = None
    for idx in range(n):
        close = 100.0 + idx * 0.1 + (1.0 if idx % 2 else 0.0)
        volume = 2000 if previous_close is not None and close > previous_close else 1000
        rows.append(
            {
                "stock_id": "2330",
                "date": (start + timedelta(days=idx)).strftime("%Y-%m-%d"),
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": volume,
                "turnover": close * volume,
            }
        )
        previous_close = close
    store.upsert_rows(rows)
    return store


def _fin_metrics():
    return {
        # fin_metrics growth fields are FRACTIONS per contract (0.30 = +30%); sources
        # normalize at emission, features no longer magnitude-guesses growth rates.
        "eps_yoy": 0.30,
        "annual_eps": [10.0, 12.0, 15.0],
        "roe": 18.0,
        "op_margin_last4": [20.0, 21.0, 22.0, 23.0],
        "pe_ttm": 35.0,
    }


def _detail(as_of_date: str):
    return {
        "month_revenue_yoy": [0.12, 0.18, 0.24],
        "foreign_net_5": [
            {"date": "2024-09-11", "value": 1.0},
            {"date": "2024-09-12", "value": 2.0},
            {"date": "2024-09-13", "value": 3.0},
            {"date": "2024-09-14", "value": 4.0},
            {"date": "2024-09-15", "value": 5.0},
            {"date": as_of_date, "value": 999.0},
        ],
        "trust_net_5": [10, 11, 12, 13, 14],
        "dealer_net_5": [-1, -2, -3, -4, -5],
    }


def test_all_deps_present_builds_expected_values(tmp_path):
    store = _store_with_rows(tmp_path)
    as_of_date = "2024-09-16"
    features = build_features(
        "2330",
        as_of_date,
        store,
        universe_returns_60d={"1111": -0.1, "2330": 0.2, "2222": 0.4},
        universe_returns_252d={"1111": -0.1, "2330": 0.2, "2222": 0.4},
        fin_metrics=_fin_metrics(),
        detail=_detail(as_of_date),
        eps_filing_date="2024-09-01",
        event_window_active=False,
    )

    assert isinstance(features, CanslimFeatures)
    assert features.close is not None
    assert features.ma20 is not None
    assert features.ma60 is not None
    assert features.ma120 is not None
    assert features.ma120_slope is not None
    assert features.high_252d is not None
    assert features.pct_from_52w_high is not None
    assert features.avg_volume_20 is not None
    assert features.avg_volume_50 is not None
    assert features.avg_turnover_20 is not None
    assert features.up_down_volume_ratio_10 == pytest.approx(2.0)
    assert features.box_high_20 is not None
    assert features.box_low_20 is not None
    assert features.month_revenue_yoy == [0.12, 0.18, 0.24]
    assert features.quarterly_eps_yoy == pytest.approx(0.30)
    assert features.eps_cagr_3y == pytest.approx((15.0 / 10.0) ** 0.5 - 1)
    assert features.roe_ttm == pytest.approx(0.18)
    assert features.op_margin_last4 == [0.20, 0.21, 0.22, 0.23]
    assert features.pe_ttm == pytest.approx(35.0)
    assert features.volume_ratio_recent_vs_prior_20 is not None
    assert features.is_20d_high is not None
    assert features.event_window_active is False
    assert features.foreign_net_5 == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert features.trust_net_5 == [10.0, 11.0, 12.0, 13.0, 14.0]
    assert features.dealer_net_5 == [-1.0, -2.0, -3.0, -4.0, -5.0]
    assert features.rs_60d_pct == pytest.approx(0.5)
    assert features.rs_252d_pct == pytest.approx(0.5)


def test_missing_dependencies_mark_missing_fields(tmp_path):
    store = _store_with_rows(tmp_path)
    features = build_features("2330", "2024-09-16", store)

    assert features.month_revenue_yoy is None
    assert features.quarterly_eps_yoy is None
    assert features.eps_cagr_3y is None
    assert features.roe_ttm is None
    assert features.op_margin_last4 is None
    assert features.foreign_net_5 is None
    assert features.trust_net_5 is None
    assert features.dealer_net_5 is None
    assert features.rs_60d_pct is None
    assert features.rs_252d_pct is None
    for field in (
        "month_revenue_yoy",
        "quarterly_eps_yoy",
        "eps_cagr_3y",
        "roe_ttm",
        "op_margin_last4",
        "foreign_net_5",
        "trust_net_5",
        "dealer_net_5",
        "rs_60d_pct",
        "rs_252d_pct",
    ):
        assert field in features.missing_fields


def test_eps_pit_gate_blocks_future_filing_date(tmp_path):
    store = _store_with_rows(tmp_path)
    features = build_features(
        "2330",
        "2024-09-16",
        store,
        fin_metrics=_fin_metrics(),
        detail=_detail("2024-09-16"),
        eps_filing_date="2024-09-20",
    )

    assert features.quarterly_eps_yoy is None
    assert "quarterly_eps_yoy" in features.missing_fields


def test_unavailable_fields_always_none_with_warnings(tmp_path):
    store = _store_with_rows(tmp_path)
    features = build_features("2330", "2024-09-16", store)

    assert features.day_trade_ratio is None
    assert features.chip_concentration is None
    assert "day_trade_ratio unavailable in data layer" in features.data_warnings
    assert "chip_concentration unavailable in data layer" in features.data_warnings


def test_insufficient_bars_mark_long_lookback_fields_missing(tmp_path):
    store = _store_with_rows(tmp_path, n=100)
    features = build_features("2330", "2024-04-09", store)

    assert features.ma120 is None
    assert features.ma120_slope is None
    assert features.high_252d is None
    assert features.pct_from_52w_high is None
    for field in ("ma120", "ma120_slope", "high_252d", "pct_from_52w_high"):
        assert field in features.missing_fields


def test_rs_percentile_correct_on_small_universe(tmp_path):
    store = _store_with_rows(tmp_path)
    features = build_features(
        "2330",
        "2024-09-16",
        store,
        universe_returns_60d={"1000": -0.2, "1001": 0.1, "2330": 0.4, "1002": 0.8},
        universe_returns_252d={"1000": 0.8, "1001": 0.4, "2330": 0.1, "1002": -0.2},
    )

    assert features.rs_60d_pct == pytest.approx(2 / 3)
    assert features.rs_252d_pct == pytest.approx(1 / 3)


def test_breakout_extension_fields_exclude_latest_bar(tmp_path):
    store = _store_with_rows(tmp_path)
    features = build_features("2330", "2024-09-16", store)

    assert features.latest_volume == pytest.approx(2000.0)
    assert features.box_high_20 == pytest.approx(127.9)
    assert features.box_high_prior_20 == pytest.approx(127.7)
    assert features.box_low_prior_20 == pytest.approx(123.0)


def test_breakout_extension_fields_need_prior_twenty_bars(tmp_path):
    store = _store_with_rows(tmp_path, n=20)
    features = build_features("2330", "2024-01-20", store)

    assert features.latest_volume is not None
    assert features.box_high_prior_20 is None
    assert features.box_low_prior_20 is None
    assert "box_high_prior_20" in features.missing_fields
    assert "box_low_prior_20" in features.missing_fields


def test_avg_volume_20_is_populated_from_recent_volume(tmp_path):
    store = _store_with_rows(tmp_path, n=25)
    features = build_features("2330", "2024-01-25", store)

    assert features.avg_volume_20 is not None
    assert "avg_volume_20" not in features.missing_fields


def test_risk_extension_fields_default_to_unknown_when_not_injected(tmp_path):
    store = _store_with_rows(tmp_path)
    features = build_features("2330", "2024-09-16", store, fin_metrics={"eps_yoy": 0.30})

    assert features.pe_ttm is None
    assert features.event_window_active is None
    assert "pe_ttm" in features.missing_fields
    assert "event_window_active" in features.missing_fields


def test_volume_divergence_fields_need_twenty_bars(tmp_path):
    store = _store_with_rows(tmp_path, n=19)
    features = build_features("2330", "2024-01-19", store)

    assert features.volume_ratio_recent_vs_prior_20 is None
    assert features.is_20d_high is None
    assert "volume_ratio_recent_vs_prior_20" in features.missing_fields
    assert "is_20d_high" in features.missing_fields
