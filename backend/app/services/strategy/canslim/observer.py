"""Three-horizon CAN SLIM observation builder.

Status mapping is deterministic and intentionally graded:
- hard_blocked -> watching (card still surfaces with scores)
- any R-rule triggered -> invalidating
- grade S/A with breakout catalyst rules -> trigger_proximity
- grade S/A/B -> watching
- otherwise -> neutral

Direction is similarly score-based: strong signal with contained risk points up;
dominant risk points down; conflict cases resolve to sideways/unclear. No card
text uses action verbs.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.app.services.strategy.canslim.aggregator import AggregateResult, aggregate
from backend.app.services.strategy.canslim.base_detector import detect_base
from backend.app.services.strategy.canslim.features import CanslimFeatures, build_features
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.regime import build_market_features
from backend.app.services.strategy.canslim.rules_growth import GROWTH_RULES, HORIZONS as GROWTH_HORIZONS
from backend.app.services.strategy.canslim.rules_institutional import (
    HORIZONS as INSTITUTIONAL_HORIZONS,
    INSTITUTIONAL_RULES,
)
from backend.app.services.strategy.canslim.rules_market import HORIZONS as MARKET_HORIZONS, MARKET_RULES
from backend.app.services.strategy.canslim.rules_risk import HORIZONS as RISK_HORIZONS, RISK_RULES
from backend.app.services.strategy.canslim.rules_supply import HORIZONS as SUPPLY_HORIZONS, SUPPLY_RULES
from backend.app.services.strategy.canslim.rules_technical import HORIZONS as TECHNICAL_HORIZONS, TECHNICAL_RULES
from backend.app.services.strategy.canslim.types import HorizonObservation, MarketFeatures, RuleResult

HORIZONS = ["short_term", "swing_term", "long_term"]
BREAKOUT_RULE_IDS = {"T-2", "T-4", "T-5"}
FUNDAMENTAL_RULE_IDS = {"G-1", "G-2", "G-3", "G-4", "G-5"}
OVERHEAT_RULE_IDS = {"R-1", "R-2"}

INVALIDATION_SIGNALS = {
    "G-1": "G-1 revenue momentum fades below its threshold",
    "G-2": "G-2 quarterly EPS growth weakens",
    "G-3": "G-3 annual EPS compounding breaks",
    "G-4": "G-4 ROE quality fades",
    "G-5": "G-5 operating margin trend weakens",
    "T-1": "T-1 relative strength leaves leadership zone",
    "T-2": "T-2 loses 52-week-high proximity",
    "T-3": "T-3 moving-average structure breaks",
    "T-4": "T-4 returns inside the base",
    "T-5": "T-5 volume expansion fades",
    "SD-1": "SD-1 liquidity falls below floor",
    "SD-2": "SD-2 up-day volume support fades",
    "I-1": "I-1 foreign flow no longer confirms",
    "I-2": "I-2 trust flow no longer confirms",
    "I-3": "I-3 institution alignment fades",
    "M-1": "M-1 TAIEX regime weakens",
    "M-2": "M-2 TPEX confirmation weakens",
    "M-3": "M-3 breadth deteriorates",
    "M-4": "M-4 external market support fades",
    "R-1": "R-1 extension remains elevated",
    "R-2": "R-2 price-volume divergence remains active",
    "R-3": "R-3 institution selling pressure remains active",
    "R-4": "R-4 event window remains active",
    "R-5": "R-5 market risk-off remains active",
    "R-6": "R-6 liquidity hard block remains active",
    "R-7": "R-7 day-trade risk cannot be assessed",
    "R-8": "R-8 valuation-growth mismatch remains active",
}


def observe(
    symbol: str,
    as_of_date: str,
    *,
    store=None,
    market=None,
    fin_metrics=None,
    detail=None,
    universe_returns_60d=None,
    universe_returns_252d=None,
    event_window_active=None,
    eps_filing_date=None,
) -> dict[str, HorizonObservation]:
    params = load_params()
    features = build_features(
        symbol,
        as_of_date,
        store,
        universe_returns_60d=universe_returns_60d,
        universe_returns_252d=universe_returns_252d,
        fin_metrics=fin_metrics,
        detail=detail,
        eps_filing_date=eps_filing_date,
        event_window_active=event_window_active,
    )
    market_features = _market_features(as_of_date, market=market, store=store)
    bars = store.get_ohlcv_as_of(symbol, as_of_date, 180) if store is not None else None
    base = detect_base(bars, params) if bars is not None else detect_base(_empty_bars(), params)

    observations: dict[str, HorizonObservation] = {}
    for horizon in HORIZONS:
        rule_results = _evaluate_rules(features, market_features, params, horizon)
        aggregate_result = aggregate(rule_results, base, horizon, params)
        observations[horizon] = _to_observation(aggregate_result, rule_results, features, market_features)
    return observations


def _market_features(as_of_date: str, *, market, store) -> MarketFeatures:
    if isinstance(market, MarketFeatures):
        return market
    if isinstance(market, Mapping):
        return build_market_features(as_of_date, index_bundle=market, store=store)
    return build_market_features(as_of_date, store=store)


def _evaluate_rules(
    features: CanslimFeatures,
    market: MarketFeatures,
    params: Mapping[str, Any],
    horizon: str,
) -> list[RuleResult]:
    results: list[RuleResult] = []
    for rule, horizons in _stock_rule_specs():
        if horizon in horizons:
            results.append(rule(features, params))
    for rule, horizons in _market_rule_specs():
        if horizon in horizons:
            results.append(rule(market, params))
    for rule, horizons in _risk_rule_specs():
        if horizon in horizons:
            results.append(rule(features, market, params, horizon))
    return results


def _stock_rule_specs() -> list[tuple[Callable, tuple[str, ...]]]:
    return [
        *[(rule, GROWTH_HORIZONS[rule_id]) for rule_id, rule in zip(["G-1", "G-2", "G-3", "G-4", "G-5"], GROWTH_RULES)],
        *[(rule, TECHNICAL_HORIZONS[rule_id]) for rule_id, rule in zip(["T-1", "T-2", "T-3", "T-4", "T-5"], TECHNICAL_RULES)],
        *[(rule, SUPPLY_HORIZONS[rule_id]) for rule_id, rule in zip(["SD-1", "SD-2", "SD-3", "SD-4"], SUPPLY_RULES)],
        *[
            (rule, INSTITUTIONAL_HORIZONS[rule_id])
            for rule_id, rule in zip(["I-1", "I-2", "I-3", "I-4"], INSTITUTIONAL_RULES)
        ],
    ]


def _market_rule_specs() -> list[tuple[Callable, tuple[str, ...]]]:
    return [(rule, MARKET_HORIZONS[rule_id]) for rule_id, rule in zip(["M-1", "M-2", "M-3", "M-4"], MARKET_RULES)]


def _risk_rule_specs() -> list[tuple[Callable, tuple[str, ...]]]:
    return [(rule, RISK_HORIZONS[rule_id]) for rule_id, rule in zip([f"R-{idx}" for idx in range(1, 9)], RISK_RULES)]


def _to_observation(
    aggregate_result: AggregateResult,
    rule_results: list[RuleResult],
    features: CanslimFeatures,
    market: MarketFeatures,
) -> HorizonObservation:
    triggered = set(aggregate_result.triggered_rule_ids)
    status = _status(aggregate_result, triggered, rule_results, features)
    direction = _direction_hint(aggregate_result, triggered, features)
    risk_level = _risk_level(aggregate_result.risk_score)
    confidence_level = _confidence_level(aggregate_result.confidence_score, aggregate_result.low_confidence)
    evidence = [_safe_card_text(result.reason) for result in rule_results if result.triggered and result.reason]

    return HorizonObservation(
        horizon=aggregate_result.horizon,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        direction_hint=direction,  # type: ignore[arg-type]
        evidence_based_reasons=evidence,
        triggered_rule_ids=aggregate_result.triggered_rule_ids,
        suitable_strategy_examples=[f"{aggregate_result.grade}-grade observation"],
        key_observation_conditions=_key_conditions(aggregate_result),
        invalidation_signals=[_safe_card_text(value) for value in _invalidation_signals(rule_results)],
        risk_level=risk_level,  # type: ignore[arg-type]
        confidence_level=confidence_level,  # type: ignore[arg-type]
        scores={
            "signal": aggregate_result.signal_score,
            "signal_raw": aggregate_result.signal_raw,
            "signal_achievable_max": aggregate_result.signal_achievable_max,
            "risk": aggregate_result.risk_score,
            "confidence": aggregate_result.confidence_score,
            "grade": aggregate_result.grade,
            "hard_blocked": aggregate_result.hard_blocked,
            "blocking_rule_ids": aggregate_result.blocking_rule_ids,
        },
        data_warnings=[_safe_card_text(value) for value in [*features.data_warnings, *market.data_warnings, *aggregate_result.data_warnings]],
    )


def _status(
    aggregate_result: AggregateResult,
    triggered: set[str],
    rule_results: list[RuleResult],
    features: CanslimFeatures,
) -> str:
    if aggregate_result.hard_blocked:
        return "watching"
    if any(rule_id.startswith("R-") for rule_id in triggered):
        return "invalidating"
    if _foreign_trust_divergence(triggered, features):
        return "watching"
    if triggered & BREAKOUT_RULE_IDS and not (triggered & FUNDAMENTAL_RULE_IDS):
        return "watching"
    if aggregate_result.grade in {"S", "A"} and triggered & BREAKOUT_RULE_IDS:
        return "trigger_proximity"
    if aggregate_result.grade in {"S", "A", "B"}:
        return "watching"
    return "neutral"


def _direction_hint(aggregate_result: AggregateResult, triggered: set[str], features: CanslimFeatures) -> str:
    if aggregate_result.hard_blocked and "R-5" in triggered:
        return "down"
    if _foreign_trust_divergence(triggered, features):
        return "unclear"
    if triggered & OVERHEAT_RULE_IDS and ((triggered & FUNDAMENTAL_RULE_IDS) or _strong_fundamentals(features)):
        return "sideways"
    if triggered & BREAKOUT_RULE_IDS and not (triggered & FUNDAMENTAL_RULE_IDS):
        return "unclear"
    if aggregate_result.risk_score >= 60 or any(rule_id in triggered for rule_id in {"R-3", "R-5", "R-8"}):
        return "down"
    if aggregate_result.signal_score >= 35 and aggregate_result.risk_score < aggregate_result.signal_score:
        return "up"
    if aggregate_result.signal_score > 0:
        return "sideways"
    return "unclear"


def _risk_level(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 45:
        return "elevated"
    if score >= 20:
        return "moderate"
    return "low"


def _confidence_level(score: int, low_confidence: bool) -> str:
    if low_confidence:
        return "low"
    if score >= 70:
        return "high"
    return "moderate"


def _key_conditions(aggregate_result: AggregateResult) -> list[str]:
    return [
        f"grade={aggregate_result.grade}",
        f"signal_score={aggregate_result.signal_score}",
        f"risk_score={aggregate_result.risk_score}",
        f"confidence_score={aggregate_result.confidence_score}",
        f"hard_blocked={aggregate_result.hard_blocked}",
    ]


def _invalidation_signals(rule_results: list[RuleResult]) -> list[str]:
    rule_ids = [result.rule_id for result in rule_results]
    return [INVALIDATION_SIGNALS[rule_id] for rule_id in rule_ids if rule_id in INVALIDATION_SIGNALS]


def _foreign_trust_divergence(triggered: set[str], features: CanslimFeatures) -> bool:
    if "I-1" not in triggered or features.trust_net_5 is None:
        return False
    recent = features.trust_net_5[-3:]
    return bool(recent and sum(1 for value in recent if value < 0) >= 2)


def _strong_fundamentals(features: CanslimFeatures) -> bool:
    checks = [
        features.quarterly_eps_yoy is not None and features.quarterly_eps_yoy >= 0.25,
        features.roe_ttm is not None and features.roe_ttm >= 0.15,
        features.eps_cagr_3y is not None and features.eps_cagr_3y >= 0.25,
    ]
    return sum(1 for item in checks if item) >= 2


def _empty_bars():
    import pandas as pd

    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _safe_card_text(value: str) -> str:
    replacements = {
        "buy": "positive-flow",
        "sell": "negative-flow",
        "hold": "carry",
        "買": "進場意向",
        "賣": "退出意向",
        "持有": "續留意向",
        "threshold": "line",
        "seller": "negative-flow",
        "selling": "negative-flow",
    }
    text = value
    for old, new in replacements.items():
        text = text.replace(old, new).replace(old.upper(), new).replace(old.capitalize(), new)
    return text
