import pytest

from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.rules_market import (
    HORIZONS,
    MARKET_RULES,
    evaluate_m1,
    evaluate_m2,
    evaluate_m3,
    evaluate_m4,
)
from backend.app.services.strategy.canslim.types import MarketFeatures


@pytest.fixture(scope="module")
def params():
    return load_params()


def _features(**overrides) -> MarketFeatures:
    values = {
        "taiex_close": 20_000.0,
        "taiex_ma150": 19_000.0,
        "taiex_ma150_slope": 0.01,
        "tpex_close": 250.0,
        "tpex_ma150": 240.0,
        "tpex_ma150_slope": 0.01,
        "breadth_above_ma60_pct": 0.65,
        "sox_above_ma60": True,
        "nasdaq_above_ma60": True,
    }
    values.update(overrides)
    return MarketFeatures(**values)


def _rule(params, rule_id):
    return params["market"]["rules"][rule_id]


def test_market_features_type_is_frozen():
    features = _features()

    with pytest.raises(Exception):
        features.taiex_close = 1.0


def test_m1_triggers_on_taiex_uptrend_without_risk(params):
    result = evaluate_m1(_features(), params)

    assert result.triggered is True
    assert result.signal_delta == 0
    assert result.risk_delta == 0
    assert result.confidence_delta == 0
    assert result.reason is not None and "M-1" in result.reason


def test_m1_adds_risk_when_taiex_regime_fails(params):
    rule = _rule(params, "M-1")
    result = evaluate_m1(_features(taiex_close=18_000.0, taiex_ma150=19_000.0), params)

    assert result.triggered is False
    assert result.risk_delta == rule["effects"]["risk_delta_on_fail"]
    assert result.hard_block is False
    assert result.reason is not None and rule["effects"]["regime_on_fail"] in result.reason


def test_m1_missing_inputs_have_warning_and_no_risk(params):
    result = evaluate_m1(_features(taiex_ma150_slope=None), params)

    assert result.triggered is False
    assert result.risk_delta == 0
    assert result.data_warning is not None
    assert result.hard_block is False


def test_m2_triggers_when_taiex_and_tpex_both_up(params):
    result = evaluate_m2(_features(), params)

    assert result.triggered is True
    assert result.risk_delta == 0
    assert result.reason is not None and "M-2" in result.reason


def test_m2_adds_risk_when_tpex_disagrees_with_taiex(params):
    rule = _rule(params, "M-2")
    result = evaluate_m2(_features(tpex_close=230.0, tpex_ma150=240.0), params)

    assert result.triggered is False
    assert result.risk_delta == rule["effects"]["risk_delta_if_disagrees_with_taiex"]
    assert result.hard_block is False


def test_m2_missing_inputs_have_warning_and_no_risk(params):
    result = evaluate_m2(_features(tpex_close=None), params)

    assert result.triggered is False
    assert result.risk_delta == 0
    assert result.data_warning is not None


def test_m3_positive_breadth_adds_confidence(params):
    rule = _rule(params, "M-3")
    value = rule["thresholds"]["universe_above_ma60_pct_min"]
    result = evaluate_m3(_features(breadth_above_ma60_pct=value), params)

    assert result.triggered is True
    assert result.confidence_delta == rule["effects"]["confidence_delta_if_met"]
    assert result.risk_delta == 0
    assert result.reason is not None and "M-3" in result.reason


def test_m3_weak_breadth_adds_risk(params):
    rule = _rule(params, "M-3")
    value = rule["thresholds"]["risk_pct_below"] - 0.01
    result = evaluate_m3(_features(breadth_above_ma60_pct=value), params)

    assert result.triggered is False
    assert result.risk_delta == rule["effects"]["risk_delta_if_below"]
    assert result.confidence_delta == 0


def test_m3_middle_breadth_has_no_delta(params):
    rule = _rule(params, "M-3")
    low = rule["thresholds"]["risk_pct_below"]
    high = rule["thresholds"]["universe_above_ma60_pct_min"]
    result = evaluate_m3(_features(breadth_above_ma60_pct=(low + high) / 2), params)

    assert result.triggered is False
    assert result.risk_delta == 0
    assert result.confidence_delta == 0


def test_m3_missing_breadth_has_warning_and_no_delta(params):
    result = evaluate_m3(_features(breadth_above_ma60_pct=None), params)

    assert result.triggered is False
    assert result.risk_delta == 0
    assert result.confidence_delta == 0
    assert result.data_warning is not None


def test_m4_both_external_markets_supportive_adds_signal_and_confidence(params):
    rule = _rule(params, "M-4")
    result = evaluate_m4(_features(sox_above_ma60=True, nasdaq_above_ma60=True), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.risk_delta == 0


def test_m4_both_external_markets_below_adds_risk(params):
    rule = _rule(params, "M-4")
    result = evaluate_m4(_features(sox_above_ma60=False, nasdaq_above_ma60=False), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.risk_delta == rule["effects"]["risk_delta_if_both_below"]


def test_m4_mixed_external_markets_have_no_delta(params):
    result = evaluate_m4(_features(sox_above_ma60=True, nasdaq_above_ma60=False), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.risk_delta == 0
    assert result.confidence_delta == 0


def test_m4_missing_external_inputs_have_warning_and_no_delta(params):
    result = evaluate_m4(_features(sox_above_ma60=None), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.risk_delta == 0
    assert result.data_warning is not None


def test_no_market_rule_returns_hard_block(params):
    scenarios = [
        _features(taiex_close=18_000.0, taiex_ma150=19_000.0),
        _features(tpex_close=230.0, tpex_ma150=240.0),
        _features(breadth_above_ma60_pct=0.10),
        _features(sox_above_ma60=False, nasdaq_above_ma60=False),
    ]

    for rule in MARKET_RULES:
        for features in scenarios:
            assert rule(features, params).hard_block is False


def test_market_rules_and_horizons_are_exposed_from_yaml(params):
    assert MARKET_RULES == [evaluate_m1, evaluate_m2, evaluate_m3, evaluate_m4]
    for rule_id, horizons in HORIZONS.items():
        assert horizons == tuple(_rule(params, rule_id)["horizons"])
