from __future__ import annotations

from typing import Any

from backend.screeners.multi_factor_surge.config import CONFIG, clamp_score
from backend.screeners.multi_factor_surge.schemas import ModuleScore


def _num(value: Any) -> float | None:
    if value is None or value == "N/A":
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if abs(value) > 1.5:
        value = value / 100
    return value


def score_fundamentals(fundamentals: dict[str, Any] | None) -> tuple[ModuleScore, dict[str, Any]]:
    metrics: dict[str, Any] = {
        "eps_yoy_growth": None,
        "eps_qoq_streak": None,
        "roe_ttm": None,
        "revenue_2m_avg_vs_12m_max": None,
        "gross_margin": None,
        "cf_per_share_to_eps": None,
        "share_capital": None,
    }
    missing: list[str] = []
    reasons: list[str] = []
    if not fundamentals:
        return ModuleScore(
            score=int(CONFIG["fundamental"]["neutral_score"]),
            missing_data=["eps_unavailable", "revenue_unavailable", "roe_unavailable"],
            is_neutral_fallback=True,
        ), metrics

    eps_yoy = _num(fundamentals.get("eps_yoy") or fundamentals.get("eps_yoy_growth"))
    revenue_yoy = _num(fundamentals.get("revenue_yoy"))
    roe = _num(fundamentals.get("roe") or fundamentals.get("roe_ttm"))
    eps_streak = fundamentals.get("eps_qoq_streak")
    revenue_near_high = fundamentals.get("revenue_2m_avg_vs_12m_max")

    if eps_yoy is None:
        missing.append("eps_unavailable")
    else:
        metrics["eps_yoy_growth"] = round(eps_yoy, 4)
        if eps_yoy >= CONFIG["fundamental"]["eps_yoy_strong"]:
            reasons.append(f"EPS 年增 {eps_yoy:.1%}")
        elif eps_yoy >= CONFIG["fundamental"]["eps_yoy_good"]:
            reasons.append(f"EPS 年增轉強 {eps_yoy:.1%}")

    if revenue_yoy is None and revenue_near_high is None:
        missing.append("revenue_unavailable")
    else:
        metrics["revenue_2m_avg_vs_12m_max"] = bool(revenue_near_high) if revenue_near_high is not None else revenue_yoy >= CONFIG["fundamental"]["eps_yoy_good"]
        if metrics["revenue_2m_avg_vs_12m_max"]:
            reasons.append("近月營收接近或突破 12 月高位")

    if roe is None:
        missing.append("roe_unavailable")
    else:
        metrics["roe_ttm"] = round(roe, 4)
        if roe >= CONFIG["fundamental"]["roe_strong"]:
            reasons.append(f"ROE TTM {roe:.1%}")

    if eps_streak is not None:
        try:
            metrics["eps_qoq_streak"] = int(eps_streak)
        except (TypeError, ValueError):
            metrics["eps_qoq_streak"] = None

    if len(missing) == 3:
        return ModuleScore(
            score=int(CONFIG["fundamental"]["neutral_score"]),
            missing_data=missing,
            is_neutral_fallback=True,
        ), metrics

    score = 50
    if eps_yoy is not None:
        if eps_yoy >= CONFIG["fundamental"]["eps_yoy_strong"]:
            score += 25
        elif eps_yoy >= CONFIG["fundamental"]["eps_yoy_good"]:
            score += 15
        elif eps_yoy < 0:
            score -= 10
    if roe is not None:
        if roe >= CONFIG["fundamental"]["roe_strong"]:
            score += 15
        elif roe >= CONFIG["fundamental"]["roe_good"]:
            score += 8
    if metrics["revenue_2m_avg_vs_12m_max"]:
        score += 10
    if metrics["eps_qoq_streak"] and metrics["eps_qoq_streak"] >= CONFIG["fundamental"]["eps_qoq_streak_good"]:
        score += 8

    return ModuleScore(score=clamp_score(score), reasons=reasons, missing_data=missing), metrics
