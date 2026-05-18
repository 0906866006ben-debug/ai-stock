"""
Tests for synthesis agent.
"""
import pytest
from backend.app.agents.synthesis_agent import synthesize_analysis
from backend.app.models.schemas import (
    ComprehensiveAnalysis,
    FundamentalAnalysis,
    FundamentalMetrics,
    TechnicalAnalysis,
    ChipAnalysis,
    NewsAnalysis,
)


@pytest.mark.asyncio
async def test_synthesis_basic():
    """Test synthesis agent with basic pillar inputs."""
    fundamental = FundamentalAnalysis(
        summary="基本面良好",
        revenue_trend="improving",
        profitability={"trend": "improving"},
        valuation={"level": "fair"},
        financial_health={"debt_risk": "low"},
        risks=["政策風險"],
        catalysts=["業績成長"],
        metrics=FundamentalMetrics(latest_revenue="100B", pe_ratio=15.0),
        confidence=0.80,
        is_mock=False,
    )

    technical = TechnicalAnalysis(
        summary="技術面強勢",
        trend="uptrend",
        momentum={"rsi": 65, "rsi_signal": "bullish"},
        volatility={"atr": 10, "bb_position": "middle"},
        key_levels={"resistance": 100, "support": 90},
        risks=["超買"],
        opportunities=["破高"],
        confidence=0.75,
        is_mock=False,
    )

    chip = ChipAnalysis(
        summary="籌碼積極",
        institutional_sentiment={
            "foreign": {"5d_net": 1000000, "trend": "accumulating", "signal": "strong"},
            "domestic_fund": {"5d_net": 500000, "trend": "accumulating"},
            "dealer": {"5d_net": -200000},
        },
        chip_position={"overall_trend": "accumulation"},
        risk_indicators={"margin_ratio": "normal"},
        liquidity={"daily_turnover": "normal"},
        risks=["融資正常"],
        signals=["機構買進"],
        confidence=0.70,
        is_mock=False,
    )

    news = NewsAnalysis(
        summary="消息面樂觀",
        recent_headlines=[],
        sentiment_aggregate={
            "bullish_count": 3,
            "neutral_count": 1,
            "bearish_count": 0,
            "overall_score": 0.85,
            "trend": "improving",
        },
        key_catalysts=[],
        macro_impact={},
        risks=["市場預期"],
        opportunities=["持續看好"],
        confidence=0.72,
        is_mock=False,
    )

    result = await synthesize_analysis(
        symbol="2330",
        company_name="台積電",
        current_price=100.0,
        fundamental=fundamental,
        technical=technical,
        chip=chip,
        news=news,
    )

    assert isinstance(result, ComprehensiveAnalysis)
    assert result.overall_direction in ["bullish", "bearish", "neutral"]
    assert isinstance(result.confirmation_pillars, dict)
    assert 0.0 <= result.confirmation_score <= 1.0
    assert 0.0 <= result.composite_confidence <= 1.0
    assert result.target_price > 0
    assert result.stop_loss > 0
    assert result.recommendation is not None


@pytest.mark.asyncio
async def test_synthesis_conflict_detection():
    """Test synthesis agent detects conflicts."""
    fundamental = FundamentalAnalysis(
        summary="基本面良好",
        revenue_trend="improving",
        profitability={"trend": "improving"},
        valuation={"level": "fair"},
        financial_health={"debt_risk": "low"},
        risks=[],
        catalysts=[],
        metrics=FundamentalMetrics(),
        confidence=0.80,
        is_mock=False,
    )

    technical = TechnicalAnalysis(
        summary="技術面弱勢",
        trend="downtrend",
        momentum={"rsi": 35},
        volatility={},
        key_levels={},
        risks=["超賣"],
        opportunities=[],
        confidence=0.75,
        is_mock=False,
    )

    chip = ChipAnalysis(
        summary="籌碼中立",
        institutional_sentiment={"foreign": {"trend": "neutral"}, "domestic_fund": {"trend": "neutral"}},
        chip_position={},
        risk_indicators={},
        liquidity={},
        risks=[],
        signals=[],
        confidence=0.70,
        is_mock=False,
    )

    news = NewsAnalysis(
        summary="消息面樂觀",
        recent_headlines=[],
        sentiment_aggregate={"trend": "improving", "overall_score": 0.75},
        key_catalysts=[],
        macro_impact={},
        risks=[],
        opportunities=[],
        confidence=0.72,
        is_mock=False,
    )

    result = await synthesize_analysis(
        symbol="2330",
        company_name="台積電",
        current_price=100.0,
        fundamental=fundamental,
        technical=technical,
        chip=chip,
        news=news,
    )

    assert len(result.conflicts) > 0
    assert "基本面" in result.conflicts[0] or "技術面" in result.conflicts[0]


@pytest.mark.asyncio
async def test_synthesis_confirmation_scoring(monkeypatch):
    """Test confirmation scoring when all pillars agree."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    fundamental = FundamentalAnalysis(
        summary="基本面良好",
        revenue_trend="improving",
        profitability={"trend": "improving"},
        valuation={"level": "fair"},
        financial_health={"debt_risk": "low"},
        risks=[],
        catalysts=[],
        metrics=FundamentalMetrics(),
        confidence=0.80,
        is_mock=False,
    )

    technical = TechnicalAnalysis(
        summary="技術面強勢",
        trend="uptrend",
        momentum={},
        volatility={},
        key_levels={},
        risks=[],
        opportunities=[],
        confidence=0.75,
        is_mock=False,
    )

    chip = ChipAnalysis(
        summary="籌碼積極",
        institutional_sentiment={"foreign": {"trend": "accumulating"}, "domestic_fund": {"trend": "accumulating"}},
        chip_position={},
        risk_indicators={},
        liquidity={},
        risks=[],
        signals=[],
        confidence=0.70,
        is_mock=False,
    )

    news = NewsAnalysis(
        summary="消息面樂觀",
        recent_headlines=[],
        sentiment_aggregate={"trend": "improving", "overall_score": 0.75},
        key_catalysts=[],
        macro_impact={},
        risks=[],
        opportunities=[],
        confidence=0.72,
        is_mock=False,
    )

    result = await synthesize_analysis(
        symbol="2330",
        company_name="台積電",
        current_price=100.0,
        fundamental=fundamental,
        technical=technical,
        chip=chip,
        news=news,
    )

    # All 4 agree on bullish
    assert result.confirmation_score == 1.0
    assert result.overall_direction == "bullish"
    assert len(result.conflicts) == 0


def test_synthesis_schema():
    """Test ComprehensiveAnalysis schema validation."""
    analysis = ComprehensiveAnalysis(
        summary="綜合評估：台積電看漲，中度信心。建議布局。",
        overall_direction="bullish",
        confirmation_pillars={
            "基本面": "bullish",
            "技術面": "uptrend",
            "籌碼面": "bullish",
            "消息面": "bullish",
        },
        confirmation_score=0.75,
        conflicts=[],
        composite_confidence=0.75,
        target_price=110.0,
        stop_loss=92.0,
        timeframe="中期（3-6個月）",
        conviction_level="中",
        recommendation="建議布局",
        key_risks=["政策風險", "景氣風險"],
        catalyst_timeline=["業績公佈", "新產品發佈"],
        conflict_resolution="四大柱位共識度高。",
        is_mock=False,
    )

    assert analysis.overall_direction == "bullish"
    assert analysis.confirmation_score == 0.75
    assert analysis.target_price == 110.0
