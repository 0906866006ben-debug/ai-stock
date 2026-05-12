"""
Tests for comprehensive analysis graph.
"""
import pytest
from backend.app.graphs.comprehensive_analysis_graph import run_comprehensive_analysis


@pytest.mark.asyncio
async def test_comprehensive_analysis_2330():
    """Test comprehensive analysis for 2330 (TSMC)."""
    result = await run_comprehensive_analysis("2330")

    assert result is not None
    assert result["symbol"] == "2330"
    assert result["current_price"] > 0
    assert result["fundamental_analysis"] is not None
    assert result["technical_analysis"] is not None
    assert result["chip_analysis"] is not None
    assert result["news_analysis"] is not None
    assert result["comprehensive_analysis"] is not None


@pytest.mark.asyncio
async def test_comprehensive_analysis_0050():
    """Test comprehensive analysis for 0050 (Taiwan 50 ETF)."""
    result = await run_comprehensive_analysis("0050")

    assert result is not None
    assert result["symbol"] == "0050"
    assert result["company_name"] is not None
    assert result["comprehensive_analysis"] is not None


@pytest.mark.asyncio
async def test_comprehensive_analysis_unknown():
    """Test comprehensive analysis for unknown symbol."""
    result = await run_comprehensive_analysis("9999")

    assert result is not None
    assert result["symbol"] == "9999"
    # May have mock results even for unknown symbols
