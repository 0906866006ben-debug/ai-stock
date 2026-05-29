from __future__ import annotations

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pillar_screening import screen_A, screen_C


def _features(**overrides) -> CanslimFeatures:
    data = {"symbol": "2330", "as_of_date": "2026-01-02", "eps_cagr_3y": 0.3, "roe_ttm": 0.2}
    data.update(overrides)
    return CanslimFeatures(**data)


def _p():
    return load_params()


# ── C: revenue fallback (quarterly EPS unavailable) must require sustained growth ──

def test_c_revenue_fallback_sustained_growth_is_weak():
    p = _p()
    f = _features(quarterly_eps_yoy=None, month_revenue_yoy=[0.12, 0.10, 0.11, 0.13, 0.12])
    v = screen_C(f, {}, p)
    assert v.status == "Weak"
    assert "sustained" in v.reason


def test_c_revenue_fallback_below_floor_is_fail():
    p = _p()
    f = _features(quarterly_eps_yoy=None, month_revenue_yoy=[0.02, 0.02, 0.02, 0.02, 0.02])
    v = screen_C(f, {}, p)
    assert v.status == "Fail"
    assert "below growth floor" in v.reason


def test_c_revenue_fallback_one_month_spike_not_sustained_is_fail():
    p = _p()
    # latest month clears the floor but only 1 of 5 months is positive -> not sustained.
    f = _features(quarterly_eps_yoy=None, month_revenue_yoy=[-0.1, -0.1, -0.1, -0.1, 0.2])
    v = screen_C(f, {}, p)
    assert v.status == "Fail"
    assert "not sustained" in v.reason


# ── A: annual-EPS stability guard caps a mid-period collapse to Weak ──

def test_a_strong_cagr_but_midperiod_collapse_capped_to_weak():
    p = _p()
    # CAGR passes (20/10 -> ~41%) and ROE passes, but EPS collapsed 10->3 mid-period.
    f = _features(eps_cagr_3y=0.41, roe_ttm=0.2, annual_eps_last3=[10.0, 3.0, 20.0])
    v = screen_A(f, {}, p)
    assert v.status == "Weak"
    assert "stability" in " ".join(v.data_warnings).lower()


def test_a_steady_growth_stays_pass():
    p = _p()
    f = _features(eps_cagr_3y=0.30, roe_ttm=0.2, annual_eps_last3=[10.0, 13.0, 17.0])
    v = screen_A(f, {}, p)
    assert v.status == "Pass"


def test_a_no_annual_series_unaffected():
    p = _p()
    f = _features(eps_cagr_3y=0.30, roe_ttm=0.2)  # annual_eps_last3 is None
    assert screen_A(f, {}, p).status == "Pass"


# ── C: earnings acceleration (O'Neil) ──

def test_c_accelerating_series_passes_with_driver():
    p = _p()
    f = _features(quarterly_eps_yoy=0.50, quarterly_eps_yoy_series=[0.2, 0.3, 0.5])
    v = screen_C(f, {}, p)
    assert v.status == "Pass"
    assert any("accelerating" in d for d in v.drivers)


def test_c_severe_deceleration_caps_pass_to_weak():
    p = _p()
    # latest 0.40 passes the band but growth-rate more than halved (1.0 -> 0.40).
    f = _features(quarterly_eps_yoy=0.40, quarterly_eps_yoy_series=[0.8, 1.0, 0.40])
    v = screen_C(f, {}, p)
    assert v.status == "Weak"
    assert "decelerat" in " ".join(v.data_warnings).lower()


def test_c_few_quarters_no_severe_cap():
    p = _p()
    # only 2 quarters (< accel_min_quarters=3) -> no severe cap even if lower.
    f = _features(quarterly_eps_yoy=0.40, quarterly_eps_yoy_series=[1.0, 0.40])
    assert screen_C(f, {}, p).status == "Pass"


def test_c_no_series_unaffected():
    p = _p()
    f = _features(quarterly_eps_yoy=0.40)  # no series
    assert screen_C(f, {}, p).status == "Pass"
