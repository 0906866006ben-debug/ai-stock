"""Point-in-time fundamentals/chip history store for backtests.

This store mirrors HistoricalDataStore's SQLite pattern but keeps dated
fundamental and chip datasets. Financial statement PIT reads are gated by
filing_date, never by period_end, to avoid look-ahead leakage.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from backend.app.services.tw_calendar import _quarter_deadline


DEFAULT_PIT_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "pit_fundamentals.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS month_revenue (
    stock_id TEXT NOT NULL,
    date TEXT NOT NULL,
    revenue REAL,
    revenue_yoy REAL,
    revenue_mom REAL,
    raw_json TEXT,
    PRIMARY KEY (stock_id, date)
);
CREATE TABLE IF NOT EXISTS institutional (
    stock_id TEXT NOT NULL,
    date TEXT NOT NULL,
    foreign_net REAL,
    trust_net REAL,
    dealer_net REAL,
    raw_json TEXT,
    PRIMARY KEY (stock_id, date)
);
CREATE TABLE IF NOT EXISTS margin (
    stock_id TEXT NOT NULL,
    date TEXT NOT NULL,
    margin_balance REAL,
    short_balance REAL,
    raw_json TEXT,
    PRIMARY KEY (stock_id, date)
);
CREATE TABLE IF NOT EXISTS per (
    stock_id TEXT NOT NULL,
    date TEXT NOT NULL,
    per REAL,
    pbr REAL,
    dividend_yield REAL,
    raw_json TEXT,
    PRIMARY KEY (stock_id, date)
);
CREATE TABLE IF NOT EXISTS financials (
    stock_id TEXT NOT NULL,
    period_end TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    eps REAL,
    roe REAL,
    gross_margin REAL,
    operating_margin REAL,
    net_margin REAL,
    raw_json TEXT,
    PRIMARY KEY (stock_id, period_end)
);
CREATE TABLE IF NOT EXISTS balance_sheet (
    stock_id TEXT NOT NULL,
    period_end TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    equity REAL,
    equity_parent REAL,
    raw_json TEXT,
    PRIMARY KEY (stock_id, period_end)
);
CREATE INDEX IF NOT EXISTS idx_month_revenue_date ON month_revenue(stock_id, date);
CREATE INDEX IF NOT EXISTS idx_institutional_date ON institutional(stock_id, date);
CREATE INDEX IF NOT EXISTS idx_margin_date ON margin(stock_id, date);
CREATE INDEX IF NOT EXISTS idx_per_date ON per(stock_id, date);
CREATE INDEX IF NOT EXISTS idx_financials_filing ON financials(stock_id, filing_date);
CREATE INDEX IF NOT EXISTS idx_balance_sheet_filing ON balance_sheet(stock_id, filing_date);
"""


class PitFundamentalsStore:
    """SQLite-backed PIT fundamentals store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_PIT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.executescript(_SCHEMA_SQL)

    def upsert_month_revenue(self, rows: Iterable[dict]) -> int:
        return self._upsert(
            "month_revenue",
            rows,
            ("stock_id", "date", "revenue", "revenue_yoy", "revenue_mom", "raw_json"),
        )

    def upsert_institutional(self, rows: Iterable[dict]) -> int:
        return self._upsert(
            "institutional",
            rows,
            ("stock_id", "date", "foreign_net", "trust_net", "dealer_net", "raw_json"),
        )

    def upsert_margin(self, rows: Iterable[dict]) -> int:
        return self._upsert(
            "margin",
            rows,
            ("stock_id", "date", "margin_balance", "short_balance", "raw_json"),
        )

    def upsert_per(self, rows: Iterable[dict]) -> int:
        return self._upsert(
            "per",
            rows,
            ("stock_id", "date", "per", "pbr", "dividend_yield", "raw_json"),
        )

    def upsert_financials(self, rows: Iterable[dict]) -> int:
        prepared = []
        for row in rows:
            item = dict(row)
            if not item.get("filing_date"):
                item["filing_date"] = derive_filing_date(str(item["period_end"]))
            prepared.append(item)
        return self._upsert(
            "financials",
            prepared,
            (
                "stock_id",
                "period_end",
                "filing_date",
                "eps",
                "roe",
                "gross_margin",
                "operating_margin",
                "net_margin",
                "raw_json",
            ),
        )

    def get_month_revenue_as_of(self, stock_id: str, as_of_date: str, limit: int = 12) -> pd.DataFrame:
        return self._get_dated_as_of("month_revenue", stock_id, as_of_date, limit)

    def get_institutional_as_of(self, stock_id: str, as_of_date: str, limit: int = 20) -> pd.DataFrame:
        return self._get_dated_as_of("institutional", stock_id, as_of_date, limit)

    def get_margin_as_of(self, stock_id: str, as_of_date: str, limit: int = 20) -> pd.DataFrame:
        return self._get_dated_as_of("margin", stock_id, as_of_date, limit)

    def get_per_as_of(self, stock_id: str, as_of_date: str, limit: int = 20) -> pd.DataFrame:
        return self._get_dated_as_of("per", stock_id, as_of_date, limit)

    def get_financials_as_of(self, stock_id: str, as_of_date: str, limit: int = 8) -> pd.DataFrame:
        sql = """
            SELECT *
            FROM financials
            WHERE stock_id = ? AND filing_date <= ?
            ORDER BY period_end DESC
            LIMIT ?
        """
        with self._connect() as conn:
            df = pd.read_sql_query(sql, conn, params=(stock_id, as_of_date, limit))
        return df.iloc[::-1].reset_index(drop=True)

    def get_balance_sheet_as_of(self, stock_id: str, as_of_date: str, limit: int = 8) -> pd.DataFrame:
        sql = """
            SELECT *
            FROM balance_sheet
            WHERE stock_id = ? AND filing_date <= ?
            ORDER BY period_end DESC
            LIMIT ?
        """
        with self._connect() as conn:
            df = pd.read_sql_query(sql, conn, params=(stock_id, as_of_date, limit))
        return df.iloc[::-1].reset_index(drop=True)

    def upsert_balance_sheet(self, rows: Iterable[dict]) -> int:
        prepared = []
        for row in rows:
            item = dict(row)
            if not item.get("filing_date"):
                item["filing_date"] = derive_filing_date(str(item["period_end"]))
            prepared.append(item)
        return self._upsert(
            "balance_sheet",
            prepared,
            ("stock_id", "period_end", "filing_date", "equity", "equity_parent", "raw_json"),
        )

    def row_count(self, table: str) -> int:
        if table not in {"month_revenue", "institutional", "margin", "per", "financials", "balance_sheet"}:
            raise ValueError(f"Unknown table: {table}")
        with self._connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0

    def _upsert(self, table: str, rows: Iterable[dict], columns: tuple[str, ...]) -> int:
        rows = [{col: row.get(col) for col in columns} for row in rows]
        if not rows:
            return 0
        placeholders = ", ".join(f":{col}" for col in columns)
        col_sql = ", ".join(columns)
        sql = f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})"
        with self._connect() as conn:
            conn.executemany(sql, rows)
        return len(rows)

    def _get_dated_as_of(self, table: str, stock_id: str, as_of_date: str, limit: int) -> pd.DataFrame:
        sql = f"""
            SELECT *
            FROM {table}
            WHERE stock_id = ? AND date <= ?
            ORDER BY date DESC
            LIMIT ?
        """
        with self._connect() as conn:
            df = pd.read_sql_query(sql, conn, params=(stock_id, as_of_date, limit))
        return df.iloc[::-1].reset_index(drop=True)


class CachedPitFundamentalsStore:
    """In-memory read cache for PIT fundamentals/chip datasets."""

    _TABLES = ("month_revenue", "institutional", "margin", "per", "financials", "balance_sheet")
    _PERIOD_TABLES = ("financials", "balance_sheet")

    def __init__(self, db_path: Path | str, universe: list[str] | None = None) -> None:
        self.db_path = Path(db_path)
        self._underlying = PitFundamentalsStore(db_path)
        self._frames: dict[str, dict[str, pd.DataFrame]] = {table: {} for table in self._TABLES}
        stock_filter = set(str(stock) for stock in universe) if universe else None
        with self._underlying._connect() as conn:
            for table in self._TABLES:
                sort_col = "filing_date" if table in self._PERIOD_TABLES else "date"
                # Read in chunks and keep only universe rows per chunk, so a bounded
                # universe never materializes the whole (multi-GB) table in RAM. On a
                # small-RAM host an unfiltered SELECT * of a large table OOMs.
                parts: list[pd.DataFrame] = []
                for chunk in pd.read_sql_query(f"SELECT * FROM {table}", conn, chunksize=200_000):
                    if stock_filter is not None and not chunk.empty:
                        chunk = chunk[chunk["stock_id"].astype(str).isin(stock_filter)]
                    if not chunk.empty:
                        parts.append(chunk)
                if not parts:
                    continue
                df = pd.concat(parts, ignore_index=True)
                for stock_id, frame in df.groupby("stock_id", sort=False):
                    frame = frame.sort_values(sort_col).reset_index(drop=True)
                    self._frames[table][str(stock_id)] = frame

    def get_month_revenue_as_of(self, stock_id: str, as_of_date: str, limit: int = 12) -> pd.DataFrame:
        return self._get_dated_as_of("month_revenue", stock_id, as_of_date, limit)

    def get_institutional_as_of(self, stock_id: str, as_of_date: str, limit: int = 20) -> pd.DataFrame:
        return self._get_dated_as_of("institutional", stock_id, as_of_date, limit)

    def get_margin_as_of(self, stock_id: str, as_of_date: str, limit: int = 20) -> pd.DataFrame:
        return self._get_dated_as_of("margin", stock_id, as_of_date, limit)

    def get_per_as_of(self, stock_id: str, as_of_date: str, limit: int = 20) -> pd.DataFrame:
        return self._get_dated_as_of("per", stock_id, as_of_date, limit)

    def get_financials_as_of(self, stock_id: str, as_of_date: str, limit: int = 8) -> pd.DataFrame:
        return self._get_period_as_of("financials", stock_id, as_of_date, limit)

    def get_balance_sheet_as_of(self, stock_id: str, as_of_date: str, limit: int = 8) -> pd.DataFrame:
        return self._get_period_as_of("balance_sheet", stock_id, as_of_date, limit)

    def _get_period_as_of(self, table: str, stock_id: str, as_of_date: str, limit: int) -> pd.DataFrame:
        frame = self._frames[table].get(str(stock_id))
        if frame is None or frame.empty:
            return pd.DataFrame()
        filtered = frame[frame["filing_date"] <= as_of_date].sort_values("period_end").tail(limit)
        return filtered.reset_index(drop=True)

    def _get_dated_as_of(self, table: str, stock_id: str, as_of_date: str, limit: int) -> pd.DataFrame:
        frame = self._frames[table].get(str(stock_id))
        if frame is None or frame.empty:
            return pd.DataFrame()
        filtered = frame[frame["date"] <= as_of_date].tail(limit)
        return filtered.reset_index(drop=True)


def derive_filing_date(period_end: str) -> str:
    parsed = datetime.strptime(period_end[:10], "%Y-%m-%d").date()
    quarter = (parsed.month - 1) // 3 + 1
    return _quarter_deadline(parsed.year, quarter).strftime("%Y-%m-%d")
