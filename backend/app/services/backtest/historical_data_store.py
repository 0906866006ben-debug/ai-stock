"""SQLite-backed OHLCV cache for point-in-time backtest replay.

Why SQLite (not parquet/csv):
- Index on (stock_id, date) gives O(log n) point-in-time queries
- Single file, no schema migrations needed
- Easy to backup / share

Schema:
    ohlcv(stock_id TEXT, date TEXT, open REAL, high REAL, low REAL,
          close REAL, volume INT, turnover REAL,
          PRIMARY KEY (stock_id, date))

Usage:
    store = HistoricalDataStore()
    store.upsert_rows(rows)  # batch insert/update
    df = store.get_ohlcv("2330", "2024-01-01", "2024-06-30")

Speedup layer:
    CachedHistoricalDataStore pre-loads the full universe OHLCV into RAM,
    serving the same interface but turning per-call SQLite queries into
    in-memory slicing. Use it when running the optimizer (many trials over
    the same data) — drops ~24k DB roundtrips per trial.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Optional

import pandas as pd


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "historical_data.db"


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ohlcv (
    stock_id TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    turnover REAL,
    PRIMARY KEY (stock_id, date)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv(date);
CREATE INDEX IF NOT EXISTS idx_ohlcv_stock ON ohlcv(stock_id);
"""


class HistoricalDataStore:
    """Thin wrapper around SQLite for OHLCV history. Thread-safe via per-call connection."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
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
            conn.executescript(_SCHEMA_SQL)

    # ── Write paths ─────────────────────────────────────────────────────────

    def upsert_rows(self, rows: Iterable[dict]) -> int:
        """Bulk INSERT OR REPLACE for OHLCV rows.

        Each row dict must have: stock_id, date (YYYY-MM-DD), open, high, low,
        close, volume, turnover.
        Returns count of rows written.
        """
        rows = list(rows)
        if not rows:
            return 0
        sql = """
            INSERT OR REPLACE INTO ohlcv
              (stock_id, date, open, high, low, close, volume, turnover)
            VALUES (:stock_id, :date, :open, :high, :low, :close, :volume, :turnover)
        """
        with self._connect() as conn:
            conn.executemany(sql, rows)
        return len(rows)

    # ── Read paths ──────────────────────────────────────────────────────────

    def get_ohlcv(
        self,
        stock_id: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Returns DataFrame with index=date (string), columns=open/high/low/close/volume/turnover."""
        sql = """
            SELECT date, open, high, low, close, volume, turnover
            FROM ohlcv
            WHERE stock_id = ? AND date >= ? AND date <= ?
            ORDER BY date ASC
        """
        with self._connect() as conn:
            df = pd.read_sql_query(sql, conn, params=(stock_id, start_date, end_date))
        return df

    def get_ohlcv_as_of(
        self,
        stock_id: str,
        as_of_date: str,
        lookback_bars: int,
    ) -> pd.DataFrame:
        """Returns the most recent N bars on or before `as_of_date`. POINT-IN-TIME safe."""
        sql = """
            SELECT date, open, high, low, close, volume, turnover
            FROM ohlcv
            WHERE stock_id = ? AND date <= ?
            ORDER BY date DESC
            LIMIT ?
        """
        with self._connect() as conn:
            df = pd.read_sql_query(sql, conn, params=(stock_id, as_of_date, lookback_bars))
        return df.iloc[::-1].reset_index(drop=True)  # reverse to chronological order

    def get_available_dates(self, stock_id: str) -> list[str]:
        sql = "SELECT DISTINCT date FROM ohlcv WHERE stock_id = ? ORDER BY date ASC"
        with self._connect() as conn:
            cursor = conn.execute(sql, (stock_id,))
            return [row[0] for row in cursor.fetchall()]

    def get_all_trading_dates(self, start_date: str, end_date: str) -> list[str]:
        """Union of all trading dates across all stocks within range."""
        sql = """
            SELECT DISTINCT date FROM ohlcv
            WHERE date >= ? AND date <= ?
            ORDER BY date ASC
        """
        with self._connect() as conn:
            cursor = conn.execute(sql, (start_date, end_date))
            return [row[0] for row in cursor.fetchall()]

    def list_stocks(self) -> list[str]:
        sql = "SELECT DISTINCT stock_id FROM ohlcv ORDER BY stock_id"
        with self._connect() as conn:
            cursor = conn.execute(sql)
            return [row[0] for row in cursor.fetchall()]

    def get_latest_date(self, stock_id: str) -> Optional[str]:
        sql = "SELECT MAX(date) FROM ohlcv WHERE stock_id = ?"
        with self._connect() as conn:
            row = conn.execute(sql, (stock_id,)).fetchone()
        return row[0] if row and row[0] else None

    def row_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()
        return row[0] if row else 0


# ───────────────────────────────────────────────────────────────────────────
# In-memory cached store — used by the backtest optimizer to avoid hammering
# SQLite. Drop-in replacement for HistoricalDataStore (same read API).
# ───────────────────────────────────────────────────────────────────────────

class CachedHistoricalDataStore:
    """Pre-loads OHLCV for a fixed universe into RAM; serves reads from memory.

    Use this when you need to query many (stock, date) combinations against the
    same fixed universe + date range — e.g. running 30 optimizer trials over
    800 trading days × 30 stocks (= 24k point-in-time queries per trial).
    """

    def __init__(
        self,
        db_path: Path | str,
        universe: list[str],
        start_date: str,
        end_date: str,
        lookback_buffer_days: int = 365,
        forward_buffer_days: int = 90,
    ) -> None:
        """Load OHLCV for `universe` covering [start_date - lookback, end_date + forward].

        - lookback_buffer_days: extra history before start_date (for indicator warm-up)
        - forward_buffer_days: extra history after end_date (for trade exit simulation)
        """
        self.db_path = Path(db_path)
        self._underlying = HistoricalDataStore(db_path)
        self.start_date = start_date
        self.end_date = end_date

        # Widen the window to cover indicator warm-up + future exit simulation.
        load_start = (pd.Timestamp(start_date) - pd.Timedelta(days=lookback_buffer_days)).strftime("%Y-%m-%d")
        load_end = (pd.Timestamp(end_date) + pd.Timedelta(days=forward_buffer_days)).strftime("%Y-%m-%d")

        # Pull each stock once. Index by date (string YYYY-MM-DD) — pandas .loc
        # accepts string slicing if the index is sorted.
        self._frames: dict[str, pd.DataFrame] = {}
        for stock_id in universe:
            df = self._underlying.get_ohlcv(stock_id, load_start, load_end)
            if df.empty:
                continue
            # Keep date column AS a sorted index so .loc[:as_of] works in O(log n)
            df = df.sort_values("date").reset_index(drop=True)
            df.index = pd.Index(df["date"].values, name="date_idx")
            self._frames[stock_id] = df

        # Pre-compute trading dates set across universe for get_all_trading_dates.
        all_dates: set[str] = set()
        for df in self._frames.values():
            all_dates.update(df["date"].tolist())
        self._sorted_dates: list[str] = sorted(all_dates)

    # ── Read paths (same interface as HistoricalDataStore) ──────────────────

    def get_ohlcv_as_of(self, stock_id: str, as_of_date: str, lookback_bars: int) -> pd.DataFrame:
        """Latest N bars on or before as_of_date. Point-in-time safe."""
        df = self._frames.get(stock_id)
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        # df.index is sorted dates; slice up to as_of_date inclusive, take last N.
        sliced = df.loc[df.index <= as_of_date]
        if sliced.empty:
            return pd.DataFrame(columns=df.columns)
        result = sliced.tail(lookback_bars).reset_index(drop=True)
        return result

    def get_ohlcv(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Date-range slice. Same shape as HistoricalDataStore.get_ohlcv."""
        df = self._frames.get(stock_id)
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        mask = (df.index >= start_date) & (df.index <= end_date)
        return df.loc[mask].reset_index(drop=True)

    def get_all_trading_dates(self, start_date: str, end_date: str) -> list[str]:
        # Linear filter is fine; usually <2000 dates.
        return [d for d in self._sorted_dates if start_date <= d <= end_date]

    def list_stocks(self) -> list[str]:
        return sorted(self._frames.keys())

    def get_latest_date(self, stock_id: str) -> Optional[str]:
        df = self._frames.get(stock_id)
        if df is None or df.empty:
            return None
        return str(df.index[-1])

    # ── Pass-through for write paths (rare, only when downloader is running) ──

    def upsert_rows(self, rows: Iterable[dict]) -> int:
        # Writes invalidate the cache — but the optimizer is read-only, so we
        # delegate to the underlying store without refreshing cache.
        return self._underlying.upsert_rows(rows)

    def row_count(self) -> int:
        return sum(len(df) for df in self._frames.values())
