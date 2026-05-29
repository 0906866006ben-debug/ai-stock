import pytest

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.rules_growth import evaluate_g4
from backend.app.services.strategy.canslim.rules_supply import (
    HORIZONS,
    SUPPLY_RULES,
    evaluate_sd1,
    evaluate_sd2,
    evaluate_sd3,
    evaluate_sd4,
)
from backend.app.services.strategy.canslim.rules_technical import evaluate_t5


@pytest.fixture(scope="module")
def params():
    return load_params()


def _features(**overrides) -> CanslimFeatures:
    values = {
        "symbol": "2330",
        "as_of_date": "2024-09-16",
        "avg_turnover_20": 50_000_000.0,
        "up_down_volume_ratio_10": 1.5,
        "roe_ttm": 0.18,
        "avg_volume_50": 1000.0,
        "latest_volume": 1600.0,
    }
    values.update(overrides)
    return CanslimFeatures(**values)


def _rule(params, rule_id):
    return params["supply"]["rules"][rule_id]


def test_sd1_passes_liquidity_floor_without_hard_block(params):
    rule = _rule(params, "SD-1")
    floor = rule["thresholds"]["avg_turnover_20_min_twd"]
    result = evaluate_sd1(_features(avg_turnover_20=floor), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == 0
    assert result.hard_block is False
    assert result.reason is not None and "SD-1" in result.reason


def test_sd1_fails_liquidity_floor_with_hard_block(params):
    floor = _rule(params, "SD-1")["thresholds"]["avg_turnover_20_min_twd"]
    result = evaluate_sd1(_features(avg_turnover_20=floor * 0.5), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0
    assert result.hard_block is True
    assert result.reason is not None and "SD-1" in result.reason


def test_sd1_missing_turnover_is_conservative_hard_block(params):
    result = evaluate_sd1(_features(avg_turnover_20=None), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0
    assert result.hard_block is True
    assert result.data_warning is not None


def test_sd2_triggers_on_up_day_volume_expansion(params):
    rule = _rule(params, "SD-2")
    value = rule["thresholds"]["up_to_down_volume_ratio_min"]
    result = evaluate_sd2(_features(up_down_volume_ratio_10=value), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.hard_block is False
    assert result.reason is not None and "SD-2" in result.reason


def test_sd2_does_not_trigger_below_volume_ratio_threshold(params):
    value = _rule(params, "SD-2")["thresholds"]["up_to_down_volume_ratio_min"]
    result = evaluate_sd2(_features(up_down_volume_ratio_10=value * 0.5), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0
    assert result.hard_block is False


def test_sd2_missing_volume_ratio_has_no_penalty(params):
    result = evaluate_sd2(_features(up_down_volume_ratio_10=None), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0
    assert result.hard_block is False


def test_sd3_day_trade_ratio_unavailable_returns_missing_confidence(params):
    rule = _rule(params, "SD-3")
    result = evaluate_sd3(_features(), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.risk_delta == 0
    assert result.confidence_delta == rule["effects"]["confidence_delta_missing"]
    assert result.hard_block is False
    assert result.data_warning is not None


def test_sd4_chip_concentration_unavailable_is_null_rule(params):
    result = evaluate_sd4(_features(), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.risk_delta == 0
    assert result.confidence_delta == 0
    assert result.hard_block is False
    assert result.data_warning is not None


def test_growth_and_technical_results_default_hard_block_false(params):
    growth_result = evaluate_g4(_features(roe_ttm=0.20), params)
    technical_result = evaluate_t5(_features(avg_volume_50=1000.0, latest_volume=2000.0), params)

    assert growth_result.triggered is True
    assert growth_result.hard_block is False
    assert technical_result.triggered is True
    assert technical_result.hard_block is False


def test_supply_rules_and_horizons_are_exposed_from_yaml(params):
    assert SUPPLY_RULES == [evaluate_sd1, evaluate_sd2, evaluate_sd3, evaluate_sd4]
    for rule_id, horizons in HORIZONS.items():
        assert horizons == tuple(_rule(params, rule_id)["horizons"])
