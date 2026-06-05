from __future__ import annotations

import pytest

from backend.app.services.tw_stock_master_cache import StockMasterCache
from backend.app.services import tw_stocks_list


def test_stock_master_cache_round_trip(tmp_path):
    cache = StockMasterCache(tmp_path / "stock_master.db")
    written = cache.write_stocks(
        [
            {
                "stock_code": "2330",
                "company_name": "台積電",
                "market_type": "上市",
                "industry": "半導體",
                "source": "twse_official",
            }
        ],
        source="twse_tpex_official",
    )

    snapshot = cache.read_snapshot(max_age_seconds=86400)

    assert written == 1
    assert snapshot is not None
    assert snapshot.is_stale is False
    assert snapshot.stocks[0]["stock_code"] == "2330"
    assert snapshot.stocks[0]["company_name"] == "台積電"


@pytest.mark.asyncio
async def test_get_tw_stocks_uses_fresh_master_cache(tmp_path, monkeypatch):
    cache = StockMasterCache(tmp_path / "stock_master.db")
    cache.write_stocks(
        [
            {
                "stock_code": "2330",
                "company_name": "台積電",
                "market_type": "上市",
                "industry": "半導體",
                "source": "twse_official",
            }
        ],
        source="twse_tpex_official",
    )
    monkeypatch.setattr(tw_stocks_list, "StockMasterCache", lambda: cache)

    async def fail_live_fetch():
        raise AssertionError("fresh stock master cache should avoid live fetch")

    monkeypatch.setattr(tw_stocks_list, "_fetch_from_public_openapi_with_report", fail_live_fetch)

    result = await tw_stocks_list.get_tw_stocks()

    assert result["data_source"] == "cache"
    assert result["stocks"][0]["stock_code"] == "2330"
    assert result["source_report"]["fallback_used"] is False
