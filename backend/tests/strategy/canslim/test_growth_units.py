"""Regression for the _normalize_ratio >100%-growth corruption (HIGH-1).

A growth rate that legitimately exceeds 1.0 (>100% YoY) must survive feature
extraction as a fraction, not be divided by 100. The PIT path emits fractions; the
live fallback emits percent and must be normalized at its source.
"""
from __future__ import annotations

from backend.app.services.strategy.canslim.features import build_features, _extract_month_revenue_yoy
from backend.app.services.strategy.canslim.live_screening import _metrics_to_canslim
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pillar_screening import screen_C
from backend.app.services.backtest.historical_data_store import HistoricalDataStore


def _store(tmp_path):
    return HistoricalDataStore(tmp_path / "ohlcv.db")  # empty; growth comes from fin_metrics


def test_quarterly_eps_yoy_over_100pct_survives(tmp_path):
    f = build_features(
        "2330", "2025-06-30", _store(tmp_path),
        fin_metrics={"quarterly_eps_yoy": 1.5},  # +150% growth, fraction
        eps_filing_date="2025-05-01",
    )
    assert f.quarterly_eps_yoy == 1.5  # NOT 0.015


def test_quarterly_eps_yoy_fraction_under_1_unchanged(tmp_path):
    f = build_features(
        "2330", "2025-06-30", _store(tmp_path),
        fin_metrics={"quarterly_eps_yoy": 0.30},
        eps_filing_date="2025-05-01",
    )
    assert abs(f.quarterly_eps_yoy - 0.30) < 1e-9


def test_month_revenue_yoy_over_100pct_survives():
    out = _extract_month_revenue_yoy({"month_revenue_yoy": [0.2, 1.5, 2.0]})
    assert out == [0.2, 1.5, 2.0]  # +150%, +200% preserved, not /100


def test_screen_c_passes_hypergrowth_after_fix(tmp_path):
    # 150% quarterly EPS YoY must clear the C pass band (0.25), not fail at 1.5%.
    f = build_features(
        "2330", "2025-06-30", _store(tmp_path),
        fin_metrics={"quarterly_eps_yoy": 1.5},
        eps_filing_date="2025-05-01",
    )
    assert screen_C(f, {}, load_params()).status == "Pass"


def test_live_metrics_percent_eps_yoy_normalized_to_fraction():
    # fetch_real_metrics emits percent (eps_yoy=120.0 means +120%).
    out, _ = _metrics_to_canslim({"eps_yoy": 120.0, "roe": 18.0, "pe_ratio": 15.0})
    assert abs(out["quarterly_eps_yoy"] - 1.20) < 1e-9  # fraction
    # roe left as-is (percent); features._normalize_ratio handles it downstream.
    assert out["roe"] == 18.0


def test_live_metrics_missing_eps_yoy_is_none():
    out, _ = _metrics_to_canslim({"roe": 18.0, "pe_ratio": 15.0})
    assert "quarterly_eps_yoy" not in out  # None filtered out
