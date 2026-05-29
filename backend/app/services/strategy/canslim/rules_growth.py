"""Pure CAN SLIM growth rule evaluators."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from statistics import mean
from typing import Any

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.types import RuleResult

Params = Mapping[str, Any]
GrowthRule = Callable[[CanslimFeatures, Params], RuleResult]

HORIZONS: dict[str, tuple[str, ...]] = {}


def evaluate_g1(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "G-1")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    values = features.month_revenue_yoy
    required = int(thresholds["min_months_required"])

    if values is None or len(values) < required:
        return _missing("G-1", effects, "month_revenue_yoy missing or insufficient")

    latest = values[-1]
    previous = values[-2]
    triggered = latest >= float(thresholds["latest_month_revenue_yoy_min"]) and latest > previous
    if not triggered:
        return RuleResult(rule_id="G-1", triggered=False)
    return RuleResult(
        rule_id="G-1",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta_complete"]),
        reason=f"G-1 month_revenue_yoy latest={latest:.4f}, previous={previous:.4f}",
    )


def evaluate_g2(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "G-2")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    value = features.quarterly_eps_yoy

    if value is None:
        return _missing("G-2", effects, "quarterly_eps_yoy missing")
    if value < float(thresholds["quarterly_eps_yoy_min"]):
        return RuleResult(rule_id="G-2", triggered=False)
    return RuleResult(
        rule_id="G-2",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"G-2 quarterly_eps_yoy={value:.4f}",
    )


def evaluate_g3(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "G-3")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    value = features.eps_cagr_3y

    if value is None:
        return _missing("G-3", effects, "eps_cagr_3y missing")
    if value < float(thresholds["annual_eps_cagr_3y_min"]):
        return RuleResult(rule_id="G-3", triggered=False)
    return RuleResult(
        rule_id="G-3",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"G-3 eps_cagr_3y={value:.4f}",
    )


def evaluate_g4(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "G-4")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    value = features.roe_ttm

    if value is None:
        return _missing("G-4", effects, "roe_ttm missing")
    if value < float(thresholds["roe_ttm_min"]):
        return RuleResult(rule_id="G-4", triggered=False)
    return RuleResult(
        rule_id="G-4",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"G-4 roe_ttm={value:.4f}",
    )


def evaluate_g5(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "G-5")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    values = features.op_margin_last4
    required = int(thresholds["quarters_required"])

    if values is None or len(values) < required:
        return _missing("G-5", effects, "op_margin_last4 missing or insufficient")

    recent = values[-required:]
    latest = recent[-1]
    prior_mean = mean(recent[:-1])
    triggered = latest >= prior_mean * float(thresholds["latest_vs_prior_mean_min_multiplier"])
    if not triggered:
        return RuleResult(rule_id="G-5", triggered=False)

    risk_delta = 0
    if _has_margin_downtrend(recent, thresholds):
        risk_delta = int(effects["risk_delta_if_downtrend"])

    return RuleResult(
        rule_id="G-5",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        risk_delta=risk_delta,
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"G-5 op_margin_latest={latest:.4f}, prior_mean={prior_mean:.4f}",
    )


def _rule(params: Params, rule_id: str) -> Params:
    return params["growth"]["rules"][rule_id]


def _missing(rule_id: str, effects: Params, data_warning: str) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        triggered=False,
        confidence_delta=int(effects["missing_data_confidence_delta"]),
        data_warning=data_warning,
    )


def _has_margin_downtrend(values: list[float], thresholds: Params) -> bool:
    required_decline = float(thresholds["downtrend_bps_over_4q"]) / 10000.0
    decline = values[0] - values[-1]
    return decline >= required_decline


GROWTH_RULES: list[GrowthRule] = [
    evaluate_g1,
    evaluate_g2,
    evaluate_g3,
    evaluate_g4,
    evaluate_g5,
]

HORIZONS.update(
    {
        "G-1": ("swing_term",),
        "G-2": ("swing_term", "long_term"),
        "G-3": ("long_term",),
        "G-4": ("long_term",),
        "G-5": ("long_term",),
    }
)
