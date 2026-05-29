"""Deterministic CANSLIM Reviewer / Judge.

Audits the QUALITY of a `CanslimFullResult`; it does not re-analyze the stock.
Deterministic on purpose: a rule-based judge stays backtestable, free, and cannot
itself hallucinate. Rubric weights / thresholds come from the YAML `reviewer:`
block (tunable).

Hard rejections (per spec):
- any direct buy/sell/guaranteed-profit language anywhere in the output
- mock/fallback data carrying HIGH confidence
- a core C/A/L/I/M factor insufficient while overall confidence is HIGH
- no invalidation_signals
"""
from __future__ import annotations

from typing import Any, Mapping

from backend.app.models.screener_schemas import CanslimFullResult, CanslimReviewResult
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.screening_language import (
    contains_forbidden_action_language,
)

CORE_FACTORS = ("C", "A", "L", "I", "M")


def review(full: CanslimFullResult, *, params: Mapping[str, Any] | None = None) -> CanslimReviewResult:
    params = params or load_params()
    rcfg = params["reviewer"]
    weights = rcfg["dimensions"]

    by_factor = {f.factor: f for f in full.per_factor_scores}
    critical: list[str] = []
    warnings: list[str] = []
    missing_evidence: list[str] = []
    overconfidence: list[str] = []
    fixes: list[str] = []
    dim_scores: list[dict[str, Any]] = []

    def add_dim(name: str, ok: bool, reason: str, issues: list[str]):
        w = int(weights.get(name, 0))
        dim_scores.append({"dimension_name": name, "score": w if ok else 0, "weight": w,
                           "reason": reason, "evidence": [], "issues": issues})

    # 1. Factor completeness — all 7 present + each has a reason.
    present = len(full.per_factor_scores) == 7
    all_reasoned = all(f.reason for f in full.per_factor_scores)
    ok1 = present and all_reasoned
    iss1 = []
    if not present: iss1.append("not all 7 CANSLIM factors present")
    if not all_reasoned: iss1.append("a factor lacks a reason"); fixes.append("add reason for every factor")
    if not all_reasoned: warnings.append("factor missing reason")
    add_dim("factor_completeness", ok1, "all 7 factors with reason" if ok1 else "incomplete", iss1)

    # 2. Evidence & traceability — non-null factors carry data_used; high scores have evidence.
    untraced = [f.factor for f in full.per_factor_scores if f.score is not None and not f.data_used]
    high_no_ev = [f.factor for f in full.per_factor_scores if (f.score or 0) >= 80 and not f.data_used]
    ok2 = not high_no_ev
    if untraced: missing_evidence.extend(f"{x}: no data_used" for x in untraced)
    if high_no_ev: warnings.append("high factor score without data_used")
    add_dim("evidence_traceability", ok2, "scored factors traceable" if ok2 else "high score lacks evidence",
            [f"{x} high score no evidence" for x in high_no_ev])

    # 3. Confidence & missing-data control — the hard-rejection gates.
    core_missing = [f for f in CORE_FACTORS if by_factor.get(f) and by_factor[f].score is None]
    mock_high = full.is_mock_or_fallback_data and full.confidence == "HIGH"
    core_missing_high = bool(core_missing) and full.confidence == "HIGH"
    ok3 = not mock_high and not core_missing_high
    if mock_high:
        critical.append("mock/fallback data presented with HIGH confidence")
        overconfidence.append("mock + HIGH confidence")
        fixes.append("cap confidence to MEDIUM/LOW when data is mock/fallback")
    if core_missing_high:
        critical.append(f"core factors {core_missing} insufficient but confidence is HIGH")
        overconfidence.append(f"core missing {core_missing} + HIGH")
        fixes.append("never allow HIGH confidence with a missing core C/A/L/I/M factor")
    add_dim("confidence_missing_data_control", ok3, "confidence consistent with data" if ok3 else "overconfident", [])

    # 4. Risk & invalidation quality.
    has_inval = len(full.invalidation_signals) > 0
    has_obs = len(full.observation_conditions) > 0
    has_levels = bool(full.risk_level) and bool(full.confidence)
    ok4 = has_inval and has_obs and has_levels
    if not has_inval:
        critical.append("no invalidation_signals")
        fixes.append("add invalidation_signals")
    if not has_obs: warnings.append("no observation_conditions"); fixes.append("add observation_conditions")
    add_dim("risk_invalidation_quality", ok4, "risk/invalidation/observation present" if ok4 else "missing", [])

    # 5. Market-direction handling — weak/unconfirmed regime must be conservative.
    regime = full.screening_result.market_regime
    weak_regime = regime in {"unknown", "severe", "risk_off"}
    conservative = ("觀察" in full.suggested_strategy) or ("不宜追高" in full.suggested_strategy) or full.pass_status in {"WATCHLIST", "FAIL", "INSUFFICIENT_DATA"}
    ok5 = (not weak_regime) or conservative
    if not ok5:
        warnings.append("weak market direction but strategy not conservative")
        fixes.append("force conservative strategy when M is weak/unknown")
    add_dim("market_direction_handling", ok5, "M handled" if ok5 else "M ignored", [])

    # 6. Conditional-recommendation compliance — no action verbs anywhere.
    surfaces = [full.suggested_strategy, *full.positive_reasons, *full.negative_reasons,
                *full.observation_conditions, *full.invalidation_signals,
                *[f.reason for f in full.per_factor_scores]]
    has_verbs = contains_forbidden_action_language(surfaces)
    ok6 = not has_verbs
    if has_verbs:
        critical.append("direct buy/sell/guaranteed-profit language present")
        fixes.append("remove action/guarantee language; use conditional observation wording")
    add_dim("conditional_recommendation_compliance", ok6, "verb-free conditional" if ok6 else "action language", [])

    # 7. Backtestability — deterministic numeric fields + as_of_date present.
    ok7 = bool(full.as_of_date) and isinstance(full.overall_score, int) and any(f.score is not None for f in full.per_factor_scores)
    add_dim("backtestability", ok7, "deterministic + dated" if ok7 else "not reproducible", [])

    review_score = sum(d["score"] for d in dim_scores)
    if critical:
        status = "REJECTED"
    elif review_score < int(rcfg["approve_min_score"]) or warnings:
        status = "NEEDS_REVISION"
    else:
        status = "APPROVED"

    comment = {
        "APPROVED": "CANSLIM output meets evidence, confidence, and compliance checks.",
        "NEEDS_REVISION": "CANSLIM output usable but has quality gaps to fix.",
        "REJECTED": "CANSLIM output violates a hard safety/compliance rule.",
    }[status]

    return CanslimReviewResult(
        review_score=review_score,
        review_status=status,
        dimension_scores=dim_scores,
        critical_issues=critical,
        warnings=warnings,
        missing_evidence=missing_evidence,
        overconfidence_flags=overconfidence,
        required_fixes=fixes,
        final_comment=comment,
    )
