"""CAN SLIM three-score aggregator.

This module intentionally composes rule outputs as graded scores. It never
requires all rules or pillars to trigger, and hard blocks are reported as a
separate flag without zeroing signal, risk, confidence, or grade.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.services.strategy.canslim.base_detector import BasePattern
from backend.app.services.strategy.canslim.types import RuleResult


class AggregateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon: str
    signal_score: int
    signal_raw: int
    signal_achievable_max: int
    risk_score: int
    confidence_score: int
    grade: Literal["S", "A", "B", "C"]
    hard_blocked: bool
    blocking_rule_ids: list[str] = Field(default_factory=list)
    low_confidence: bool
    triggered_rule_ids: list[str] = Field(default_factory=list)
    pillar_breakdown: dict[str, int] = Field(default_factory=dict)
    data_warnings: list[str] = Field(default_factory=list)


Params = Mapping[str, Any]

SIGNAL_PILLARS = {
    "growth_quality": {"G-1", "G-2", "G-3", "G-4", "G-5"},
    "technical_leadership": {"T-1", "T-3"},
    "breakout_catalyst": {"T-2", "T-4", "T-5"},
    "supply_demand": {"SD-1", "SD-2"},
    "institutional": {"I-1", "I-2", "I-3"},
}

RISK_COMPONENTS = {
    "market_regime_max": {"M-1", "R-5"},
    "institutional_reversal_max": {"R-3"},
    "technical_overheat_max": {"R-1", "R-2"},
    "event_window_max": {"R-4"},
    "daytrade_divergence_max": {"SD-3", "R-7"},
    "valuation_mismatch_max": {"R-8"},
}


def aggregate(rule_results: list[RuleResult], base: BasePattern, horizon: str, params: Params) -> AggregateResult:
    scoring = params["scoring"]
    hard_blocked = any(result.hard_block for result in rule_results)
    blocking_rule_ids = [result.rule_id for result in rule_results if result.hard_block]
    triggered_rule_ids = [result.rule_id for result in rule_results if result.triggered]
    data_warnings = [result.data_warning for result in rule_results if result.data_warning]
    data_warnings.extend(base.data_warnings)

    pillar_breakdown = _signal_breakdown(rule_results, base, scoring)
    signal_raw = _clamp_int(sum(pillar_breakdown.values()), scoring["signal"]["range_min"], scoring["signal"]["range_max"])
    signal_achievable_max = _achievable_signal_max(horizon, params)
    signal_score = _clamp_int(
        round(signal_raw / signal_achievable_max * 100),
        scoring["signal"]["range_min"],
        scoring["signal"]["range_max"],
    )
    risk_score = _risk_score(rule_results, scoring)
    confidence_score = _confidence_score(rule_results, scoring, hard_blocked)

    return AggregateResult(
        horizon=horizon,
        signal_score=signal_score,
        signal_raw=signal_raw,
        signal_achievable_max=signal_achievable_max,
        risk_score=risk_score,
        confidence_score=confidence_score,
        grade=_grade(signal_score, scoring),
        hard_blocked=hard_blocked,
        blocking_rule_ids=blocking_rule_ids,
        low_confidence=confidence_score < int(scoring["confidence"]["low_confidence_below"]),
        triggered_rule_ids=triggered_rule_ids,
        pillar_breakdown=pillar_breakdown,
        data_warnings=data_warnings,
    )


def _signal_breakdown(rule_results: list[RuleResult], base: BasePattern, scoring: Params) -> dict[str, int]:
    caps = scoring["signal"]["pillar_caps"]
    breakdown: dict[str, int] = {}
    for pillar, rule_ids in SIGNAL_PILLARS.items():
        raw = sum(result.signal_delta for result in rule_results if result.rule_id in rule_ids)
        cap = int(caps[pillar])
        breakdown[pillar] = min(max(int(raw), 0), cap)

    breakout_cap = int(caps["breakout_catalyst"])
    remaining_breakout_cap = max(0, breakout_cap - breakdown["breakout_catalyst"])
    base_contribution = round(base.quality_score / 100 * remaining_breakout_cap)
    breakdown["breakout_catalyst"] = min(breakout_cap, breakdown["breakout_catalyst"] + base_contribution)
    return breakdown


def _achievable_signal_max(horizon: str, params: Params) -> int:
    caps = params["scoring"]["signal"]["pillar_caps"]
    total = 0
    for pillar, rule_ids in SIGNAL_PILLARS.items():
        cap = int(caps[pillar])
        if pillar == "breakout_catalyst":
            total += cap
            continue

        raw = 0
        for rule_id in rule_ids:
            rule_params = _rule_params(rule_id, params)
            if rule_params and horizon in tuple(rule_params.get("horizons", ())):
                raw += int(rule_params.get("effects", {}).get("signal_delta", 0))
        total += min(max(raw, 0), cap)
    return max(int(total), 1)


def _rule_params(rule_id: str, params: Params) -> Params | None:
    if rule_id.startswith("G-"):
        return params["growth"]["rules"].get(rule_id)
    if rule_id.startswith("T-"):
        return params["technical"]["rules"].get(rule_id)
    if rule_id.startswith("SD-"):
        return params["supply"]["rules"].get(rule_id)
    if rule_id.startswith("I-"):
        return params["institutional"]["rules"].get(rule_id)
    return None


def _risk_score(rule_results: list[RuleResult], scoring: Params) -> int:
    caps = scoring["risk"]["components"]
    total = 0
    for component, rule_ids in RISK_COMPONENTS.items():
        raw = sum(result.risk_delta for result in rule_results if result.rule_id in rule_ids)
        total += min(max(int(raw), 0), int(caps[component]))
    return _clamp_int(total, scoring["risk"]["range_min"], scoring["risk"]["range_max"])


def _confidence_score(rule_results: list[RuleResult], scoring: Params, hard_blocked: bool) -> int:
    config = scoring["confidence"]
    score = int(config["baseline"]) + sum(result.confidence_delta for result in rule_results)
    if hard_blocked:
        score += int(config["hard_block_penalty"])
    return _clamp_int(score, config["range_min"], config["range_max"])


def _grade(signal_score: int, scoring: Params) -> Literal["S", "A", "B", "C"]:
    grades = scoring["grades"]
    if signal_score >= int(grades["S_signal_min"]):
        return "S"
    if signal_score >= int(grades["A_signal_min"]):
        return "A"
    if signal_score >= int(grades["B_signal_min"]):
        return "B"
    return "C"


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(int(minimum), min(int(maximum), int(value)))
