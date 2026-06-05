"""Consolidated CANSLIM output adapter.

Maps the validated `ScreeningResult` into the decision-support `CanslimFullResult`
(the 15 required fields). This is a PRESENTATION layer only — it does not change
any signal/score/grade math.

Design decision (2026-05-26 diagnostic, Docs/planning/canslim_diagnostic_2026-05-26.md):
the grade letter is NOT an OOS-stable ranking, so it must never on its own grant
HIGH confidence. The stable edge is EXTENSION (proximity to the 52-week high, which
the N pillar already encodes) plus a confirmed market REGIME. Confidence is driven
by those + data quality; grade is reported as a match-degree label.

All thresholds come from the YAML `presentation:` block (tunable), never hardcoded.
"""
from __future__ import annotations

from typing import Any, Mapping

from backend.app.models.screener_schemas import (
    CanslimFactorScore,
    CanslimFullResult,
    ScreeningResult,
)
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.screening_language import (
    clean_string_list,
    clean_user_facing_text,
)

FACTORS = ("C", "A", "N", "S", "L", "I", "M")
_NULL_STATUSES = {"AI_Review_Required", "Insufficient_Data"}


def build_full_result(result: ScreeningResult, *, params: Mapping[str, Any] | None = None) -> CanslimFullResult:
    """Derive the consolidated CANSLIM output from a validated ScreeningResult."""
    params = params or load_params()
    cfg = params["presentation"]
    bands = cfg["factor_score_bands"]
    weights = cfg["factor_weights"]
    core_factors = list(cfg["core_factors"])

    per_factor = _build_factor_scores(result, bands)
    by_factor = {f.factor: f for f in per_factor}

    non_null = [f for f in per_factor if f.score is not None]
    coverage = len(non_null) / len(FACTORS)
    core_missing = [f for f in core_factors if by_factor[f].score is None]

    overall_score = _overall_score(non_null, weights)
    confidence = _confidence(result, by_factor, core_missing, coverage, cfg)
    risk_level = _risk_level(result, cfg)
    pass_status = _pass_status(result, by_factor, core_missing, confidence, cfg)
    data_quality = _data_quality(result, coverage, cfg)

    positive = [f"{f.factor}: {f.reason}" for f in per_factor if f.status == "Pass"]
    negative = [f"{f.factor}: {f.reason}" for f in per_factor if f.status == "Fail"]
    missing = [f"{f.factor} 資料不足/需審查" for f in per_factor if f.score is None]
    missing += list(result.needs_manual_review)

    # Data-driven swing exit/invalidation conditions (from live features) lead; the
    # static YAML templates remain as generic fallbacks. structure_status stays
    # accessible via the embedded screening_result.
    invalidation = clean_string_list([*result.exit_signals, *cfg.get("invalidation_templates", [])])
    observation = clean_string_list(cfg.get("observation_templates", []))
    suggested = _suggested_strategy(result, pass_status, by_factor, cfg)

    # Display grade uses raw_grade (signal quality, regime-independent) so users can identify
    # strong setups even during risk_off markets to add to watchlists.  candidate_grade
    # (regime-adjusted) is kept for pass_status gating only.
    # S folds into A per 2026-05-30 redesign (S band is noise-level at 15yr scale).
    raw = result.raw_grade or result.candidate_grade
    display_grade = "A" if raw == "S" else raw

    return CanslimFullResult(
        stock_id=result.stock_id,
        as_of_date=result.as_of_date,
        overall_score=overall_score,
        grade=display_grade,
        pass_status=pass_status,
        confidence=confidence,
        risk_level=risk_level,
        per_factor_scores=per_factor,
        positive_reasons=clean_string_list(positive),
        negative_reasons=clean_string_list(negative),
        missing_data=clean_string_list(missing),
        invalidation_signals=invalidation,
        observation_conditions=observation,
        suggested_strategy=suggested,
        data_quality=data_quality,
        is_mock_or_fallback_data=bool(result.is_mock),
        durability_score=result.durability_score,
        durability_components=dict(result.durability_components or {}),
        durability_metrics=result.durability_metrics,
        reviewer_result=None,
        screening_result=result,
    )


def _build_factor_scores(result: ScreeningResult, bands: Mapping[str, Any]) -> list[CanslimFactorScore]:
    out: list[CanslimFactorScore] = []
    for factor in FACTORS:
        status = result.pillars.get(factor, "Neutral")
        metric = result.pillar_metrics.get(factor)
        if status in _NULL_STATUSES:
            score = None
            missing = [f"{factor} pillar status {status}"]
        else:
            score = int(bands.get(status, 50))
            missing = []
        reason = clean_user_facing_text(metric) if metric else f"{factor} 條件狀態 {status}"
        data_used = [clean_user_facing_text(metric)] if metric else []
        out.append(CanslimFactorScore(
            factor=factor, status=status, score=score,
            reason=reason, data_used=data_used, missing_data=missing,
        ))
    return out


def _overall_score(non_null: list[CanslimFactorScore], weights: Mapping[str, Any]) -> int:
    if not non_null:
        return 0
    total_w = sum(float(weights.get(f.factor, 1.0)) for f in non_null)
    if total_w <= 0:
        return 0
    acc = sum(float(weights.get(f.factor, 1.0)) * f.score for f in non_null)
    return int(round(acc / total_w))


def _confidence(result, by_factor, core_missing, coverage, cfg) -> str:
    c = cfg["confidence"]
    core_factors = list(cfg["core_factors"])
    if len(core_missing) >= int(c["insufficient_core_missing_min"]):
        return "LOW"
    # HIGH requires real data + confirmed regime + near-high (N) + every CORE factor
    # actually passing (a weak/failing core factor, e.g. weak institutional, must
    # not reach HIGH — only lowers to MEDIUM at best). Grade is never an input here.
    core_all_pass = all(by_factor[f].status == "Pass" for f in core_factors)
    high_ok = (
        (not result.is_mock or not c.get("block_high_when_mock", True))
        and result.market_regime in list(c["high_requires_regime"])
        and by_factor["N"].status in list(c["high_requires_n_status"])
        and not core_missing
        and core_all_pass
    )
    if high_ok:
        return "HIGH"
    if result.is_mock or result.market_regime == "unknown" or coverage < float(cfg["coverage_floor"]):
        return "LOW"
    return "MEDIUM"


def _risk_level(result, cfg) -> str:
    r = cfg["risk"]
    if result.market_regime == "severe":
        return str(r["severe_regime_level"])
    score = int(result.scores.get("risk", 0) or 0)
    if score >= int(r["high_score_at_or_above"]):
        level = "HIGH"
    elif score >= int(r["medium_score_at_or_above"]):
        level = "MEDIUM"
    else:
        level = "LOW"
    if result.market_regime == "unknown" and level == "LOW":
        return str(r["unknown_regime_min_level"])
    return level


def _pass_status(result, by_factor, core_missing, confidence, cfg) -> str:
    ps = cfg["pass_status"]
    if len(core_missing) >= int(cfg["confidence"]["insufficient_core_missing_min"]):
        return "INSUFFICIENT_DATA"
    if result.candidate_grade in list(ps["fail_grades"]):
        return "FAIL"
    if by_factor["C"].status == "Fail" and by_factor["A"].status == "Fail":
        return "FAIL"
    # Growth eligibility gate (2026-05-30 redesign): CANSLIM is a GROWTH screen, so a single
    # failing earnings pillar (C or A) blocks PASS even when grade/regime/confidence qualify
    # — such a name can still be WATCHLIST, never a clean growth PASS. C/A are gates here,
    # not score drivers (their standalone forward-return edge is weak; see factor_weights).
    ca_gate_ok = by_factor["C"].status != "Fail" and by_factor["A"].status != "Fail"
    if (
        result.candidate_grade in list(ps["pass_grades"])
        and result.market_regime != "severe"
        and confidence in {"HIGH", "MEDIUM"}
        and ca_gate_ok
    ):
        return "PASS"
    return "WATCHLIST"


def _data_quality(result, coverage, cfg) -> str:
    if result.is_mock:
        return "LOW"
    if coverage >= 0.85:
        return "HIGH"
    if coverage >= float(cfg["coverage_floor"]):
        return "MEDIUM"
    return "LOW"


def _suggested_strategy(result, pass_status, by_factor, cfg) -> str:
    t = cfg["suggested_strategy_templates"]
    if pass_status == "INSUFFICIENT_DATA":
        text = t["insufficient"]
    elif pass_status == "FAIL":
        text = t["fail"]
    elif result.market_regime in {"unknown", "severe", "risk_off"}:
        # Weak / unconfirmed market direction forces conservative language.
        text = t["conservative"]
    elif by_factor["N"].status == "Pass":
        text = t["watchlist_near_high"]
    else:
        text = t["watchlist_default"]
    return clean_user_facing_text(text)
