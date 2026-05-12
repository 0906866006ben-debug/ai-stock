import pytest

from backend.app.services.tw_stocks_list import _fetch_from_finmind


@pytest.mark.asyncio
async def test_fetch_from_finmind_uses_stock_name(httpx_mock):
    httpx_mock.add_response(
        json={
            "status": 200,
            "data": [
                {
                    "stock_id": "1902",
                    "stock_name": "台紙",
                    "type": "twse",
                    "industry_category": "造紙",
                }
            ],
        }
    )

    result = await _fetch_from_finmind("test-token")

    assert result[0]["stock_code"] == "1902"
    assert result[0]["company_name"] == "台紙"
    assert result[0]["market_type"] == "上市"
    assert result[0]["industry"] == "造紙"
