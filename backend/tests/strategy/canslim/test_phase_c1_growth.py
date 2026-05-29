import pytest

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.rules_growth import (
    GROWTH_RULES,
    HORIZONS,
    evaluate_g1,
    evaluate_g2,
    evaluate_g3,
    evaluate_g4,
    evaluate_g5,
)


@pytest.fixture(scope="module")
def params():
    return load_params()


def _features(**overrides) -> CanslimFeatures:
    values = {
        "symbol": "2330",
        "as_of_date": "2024-09-16",
        "month_revenue_yoy": [0.12, 0.18, 0.24],
        "quarterly_eps_yoy": 0.30,
        "eps_cagr_3y": 0.30,
        "roe_ttm": 0.18,
        "op_margin_last4": [0.20, 0.21, 0.22, 0.23],
    }
    values.update(overrides)
    return CanslimFeatures(**values)


def _rule(params, rule_id):
    return params["growth"]["rules"][rule_id]


def test_g1_triggers_on_revenue_growth_acceleration(params):
    rule = _rule(params, "G-1")
    threshold = rule["thresholds"]["latest_month_revenue_yoy_min"]
    result = evaluate_g1(
        _features(month_revenue_yoy=[threshold * 0.8, threshold, threshold * 1.2]),
        params,
    )

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta_complete"]
    assert result.risk_delta == 0
    assert result.reason is not None and "G-1" in result.reason


def test_g1_does_not_trigger_without_acceleration(params):
    threshold = _rule(params, "G-1")["thresholds"]["latest_month_revenue_yoy_min"]
    result = evaluate_g1(_features(month_revenue_yoy=[threshold, threshold * 1.2, threshold]), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


@pytest.mark.parametrize("values", [None, [0.30]])
def test_g1_missing_or_insufficient_revenue_data(params, values):
    rule = _rule(params, "G-1")
    result = evaluate_g1(_features(month_revenue_yoy=values), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == rule["effects"]["missing_data_confidence_delta"]
    assert result.data_warning is not None


def test_g2_triggers_on_strong_quarterly_eps(params):
    rule = _rule(params, "G-2")
    value = rule["thresholds"]["quarterly_eps_yoy_min"]
    result = evaluate_g2(_features(quarterly_eps_yoy=value), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "G-2" in result.reason


def test_g2_does_not_trigger_below_eps_threshold(params):
    value = _rule(params, "G-2")["thresholds"]["quarterly_eps_yoy_min"]
    result = evaluate_g2(_features(quarterly_eps_yoy=value * 0.5), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_g2_missing_eps_data(params):
    rule = _rule(params, "G-2")
    result = evaluate_g2(_features(quarterly_eps_yoy=None), params)

    assert result.triggered is False
    assert result.confidence_delta == rule["effects"]["missing_data_confidence_delta"]
    assert result.data_warning is not None


def test_g3_triggers_on_eps_cagr(params):
    rule = _rule(params, "G-3")
    value = rule["thresholds"]["annual_eps_cagr_3y_min"]
    result = evaluate_g3(_features(eps_cagr_3y=value), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "G-3" in result.reason


def test_g3_does_not_trigger_below_cagr_threshold(params):
    value = _rule(params, "G-3")["thresholds"]["annual_eps_cagr_3y_min"]
    result = evaluate_g3(_features(eps_cagr_3y=value * 0.5), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_g3_missing_cagr_data(params):
    rule = _rule(params, "G-3")
    result = evaluate_g3(_features(eps_cagr_3y=None), params)

    assert result.triggered is False
    assert result.confidence_delta == rule["effects"]["missing_data_confidence_delta"]
    assert result.data_warning is not None


def test_g4_triggers_on_strong_roe(params):
    rule = _rule(params, "G-4")
    value = rule["thresholds"]["roe_ttm_min"]
    result = evaluate_g4(_features(roe_ttm=value), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "G-4" in result.reason


def test_g4_does_not_trigger_below_roe_threshold(params):
    value = _rule(params, "G-4")["thresholds"]["roe_ttm_min"]
    result = evaluate_g4(_features(roe_ttm=value * 0.5), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_g4_missing_roe_data(params):
    rule = _rule(params, "G-4")
    result = evaluate_g4(_features(roe_ttm=None), params)

    assert result.triggered is False
    assert result.confidence_delta == rule["effects"]["missing_data_confidence_delta"]
    assert result.data_warning is not None


def test_g5_triggers_when_latest_margin_holds_up(params):
    rule = _rule(params, "G-5")
    multiplier = rule["thresholds"]["latest_vs_prior_mean_min_multiplier"]
    prior = [0.20, 0.21, 0.22]
    latest = sum(prior) / len(prior) * multiplier
    result = evaluate_g5(_features(op_margin_last4=[*prior, latest]), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.risk_delta == 0
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "G-5" in result.reason


def test_g5_does_not_trigger_when_latest_margin_breaks_threshold(params):
    rule = _rule(params, "G-5")
    multiplier = rule["thresholds"]["latest_vs_prior_mean_min_multiplier"]
    prior = [0.20, 0.21, 0.22]
    latest = sum(prior) / len(prior) * multiplier * 0.9
    result = evaluate_g5(_features(op_margin_last4=[*prior, latest]), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


@pytest.mark.parametrize("values", [None, [0.20, 0.19]])
def test_g5_missing_or_insufficient_margin_data(params, values):
    rule = _rule(params, "G-5")
    result = evaluate_g5(_features(op_margin_last4=values), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == rule["effects"]["missing_data_confidence_delta"]
    assert result.data_warning is not None


def test_g5_adds_risk_when_margin_has_four_quarter_downtrend(params):
    rule = _rule(params, "G-5")
    downtrend_bps = rule["thresholds"]["downtrend_bps_over_4q"]
    decline = downtrend_bps / 10000
    first = 0.30
    latest = first - decline
    result = evaluate_g5(_features(op_margin_last4=[first, first - decline / 3, first - decline / 2, latest]), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.risk_delta == rule["effects"]["risk_delta_if_downtrend"]


def test_growth_rules_and_horizons_are_exposed_from_yaml(params):
    assert GROWTH_RULES == [evaluate_g1, evaluate_g2, evaluate_g3, evaluate_g4, evaluate_g5]
    for rule_id, horizons in HORIZONS.items():
        assert horizons == tuple(_rule(params, rule_id)["horizons"])
