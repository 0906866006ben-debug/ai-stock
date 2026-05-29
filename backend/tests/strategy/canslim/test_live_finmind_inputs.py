from __future__ import annotations

import json

from backend.app.services.strategy.canslim import live_finmind_inputs as lfi


def test_institutional_pivot_buckets_by_name():
    rows = [
        {"date": "2026-05-20", "name": "Foreign_Investor", "buy": 100, "sell": 40},
        {"date": "2026-05-20", "name": "Investment_Trust", "buy": 30, "sell": 10},
        {"date": "2026-05-20", "name": "Dealer_self", "buy": 5, "sell": 8},
    ]
    df = lfi._institutional_df(rows)
    row = df.iloc[0]
    assert row["foreign_net"] == 60
    assert row["trust_net"] == 20
    assert row["dealer_net"] == -3


def test_financials_grouped_with_eps_and_raw_json():
    rows = [
        {"date": "2026-03-31", "type": "EPS", "value": 8.7},
        {"date": "2026-03-31", "type": "Revenue", "value": 1000.0},
        {"date": "2026-03-31", "type": "IncomeAfterTaxes", "value": 250.0},
    ]
    df = lfi._financials_df(rows)
    r = df.iloc[0]
    assert r["period_end"] == "2026-03-31"
    assert r["eps"] == 8.7
    assert r["filing_date"] == "2026-05-15"  # +45 days
    items = json.loads(r["raw_json"])
    assert {"type": "Revenue", "value": 1000.0} in items


async def test_build_live_inputs_decodes_finmind(monkeypatch):
    async def fake_query(dataset, *, data_id="", start_date="", end_date="", row_limit=500):
        data = {
            "TaiwanStockMonthRevenue": [
                {"date": "2025-04-01", "revenue": 100}, {"date": "2026-04-01", "revenue": 150},
            ],
            "TaiwanStockInstitutionalInvestorsBuySell": [
                {"date": "2026-05-20", "name": "Foreign_Investor", "buy": 100, "sell": 40},
            ],
            "TaiwanStockFinancialStatements": [
                {"date": "2025-03-31", "type": "EPS", "value": 5.0},
                {"date": "2026-03-31", "type": "EPS", "value": 8.0},
            ],
            "TaiwanStockBalanceSheet": [
                {"date": "2026-03-31", "type": "EquityAttributableToOwnersOfParent", "value": 1000.0},
            ],
            "TaiwanStockPER": [{"date": "2026-05-20", "PER": 18.5}],
        }.get(dataset, [])
        return {"dataset": dataset, "status": "ok", "rows": data, "columns": [], "count": len(data)}

    monkeypatch.setattr(lfi, "query_finmind", fake_query)
    lfi.file_cache.clear(lfi._CACHE_NAMESPACE)
    detail, fin_metrics, eps_filing = await lfi.build_live_inputs("2330", "2026-05-24")
    assert detail.get("month_revenue_yoy")  # YoY computed from the revenue series
    assert detail.get("foreign_net_5")
    assert fin_metrics.get("quarterly_eps_yoy") == 0.6  # (8-5)/5 from EPS series
    assert fin_metrics.get("pe_ttm") == 18.5
    assert eps_filing == "2026-05-15"  # 2026-03-31 + 45d
