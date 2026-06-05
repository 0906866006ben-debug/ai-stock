from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

from backend.app.db.sqlite_utils import get_indexes, get_table_info, safe_create_index


migration = importlib.import_module("backend.app.db.migrations.001_sqlite_indexes")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _create_minimal_historical_db(path: Path) -> None:
    with _connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE ohlcv (
                stock_id TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                turnover REAL,
                PRIMARY KEY (stock_id, date)
            )
            """
        )
        conn.executemany(
            "INSERT INTO ohlcv (stock_id, date, close) VALUES (?, ?, ?)",
            [("2330", "2024-01-01", 100.0), ("2330", "2024-01-02", 101.0)],
        )


def _create_minimal_pit_db(path: Path) -> None:
    with _connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE month_revenue (
                stock_id TEXT NOT NULL, date TEXT NOT NULL, revenue REAL,
                revenue_yoy REAL, revenue_mom REAL, raw_json TEXT,
                PRIMARY KEY (stock_id, date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE institutional (
                stock_id TEXT NOT NULL, date TEXT NOT NULL, foreign_net REAL,
                trust_net REAL, dealer_net REAL, raw_json TEXT,
                PRIMARY KEY (stock_id, date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE margin (
                stock_id TEXT NOT NULL, date TEXT NOT NULL, margin_balance REAL,
                short_balance REAL, raw_json TEXT,
                PRIMARY KEY (stock_id, date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE per (
                stock_id TEXT NOT NULL, date TEXT NOT NULL, per REAL,
                pbr REAL, dividend_yield REAL, raw_json TEXT,
                PRIMARY KEY (stock_id, date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE financials (
                stock_id TEXT NOT NULL, period_end TEXT NOT NULL, filing_date TEXT NOT NULL,
                eps REAL, roe REAL, gross_margin REAL, operating_margin REAL,
                net_margin REAL, raw_json TEXT,
                PRIMARY KEY (stock_id, period_end)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE balance_sheet (
                stock_id TEXT NOT NULL, period_end TEXT NOT NULL, filing_date TEXT NOT NULL,
                equity REAL, equity_parent REAL, raw_json TEXT,
                PRIMARY KEY (stock_id, period_end)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE cash_flow (
                stock_id TEXT NOT NULL, period_end TEXT NOT NULL, filing_date TEXT NOT NULL,
                cfo REAL, raw_json TEXT,
                PRIMARY KEY (stock_id, period_end)
            )
            """
        )
        conn.execute("INSERT INTO institutional (stock_id, date, foreign_net) VALUES ('2330', '2024-01-02', 1)")
        conn.execute("INSERT INTO financials (stock_id, period_end, filing_date, eps) VALUES ('2330', '2023-12-31', '2024-03-31', 10)")


def _create_minimal_stock_master_db(path: Path) -> None:
    with _connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE stock_master (
                stock_code TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                market_type TEXT,
                industry TEXT,
                source TEXT,
                raw_json TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO stock_master
                (stock_code, company_name, market_type, industry, source, updated_at)
            VALUES ('2330', 'TSMC', '上市', '半導體', 'test', '2024-01-01')
            """
        )


def _row_count(path: Path, table: str) -> int:
    with _connect(path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_safe_create_index_skips_missing_table_and_column(tmp_path: Path):
    db_path = tmp_path / "missing.db"
    with _connect(db_path) as conn:
        conn.execute("CREATE TABLE ohlcv (stock_id TEXT)")

        missing_table = safe_create_index(conn, "idx_missing_table", "not_there", ("stock_id",))
        missing_column = safe_create_index(conn, "idx_missing_column", "ohlcv", ("date",))

    assert missing_table["status"] == "skipped_missing_table"
    assert missing_column["status"] == "skipped_missing_column"


def test_migration_is_idempotent_and_preserves_rows_and_json_cache(tmp_path: Path):
    historical = tmp_path / "historical.db"
    pit = tmp_path / "pit.db"
    stock_master = tmp_path / "stock_master.db"
    cache_file = tmp_path / "cache" / "analysis.json"
    cache_file.parent.mkdir()
    cache_file.write_text('{"ok": true}', encoding="utf-8")

    _create_minimal_historical_db(historical)
    _create_minimal_pit_db(pit)
    _create_minimal_stock_master_db(stock_master)
    before = {
        "ohlcv": _row_count(historical, "ohlcv"),
        "institutional": _row_count(pit, "institutional"),
        "financials": _row_count(pit, "financials"),
        "stock_master": _row_count(stock_master, "stock_master"),
    }

    paths = {"historical": historical, "pit": pit, "stock_master": stock_master}
    first = migration.migrate(paths)
    second = migration.migrate(paths)

    after = {
        "ohlcv": _row_count(historical, "ohlcv"),
        "institutional": _row_count(pit, "institutional"),
        "financials": _row_count(pit, "financials"),
        "stock_master": _row_count(stock_master, "stock_master"),
    }
    assert before == after
    assert cache_file.exists()
    assert any(result["status"] == "created" for result in first)
    assert all(result["status"] != "error" for result in first + second)
    assert any(result["status"] == "skipped_existing_equivalent" for result in second)


def test_sqlite_audit_helpers_read_schema_and_indexes(tmp_path: Path):
    db_path = tmp_path / "audit.db"
    _create_minimal_historical_db(db_path)
    with _connect(db_path) as conn:
        info = get_table_info(conn, "ohlcv")
        created = safe_create_index(conn, "idx_ohlcv_date_stock", "ohlcv", ("date", "stock_id"))
        indexes = get_indexes(conn, "ohlcv")

    assert [row["name"] for row in info] == [
        "stock_id",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
    ]
    assert created["status"] == "created"
    assert any(index["columns"][:2] == ["date", "stock_id"] for index in indexes)


def test_existing_backtest_service_imports():
    module = importlib.import_module("backend.app.services.backtest.historical_data_store")
    assert hasattr(module, "HistoricalDataStore")


def test_fastapi_app_imports_without_db_migration_side_effects():
    module = importlib.import_module("backend.app.main")
    assert module.app.title == "AI Stock Analysis API"

