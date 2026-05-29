from pathlib import Path

import pytest

from backend.app.services.backtest.v2.tier_classifier import (
    EntryTier,
    classify_tier,
    load_tier_thresholds,
    parse_entry_tier,
    position_multiplier,
)


def _base_features(**overrides):
    features = {
        "range_90d": 0.20,
        "volume_contraction_ratio": 0.80,
        "ema_spread": 0.04,
        "close": 101.0,
        "base_high": 100.0,
        "close_to_base_high": 1.01,
        "avg_turnover_20": 120_000_000,
        "return_90d": 0.08,
        "ema5_slope": 0.01,
        "ema10_slope": 0.005,
        "ema20_slope": 0.001,
        "base_range_pct": 0.12,
        "volume_today": 150_000,
        "avg_vol_50": 100_000,
        "trend_template_ok": True,
    }
    features.update(overrides)
    return features


def _scores(**overrides):
    scores = {
        "pre_breakout_score": 72,
        "ema_micro_upturn_score": 65,
        "base_compression_score": 63,
        "ema_down_to_up_transition_score": 55,
    }
    scores.update(overrides)
    return scores


def test_tier_none_when_basic_invariant_fails():
    assert classify_tier(_base_features(range_90d=0.35), _scores(), risk_score=30) == EntryTier.NONE


def test_tier_c_basic_flat_base_passes():
    features = _base_features(ema_spread=0.07, volume_today=100_000)
    assert classify_tier(features, _scores(pre_breakout_score=20), risk_score=80) == EntryTier.C


def test_tier_b_with_ema_convergence():
    scores = _scores(pre_breakout_score=52, ema_micro_upturn_score=0, base_compression_score=0)
    assert classify_tier(_base_features(volume_today=125_000), scores, risk_score=50) == EntryTier.B


def test_tier_a_with_volume_confirmation():
    scores = _scores(pre_breakout_score=62, ema_micro_upturn_score=55, base_compression_score=51)
    features = _base_features(volume_today=142_000, avg_turnover_20=80_000_000)
    assert classify_tier(features, scores, risk_score=40) == EntryTier.A


def test_tier_s_full_premium_with_trend_template():
    assert classify_tier(_base_features(), _scores(), risk_score=20) == EntryTier.S


def test_cascading_demotes_on_failed_condition():
    scores = _scores(ema_down_to_up_transition_score=49)
    assert classify_tier(_base_features(), scores, risk_score=20) == EntryTier.A


def test_position_multiplier_returns_correct_value():
    multipliers = {"C": 0.3, "B": 0.7, "A": 1.0, "S": 1.5}
    assert position_multiplier(EntryTier.C, multipliers) == 0.3
    assert position_multiplier("S", multipliers) == 1.5
    assert position_multiplier(0, multipliers) == 0.0


def test_tier_thresholds_loaded_from_yaml():
    thresholds = load_tier_thresholds()
    assert Path(__file__).exists()
    assert thresholds["tiers"]["C"]["range_90d_min"] == pytest.approx(0.10)
    assert thresholds["position_multipliers"]["S"] == pytest.approx(1.5)


def test_int_enum_comparison_works():
    assert EntryTier.S > EntryTier.A > EntryTier.B > EntryTier.C > EntryTier.NONE


def test_legacy_int_input_compat():
    assert parse_entry_tier(2) == EntryTier.B
    assert parse_entry_tier("2") == EntryTier.B
    assert parse_entry_tier("B") == EntryTier.B

