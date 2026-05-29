from __future__ import annotations

from backend.app.models.screener_schemas import ScreeningResult
from backend.app.services.strategy.canslim.canslim_output import build_full_result
from backend.app.services.strategy.canslim.reviewer import review


def _full(pillars=None, *, grade="A", regime="risk_on", is_mock=False):
    base = {p: "Pass" for p in ("C", "A", "N", "S", "L", "I", "M")}
    base.update(pillars or {})
    sr = ScreeningResult(
        stock_id="2330", as_of_date="2024-06-28", is_mock=is_mock,
        candidate_grade=grade, canslim_match="7/7", pillars=base,
        pillar_metrics={p: f"{p} metric" for p in base},
        scores={"signal": 70, "risk": 20, "confidence": 75},
        market_regime=regime, interpretation="conditional observation",
        action_type="Watchlist Candidate",
    )
    return build_full_result(sr)


def test_clean_high_quality_output_is_approved():
    r = review(_full())
    assert r.review_status == "APPROVED"
    assert r.review_score >= 80
    assert not r.critical_issues


def test_reviewer_rejects_missing_invalidation_signals():
    full = _full().model_copy(update={"invalidation_signals": []})
    r = review(full)
    assert r.review_status == "REJECTED"
    assert any("invalidation" in c.lower() for c in r.critical_issues)


def test_reviewer_rejects_direct_buy_language():
    full = _full().model_copy(update={"suggested_strategy": "strong buy now, guaranteed profit"})
    r = review(full)
    assert r.review_status == "REJECTED"
    assert any("language" in c.lower() for c in r.critical_issues)


def test_reviewer_rejects_mock_data_with_high_confidence():
    full = _full(is_mock=True).model_copy(update={"confidence": "HIGH"})
    r = review(full)
    assert r.review_status == "REJECTED"
    assert r.overconfidence_flags


def test_reviewer_rejects_core_missing_with_high_confidence():
    full = _full({"L": "Insufficient_Data"}).model_copy(update={"confidence": "HIGH"})
    r = review(full)
    assert r.review_status == "REJECTED"
