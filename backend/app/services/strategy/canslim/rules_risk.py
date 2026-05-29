"""Pure CAN SLIM risk rule evaluators."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.rules_market import is_regime_risk_off
from backend.app.services.strategy.canslim.types import MarketFeatures, RuleResult

Params = Mapping[str, Any]
RiskRule = Callable[[CanslimFeatures, MarketFeatures, Params, str], RuleResult]


def evaluate_r1(features: CanslimFeatures, market: MarketFeatures, params: Params, horizon: str) -> RuleResult:
    rule = _rule(params, "R-1")
    threshold = float(rule["thresholds"]["close_to_ma20_multiplier_above"])
    if features.close is None or features.ma20 is None:
        return RuleResult(rule_id="R-1", triggered=False)
    if features.close <= features.ma20 * threshold:
        return RuleResult(rule_id="R-1", triggered=False)
    return RuleResult(
        rule_id="R-1",
        triggered=True,
        risk_delta=int(rule["effects"]["risk_delta"]),
        reason=f"R-1 close_to_ma20={features.close / features.ma20:.4f}",
    )


def evaluate_r2(features: CanslimFeatures, market: MarketFeatures, params: Params, horizon: str) -> RuleResult:
    rule = _rule(params, "R-2")
    if features.is_20d_high is None or features.volume_ratio_recent_vs_prior_20 is None:
        return RuleResult(rule_id="R-2", triggered=False)
    max_ratio = 1 - float(rule["thresholds"]["volume_decline_pct_min"])
    if not features.is_20d_high or features.volume_ratio_recent_vs_prior_20 > max_ratio:
        return RuleResult(rule_id="R-2", triggered=False)
    return RuleResult(
        rule_id="R-2",
        triggered=True,
        risk_delta=int(rule["effects"]["risk_delta"]),
        reason=f"R-2 volume_ratio_recent_vs_prior_20={features.volume_ratio_recent_vs_prior_20:.4f}",
    )


def evaluate_r3(features: CanslimFeatures, market: MarketFeatures, params: Params, horizon: str) -> RuleResult:
    rule = _rule(params, "R-3")
    thresholds = rule["thresholds"]
    if features.foreign_net_5 is None or features.trust_net_5 is None:
        return RuleResult(rule_id="R-3", triggered=False)
    lookback = int(thresholds["lookback_days"])
    required = int(thresholds["net_seller_days_min"])
    foreign_sellers = sum(1 for value in features.foreign_net_5[-lookback:] if value < 0)
    trust_sellers = sum(1 for value in features.trust_net_5[-lookback:] if value < 0)
    if foreign_sellers < required or trust_sellers < required:
        return RuleResult(rule_id="R-3", triggered=False)
    return RuleResult(
        rule_id="R-3",
        triggered=True,
        risk_delta=int(rule["effects"]["risk_delta"]),
        reason=f"R-3 foreign_seller_days={foreign_sellers}, trust_seller_days={trust_sellers}",
    )


def evaluate_r4(features: CanslimFeatures, market: MarketFeatures, params: Params, horizon: str) -> RuleResult:
    rule = _rule(params, "R-4")
    if features.event_window_active is None:
        return RuleResult(
            rule_id="R-4",
            triggered=False,
            data_warning="event calendar unknown - not blocking",
        )
    if not features.event_window_active:
        return RuleResult(rule_id="R-4", triggered=False)
    return RuleResult(
        rule_id="R-4",
        triggered=True,
        risk_delta=int(rule["effects"]["risk_delta"]),
        hard_block=True,
        reason="R-4 event_window_active=True",
    )


def evaluate_r5(features: CanslimFeatures, market: MarketFeatures, params: Params, horizon: str) -> RuleResult:
    rule = _rule(params, "R-5")
    risk_off = is_regime_risk_off(market, params)
    if risk_off is None:
        return RuleResult(
            rule_id="R-5",
            triggered=False,
            data_warning="market regime inputs missing - not blocking",
        )

    if not risk_off:
        return RuleResult(rule_id="R-5", triggered=False)
    if horizon == "short_term":
        return RuleResult(
            rule_id="R-5",
            triggered=True,
            hard_block=True,
            reason="R-5 market_risk_off short_term",
        )
    return RuleResult(
        rule_id="R-5",
        triggered=True,
        risk_delta=int(rule["effects"]["swing_long_risk_delta"]),
        reason=f"R-5 market_risk_off horizon={horizon}",
    )


def evaluate_r6(features: CanslimFeatures, market: MarketFeatures, params: Params, horizon: str) -> RuleResult:
    rule = _rule(params, "R-6")
    floor = float(rule["thresholds"]["avg_turnover_20_below_twd"])
    if features.avg_turnover_20 is None:
        return RuleResult(
            rule_id="R-6",
            triggered=True,
            hard_block=True,
            data_warning="avg_turnover_20 missing - liquidity unknown, blocking",
            reason=f"R-6 liquidity_floor={floor:.0f}",
        )
    if features.avg_turnover_20 >= floor:
        return RuleResult(rule_id="R-6", triggered=False)
    return RuleResult(
        rule_id="R-6",
        triggered=True,
        hard_block=True,
        reason=f"R-6 avg_turnover_20={features.avg_turnover_20:.0f}, liquidity_floor={floor:.0f}",
    )


def evaluate_r7(features: CanslimFeatures, market: MarketFeatures, params: Params, horizon: str) -> RuleResult:
    return RuleResult(
        rule_id="R-7",
        triggered=False,
        data_warning="day_trade_ratio unavailable - day-trade risk filter inactive",
    )


def evaluate_r8(features: CanslimFeatures, market: MarketFeatures, params: Params, horizon: str) -> RuleResult:
    rule = _rule(params, "R-8")
    thresholds = rule["thresholds"]
    if features.pe_ttm is None or features.quarterly_eps_yoy is None:
        return RuleResult(rule_id="R-8", triggered=False)
    if not (
        features.pe_ttm > float(thresholds["pe_ttm_above"])
        and features.quarterly_eps_yoy < float(thresholds["quarterly_eps_yoy_below"])
    ):
        return RuleResult(rule_id="R-8", triggered=False)
    return RuleResult(
        rule_id="R-8",
        triggered=True,
        risk_delta=int(rule["effects"]["risk_delta"]),
        reason=f"R-8 pe_ttm={features.pe_ttm:.4f}, quarterly_eps_yoy={features.quarterly_eps_yoy:.4f}",
    )


def _rule(params: Params, rule_id: str) -> Params:
    return params["risk"]["rules"][rule_id]


def _load_horizons() -> dict[str, tuple[str, ...]]:
    params = load_params()
    return {
        rule_id: tuple(rule["horizons"])
        for rule_id, rule in params["risk"]["rules"].items()
        if rule_id in {"R-1", "R-2", "R-3", "R-4", "R-5", "R-6", "R-7", "R-8"}
    }


RISK_RULES: list[RiskRule] = [
    evaluate_r1,
    evaluate_r2,
    evaluate_r3,
    evaluate_r4,
    evaluate_r5,
    evaluate_r6,
    evaluate_r7,
    evaluate_r8,
]

HORIZONS = _load_horizons()
