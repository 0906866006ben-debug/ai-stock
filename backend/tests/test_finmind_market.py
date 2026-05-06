import pytest
import os
from pytest_httpx import HTTPXMock


SAMPLE_FINMIND_PRICE_RESPONSE = {
    "msg": "success",
    "status": 200,
    "data": [
        {
            "date": "2025-04-01",
            "stock_id": "2330",
            "Trading_Volume": 20000000,
            "open": 940.0,
            "max": 960.0,
            "min": 935.0,
            "close": 950.0,
        },
        {
            "date": "2025-04-02",
            "stock_id": "2330",
            "Trading_Volume": 18000000,
            "open": 950.0,
            "max": 965.0,
            "min": 945.0,
            "close": 958.0,
        },
    ],
}


@pytest.mark.asyncio
async def test_mock_returned_when_no_api_key(monkeypatch):
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    from backend.app.services.finmind_market import get_tw_market_data
    data, is_mock = await get_tw_market_data("2330")
    assert is_mock is True
    assert "chart_data" in data
    assert len(data["chart_data"]) > 0
    assert data["current_price"] > 0


@pytest.mark.asyncio
async def test_live_data_parsed_correctly(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=SAMPLE_FINMIND_PRICE_RESPONSE)

    from backend.app.services import finmind_market
    import importlib
    importlib.reload(finmind_market)
    from backend.app.services.finmind_market import get_tw_market_data

    data, is_mock = await get_tw_market_data("2330")
    assert is_mock is False
    assert data["current_price"] == 958.0
    assert data["volume"] == 18000000
    # price_change_percent = (958-950)/950*100 ≈ 0.84
    assert abs(data["price_change_percent"] - ((958 - 950) / 950 * 100)) < 0.01
    assert len(data["chart_data"]) == 2
    first = data["chart_data"][0]
    assert first["time"] == "2025-04-01"
    assert first["high"] == 960.0  # mapped from 'max'
    assert first["low"] == 935.0   # mapped from 'min'
    assert first["volume"] == 20000000


@pytest.mark.asyncio
async def test_empty_data_returns_mock(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json={"msg": "success", "status": 200, "data": []})

    from backend.app.services.finmind_market import get_tw_market_data
    data, is_mock = await get_tw_market_data("2330")
    assert is_mock is True


@pytest.mark.asyncio
async def test_network_error_returns_mock(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_exception(Exception("network failure"))

    from backend.app.services.finmind_market import get_tw_market_data
    data, is_mock = await get_tw_market_data("2330")
    assert is_mock is True
