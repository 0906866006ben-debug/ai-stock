import pytest

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.rules_risk import (
    HORIZONS,
    RISK_RULES,
    evaluate_r1,
    evaluate_r2,
    evaluate_r3,
    evaluate_r4,
    evaluate_r5,
    evaluate_r6,
    evaluate_r7,
    evaluate_r8,
)
from backend.app.services.strategy.canslim.types import MarketFeatures


@pytest.fixture(scope="module")
def params():
    return load_params()


def _features(**overrides) -> CanslimFeatures:
    values = {
        "symbol": "2330",
        "as_of_date": "2024-09-16",
        "close": 120.0,
        "ma20": 100.0,
        "is_20d_high": True,
        "volume_ratio_recent_vs_prior_20": 0.70,
        "foreign_net_5": [1.0, 2.0, -1.0, -2.0, -3.0],
        "trust_net_5": [1.0, 2.0, -1.0, -2.0, -3.0],
        "avg_turnover_20": 50_000_000.0,
        "day_trade_ratio": None,
        "quarterly_eps_yoy": 0.10,
        "pe_ttm": 50.0,
        "event_window_active": False,
    }
    values.update(overrides)
    return CanslimFeatures(**values)


def _market(**overrides) -> MarketFeatures:
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
    return params["risk"]["rules"][rule_id]


def test_r1_triggers_when_extended_from_ma20(params):
    rule = _rule(params, "R-1")
    result = evaluate_r1(_features(), _market(), params, "swing_term")

    assert result.triggered is True
    assert result.risk_delta == rule["effects"]["risk_delta"]
    assert result.hard_block is False


def test_r1_does_not_trigger_when_not_extended(params):
    result = evaluate_r1(_features(close=110.0), _market(), params, "swing_term")

    assert result.triggered is False
    assert result.risk_delta == 0
    assert result.hard_block is False


def test_r2_triggers_on_high_with_volume_divergence(params):
    rule = _rule(params, "R-2")
    result = evaluate_r2(_features(), _market(), params, "swing_term")

    assert result.triggered is True
    assert result.risk_delta == rule["effects"]["risk_delta"]
    assert result.hard_block is False


def test_r2_does_not_trigger_without_volume_decline(params):
    result = evaluate_r2(_features(volume_ratio_recent_vs_prior_20=1.0), _market(), params, "swing_term")

    assert result.triggered is False
    assert result.risk_delta == 0


def test_r3_triggers_on_foreign_and_trust_selling(params):
    rule = _rule(params, "R-3")
    result = evaluate_r3(_features(), _market(), params, "swing_term")

    assert result.triggered is True
    assert result.risk_delta == rule["effects"]["risk_delta"]
    assert result.hard_block is False


def test_r3_does_not_trigger_when_one_side_is_not_selling(params):
    result = evaluate_r3(_features(trust_net_5=[1.0, 2.0, 3.0, 4.0, -2.0]), _market(), params, "swing_term")

    assert result.triggered is False
    assert result.risk_delta == 0


def test_r4_active_event_window_blocks_new_entry(params):
    rule = _rule(params, "R-4")
    result = evaluate_r4(_features(event_window_active=True), _market(), params, "short_term")

    assert result.triggered is True
    assert result.risk_delta == rule["effects"]["risk_delta"]
    assert result.hard_block is True


def test_r4_inactive_event_window_does_not_trigger(params):
    result = evaluate_r4(_features(event_window_active=False), _market(), params, "short_term")

    assert result.triggered is False
    assert result.hard_block is False


def test_r4_unknown_event_calendar_does_not_block(params):
    result = evaluate_r4(_features(event_window_active=None), _market(), params, "short_term")

    assert result.triggered is False
    assert result.hard_block is False
    assert result.risk_delta == 0
    assert result.data_warning is not None


def test_r5_short_term_risk_off_hard_blocks(params):
    result = evaluate_r5(_features(), _market(taiex_close=18_000.0, taiex_ma150=19_000.0), params, "short_term")

    assert result.triggered is True
    assert result.hard_block is True
    assert result.risk_delta == 0


def test_r5_swing_risk_off_adds_risk_without_block(params):
    rule = _rule(params, "R-5")
    result = evaluate_r5(_features(), _market(taiex_close=18_000.0, taiex_ma150=19_000.0), params, "swing_term")

    assert result.triggered is True
    assert result.hard_block is False
    assert result.risk_delta == rule["effects"]["swing_long_risk_delta"]


def test_r5_not_risk_off_does_not_trigger(params):
    result = evaluate_r5(_features(), _market(), params, "short_term")

    assert result.triggered is False
    assert result.hard_block is False
    assert result.risk_delta == 0


def test_r5_missing_market_inputs_do_not_block(params):
    result = evaluate_r5(_features(), _market(taiex_close=None), params, "short_term")

    assert result.triggered is False
    assert result.hard_block is False
    assert result.risk_delta == 0
    assert result.data_warning is not None


def test_r6_low_liquidity_hard_blocks(params):
    floor = _rule(params, "R-6")["thresholds"]["avg_turnover_20_below_twd"]
    result = evaluate_r6(_features(avg_turnover_20=floor * 0.5), _market(), params, "long_term")

    assert result.triggered is True
    assert result.hard_block is True


def test_r6_missing_liquidity_hard_blocks_with_warning(params):
    result = evaluate_r6(_features(avg_turnover_20=None), _market(), params, "long_term")

    assert result.triggered is True
    assert result.hard_block is True
    assert result.data_warning is not None


def test_r7_day_trade_ratio_unavailable_is_inactive(params):
    result = evaluate_r7(_features(), _market(), params, "short_term")

    assert result.triggered is False
    assert result.hard_block is False
    assert result.risk_delta == 0
    assert result.data_warning is not None


def test_r8_triggers_on_valuation_growth_mismatch(params):
    rule = _rule(params, "R-8")
    result = evaluate_r8(_features(), _market(), params, "long_term")

    assert result.triggered is True
    assert result.risk_delta == rule["effects"]["risk_delta"]
    assert result.hard_block is False


def test_r8_does_not_trigger_when_growth_is_not_weak(params):
    threshold = _rule(params, "R-8")["thresholds"]["quarterly_eps_yoy_below"]
    result = evaluate_r8(_features(quarterly_eps_yoy=threshold), _market(), params, "long_term")

    assert result.triggered is False
    assert result.risk_delta == 0


def test_hard_block_guardrail_only_r4_r5_short_and_r6_can_block(params):
    base_features = _features()
    base_market = _market()
    blocking_cases = {
        "R-4": (evaluate_r4, _features(event_window_active=True), base_market, "short_term"),
        "R-5": (evaluate_r5, base_features, _market(taiex_close=18_000.0, taiex_ma150=19_000.0), "short_term"),
        "R-6": (evaluate_r6, _features(avg_turnover_20=None), base_market, "swing_term"),
    }

    for rule in RISK_RULES:
        result = rule(base_features, base_market, params, "swing_term")
        if rule.__name__ in {"evaluate_r4", "evaluate_r5", "evaluate_r6"}:
            continue
        assert result.hard_block is False

    for rule_id, (rule, features, market, horizon) in blocking_cases.items():
        result = rule(features, market, params, horizon)
        assert result.hard_block is True, rule_id

    assert evaluate_r4(_features(event_window_active=None), base_market, params, "short_term").hard_block is False
    assert evaluate_r5(base_features, _market(taiex_close=None), params, "short_term").hard_block is False
    assert evaluate_r5(
        base_features,
        _market(taiex_close=18_000.0, taiex_ma150=19_000.0),
        params,
        "swing_term",
    ).hard_block is False


def test_risk_rules_and_horizons_are_exposed_from_yaml(params):
    assert RISK_RULES == [
        evaluate_r1,
        evaluate_r2,
        evaluate_r3,
        evaluate_r4,
        evaluate_r5,
        evaluate_r6,
        evaluate_r7,
        evaluate_r8,
    ]
    for rule_id, horizons in HORIZONS.items():
        assert horizons == tuple(_rule(params, rule_id)["horizons"])
