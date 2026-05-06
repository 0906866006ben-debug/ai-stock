import pytest
from pytest_httpx import HTTPXMock


def _finmind_info_response(stock_type: str, company_name: str = "台積電") -> dict:
    return {
        "msg": "success",
        "status": 200,
        "data": [{"stock_id": "2330", "company_name": company_name, "type": stock_type}],
    }


@pytest.mark.asyncio
async def test_mock_returned_when_no_api_key(monkeypatch):
    monkeypatch.delenv("FINMIND_API_KEY", raising=False)
    from backend.app.services.finmind_company import get_tw_company_info
    data, is_mock = await get_tw_company_info("2330")
    assert is_mock is True
    assert data["company_name"] == "2330"
    assert data["market_type"] == "TWSE"


@pytest.mark.asyncio
async def test_twse_mapping(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=_finmind_info_response("twse"))
    from backend.app.services.finmind_company import get_tw_company_info
    data, is_mock = await get_tw_company_info("2330")
    assert is_mock is False
    assert data["company_name"] == "台積電"
    assert data["market_type"] == "TWSE"


@pytest.mark.asyncio
async def test_tpex_mapping(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=_finmind_info_response("tpex", "某公司"))
    from backend.app.services.finmind_company import get_tw_company_info
    data, _ = await get_tw_company_info("6488")
    assert data["market_type"] == "TPEx"


@pytest.mark.asyncio
async def test_otc_mapping(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=_finmind_info_response("otc", "某公司"))
    from backend.app.services.finmind_company import get_tw_company_info
    data, _ = await get_tw_company_info("6488")
    assert data["market_type"] == "TPEx"


@pytest.mark.asyncio
async def test_unknown_type_preserved(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json=_finmind_info_response("emerging", "某公司"))
    from backend.app.services.finmind_company import get_tw_company_info
    data, _ = await get_tw_company_info("1234")
    assert data["market_type"] == "EMERGING"


@pytest.mark.asyncio
async def test_empty_response_returns_mock(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("FINMIND_API_KEY", "test-token")
    httpx_mock.add_response(json={"msg": "success", "status": 200, "data": []})
    from backend.app.services.finmind_company import get_tw_company_info
    data, is_mock = await get_tw_company_info("9999")
    assert is_mock is True
    assert data["company_name"] == "9999"
