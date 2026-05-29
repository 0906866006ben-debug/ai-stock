"""Pure CAN SLIM supply/demand rule evaluators."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.types import RuleResult

Params = Mapping[str, Any]
SupplyRule = Callable[[CanslimFeatures, Params], RuleResult]


def evaluate_sd1(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "SD-1")
    thresholds = rule["thresholds"]
    value = features.avg_turnover_20
    floor = float(thresholds["avg_turnover_20_min_twd"])

    if value is None:
        return RuleResult(
            rule_id="SD-1",
            triggered=False,
            hard_block=True,
            data_warning="avg_turnover_20 missing; liquidity floor cannot be verified",
            reason=f"SD-1 liquidity_floor={floor:.0f}",
        )
    if value < floor:
        return RuleResult(
            rule_id="SD-1",
            triggered=False,
            hard_block=True,
            reason=f"SD-1 avg_turnover_20={value:.0f}, liquidity_floor={floor:.0f}",
        )
    return RuleResult(
        rule_id="SD-1",
        triggered=True,
        reason=f"SD-1 avg_turnover_20={value:.0f}, liquidity_floor={floor:.0f}",
    )


def evaluate_sd2(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "SD-2")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    value = features.up_down_volume_ratio_10

    if value is None:
        return RuleResult(rule_id="SD-2", triggered=False)
    if value < float(thresholds["up_to_down_volume_ratio_min"]):
        return RuleResult(rule_id="SD-2", triggered=False)
    return RuleResult(
        rule_id="SD-2",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"SD-2 up_down_volume_ratio_10={value:.4f}",
    )


def evaluate_sd3(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "SD-3")
    effects = rule["effects"]
    return RuleResult(
        rule_id="SD-3",
        triggered=False,
        confidence_delta=int(effects["confidence_delta_missing"]),
        data_warning="day_trade_ratio unavailable - cannot assess day-trade risk; do not assume low",
    )


def evaluate_sd4(features: CanslimFeatures, params: Params) -> RuleResult:
    return RuleResult(
        rule_id="SD-4",
        triggered=False,
        data_warning="chip_concentration unavailable",
    )


def _rule(params: Params, rule_id: str) -> Params:
    return params["supply"]["rules"][rule_id]


def _load_horizons() -> dict[str, tuple[str, ...]]:
    params = load_params()
    return {
        rule_id: tuple(rule["horizons"])
        for rule_id, rule in params["supply"]["rules"].items()
        if rule_id in {"SD-1", "SD-2", "SD-3", "SD-4"}
    }


SUPPLY_RULES: list[SupplyRule] = [
    evaluate_sd1,
    evaluate_sd2,
    evaluate_sd3,
    evaluate_sd4,
]

HORIZONS = _load_horizons()
