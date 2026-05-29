from __future__ import annotations

from backend.app.models.schemas import CandlePoint, StockAnalysisResponse, TaiwanStockAnalysisResponse
from backend.app.models.screener_schemas import CandidateMetrics, CandidateScores, SurgeCandidateResult
from backend.app.services.strategy.canslim.screening import contains_forbidden_action_language


def _metrics(**overrides) -> CandidateMetrics:
    data = {
        "return_60d": 0.1,
        "return_20d": 0.05,
        "return_60_to_20": 0.02,
        "return_5d": 0.01,
        "avg_volume_20_lots": 1000,
        "avg_turnover_20": 50_000_000,
        "base_high": 100,
        "base_low": 90,
        "base_range_pct": 0.1,
        "volume_contraction_ratio": 0.8,
        "volume_recovery_ratio_5d": 1.2,
        "volume_today_ratio_20": 1.5,
        "ema_spread": 0.02,
        "ema5_slope": 0.01,
        "ema10_slope": 0.01,
        "ema20_slope": 0.01,
        "relative_strength_20d": None,
        "relative_strength_60d": None,
        "close_distance_from_ema20": 0.03,
    }
    data.update(overrides)
    return CandidateMetrics(**data)


def _scores() -> CandidateScores:
    return CandidateScores(
        liquidity_score=1,
        price_position_score=2,
        base_compression_score=3,
        volume_score=4,
        ema_convergence_score=5,
        relative_strength_score=6,
    )


def test_candidate_grade_alias_keeps_entry_tier() -> None:
    metrics = _metrics(entry_tier=2)

    assert metrics.entry_tier == 2
    assert metrics.candidate_grade == "Quality"


def test_candidate_grade_prefers_canslim_grade_when_available() -> None:
    metrics = _metrics(entry_tier=1, canslim_grade="A")

    assert metrics.entry_tier == 1
    assert metrics.candidate_grade == "A"


def test_screening_status_alias_keeps_candidate_type() -> None:
    result = SurgeCandidateResult(
        stock_id="2330",
        stock_name="台積電",
        candidate_type="起漲前觀察",
        surge_candidate_score=70,
        confidence_score=60,
        risk_score=20,
        scores=_scores(),
        metrics=_metrics(),
        reasons=[],
        watch_conditions=[],
        invalidation=[],
        risk_flags=[],
        missing_data=[],
        data_quality_flags=[],
    )

    dumped = result.model_dump()
    assert result.candidate_type == "起漲前觀察"
    assert result.screening_status == "起漲前觀察"
    assert dumped["candidate_type"] == dumped["screening_status"]


def test_stock_analysis_screening_summary_is_verb_free_and_recommendation_remains() -> None:
    response = StockAnalysisResponse(
        symbol="AAPL",
        company_name="Apple",
        current_price=100,
        price_change_percent=1.0,
        trend="bullish",
        confidence=0.8,
        summary="buy signal mentioned in source text with target price context",
        risks=[],
        catalysts=[],
        recommendation="buy",
        recent_news=[],
        financial_summary={},
        chart_data=[CandlePoint(time="2025-01-01", open=1, high=1, low=1, close=1, volume=1)],
        data_source="mock",
    )

    assert response.recommendation == "buy"
    assert response.screening_summary
    assert not contains_forbidden_action_language(response.screening_summary)


def test_tw_analysis_screening_summary_is_verb_free_and_recommendation_remains() -> None:
    response = TaiwanStockAnalysisResponse(
        symbol="2330",
        company_name="台積電",
        market_type="TWSE",
        current_price=950,
        price_change_percent=1.5,
        volume=10_000_000,
        trend="看漲",
        confidence=0.85,
        summary="建議觀望，目標價文字不應進入新摘要",
        risks=[],
        catalysts=[],
        recommendation="買進",
        chart_data=[CandlePoint(time="2025-01-01", open=940, high=960, low=935, close=950, volume=10_000_000)],
        data_source="mock",
        analysis_source="mock",
        analyzed_at="2025-05-07T00:00:00+00:00",
    )

    assert response.recommendation == "買進"
    assert response.screening_summary
    assert not contains_forbidden_action_language(response.screening_summary)
