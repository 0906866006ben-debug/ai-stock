from __future__ import annotations

import json

import pandas as pd

from backend.scripts import probe_data_sources


def test_probe_report_assembly_with_mocked_payloads(tmp_path):
    def fake_finmind_get(endpoint: str, params: dict):
        dataset = params.get("dataset")
        if endpoint in {"datasets", "dataset"}:
            return {
                "data": [
                    {"dataset": "TaiwanStockNews"},
                    {"dataset": "TaiwanStockDayTrading"},
                    {"dataset": "TaiwanStockHoldingSharesPer"},
                    {"dataset": "TaiwanStockIndustryIndex"},
                    {"dataset": "TaiwanStockInfo"},
                ]
            }
        payloads = {
            "TaiwanStockNews": [
                {"date": "2024-01-02", "title": "news", "link": "https://example.com/n", "source": "FinMind"}
            ],
            "TaiwanStockDayTrading": [
                {"date": "2024-01-02", "stock_id": "2330", "day_trading_volume": 100}
            ],
            "TaiwanStockHoldingSharesPer": [
                {"date": "2024-01-05", "stock_id": "2330", "HoldingSharesLevel": "1-999"}
            ],
            "TaiwanStockIndustryIndex": [
                {"date": "2024-01-02", "index_name": "半導體", "close": 100}
            ],
            "TaiwanStockInfo": [
                {"stock_id": "2330", "stock_name": "台積電", "type": "twse"},
                {"stock_id": "6488", "stock_name": "環球晶", "type": "tpex"},
            ],
        }
        return {"status": 200, "data": payloads.get(dataset, [])}

    def fake_yf_download(ticker: str, start: str):
        return pd.DataFrame(
            {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [100]},
            index=pd.to_datetime(["2020-01-02"]),
        )

    report = probe_data_sources.run_probe(
        token="SECRET_TOKEN",
        finmind_get=fake_finmind_get,
        yf_download=fake_yf_download,
        symbol="2330",
    )
    probe_data_sources.write_reports(report, tmp_path, token="SECRET_TOKEN")

    data = json.loads((tmp_path / "availability_report.json").read_text(encoding="utf-8"))
    md = (tmp_path / "availability_report.md").read_text(encoding="utf-8")

    assert data["dataset_catalog_available"] is True
    assert any(row["dataset"] == "TaiwanStockNews" and row["available"] for row in data["results"])
    assert any(row["dataset"] == "^SOX" and row["available"] for row in data["results"])
    assert "TaiwanStockNews" in md
    assert "SECRET_TOKEN" not in md


def test_token_never_appears_in_report_or_markdown(tmp_path):
    report = {
        "generated_at": "2026-01-01",
        "sample_symbol": "2330",
        "token": "SECRET_TOKEN",
        "results": [
            {
                "source": "x",
                "dataset": "TaiwanStockNews",
                "available": False,
                "earliest_date": None,
                "cadence": "event",
                "fields": ["date"],
                "pit_usable": False,
                "notes": "request used SECRET_TOKEN",
                "recommendation": "limited",
            }
        ],
    }

    probe_data_sources.write_reports(report, tmp_path, token="SECRET_TOKEN")

    raw_json = (tmp_path / "availability_report.json").read_text(encoding="utf-8")
    raw_md = (tmp_path / "availability_report.md").read_text(encoding="utf-8")
    assert "SECRET_TOKEN" not in raw_json
    assert "SECRET_TOKEN" not in raw_md
    assert "token" not in raw_json.lower()
