import pytest

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.rules_institutional import (
    HORIZONS,
    INSTITUTIONAL_RULES,
    evaluate_i1,
    evaluate_i2,
    evaluate_i3,
    evaluate_i4,
)


@pytest.fixture(scope="module")
def params():
    return load_params()


def _features(**overrides) -> CanslimFeatures:
    values = {
        "symbol": "2330",
        "as_of_date": "2024-09-16",
        "foreign_net_5": [-100.0, 50.0, 40.0, 35.0, 30.0],
        "trust_net_5": [-10.0, 12.0, 13.0, -2.0, 14.0],
        "dealer_net_5": [1.0, -1.0, 0.5, -0.5, 0.0],
        "avg_volume_20": 1000.0,
    }
    values.update(overrides)
    return CanslimFeatures(**values)


def _rule(params, rule_id):
    return params["institutional"]["rules"][rule_id]


def test_i1_triggers_on_foreign_consecutive_flow_with_cumulative_gate(params):
    rule = _rule(params, "I-1")
    result = evaluate_i1(_features(foreign_net_5=[-1.0, -2.0, 25.0, 30.0, 35.0], avg_volume_20=1000.0), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "I-1" in result.reason


def test_i1_does_not_trigger_with_only_two_recent_positive_days(params):
    result = evaluate_i1(_features(foreign_net_5=[10.0, 15.0, -1.0, 20.0, 25.0]), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_i1_missing_foreign_flow_uses_yaml_penalty(params):
    rule = _rule(params, "I-1")
    result = evaluate_i1(_features(foreign_net_5=None), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == rule["effects"]["missing_data_confidence_delta"]
    assert result.data_warning is not None


def test_i1_triggers_primary_only_when_avg_volume_20_missing(params):
    rule = _rule(params, "I-1")
    result = evaluate_i1(_features(foreign_net_5=[-1.0, -2.0, 1.0, 1.0, 1.0], avg_volume_20=None), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.data_warning is not None


def test_i1_does_not_trigger_when_cumulative_gate_fails(params):
    result = evaluate_i1(_features(foreign_net_5=[-1.0, -2.0, 1.0, 1.0, 1.0], avg_volume_20=1000.0), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_i2_triggers_when_trust_has_enough_positive_days(params):
    rule = _rule(params, "I-2")
    result = evaluate_i2(_features(trust_net_5=[1.0, -1.0, 2.0, -2.0, 3.0]), params)

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "I-2" in result.reason


def test_i2_does_not_trigger_with_too_few_positive_days(params):
    result = evaluate_i2(_features(trust_net_5=[1.0, -1.0, -2.0, -3.0, 4.0]), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_i2_missing_trust_flow_has_no_penalty(params):
    result = evaluate_i2(_features(trust_net_5=None), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_i3_triggers_only_when_foreign_and_trust_trigger(params):
    rule = _rule(params, "I-3")
    result = evaluate_i3(
        _features(
            foreign_net_5=[-1.0, -2.0, 25.0, 30.0, 35.0],
            trust_net_5=[1.0, -1.0, 2.0, -2.0, 3.0],
            avg_volume_20=1000.0,
        ),
        params,
    )

    assert result.triggered is True
    assert result.signal_delta == rule["effects"]["signal_delta"]
    assert result.confidence_delta == rule["effects"]["confidence_delta"]
    assert result.reason is not None and "I-3" in result.reason


def test_i3_does_not_trigger_when_only_one_side_triggers(params):
    result = evaluate_i3(
        _features(
            foreign_net_5=[-1.0, -2.0, 25.0, 30.0, 35.0],
            trust_net_5=[1.0, -1.0, -2.0, -3.0, 4.0],
            avg_volume_20=1000.0,
        ),
        params,
    )

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.confidence_delta == 0


def test_i4_proprietary_flow_is_untrusted_without_hedge_breakdown(params):
    result = evaluate_i4(_features(dealer_net_5=[100.0, 100.0, 100.0, 100.0, 100.0]), params)

    assert result.triggered is False
    assert result.signal_delta == 0
    assert result.risk_delta == 0
    assert result.confidence_delta == 0
    assert result.hard_block is False
    assert result.data_warning is not None


def test_institutional_rules_and_horizons_are_exposed_from_yaml(params):
    assert INSTITUTIONAL_RULES == [evaluate_i1, evaluate_i2, evaluate_i3, evaluate_i4]
    for rule_id, horizons in HORIZONS.items():
        assert horizons == tuple(_rule(params, rule_id)["horizons"])
