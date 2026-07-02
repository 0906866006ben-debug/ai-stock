import pytest


@pytest.mark.asyncio
async def test_tw_stock_graph_full_flow_mock(monkeypatch):
    """Test end-to-end Taiwan stock analysis with mock data (no API keys)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TW_AI_MODEL", raising=False)
    monkeypatch.delenv("TW_AI_MODEL_UNIFIED", raising=False)
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)

    from backend.app.graphs.tw_stock_graph import run_tw_analysis

    result = await run_tw_analysis("2330")

    # Verify state structure
    assert result["symbol"] == "2330"
    assert result["market_data"] is not None
    assert result["company_data"] is not None
    assert result["indicators_data"] is not None
    assert result["ai_result"] is not None
    assert result["data_is_mock"] is True
    assert result["analysis_is_mock"] is True

    # Verify market data shape
    market = result["market_data"]
    assert "current_price" in market
    assert "price_change_percent" in market
    assert "chart_data" in market
    assert len(market["chart_data"]) > 0

    # Verify company data (mock has known company names)
    company = result["company_data"]
    assert company["company_name"] == "台積電"  # Mock has this mapping
    assert company["market_type"] == "TWSE"  # Mock has this mapping

    # Verify indicators were computed
    indicators = result["indicators_data"]
    assert indicators is not None
    assert "ma" in indicators
    assert "rsi" in indicators
    assert "macd" in indicators
    assert "volume" in indicators
    assert "price_changes" in indicators

    # Verify AI result is mock
    ai = result["ai_result"]
    assert ai["trend"] in ("看漲", "看跌", "中立")
    assert 0.0 <= ai["confidence"] <= 1.0
    assert "summary" in ai
    assert "risks" in ai
    assert "catalysts" in ai
    assert "recommendation" in ai


@pytest.mark.asyncio
async def test_tw_stock_graph_with_api_key_set(monkeypatch):
    """Test end-to-end flow when API key is set (but doesn't make real requests).

    When FINMIND_API_KEY is set, the code attempts to fetch from API.
    We test that the graph still completes successfully.
    """
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TW_AI_MODEL", raising=False)
    monkeypatch.delenv("TW_AI_MODEL_UNIFIED", raising=False)

    from backend.app.graphs.tw_stock_graph import run_tw_analysis

    result = await run_tw_analysis("2330")

    # Verify graph executed successfully
    assert result["symbol"] == "2330"
    assert result["analysis_is_mock"] is True  # No GEMINI_API_KEY

    # Verify all nodes executed and produced output
    assert result["market_data"] is not None
    assert result["company_data"] is not None
    assert result["indicators_data"] is not None
    assert result["ai_result"] is not None

    # Verify market data has required fields
    market = result["market_data"]
    assert market["current_price"] > 0
    assert "chart_data" in market
    assert len(market["chart_data"]) > 0

    # Verify company data has required fields
    company = result["company_data"]
    assert "company_name" in company
    assert "market_type" in company

    # Verify indicators were computed from chart data
    indicators = result["indicators_data"]
    assert indicators is not None
    assert "ma" in indicators
    assert "rsi" in indicators
    assert "macd" in indicators
    assert "volume" in indicators
    assert "price_changes" in indicators


@pytest.mark.asyncio
async def test_tw_stock_graph_unknown_symbol_with_no_api_key(monkeypatch):
    """Test handling of unknown symbol with mock fallback."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TW_AI_MODEL", raising=False)
    monkeypatch.delenv("TW_AI_MODEL_UNIFIED", raising=False)
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)

    from backend.app.graphs.tw_stock_graph import run_tw_analysis

    result = await run_tw_analysis("9999")  # Unknown symbol

    # Should still complete with mock data
    assert result["symbol"] == "9999"
    assert result["data_is_mock"] is True
    assert result["analysis_is_mock"] is True

    # With unknown symbol, mock still generates chart data
    assert result["market_data"] is not None
    assert result["indicators_data"] is not None  # Indicators computed from mock data

    # Company name should be the symbol itself for unknown stocks
    company = result["company_data"]
    assert company["company_name"] == "9999"  # Unknown symbol uses symbol as name
    assert company["market_type"] == "TWSE"  # Default market type
