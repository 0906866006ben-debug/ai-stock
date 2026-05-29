"""Pure CAN SLIM institutional rule evaluators."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.types import RuleResult

Params = Mapping[str, Any]
InstitutionalRule = Callable[[CanslimFeatures, Params], RuleResult]


def evaluate_i1(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "I-1")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    values = features.foreign_net_5
    days = int(thresholds["consecutive_days_min"])

    if values is None or len(values) < days:
        return RuleResult(
            rule_id="I-1",
            triggered=False,
            confidence_delta=int(effects["missing_data_confidence_delta"]),
            data_warning="foreign_net_5 missing or insufficient",
        )

    recent = values[-days:]
    if not all(value > 0 for value in recent):
        return RuleResult(rule_id="I-1", triggered=False)

    data_warning = None
    cumulative = sum(recent)
    if features.avg_volume_20 is not None:
        minimum = features.avg_volume_20 * float(thresholds["cumulative_avg_volume_20_min_ratio"])
        if cumulative < minimum:
            return RuleResult(rule_id="I-1", triggered=False)
    else:
        data_warning = "cumulative-vs-volume check skipped; avg_volume_20 missing"

    return RuleResult(
        rule_id="I-1",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"I-1 foreign_net_last_{days}_sum={cumulative:.4f}",
        data_warning=data_warning,
    )


def evaluate_i2(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "I-2")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    values = features.trust_net_5
    lookback = int(thresholds["lookback_days"])

    if values is None:
        return RuleResult(rule_id="I-2", triggered=False)

    recent = values[-lookback:]
    positive_days = sum(1 for value in recent if value > 0)
    if positive_days < int(thresholds["net_buy_days_min"]):
        return RuleResult(rule_id="I-2", triggered=False)
    return RuleResult(
        rule_id="I-2",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason=f"I-2 trust_positive_days={positive_days}",
    )


def evaluate_i3(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "I-3")
    effects = rule["effects"]
    foreign = evaluate_i1(features, params)
    trust = evaluate_i2(features, params)

    if not (foreign.triggered and trust.triggered):
        return RuleResult(rule_id="I-3", triggered=False)
    return RuleResult(
        rule_id="I-3",
        triggered=True,
        signal_delta=int(effects["signal_delta"]),
        confidence_delta=int(effects["confidence_delta"]),
        reason="I-3 foreign_and_trust_aligned",
    )


def evaluate_i4(features: CanslimFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "I-4")
    thresholds = rule["thresholds"]
    return RuleResult(
        rule_id="I-4",
        triggered=False,
        data_warning=(
            "dealer/proprietary flow treated as untrusted - no hedge breakdown available; "
            f"assumed_hedging_ratio {float(thresholds['assumed_hedging_ratio']):.2f}"
        ),
    )


def _rule(params: Params, rule_id: str) -> Params:
    return params["institutional"]["rules"][rule_id]


def _load_horizons() -> dict[str, tuple[str, ...]]:
    params = load_params()
    return {
        rule_id: tuple(rule["horizons"])
        for rule_id, rule in params["institutional"]["rules"].items()
        if rule_id in {"I-1", "I-2", "I-3", "I-4"}
    }


INSTITUTIONAL_RULES: list[InstitutionalRule] = [
    evaluate_i1,
    evaluate_i2,
    evaluate_i3,
    evaluate_i4,
]

HORIZONS = _load_horizons()
