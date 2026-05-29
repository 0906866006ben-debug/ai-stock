from __future__ import annotations

import logging
from pathlib import Path

from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore
from backend.scripts import download_fundamentals


def test_broad_universe_source_drives_backfill_loop(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "pit.db"
    calls: list[tuple[str, str, str, str]] = []

    async def fake_fetch(dataset: str, data_id: str, start_date: str, token: str):
        calls.append((dataset, data_id, start_date, token))
        return [{"date": "2024-01-31", "revenue": 100}]

    monkeypatch.setattr(download_fundamentals, "get_tech_universe_symbols", lambda token=None: ["2330", "2454"])
    monkeypatch.setattr(download_fundamentals, "_fetch_with_status", fake_fetch)
    monkeypatch.setenv("FINMIND_API_KEY", "SECRET_TOKEN_DO_NOT_LOG")

    rc = download_fundamentals.main(
        [
            "--universe-source",
            "broad",
            "--datasets",
            "TaiwanStockMonthRevenue",
            "--db",
            str(db_path),
            "--rate-limit",
            "0",
            "--start",
            "2024-01-01",
        ]
    )

    assert rc == 0
    assert [(dataset, stock, start) for dataset, stock, start, _token in calls] == [
        ("TaiwanStockMonthRevenue", "2330", "2024-01-01"),
        ("TaiwanStockMonthRevenue", "2454", "2024-01-01"),
    ]
    assert PitFundamentalsStore(db_path).row_count("month_revenue") == 2


def test_resume_skips_existing_stock_dataset_at_or_after_start(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "pit.db"
    store = PitFundamentalsStore(db_path)
    store.upsert_month_revenue([{"stock_id": "2330", "date": "2024-01-01", "revenue": 100}])
    calls: list[tuple[str, str]] = []

    async def fake_fetch(dataset: str, data_id: str, start_date: str, token: str):
        calls.append((dataset, data_id))
        return [{"date": "2024-01-31", "revenue": 200}]

    monkeypatch.setattr(download_fundamentals, "_fetch_with_status", fake_fetch)
    monkeypatch.setenv("FINMIND_API_KEY", "SECRET_TOKEN_DO_NOT_LOG")

    rc = download_fundamentals.main(
        [
            "--stocks",
            "2330",
            "--datasets",
            "TaiwanStockMonthRevenue",
            "--db",
            str(db_path),
            "--rate-limit",
            "0",
            "--start",
            "2024-01-01",
        ]
    )

    assert rc == 0
    assert calls == []
    visible = PitFundamentalsStore(db_path).get_month_revenue_as_of("2330", "2024-02-01")
    assert visible["revenue"].tolist() == [100.0]


def test_legacy_2017_rows_do_not_skip_deeper_2010_backfill(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "pit.db"
    store = PitFundamentalsStore(db_path)
    store.upsert_month_revenue([{"stock_id": "2330", "date": "2017-01-31", "revenue": 100}])
    calls: list[tuple[str, str]] = []

    async def fake_fetch(dataset: str, data_id: str, start_date: str, token: str):
        calls.append((data_id, start_date))
        return [{"date": "2010-01-31", "revenue": 50}]

    monkeypatch.setattr(download_fundamentals, "_fetch_with_status", fake_fetch)
    monkeypatch.setenv("FINMIND_API_KEY", "SECRET_TOKEN_DO_NOT_LOG")

    rc = download_fundamentals.main(
        [
            "--stocks",
            "2330",
            "--datasets",
            "TaiwanStockMonthRevenue",
            "--db",
            str(db_path),
            "--rate-limit",
            "0",
            "--start",
            "2010-01-01",
        ]
    )

    assert rc == 0
    assert calls == [("2330", "2010-01-01")]
    visible = PitFundamentalsStore(db_path).get_month_revenue_as_of("2330", "2010-02-01")
    assert visible["revenue"].tolist() == [50.0]


def test_fetch_failure_warns_and_continues_without_mock_rows(tmp_path: Path, monkeypatch, caplog):
    db_path = tmp_path / "pit.db"
    calls: list[str] = []

    async def fake_fetch(dataset: str, data_id: str, start_date: str, token: str):
        calls.append(data_id)
        if data_id == "2330":
            raise RuntimeError("temporary FinMind failure")
        return [{"date": "2024-01-31", "revenue": 100}]

    monkeypatch.setattr(download_fundamentals, "_fetch_with_status", fake_fetch)
    monkeypatch.setenv("FINMIND_API_KEY", "SECRET_TOKEN_DO_NOT_LOG")
    caplog.set_level(logging.WARNING)

    rc = download_fundamentals.main(
        [
            "--stocks",
            "2330",
            "2454",
            "--datasets",
            "TaiwanStockMonthRevenue",
            "--db",
            str(db_path),
            "--rate-limit",
            "0",
            "--start",
            "2024-01-01",
        ]
    )

    assert rc == 0
    assert calls == ["2330", "2454"]
    assert "Fetch failed for 2330 TaiwanStockMonthRevenue" in caplog.text
    store = PitFundamentalsStore(db_path)
    assert store.row_count("month_revenue") == 1
    assert store.get_month_revenue_as_of("2330", "2024-02-01").empty
    assert store.get_month_revenue_as_of("2454", "2024-02-01")["revenue"].tolist() == [100.0]
