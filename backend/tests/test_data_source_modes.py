import pandas as pd
import pytest

from backend.app.services.finmind_market import get_tw_price_history_with_source


@pytest.mark.asyncio
async def test_production_mode_disables_mock_candles(monkeypatch) -> None:
    monkeypatch.setenv("DATA_MODE", "production")
    monkeypatch.setenv("ALLOW_MOCK_DATA", "true")
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    monkeypatch.setattr("backend.app.services.finmind_market.yf.download", lambda *args, **kwargs: pd.DataFrame())

    result = await get_tw_price_history_with_source("9999", 150)

    assert result.candles == []
    assert result.source_info.ohlcv_source == "unavailable"
    assert result.source_info.is_mock_data is False
    assert "insufficient_data" in result.source_info.data_warnings


@pytest.mark.asyncio
async def test_development_mode_allows_mock_when_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.setenv("DATA_MODE", "development")
    monkeypatch.setenv("ALLOW_MOCK_DATA", "true")
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    monkeypatch.setattr("backend.app.services.finmind_market.yf.download", lambda *args, **kwargs: pd.DataFrame())

    result = await get_tw_price_history_with_source("9999", 150)

    assert len(result.candles) >= 60
    assert result.source_info.ohlcv_source == "mock"
    assert result.source_info.is_mock_data is True
    assert "mock_ohlcv" in result.source_info.data_warnings

