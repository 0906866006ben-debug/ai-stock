from __future__ import annotations

from backend.app.models.screener_schemas import ScreeningResult
from backend.app.services.strategy.canslim.canslim_output import build_full_result


def _result(pillars, *, grade="A", regime="risk_on", is_mock=False, scores=None, action="Watchlist Candidate"):
    base = {p: "Pass" for p in ("C", "A", "N", "S", "L", "I", "M")}
    base.update(pillars)
    return ScreeningResult(
        stock_id="2330", as_of_date="2024-06-28", is_mock=is_mock,
        candidate_grade=grade, canslim_match="7/7", pillars=base,
        pillar_metrics={p: f"{p} metric" for p in base},
        scores=scores or {"signal": 70, "risk": 20, "confidence": 75},
        market_regime=regime, interpretation="conditional observation",
        action_type=action,
    )


def test_high_quality_is_pass_and_high_confidence():
    full = build_full_result(_result({}, grade="A", regime="risk_on"))
    assert full.confidence == "HIGH"
    assert full.pass_status in {"PASS", "WATCHLIST"}
    assert full.is_mock_or_fallback_data is False


def test_strong_fundamentals_weak_institutional_not_high_confidence():
    # Everything passes except institutional (a core factor) is Weak.
    full = build_full_result(_result({"I": "Weak"}, grade="A", regime="risk_on"))
    assert full.confidence != "HIGH"
    assert not (full.confidence == "HIGH" and full.pass_status == "PASS")


def test_technical_strong_but_fundamentals_fail_is_not_high_quality():
    full = build_full_result(_result({"C": "Fail", "A": "Fail"}, grade="C"))
    assert full.pass_status == "FAIL"
    assert full.confidence != "HIGH"


def test_insufficient_core_data_returns_insufficient_and_low_confidence():
    full = build_full_result(_result({"C": "Insufficient_Data", "A": "Insufficient_Data"}, grade="D"))
    assert full.pass_status == "INSUFFICIENT_DATA"
    assert full.confidence == "LOW"
    c_factor = next(f for f in full.per_factor_scores if f.factor == "C")
    assert c_factor.score is None and c_factor.missing_data


def test_weak_market_forces_conservative_strategy():
    full = build_full_result(_result({}, grade="A", regime="severe"))
    assert "觀察" in full.suggested_strategy
    assert full.confidence != "HIGH"  # severe regime cannot be HIGH


def test_mock_data_cannot_be_high_confidence():
    full = build_full_result(_result({}, grade="S", regime="risk_on", is_mock=True))
    assert full.confidence != "HIGH"
    assert full.is_mock_or_fallback_data is True
    assert full.data_quality == "LOW"


def test_grade_alone_does_not_grant_high_confidence():
    # S grade but regime unknown -> must not be HIGH (grade is not a confidence input).
    full = build_full_result(_result({}, grade="S", regime="unknown"))
    assert full.confidence != "HIGH"


def test_no_action_verbs_in_output():
    full = build_full_result(_result({}, grade="A"))
    from backend.app.services.strategy.canslim.screening_language import contains_forbidden_action_language
    assert not contains_forbidden_action_language(full.suggested_strategy)
    assert not contains_forbidden_action_language([f.reason for f in full.per_factor_scores])
