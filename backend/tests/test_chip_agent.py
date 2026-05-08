"""
Tests for chip/institutional analysis agent.
"""
import pytest
from backend.app.agents.chip_agent import analyze_chip
from backend.app.models.schemas import ChipAnalysis


@pytest.mark.asyncio
async def test_chip_analysis_mock_no_api_key(monkeypatch):
    """Test chip analysis returns mock when GEMINI_API_KEY missing."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = await analyze_chip("2330", "台積電")

    assert isinstance(result, ChipAnalysis)
    assert result.summary is not None
    assert isinstance(result.institutional_sentiment, dict)
    assert "foreign" in result.institutional_sentiment
    assert isinstance(result.chip_position, dict)
    assert isinstance(result.risk_indicators, dict)
    assert isinstance(result.risks, list)
    assert isinstance(result.signals, list)
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_chip_analysis_2330():
    """Test chip analysis for 2330 (TSMC)."""
    result = await analyze_chip("2330", "台積電")

    assert isinstance(result, ChipAnalysis)
    assert result.summary is not None
    assert result.institutional_sentiment["foreign"]["5d_net"] is not None


@pytest.mark.asyncio
async def test_chip_analysis_etf():
    """Test chip analysis for ETF."""
    result = await analyze_chip("0050", "元大台灣50")

    assert isinstance(result, ChipAnalysis)
    assert result.chip_position is not None


@pytest.mark.asyncio
async def test_chip_analysis_unknown_stock():
    """Test chip analysis for unknown symbol."""
    result = await analyze_chip("9999", "9999")

    assert result is not None
    assert result.is_mock is True


def test_chip_analysis_schema():
    """Test ChipAnalysis schema validation."""
    analysis = ChipAnalysis(
        summary="籌碼面評估：外資買進，投信觀望",
        institutional_sentiment={
            "foreign": {"5d_net": 2500000, "trend": "accumulating", "signal": "strong"},
            "domestic_fund": {"5d_net": 1200000, "trend": "accumulating"},
            "dealer": {"5d_net": -800000, "activity": "normal"},
        },
        chip_position={"overall_trend": "accumulation", "abnormal_movement": False},
        risk_indicators={"margin_ratio": "normal", "short_interest": "normal"},
        liquidity={"daily_turnover": "normal", "liquidity_risk": "low"},
        risks=["融資正常"],
        signals=["機構買進"],
        confidence=0.75,
        is_mock=False,
    )

    assert analysis.summary == "籌碼面評估：外資買進，投信觀望"
    assert analysis.confidence == 0.75
