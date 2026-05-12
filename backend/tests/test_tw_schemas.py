import pytest
from pydantic import ValidationError
from backend.app.models.schemas import CandlePoint, TaiwanStockAIAnalysis, TaiwanStockAnalysisResponse


def test_candle_point_fields():
    cp = CandlePoint(time="2025-01-01", open=100.0, high=105.0, low=98.0, close=103.0, volume=500000)
    assert cp.time == "2025-01-01"
    assert cp.volume == 500000


def test_tw_ai_analysis_valid_trend():
    a = TaiwanStockAIAnalysis(
        summary="test", trend="看漲", confidence=0.8,
        risks=[], catalysts=[], recommendation="buy",
    )
    assert a.trend == "看漲"


def test_tw_ai_analysis_invalid_trend():
    with pytest.raises(ValidationError):
        TaiwanStockAIAnalysis(
            summary="test", trend="bullish", confidence=0.8,
            risks=[], catalysts=[], recommendation="buy",
        )


def test_tw_ai_analysis_confidence_clamped():
    a = TaiwanStockAIAnalysis(
        summary="test", trend="中立", confidence=1.5,
        risks=[], catalysts=[], recommendation="hold",
    )
    assert a.confidence == 1.0

    a2 = TaiwanStockAIAnalysis(
        summary="test", trend="中立", confidence=-0.3,
        risks=[], catalysts=[], recommendation="hold",
    )
    assert a2.confidence == 0.0


def test_taiwan_response_defaults():
    from backend.app.models.schemas import CandlePoint
    resp = TaiwanStockAnalysisResponse(
        symbol="2330", company_name="台積電", market_type="TWSE",
        current_price=950.0, price_change_percent=1.5, volume=10000000,
        trend="看漲", confidence=0.85, summary="test summary",
        risks=["risk1"], catalysts=["cat1"], recommendation="買進",
        chart_data=[CandlePoint(time="2025-01-01", open=940.0, high=960.0, low=935.0, close=950.0, volume=10000000)],
        data_source="live", analysis_source="ai",
        analyzed_at="2025-05-07T00:00:00+00:00",
    )
    assert resp.currency == "TWD"
    assert resp.recent_news == []
    assert resp.disclaimer == "本分析僅供參考，不構成投資建議。"
