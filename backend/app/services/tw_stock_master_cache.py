"""Persistent Taiwan stock master cache.

This keeps stock code/name/market/industry metadata on disk so app restarts do
not force a fresh exchange/FinMind universe request before the directory can
render.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


DEFAULT_STOCK_MASTER_DB = Path(__file__).resolve().parents[2] / "data" / "stock_master.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stock_master (
    stock_code TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    market_type TEXT,
    industry TEXT,
    source TEXT,
    raw_json TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stock_master_market ON stock_master(market_type);
CREATE INDEX IF NOT EXISTS idx_stock_master_industry ON stock_master(industry);
CREATE TABLE IF NOT EXISTS stock_master_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class StockMasterSnapshot:
    stocks: list[dict]
    updated_at: str | None
    source: str
    is_stale: bool


class StockMasterCache:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_STOCK_MASTER_DB
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
            conn.executescript(_SCHEMA_SQL)

    def write_stocks(self, stocks: list[dict], *, source: str) -> int:
        if not stocks:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for stock in stocks:
            code = str(stock.get("stock_code") or stock.get("stock_id") or "").strip()
            if not code:
                continue
            item = {
                "stock_code": code,
                "company_name": str(stock.get("company_name") or stock.get("stock_name") or code),
                "market_type": stock.get("market_type"),
                "industry": stock.get("industry"),
                "source": stock.get("source") or source,
                "raw_json": json.dumps(stock, ensure_ascii=False, sort_keys=True),
                "updated_at": now,
            }
            rows.append(item)
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO stock_master
                    (stock_code, company_name, market_type, industry, source, raw_json, updated_at)
                VALUES
                    (:stock_code, :company_name, :market_type, :industry, :source, :raw_json, :updated_at)
                """,
                rows,
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO stock_master_meta (key, value)
                VALUES ('last_refresh_at', ?), ('source', ?)
                """,
                (now, source),
            )
        return len(rows)

    def read_snapshot(self, *, max_age_seconds: int | None = None) -> StockMasterSnapshot | None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT stock_code, company_name, market_type, industry, source, raw_json, updated_at
                FROM stock_master
                ORDER BY stock_code ASC
                """
            ).fetchall()
            meta_rows = conn.execute("SELECT key, value FROM stock_master_meta").fetchall()
        if not rows:
            return None
        meta = {str(row["key"]): str(row["value"]) for row in meta_rows}
        updated_at = meta.get("last_refresh_at") or str(rows[0]["updated_at"])
        source = meta.get("source") or "stock_master_cache"
        is_stale = False
        if max_age_seconds is not None:
            try:
                refreshed = datetime.fromisoformat(updated_at)
                if refreshed.tzinfo is None:
                    refreshed = refreshed.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - refreshed).total_seconds()
                is_stale = age > max_age_seconds
            except Exception:
                is_stale = True
        stocks = [
            {
                "stock_code": str(row["stock_code"]),
                "company_name": str(row["company_name"]),
                "market_type": row["market_type"],
                "industry": row["industry"],
                "source": row["source"] or source,
            }
            for row in rows
        ]
        return StockMasterSnapshot(stocks=stocks, updated_at=updated_at, source=source, is_stale=is_stale)
