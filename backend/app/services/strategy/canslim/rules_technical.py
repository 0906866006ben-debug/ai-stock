"""Pure CAN SLIM technical rule evaluators."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.types import RuleResult

Params = Mapping[str, Any]
TechnicalRule = Callable[[CanslimFeatures, Params], RuleResult]


def evaluate_t1(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "T-1")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    value = features.rs_60d_pct

    if value is None:
        return _missing("T-1", effects, "rs_60d_pct missing")
    if value < float(thresholds["rank_percentile_min"]):
        return RuleResult(rule_id="T-1", triggered=False)
    return RuleResult(
        rule_id="T-1",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"T-1 rs_60d_pct={value:.4f}",
    )


def evaluate_t2(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "T-2")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    close = features.close
    high = features.high_252d

    if close is None or high is None or high == 0:
        return RuleResult(rule_id="T-2", triggered=False)

    close_to_high = close / high
    triggered = (
        close_to_high >= float(thresholds["close_to_high_252d_min"])
        and close > high * float(thresholds["breakout_high_252d_multiplier"])
    )
    if not triggered:
        return RuleResult(rule_id="T-2", triggered=False)

    risk_delta = 0
    if features.pct_from_52w_high is not None and features.pct_from_52w_high > float(
        thresholds["risk_pct_from_52w_high_above"]
    ):
        risk_delta = int(effects["risk_delta_if_extended"])
    return RuleResult(
        rule_id="T-2",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        risk_delta=risk_delta,
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"T-2 close_to_high_252d={close_to_high:.4f}",
    )


def evaluate_t3(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "T-3")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    values = (features.close, features.ma20, features.ma60, features.ma120, features.ma120_slope)

    if any(value is None for value in values):
        return RuleResult(rule_id="T-3", triggered=False)

    close, ma20, ma60, ma120, slope = values
    triggered = close > ma20 > ma60 > ma120 and slope >= float(thresholds["ma120_slope_min"])
    if not triggered:
        return RuleResult(rule_id="T-3", triggered=False)
    return RuleResult(
        rule_id="T-3",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"T-3 ma_alignment close={close:.4f}, ma120_slope={slope:.4f}",
    )


def evaluate_t4(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "T-4")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    close = features.close
    box_high = features.box_high_prior_20
    box_low = features.box_low_prior_20

    if close is None or box_high is None or box_low is None or box_low == 0:
        return RuleResult(rule_id="T-4", triggered=False)

    tightness = (box_high - box_low) / box_low
    triggered = (
        close > box_high * float(thresholds["breakout_multiplier"])
        and tightness <= float(thresholds["box_range_pct_max"])
    )
    if not triggered:
        return RuleResult(rule_id="T-4", triggered=False)
    return RuleResult(
        rule_id="T-4",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"T-4 box_breakout close={close:.4f}, tightness={tightness:.4f}",
    )


def evaluate_t5(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "T-5")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    latest_volume = features.latest_volume
    avg_volume = features.avg_volume_50

    if latest_volume is None or avg_volume is None:
        return RuleResult(rule_id="T-5", triggered=False)
    if latest_volume < avg_volume * float(thresholds["volume_multiple_min"]):
        return RuleResult(rule_id="T-5", triggered=False)
    return RuleResult(
        rule_id="T-5",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"T-5 volume_multiple={latest_volume / avg_volume:.4f}",
    )


def _rule(params: Params, rule_id: str) -> Params:
    return params["technical"]["rules"][rule_id]


def _missing(rule_id: str, effects: Params, data_warning: str) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        triggered=False,
        confidence_delta=int(effects["missing_data_confidence_delta"]),
        data_warning=data_warning,
    )


def _load_horizons() -> dict[str, tuple[str, ...]]:
    params = load_params()
    return {
        rule_id: tuple(rule["horizons"])
        for rule_id, rule in params["technical"]["rules"].items()
        if rule_id in {"T-1", "T-2", "T-3", "T-4", "T-5"}
    }


TECHNICAL_RULES: list[TechnicalRule] = [
    evaluate_t1,
    evaluate_t2,
    evaluate_t3,
    evaluate_t4,
    evaluate_t5,
]

HORIZONS = _load_horizons()
