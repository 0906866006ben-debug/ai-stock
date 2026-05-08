"""Tests for equity research agent."""

import pytest
from backend.app.agents.equity_research_agent import (
    analyze_equity_research,
    _mock_equity_research,
)
from backend.app.models.schemas import (
    FundamentalAnalysis,
    FundamentalMetrics,
    TechnicalAnalysis,
    ChipAnalysis,
    NewsAnalysis,
    ComprehensiveAnalysis,
    EquityResearch,
)


@pytest.fixture
def mock_fundamental():
    return FundamentalAnalysis(
        summary="營收持續成長，盈利能力穩定",
        revenue_trend="improving",
        profitability={"trend": "improving", "quality": "high"},
        valuation={"level": "fair", "support": "PE 15-17"},
        financial_health={"debt_risk": "low", "liquidity": "good", "cash_flow_quality": "strong"},
        risks=["競爭加劇", "匯率風險", "原物料成本上升"],
        catalysts=["新產品發布", "併購機會", "股息提升"],
        metrics=FundamentalMetrics(
            latest_revenue="196.8B",
            revenue_yoy=8.5,
            pe_ratio=15.2,
            pb_ratio=2.8,
            roe=20.5,
            dividend_yield=2.1,
        ),
        confidence=0.75,
        is_mock=True,
    )


@pytest.fixture
def mock_technical():
    return TechnicalAnalysis(
        summary="技術面呈上升趨勢，均線排列多頭",
        trend="uptrend",
        momentum={"rsi": 55, "rsi_signal": "neutral", "macd_signal": "bullish"},
        volatility={"atr": 2.5, "bb_position": "middle", "volatility_level": "moderate"},
        key_levels={"support": 140, "resistance": 160, "breakout_potential": "high"},
        risks=["技術面過熱", "均線粘合"],
        opportunities=["突破前高", "低點買進"],
        confidence=0.7,
        is_mock=True,
    )


@pytest.fixture
def mock_chip():
    return ChipAnalysis(
        summary="籌碼面呈現積累態勢，外資淨買進",
        institutional_sentiment={
            "foreign": {"trend": "buying"},
            "domestic_fund": {"trend": "neutral"},
            "dealer": {"trend": "selling"},
        },
        chip_position={"overall_trend": "accumulating", "abnormal_movement": "none"},
        risk_indicators={"margin_ratio": "normal", "short_interest": "low"},
        liquidity={"daily_turnover": "normal", "liquidity_risk": "low"},
        risks=["籌碼異常波動", "融資餘額增加"],
        signals=["外資持續淨買進", "融券減少"],
        confidence=0.68,
        is_mock=True,
    )


@pytest.fixture
def mock_news():
    return NewsAnalysis(
        summary="消息面整體向好，利多消息較多",
        recent_headlines=[
            {"title": "公司公告新策略", "sentiment": "bullish"},
            {"title": "產業前景看好", "sentiment": "bullish"},
        ],
        sentiment_aggregate={
            "bullish_count": 6,
            "neutral_count": 3,
            "bearish_count": 1,
            "overall_score": 0.7,
            "trend": "bullish",
        },
        key_catalysts=[
            {"event": "Q3財報發布", "date": "2026-11-15", "potential_impact": "high"},
            {"event": "新產品發布", "date": "2026-12-01", "potential_impact": "medium"},
        ],
        macro_impact={"relevant_factors": "Fed利率政策", "impact_on_stock": "positive"},
        risks=["利多已反應", "財報不佳風險"],
        opportunities=["併購傳聞", "分拆上市"],
        confidence=0.72,
        is_mock=True,
    )


@pytest.fixture
def mock_comprehensive():
    return ComprehensiveAnalysis(
        summary="綜合四柱判斷，該股具中期投資價值",
        overall_direction="bullish",
        confirmation_pillars={
            "基本面": "bullish",
            "技術面": "bullish",
            "籌碼面": "bullish",
            "消息面": "bullish",
        },
        confirmation_score=0.85,
        conflicts=[],
        composite_confidence=0.73,
        target_price=165.0,
        stop_loss=135.0,
        timeframe="中期",
        conviction_level="高",
        recommendation="建議積極佈局，可分批進場",
        key_risks=["技術面過熱", "競爭加劇", "匯率風險"],
        catalyst_timeline=["Q3財報", "新產品發布", "併購傳聞"],
        conflict_resolution="四柱高度一致，看好方向明確",
        is_mock=True,
    )


@pytest.fixture
def mock_research_data():
    return {
        "headlines": [
            {"title": "2330 TSMC 獲大單帶動股價走高", "source": "Market News", "url": ""}
        ],
        "analyst_consensus": "看漲",
        "analyst_rating_counts": {"buy": 8, "hold": 3, "sell": 1},
        "price_target_range": {"low": 155, "high": 180, "median": 170},
        "social_sentiment_summary": "散戶看好，機構持續買進",
        "sentiment_stage": "early-stage",
        "narrative_source": "fallback",
    }


def test_mock_equity_research_2330(mock_comprehensive):
    """Test mock equity research generation for TSMC (2330)."""
    result = _mock_equity_research(
        symbol="2330",
        company_name="台積電",
        current_price=150.0,
        comprehensive=mock_comprehensive,
    )

    # Verify schema fields
    assert result.social_sentiment
    assert result.sentiment_stage in ["euphoric", "fearful", "skeptical", "early-stage"]
    assert len(result.catalysts) >= 3
    assert result.institutional_view
    assert result.narrative_conclusion

    # Fundamental snapshot
    assert result.valuation_verdict in ["overvalued", "fairly valued", "undervalued"]
    assert result.valuation_assumptions
    assert len(result.financial_risks) >= 3

    # Technical snapshot
    assert result.technical_verdict
    assert result.institutional_positioning
    assert result.setup_suitability

    # Scenarios
    assert result.scenario_bear.target_price == round(150 * 0.85, 2)
    assert result.scenario_base.target_price == round(150 * 1.12, 2)
    assert result.scenario_bull.target_price == round(150 * 1.30, 2)
    assert result.scenario_stretched.target_price == round(150 * 1.50, 2)

    # Action framework
    assert result.entry_zone
    assert result.add_zone
    assert result.profit_taking
    assert result.thesis_break
    assert result.key_catalyst
    assert result.hidden_risk

    # Meta
    assert result.investment_rating in ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    assert result.summary
    assert 0 <= result.confidence <= 1


def test_mock_equity_research_0050(mock_comprehensive):
    """Test mock equity research for ETF (0050)."""
    result = _mock_equity_research(
        symbol="0050",
        company_name="元大台灣50",
        current_price=100.0,
        comprehensive=mock_comprehensive,
    )

    # Verify scenarios calculated correctly
    assert result.scenario_bear.target_price == 85.0
    assert result.scenario_base.target_price == 112.0
    assert result.scenario_bull.target_price == 130.0
    assert result.scenario_stretched.target_price == 150.0


def test_equity_research_schema_validation(mock_comprehensive):
    """Verify all required EquityResearch fields are present and valid."""
    result = _mock_equity_research(
        symbol="2330", company_name="台積電", current_price=150.0, comprehensive=mock_comprehensive
    )

    # Check all required fields exist and are non-empty
    assert result.social_sentiment, "social_sentiment should not be empty"
    assert result.sentiment_stage, "sentiment_stage should not be empty"
    assert result.catalysts, "catalysts list should not be empty"
    assert result.institutional_view, "institutional_view should not be empty"
    assert result.narrative_conclusion, "narrative_conclusion should not be empty"

    assert result.valuation_verdict, "valuation_verdict should not be empty"
    assert result.valuation_assumptions, "valuation_assumptions should not be empty"
    assert result.financial_risks, "financial_risks list should not be empty"

    assert result.technical_verdict, "technical_verdict should not be empty"
    assert result.institutional_positioning, "institutional_positioning should not be empty"
    assert result.setup_suitability, "setup_suitability should not be empty"

    # Scenarios
    assert result.scenario_bear
    assert result.scenario_base
    assert result.scenario_bull
    assert result.scenario_stretched

    # Action framework
    assert result.entry_zone, "entry_zone should not be empty"
    assert result.add_zone, "add_zone should not be empty"
    assert result.profit_taking, "profit_taking should not be empty"
    assert result.thesis_break, "thesis_break should not be empty"
    assert result.key_catalyst, "key_catalyst should not be empty"
    assert result.hidden_risk, "hidden_risk should not be empty"

    # Meta
    assert result.investment_rating, "investment_rating should not be empty"
    assert result.summary, "summary should not be empty"
    assert 0 <= result.confidence <= 1, "confidence must be in [0, 1]"
    assert isinstance(result.is_mock, bool), "is_mock must be boolean"


def test_scenario_price_ordering(mock_comprehensive):
    """Verify scenario prices are correctly ordered: Bear < Base < Bull < Stretched."""
    result = _mock_equity_research(
        symbol="2330", company_name="台積電", current_price=150.0, comprehensive=mock_comprehensive
    )

    bear = result.scenario_bear.target_price
    base = result.scenario_base.target_price
    bull = result.scenario_bull.target_price
    stretched = result.scenario_stretched.target_price

    assert bear < base, f"Bear ({bear}) should be < Base ({base})"
    assert base < bull, f"Base ({base}) should be < Bull ({bull})"
    assert bull < stretched, f"Bull ({bull}) should be < Stretched ({stretched})"


def test_investment_rating_options(mock_comprehensive):
    """Test that investment_rating is one of valid enum options."""
    result = _mock_equity_research(
        symbol="2330", company_name="台積電", current_price=150.0, comprehensive=mock_comprehensive
    )

    valid_ratings = {"Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"}
    assert result.investment_rating in valid_ratings, f"Rating '{result.investment_rating}' not in {valid_ratings}"


@pytest.mark.asyncio
async def test_analyze_equity_research_mock_fallback(
    mock_fundamental,
    mock_technical,
    mock_chip,
    mock_news,
    mock_comprehensive,
    mock_research_data,
):
    """Test that analyze_equity_research returns mock when no API key."""
    # Should return mock EquityResearch when GEMINI_API_KEY not set
    result = await analyze_equity_research(
        symbol="2330",
        company_name="台積電",
        current_price=150.0,
        fundamental=mock_fundamental,
        technical=mock_technical,
        chip=mock_chip,
        news=mock_news,
        comprehensive=mock_comprehensive,
        research_data=mock_research_data,
    )

    assert result
    assert isinstance(result, EquityResearch)
    assert 0 <= result.confidence <= 1
