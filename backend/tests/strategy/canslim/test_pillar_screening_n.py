from __future__ import annotations

from backend.app.services.strategy.canslim.features import CanslimFeatures
from backend.app.services.strategy.canslim.news_pillar import NPillarAnalysis, NPillarClaim
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pillar_screening import screen_N


def _f(**ov) -> CanslimFeatures:
    data = {"symbol": "2330", "as_of_date": "2026-01-02", "close": 98.0, "high_252d": 100.0}
    data.update(ov)
    return CanslimFeatures(**data)


def _catalyst(score: int) -> NPillarAnalysis:
    return NPillarAnalysis(
        evidence="found", confidence="high", summary="new product orders",
        catalyst_score=score,
        claims=[NPillarClaim(source_url="https://e.com/1", published_date="2026-01-02", summary="新產品訂單")],
    )


def _p():
    return load_params()


def test_new_high_passes_on_price_alone_without_news():
    # close/high = 0.98 (>= 0.97) and NO catalyst -> Pass on the new-high backbone.
    v = screen_N(_f(close=98.0, high_252d=100.0), {}, _p(), n_pillar_analysis=None)
    assert v.status == "Pass"


def test_far_from_high_with_strong_catalyst_is_fail():
    # 0.80 from high; even a strong AI catalyst cannot rescue N (news != extension).
    v = screen_N(_f(close=80.0, high_252d=100.0), {}, _p(), n_pillar_analysis=_catalyst(90))
    assert v.status == "Fail"


def test_near_weak_band_strong_catalyst_upgrades_to_pass():
    # 0.96 (between weak 0.95 and pass 0.97) + strong catalyst -> upgraded to Pass.
    v = screen_N(_f(close=96.0, high_252d=100.0), {}, _p(), n_pillar_analysis=_catalyst(75))
    assert v.status == "Pass"


def test_near_weak_band_without_catalyst_is_weak():
    v = screen_N(_f(close=96.0, high_252d=100.0), {}, _p(), n_pillar_analysis=None)
    assert v.status == "Weak"


def test_price_unavailable_strong_catalyst_is_weak_not_pass():
    v = screen_N(_f(close=None, high_252d=None), {}, _p(), n_pillar_analysis=_catalyst(80))
    assert v.status == "Weak"


def test_price_unavailable_no_catalyst_is_ai_review():
    v = screen_N(_f(close=None, high_252d=None), {}, _p(), n_pillar_analysis=None)
    assert v.status == "AI_Review_Required"


def test_below_price_floor_is_fail():
    v = screen_N(_f(close=8.0, high_252d=8.1), {}, _p(), n_pillar_analysis=_catalyst(90))
    assert v.status == "Fail"
    assert "price floor" in v.reason.lower()
