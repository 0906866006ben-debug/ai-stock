from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore
from backend.scripts import download_fundamentals


def test_dated_tables_as_of_are_point_in_time(tmp_path: Path):
    store = PitFundamentalsStore(tmp_path / "pit.db")
    store.upsert_month_revenue(
        [
            {"stock_id": "2330", "date": "2024-01-31", "revenue": 100.0},
            {"stock_id": "2330", "date": "2024-02-29", "revenue": 200.0},
        ]
    )
    store.upsert_institutional(
        [
            {"stock_id": "2330", "date": "2024-01-02", "foreign_net": 10.0},
            {"stock_id": "2330", "date": "2024-01-03", "foreign_net": 20.0},
        ]
    )
    store.upsert_margin(
        [
            {"stock_id": "2330", "date": "2024-01-02", "margin_balance": 1000.0},
            {"stock_id": "2330", "date": "2024-01-04", "margin_balance": 4000.0},
        ]
    )
    store.upsert_per(
        [
            {"stock_id": "2330", "date": "2024-01-02", "per": 15.0},
            {"stock_id": "2330", "date": "2024-01-05", "per": 25.0},
        ]
    )

    assert store.get_month_revenue_as_of("2330", "2024-02-01")["date"].tolist() == ["2024-01-31"]
    assert store.get_institutional_as_of("2330", "2024-01-02")["foreign_net"].tolist() == [10.0]
    assert store.get_margin_as_of("2330", "2024-01-03")["margin_balance"].tolist() == [1000.0]
    assert store.get_per_as_of("2330", "2024-01-04")["per"].tolist() == [15.0]


def test_financials_use_filing_date_not_period_end(tmp_path: Path):
    store = PitFundamentalsStore(tmp_path / "pit.db")
    store.upsert_financials(
        [
            {
                "stock_id": "2330",
                "period_end": "2024-03-31",
                "filing_date": "2024-05-15",
                "eps": 8.0,
            }
        ]
    )

    assert store.get_financials_as_of("2330", "2024-04-30").empty
    visible = store.get_financials_as_of("2330", "2024-05-15")
    assert visible["eps"].tolist() == [8.0]


def test_financials_missing_filing_date_derives_tw_deadline(tmp_path: Path):
    store = PitFundamentalsStore(tmp_path / "pit.db")
    store.upsert_financials([{"stock_id": "2330", "period_end": "2024-12-31", "eps": 10.0}])

    assert store.get_financials_as_of("2330", "2025-03-30").empty
    visible = store.get_financials_as_of("2330", "2025-03-31")
    assert visible["filing_date"].tolist() == ["2025-03-31"]


def test_upsert_is_idempotent(tmp_path: Path):
    store = PitFundamentalsStore(tmp_path / "pit.db")
    rows = [{"stock_id": "2330", "date": "2024-01-31", "revenue": 100.0}]

    store.upsert_month_revenue(rows)
    store.upsert_month_revenue(rows)

    assert store.row_count("month_revenue") == 1


def test_backfill_script_monkeypatched_fetch_writes_expected_rows(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "pit.db"
    calls: list[tuple[str, str, str, str]] = []

    async def fake_fetch(dataset: str, data_id: str, start_date: str, token: str):
        calls.append((dataset, data_id, start_date, token))
        if dataset == "TaiwanStockMonthRevenue":
            return [{"date": "2024-01-31", "revenue": 100, "revenue_year": 0.2}]
        if dataset == "TaiwanStockInstitutionalInvestorsBuySell":
            return [{"date": "2024-01-02", "name": "Foreign_Investor", "buy": 30, "sell": 10}]
        if dataset == "TaiwanStockMarginPurchaseShortSale":
            return [{"date": "2024-01-02", "MarginPurchaseTodayBalance": 1000, "ShortSaleTodayBalance": 50}]
        if dataset == "TaiwanStockPER":
            return [{"date": "2024-01-02", "PER": 15, "PBR": 2, "dividend_yield": 3}]
        if dataset == "TaiwanStockFinancialStatements":
            return [{"date": "2024-03-31", "type": "EPS", "value": 8}]
        return []

    monkeypatch.setattr(download_fundamentals, "_fetch_with_status", fake_fetch)
    monkeypatch.setenv("FINMIND_API_KEY", "SECRET_TOKEN_DO_NOT_LOG")

    rc = download_fundamentals.main(
        [
            "--stocks",
            "2330",
            "--db",
            str(db_path),
            "--rate-limit",
            "0",
            "--start",
            "2024-01-01",
        ]
    )

    assert rc == 0
    assert len(calls) == 6  # 5 core datasets + TaiwanStockBalanceSheet
    store = PitFundamentalsStore(db_path)
    assert store.row_count("month_revenue") == 1
    assert store.row_count("institutional") == 1
    assert store.row_count("margin") == 1
    assert store.row_count("per") == 1
    assert store.row_count("financials") == 1
    assert store.get_financials_as_of("2330", "2024-05-15")["eps"].tolist() == [8.0]


def test_backfill_never_logs_token(tmp_path: Path, monkeypatch, caplog):
    token = "VERY_SECRET_FINMIND_TOKEN"

    async def fake_fetch(dataset: str, data_id: str, start_date: str, token: str):
        return [{"date": "2024-01-31", "revenue": 100}]

    monkeypatch.setattr(download_fundamentals, "_fetch_with_status", fake_fetch)
    monkeypatch.setenv("FINMIND_API_KEY", token)
    caplog.set_level(logging.INFO)

    rc = download_fundamentals.main(
        [
            "--stocks",
            "2330",
            "--datasets",
            "TaiwanStockMonthRevenue",
            "--db",
            str(tmp_path / "pit.db"),
            "--rate-limit",
            "0",
        ]
    )

    assert rc == 0
    assert token not in caplog.text


def test_schema_contains_expected_tables_and_columns(tmp_path: Path):
    db_path = tmp_path / "pit.db"
    PitFundamentalsStore(db_path)
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"month_revenue", "institutional", "margin", "per", "financials"} <= tables
        financial_cols = {row[1] for row in conn.execute("PRAGMA table_info(financials)").fetchall()}
        assert {"period_end", "filing_date", "eps", "roe", "gross_margin", "operating_margin", "net_margin"} <= financial_cols
    finally:
        conn.close()
