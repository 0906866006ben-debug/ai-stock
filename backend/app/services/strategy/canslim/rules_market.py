"""Pure CAN SLIM market/regime rule evaluators."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.types import MarketFeatures, RuleResult

Params = Mapping[str, Any]
MarketRule = Callable[[MarketFeatures, Params], RuleResult]


def evaluate_m1(features: MarketFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "M-1")
    thresholds = rule["thresholds"]
    effects = rule["effects"]

    if _missing_any(features.taiex_close, features.taiex_ma150, features.taiex_ma150_slope):
        return RuleResult(rule_id="M-1", triggered=False, data_warning="TAIEX regime inputs missing")

    uptrend = features.taiex_close > features.taiex_ma150 and features.taiex_ma150_slope >= float(thresholds["slope_min"])
    if uptrend:
        return RuleResult(
            rule_id="M-1",
            triggered=True,
            reason=f"M-1 taiex_close={features.taiex_close:.4f}, ma150_slope={features.taiex_ma150_slope:.4f}",
        )
    return RuleResult(
        rule_id="M-1",
        triggered=False,
        risk_delta=int(effects["risk_delta_on_fail"]),
        reason=f"M-1 regime_on_fail={effects['regime_on_fail']}",
    )


def evaluate_m2(features: MarketFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "M-2")
    thresholds = rule["thresholds"]
    effects = rule["effects"]

    if _missing_any(features.tpex_close, features.tpex_ma150, features.tpex_ma150_slope):
        return RuleResult(rule_id="M-2", triggered=False, data_warning="TPEX regime inputs missing")

    taiex = evaluate_m1(features, params)
    if taiex.data_warning:
        return RuleResult(rule_id="M-2", triggered=False, data_warning="TAIEX regime inputs missing")

    tpex_uptrend = features.tpex_close > features.tpex_ma150 and features.tpex_ma150_slope >= float(thresholds["slope_min"])
    if tpex_uptrend and taiex.triggered:
        return RuleResult(
            rule_id="M-2",
            triggered=True,
            reason=f"M-2 tpex_close={features.tpex_close:.4f}, ma150_slope={features.tpex_ma150_slope:.4f}",
        )
    if tpex_uptrend != taiex.triggered:
        return RuleResult(
            rule_id="M-2",
            triggered=False,
            risk_delta=int(effects["risk_delta_if_disagrees_with_taiex"]),
            reason="M-2 tpex_taiex_disagreement",
        )
    return RuleResult(rule_id="M-2", triggered=False)


def evaluate_m3(features: MarketFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "M-3")
    thresholds = rule["thresholds"]
    effects = rule["effects"]
    value = features.breadth_above_ma60_pct

    if value is None:
        return RuleResult(rule_id="M-3", triggered=False, data_warning="breadth_above_ma60_pct missing")
    if value >= float(thresholds["universe_above_ma60_pct_min"]):
        return RuleResult(
            rule_id="M-3",
            triggered=True,
            confidence_delta=int(effects["confidence_delta_if_met"]),
            reason=f"M-3 breadth_above_ma60_pct={value:.4f}",
        )
    if value < float(thresholds["risk_pct_below"]):
        return RuleResult(
            rule_id="M-3",
            triggered=False,
            risk_delta=int(effects["risk_delta_if_below"]),
            reason=f"M-3 breadth_above_ma60_pct={value:.4f}",
        )
    return RuleResult(rule_id="M-3", triggered=False)


def evaluate_m4(features: MarketFeatures, params: Params) -> RuleResult:
    rule = _rule(params, "M-4")
    effects = rule["effects"]
    sox = features.sox_above_ma60
    nasdaq = features.nasdaq_above_ma60

    if sox is None or nasdaq is None:
        return RuleResult(rule_id="M-4", triggered=False, data_warning="SOX/Nasdaq external regime inputs missing")
    if sox and nasdaq:
        return RuleResult(
            rule_id="M-4",
            triggered=True,
            signal_delta=int(effects["signal_delta"]),
            confidence_delta=int(effects["confidence_delta"]),
            reason="M-4 sox_nasdaq_supportive",
        )
    if not sox and not nasdaq:
        return RuleResult(
            rule_id="M-4",
            triggered=False,
            risk_delta=int(effects["risk_delta_if_both_below"]),
            reason="M-4 sox_nasdaq_both_below_ma60",
        )
    return RuleResult(rule_id="M-4", triggered=False)


def is_regime_risk_off(features: MarketFeatures, params: Params) -> bool | None:
    """Return R-5 market risk-off state, or None when regime inputs are unknown."""
    severity = regime_severity(features, params)
    if severity is None:
        return None
    return severity in {"risk_off", "severe"}


def regime_severity(features: MarketFeatures, params: Params) -> str | None:
    """Return risk_on/risk_off/severe, or None when regime inputs are unknown."""
    m1 = evaluate_m1(features, params)
    m2 = evaluate_m2(features, params)
    m3 = evaluate_m3(features, params)
    if m1.data_warning or m2.data_warning or m3.data_warning:
        return None
    if (not m1.triggered) and features.breadth_above_ma60_pct is not None and features.breadth_above_ma60_pct < 0.40:
        return "severe"
    if (not m1.triggered) or ((not m2.triggered) and (not m3.triggered)):
        return "risk_off"
    return "risk_on"


def _rule(params: Params, rule_id: str) -> Params:
    return params["market"]["rules"][rule_id]


def _missing_any(*values: object | None) -> bool:
    return any(value is None for value in values)


def _load_horizons() -> dict[str, tuple[str, ...]]:
    params = load_params()
    return {
        rule_id: tuple(rule["horizons"])
        for rule_id, rule in params["market"]["rules"].items()
        if rule_id in {"M-1", "M-2", "M-3", "M-4"}
    }


MARKET_RULES: list[MarketRule] = [
    evaluate_m1,
    evaluate_m2,
    evaluate_m3,
    evaluate_m4,
]

HORIZONS = _load_horizons()
