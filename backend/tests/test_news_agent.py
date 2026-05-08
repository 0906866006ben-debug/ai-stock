"""
Tests for news & sentiment analysis agent.
"""
import pytest
from backend.app.agents.news_agent import analyze_news
from backend.app.models.schemas import NewsAnalysis


@pytest.mark.asyncio
async def test_news_analysis_mock():
    """Test news analysis with mock data."""
    result = await analyze_news("2330", "台積電")

    assert isinstance(result, NewsAnalysis)
    assert result.summary is not None
    assert isinstance(result.recent_headlines, list)
    assert isinstance(result.sentiment_aggregate, dict)
    assert "overall_score" in result.sentiment_aggregate
    assert isinstance(result.key_catalysts, list)
    assert isinstance(result.macro_impact, dict)
    assert isinstance(result.risks, list)
    assert isinstance(result.opportunities, list)
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_news_analysis_etf():
    """Test news analysis for ETF."""
    result = await analyze_news("0050", "元大台灣50")

    assert isinstance(result, NewsAnalysis)
    assert result.summary is not None


@pytest.mark.asyncio
async def test_news_analysis_unknown():
    """Test news analysis for unknown symbol."""
    result = await analyze_news("9999", "9999")

    assert result is not None
    assert result.is_mock is True


def test_news_analysis_schema():
    """Test NewsAnalysis schema validation."""
    analysis = NewsAnalysis(
        summary="消息面評估：相關新聞呈改善趨勢",
        recent_headlines=[{
            "title": "台積電營收增長",
            "source": "經濟日報",
            "date": "2025-05-08",
            "sentiment": "positive",
            "impact": "short_term",
            "relevance": 0.9,
        }],
        sentiment_aggregate={
            "bullish_count": 3,
            "neutral_count": 1,
            "bearish_count": 0,
            "overall_score": 0.85,
            "trend": "improving",
        },
        key_catalysts=[{
            "event": "季度營收公佈",
            "date": "2025-08-15",
            "potential_impact": "high",
            "direction": "bullish",
        }],
        macro_impact={
            "relevant_factors": ["AI芯片需求", "美國政策"],
            "impact_on_stock": "正面",
        },
        risks=["政策變化"],
        opportunities=["業績成長"],
        confidence=0.80,
        is_mock=False,
    )

    assert analysis.confidence == 0.80
    assert analysis.sentiment_aggregate["overall_score"] == 0.85
