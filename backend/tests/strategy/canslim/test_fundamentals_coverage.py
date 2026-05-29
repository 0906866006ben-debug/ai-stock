from __future__ import annotations

from pathlib import Path

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore
from backend.scripts import download_fundamentals, report_fundamentals_coverage


def _seed_ohlcv(store: HistoricalDataStore, symbols: list[str]) -> None:
    rows = []
    for symbol in symbols:
        rows.append(
            {
                "stock_id": symbol,
                "date": "2024-01-02",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 1000,
                "turnover": 10_000,
            }
        )
    store.upsert_rows(rows)


def test_ohlcv_universe_source_uses_historical_store_list(tmp_path: Path, monkeypatch):
    ohlcv_path = tmp_path / "ohlcv.db"
    pit_path = tmp_path / "pit.db"
    _seed_ohlcv(HistoricalDataStore(ohlcv_path), ["2330", "2454"])
    calls: list[tuple[str, str, str]] = []

    async def fake_fetch(dataset: str, data_id: str, start_date: str, token: str):
        calls.append((dataset, data_id, start_date))
        return [{"date": "2024-01-31", "revenue": 100}]

    monkeypatch.setattr(download_fundamentals, "_fetch_with_status", fake_fetch)
    monkeypatch.setenv("FINMIND_API_KEY", "SECRET_TOKEN_DO_NOT_LOG")

    rc = download_fundamentals.main(
        [
            "--universe-source",
            "ohlcv",
            "--ohlcv-db",
            str(ohlcv_path),
            "--datasets",
            "TaiwanStockMonthRevenue",
            "--db",
            str(pit_path),
            "--rate-limit",
            "0",
            "--start",
            "2024-01-01",
        ]
    )

    assert rc == 0
    assert calls == [
        ("TaiwanStockMonthRevenue", "2330", "2024-01-01"),
        ("TaiwanStockMonthRevenue", "2454", "2024-01-01"),
    ]
    assert PitFundamentalsStore(pit_path).row_count("month_revenue") == 2


def test_ohlcv_universe_resume_skips_already_covered_stock_dataset(tmp_path: Path, monkeypatch):
    ohlcv_path = tmp_path / "ohlcv.db"
    pit_path = tmp_path / "pit.db"
    _seed_ohlcv(HistoricalDataStore(ohlcv_path), ["2330", "2454"])
    pit = PitFundamentalsStore(pit_path)
    pit.upsert_month_revenue([{"stock_id": "2330", "date": "2024-01-01", "revenue": 100}])
    calls: list[str] = []

    async def fake_fetch(dataset: str, data_id: str, start_date: str, token: str):
        calls.append(data_id)
        return [{"date": "2024-01-31", "revenue": 200}]

    monkeypatch.setattr(download_fundamentals, "_fetch_with_status", fake_fetch)
    monkeypatch.setenv("FINMIND_API_KEY", "SECRET_TOKEN_DO_NOT_LOG")

    rc = download_fundamentals.main(
        [
            "--universe-source",
            "ohlcv",
            "--ohlcv-db",
            str(ohlcv_path),
            "--datasets",
            "TaiwanStockMonthRevenue",
            "--db",
            str(pit_path),
            "--rate-limit",
            "0",
            "--start",
            "2024-01-01",
        ]
    )

    assert rc == 0
    assert calls == ["2454"]
    visible = PitFundamentalsStore(pit_path).get_month_revenue_as_of("2454", "2024-02-01")
    assert visible["revenue"].tolist() == [200.0]


def test_coverage_report_counts_dataset_and_fully_covered_symbols(tmp_path: Path):
    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    _seed_ohlcv(ohlcv, ["2330", "2454", "9999"])

    pit.upsert_month_revenue(
        [
            {"stock_id": "2330", "date": "2024-01-01", "revenue": 100},
            {"stock_id": "2454", "date": "2024-01-01", "revenue": 80},
        ]
    )
    pit.upsert_institutional(
        [
            {"stock_id": "2330", "date": "2024-01-02", "foreign_net": 1, "trust_net": 1, "dealer_net": 0},
        ]
    )
    pit.upsert_margin([{"stock_id": "2330", "date": "2024-01-02", "margin_balance": 100, "short_balance": 1}])
    pit.upsert_per([{"stock_id": "2330", "date": "2024-01-02", "per": 15, "pbr": 2, "dividend_yield": 1}])
    pit.upsert_financials([{"stock_id": "2330", "period_end": "2024-03-31", "filing_date": "2024-05-15", "eps": 8}])

    report = report_fundamentals_coverage.compute_coverage(ohlcv_store=ohlcv, pit_store=pit)

    assert report["ohlcv_universe_count"] == 3
    assert report["datasets"]["TaiwanStockMonthRevenue"]["covered_symbols"] == 2
    assert report["datasets"]["TaiwanStockFinancialStatements"]["covered_symbols"] == 1
    assert report["fully_covered_count"] == 1
    assert report["fully_covered_symbols"] == ["2330"]
    assert report["no_fundamentals_symbols"] == ["9999"]


def test_coverage_report_writes_markdown_and_json(tmp_path: Path):
    ohlcv = HistoricalDataStore(tmp_path / "ohlcv.db")
    pit = PitFundamentalsStore(tmp_path / "pit.db")
    _seed_ohlcv(ohlcv, ["2330"])

    report = report_fundamentals_coverage.compute_coverage(ohlcv_store=ohlcv, pit_store=pit)
    md_path, json_path = report_fundamentals_coverage.write_reports(report, tmp_path / "out")

    assert md_path.exists()
    assert json_path.exists()
    assert "PIT Fundamentals Coverage" in md_path.read_text(encoding="utf-8")
