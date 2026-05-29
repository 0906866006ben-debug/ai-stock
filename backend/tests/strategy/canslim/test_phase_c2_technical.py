import pytest

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.rules_technical import (
    HORIZONS,
    TECHNICAL_RULES,
    evaluate_t1,
    evaluate_t2,
    evaluate_t3,
    evaluate_t4,
    evaluate_t5,
)


@pytest.fixture(scope="module")
def params():
    return load_params()


def _features(**overrides) -> CanslimFeatures:
    values = {
        "symbol": "2330",
        "as_of_date": "2024-09-16",
        "close": 105.0,
        "ma20": 100.0,
        "ma60": 90.0,
        "ma120": 80.0,
        "ma120_slope": 0.01,
        "high_252d": 100.0,
        "pct_from_52w_high": 0.0,
        "rs_60d_pct": 0.80,
        "avg_volume_50": 1000.0,
        "latest_volume": 1600.0,
        "box_high_prior_20": 100.0,
        "box_low_prior_20": 90.0,
    }
    values.update(overrides)
    return CanslimFeatures(**values)


def _rule(params, rule_id):
    return params["technical"]["rules"][rule_id]


def test_t1_triggers_on_top_quartile_relative_strength(params):
    rule = _rule(params, "T-1")
    value = rule["thresholds"]["rank_percentile_min"]
    result = evaluate_t1(_features(rs_60d_pct=value), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "T-1" in result.reason


def test_t1_does_not_trigger_below_relative_strength_threshold(params):
    value = _rule(params, "T-1")["thresholds"]["rank_percentile_min"]
    result = evaluate_t1(_features(rs_60d_pct=value * 0.5), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_t1_missing_relative_strength_uses_yaml_penalty(params):
    rule = _rule(params, "T-1")
    result = evaluate_t1(_features(rs_60d_pct=None), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == rule["effects"]["missing_data_confidence_delta"]
    assert result.data_warning is not None


def test_t2_triggers_near_52w_high_breakout(params):
    rule = _rule(params, "T-2")
    high = 100.0
    close = high * rule["thresholds"]["breakout_high_252d_multiplier"] + 0.01
    result = evaluate_t2(_features(close=close, high_252d=high), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.risk_delta == 0
    assert result.reason is not None and "T-2" in result.reason


def test_t2_adds_risk_when_extended_from_52w_high(params):
    rule = _rule(params, "T-2")
    high = 100.0
    extension = rule["thresholds"]["risk_pct_from_52w_high_above"] + 0.01
    result = evaluate_t2(_features(close=high * (1 + extension), high_252d=high, pct_from_52w_high=extension), params)

    assert result.triggered is True
    assert result.risk_delta == rule["effects"]["risk_delta_if_extended"]


def test_t2_does_not_trigger_without_breakout_condition(params):
    threshold = _rule(params, "T-2")["thresholds"]["close_to_high_252d_min"]
    high = 100.0
    result = evaluate_t2(_features(close=high * threshold, high_252d=high), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


@pytest.mark.parametrize("overrides", [{"close": None}, {"high_252d": None}])
def test_t2_missing_price_data_has_no_penalty(params, overrides):
    result = evaluate_t2(_features(**overrides), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_t3_triggers_on_stage_two_ma_alignment(params):
    rule = _rule(params, "T-3")
    result = evaluate_t3(_features(), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "T-3" in result.reason


def test_t3_does_not_trigger_when_ma_stack_breaks(params):
    result = evaluate_t3(_features(ma20=80.0, ma60=90.0), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_t3_missing_ma_data_has_no_penalty(params):
    result = evaluate_t3(_features(ma120_slope=None), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_t4_triggers_on_tight_box_breakout(params):
    rule = _rule(params, "T-4")
    high = 100.0
    close = high * rule["thresholds"]["breakout_multiplier"] + 0.01
    result = evaluate_t4(_features(close=close, box_high_prior_20=high, box_low_prior_20=95.0), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "T-4" in result.reason


def test_t4_does_not_trigger_when_box_is_too_wide(params):
    rule = _rule(params, "T-4")
    high = 100.0
    low = high / (1 + rule["thresholds"]["box_range_pct_max"] + 0.05)
    close = high * rule["thresholds"]["breakout_multiplier"] + 0.01
    result = evaluate_t4(_features(close=close, box_high_prior_20=high, box_low_prior_20=low), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


@pytest.mark.parametrize("overrides", [{"close": None}, {"box_high_prior_20": None}, {"box_low_prior_20": None}])
def test_t4_missing_box_data_has_no_penalty(params, overrides):
    result = evaluate_t4(_features(**overrides), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_t5_triggers_on_volume_expansion(params):
    rule = _rule(params, "T-5")
    avg_volume = 1000.0
    latest = avg_volume * rule["thresholds"]["volume_multiple_min"]
    result = evaluate_t5(_features(avg_volume_50=avg_volume, latest_volume=latest), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "T-5" in result.reason


def test_t5_does_not_trigger_below_volume_multiple(params):
    rule = _rule(params, "T-5")
    avg_volume = 1000.0
    latest = avg_volume * rule["thresholds"]["volume_multiple_min"] * 0.9
    result = evaluate_t5(_features(avg_volume_50=avg_volume, latest_volume=latest), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


@pytest.mark.parametrize("overrides", [{"latest_volume": None}, {"avg_volume_50": None}])
def test_t5_missing_volume_data_has_no_penalty(params, overrides):
    result = evaluate_t5(_features(**overrides), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_technical_rules_and_horizons_are_exposed_from_yaml(params):
    assert TECHNICAL_RULES == [evaluate_t1, evaluate_t2, evaluate_t3, evaluate_t4, evaluate_t5]
    for rule_id, horizons in HORIZONS.items():
        assert horizons == tuple(_rule(params, rule_id)["horizons"])
