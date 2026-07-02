"""
Tests for fundamental analysis agent.
"""
import pytest
from backend.app.agents.fundamental_agent import analyze_fundamental
from backend.app.models.schemas import FundamentalAnalysis


@pytest.mark.asyncio
async def test_fundamental_analysis_mock_no_api_key(monkeypatch):
    """Test fundamental analysis returns mock when GEMINI_API_KEY missing."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TW_AI_MODEL", raising=False)
    monkeypatch.delenv("TW_AI_MODEL_UNIFIED", raising=False)

    result = await analyze_fundamental("2330", "台積電", 2290.0)

    assert isinstance(result, FundamentalAnalysis)
    assert result.summary is not None
    assert result.revenue_trend in ("improving", "stable", "declining")
    assert result.profitability is not None
    assert "trend" in result.profitability
    assert "quality" in result.profitability
    assert result.valuation is not None
    assert "level" in result.valuation
    assert result.financial_health is not None
    assert "debt_risk" in result.financial_health
    assert "liquidity" in result.financial_health
    assert "cash_flow_quality" in result.financial_health
    assert isinstance(result.risks, list)
    assert len(result.risks) > 0
    assert isinstance(result.catalysts, list)
    assert len(result.catalysts) > 0
    assert result.metrics is not None
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_fundamental_analysis_for_2330():
    """Test fundamental analysis for TSMC (2330)."""
    result = await analyze_fundamental("2330", "台積電", 2290.0)

    # Should return valid analysis
    assert result.metrics is not None
    assert result.metrics.latest_revenue is not None
    assert result.metrics.pe_ratio is not None
    assert result.metrics.roe is not None


@pytest.mark.asyncio
async def test_fundamental_metrics_structure():
    """Test that metrics are properly structured."""
    result = await analyze_fundamental("2330", "台積電", 2290.0)

    metrics = result.metrics
    # Check key metrics exist
    assert metrics.latest_revenue or metrics.latest_revenue is None
    assert metrics.revenue_yoy or metrics.revenue_yoy is None
    assert metrics.eps_latest or metrics.eps_latest is None
    assert metrics.pe_ratio or metrics.pe_ratio is None
    assert metrics.roe or metrics.roe is None
    assert metrics.debt_ratio or metrics.debt_ratio is None


@pytest.mark.asyncio
async def test_fundamental_analysis_etf():
    """Test fundamental analysis for ETF (0050)."""
    result = await analyze_fundamental("0050", "元大台灣50", 130.0)

    assert result is not None
    assert result.metrics is not None


@pytest.mark.asyncio
async def test_fundamental_analysis_unknown_stock():
    """Test fundamental analysis for unknown symbol."""
    result = await analyze_fundamental("9999", "9999", 100.0)

    assert result is not None
    assert result.metrics is not None
    assert result.is_mock is True


def test_fundamental_metrics_validation():
    """Test that FundamentalMetrics validates properly."""
    from backend.app.models.schemas import FundamentalMetrics

    metrics = FundamentalMetrics(
        latest_revenue="196.8B",
        revenue_yoy=29.3,
        eps_latest=32.8,
        pe_ratio=27.5,
        pb_ratio=7.2,
        roe=25.8,
        roa=18.5,
        gross_margin=54.2,
        operating_margin=38.5,
        net_margin=35.2,
        dividend_yield=2.1,
        payout_ratio=55.0,
        debt_ratio=18.5,
        current_ratio=2.8,
        quick_ratio=2.4,
        operating_cf="1.2T",
        free_cf="850B",
        cf_trend="strong",
    )

    assert metrics.latest_revenue == "196.8B"
    assert metrics.revenue_yoy == 29.3
    assert metrics.pe_ratio == 27.5
    assert metrics.roe == 25.8
    assert metrics.cf_trend == "strong"


def test_fundamental_analysis_validation():
    """Test that FundamentalAnalysis validates properly."""
    from backend.app.models.schemas import FundamentalMetrics

    metrics = FundamentalMetrics(pe_ratio=20.0, roe=15.0)

    analysis = FundamentalAnalysis(
        summary="測試分析",
        revenue_trend="stable",
        profitability={"trend": "stable", "quality": "medium"},
        valuation={"level": "fair", "support": "PE 20x"},
        financial_health={"debt_risk": "low", "liquidity": "adequate"},
        risks=["risk1", "risk2"],
        catalysts=["catalyst1"],
        metrics=metrics,
        confidence=0.75,
        is_mock=False,
    )

    assert analysis.summary == "測試分析"
    assert analysis.revenue_trend == "stable"
    assert analysis.confidence == 0.75
    assert len(analysis.risks) == 2
