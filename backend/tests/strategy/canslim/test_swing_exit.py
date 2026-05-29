"""Swing exit / invalidation layer — each signal fires, verb-free, precedence."""
from __future__ import annotations

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.screening_language import contains_forbidden_action_language
from backend.app.services.strategy.canslim.swing_exit import evaluate_swing_exit


def _f(**ov) -> CanslimFeatures:
    return CanslimFeatures(symbol="2330", as_of_date="2026-01-02", **ov)


def _p():
    return load_params()


def test_none_features_is_intact():
    r = evaluate_swing_exit(None, _p())
    assert r == {"exit_signals": [], "structure_status": "intact"}


def test_intact_when_above_mas_and_not_extended():
    f = _f(close=105.0, ma20=100.0, ma60=95.0)
    r = evaluate_swing_exit(f, _p())
    assert r["structure_status"] == "intact"
    assert r["exit_signals"] == []


def test_below_ma20_is_weakening():
    f = _f(close=98.0, ma20=100.0, ma60=90.0)
    r = evaluate_swing_exit(f, _p())
    assert r["structure_status"] == "weakening"
    assert any("20日均線" in s for s in r["exit_signals"])


def test_below_ma60_is_invalidated():
    f = _f(close=88.0, ma20=100.0, ma60=90.0)
    r = evaluate_swing_exit(f, _p())
    assert r["structure_status"] == "invalidated"
    assert any("60日均線" in s for s in r["exit_signals"])


def test_overextension_is_profit_watch():
    # close 20% above MA20, still above both MAs -> profit-watch (not weakening).
    f = _f(close=120.0, ma20=100.0, ma60=90.0)
    r = evaluate_swing_exit(f, _p())
    assert r["structure_status"] == "profit_watch"
    assert any("延伸" in s or "獲利" in s for s in r["exit_signals"])


def test_volume_price_divergence():
    f = _f(close=105.0, ma20=100.0, ma60=95.0, pct_from_52w_high=-0.02,
           volume_ratio_recent_vs_prior_20=0.7)
    r = evaluate_swing_exit(f, _p())
    assert any("背離" in s for s in r["exit_signals"])


def test_limit_down_invalidated():
    f = _f(close=105.0, ma20=100.0, ma60=95.0, at_limit_down=True)
    r = evaluate_swing_exit(f, _p())
    assert r["structure_status"] == "invalidated"


def test_base_low_break_invalidated():
    f = _f(close=94.0, ma20=100.0, ma60=92.0, box_low_20=95.0)
    r = evaluate_swing_exit(f, _p())
    assert r["structure_status"] == "invalidated"
    assert any("盤整低點" in s for s in r["exit_signals"])


def test_all_signals_are_verb_free():
    # Trigger several at once; nothing may contain buy/sell/hold/exit action language.
    f = _f(close=88.0, ma20=100.0, ma60=90.0, box_low_20=95.0,
           pct_from_52w_high=-0.02, volume_ratio_recent_vs_prior_20=0.7,
           at_limit_down=True, latest_volume=5_000_000, avg_volume_20=1_000_000)
    r = evaluate_swing_exit(f, _p())
    assert r["exit_signals"]
    assert not contains_forbidden_action_language(r["exit_signals"])
