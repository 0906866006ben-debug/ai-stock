from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.app.models.quality_snapshot import QualityWatchHistoryItem, QuarterlySnapshot


DEFAULT_QUALITY_SNAPSHOT_DB = Path(__file__).resolve().parents[2] / "data" / "quality_snapshots.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS quality_snapshots (
    quarter TEXT PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    symbols_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_snapshots_generated_at ON quality_snapshots(generated_at);
"""


class QualitySnapshotStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_QUALITY_SNAPSHOT_DB
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

    def write_snapshot(self, snapshot: QuarterlySnapshot) -> None:
        payload = snapshot.model_dump(mode="json")
        symbols = [stock.symbol for stock in snapshot.snapshot_stocks]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_snapshots
                    (quarter, as_of_date, generated_at, snapshot_json, symbols_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.quarter,
                    snapshot.as_of_date,
                    snapshot.generated_at,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(symbols, ensure_ascii=False),
                ),
            )

    def read_snapshot(self, quarter: str) -> QuarterlySnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT snapshot_json FROM quality_snapshots WHERE quarter = ?",
                (quarter,),
            ).fetchone()
        if row is None:
            return None
        return QuarterlySnapshot(**json.loads(row["snapshot_json"]))

    def get_latest_snapshot(self) -> QuarterlySnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT snapshot_json
                FROM quality_snapshots
                ORDER BY as_of_date DESC, generated_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return QuarterlySnapshot(**json.loads(row["snapshot_json"]))

    def list_quarters(self) -> list[QualityWatchHistoryItem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT quarter, as_of_date, generated_at, snapshot_json
                FROM quality_snapshots
                ORDER BY as_of_date DESC, generated_at DESC
                """
            ).fetchall()
        out: list[QualityWatchHistoryItem] = []
        for row in rows:
            payload = json.loads(row["snapshot_json"])
            out.append(QualityWatchHistoryItem(
                quarter=str(row["quarter"]),
                as_of_date=str(row["as_of_date"]),
                generated_at=str(row["generated_at"]),
                stock_count=len(payload.get("snapshot_stocks") or []),
            ))
        return out
