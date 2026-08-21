from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .schemas import DataAssetSummary, DataTier, IntervalCoverage


def _utc_from_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]).lower()
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def inspect_crypto_sqlite(path: Path, *, now: datetime | None = None) -> DataAssetSummary:
    now = now or datetime.now(timezone.utc)
    warnings: list[str] = []
    if not path.exists():
        raise FileNotFoundError(f"market data store not found: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"market data store is empty: {path}")

    with _connect_read_only(path) as conn:
        tables = _table_names(conn)
        if "klines" not in tables:
            raise ValueError("market data store has no klines table")

        intervals = [
            IntervalCoverage(
                interval=str(row[0]),
                rows=int(row[1]),
                start_at=_utc_from_ms(row[2]),
                end_at=_utc_from_ms(row[3]),
                symbols=int(row[4]),
            )
            for row in conn.execute(
                "SELECT itv, COUNT(*), MIN(open_ms), MAX(open_ms), COUNT(DISTINCT sym) "
                "FROM klines GROUP BY itv ORDER BY itv"
            )
        ]

        funding_rows = funding_symbols = 0
        funding_start = funding_end = None
        if "funding" in tables:
            row = conn.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts), COUNT(DISTINCT sym) FROM funding"
            ).fetchone()
            funding_rows = int(row[0])
            funding_start = _utc_from_ms(row[1])
            funding_end = _utc_from_ms(row[2])
            funding_symbols = int(row[3])

        sample = conn.execute(
            "SELECT o, h, l, c, v, qv FROM klines ORDER BY rowid DESC LIMIT 10000"
        ).fetchall()
        violations = sum(
            1
            for o, h, low, c, v, qv in sample
            if low > min(o, c) or h < max(o, c) or h < low or v < 0 or qv < 0
        )

    oi_available = bool(tables & {"open_interest", "oi", "oi_history", "open_interest_history"})
    premium_available = bool(tables & {"premium_index", "premium", "premium_index_history"})
    has_price = any(item.rows > 0 for item in intervals)
    if not has_price or violations:
        tier = DataTier.INVALID
    elif funding_rows and oi_available and premium_available:
        tier = DataTier.FULL_DERIVATIVES
    elif funding_rows and premium_available:
        tier = DataTier.NO_HISTORICAL_OI
    elif funding_rows:
        tier = DataTier.PRICE_FUNDING_ONLY
    else:
        tier = DataTier.PRICE_ONLY

    if not oi_available:
        warnings.append("Missing OI: historical open interest is unavailable; the value remains null and full-five-factor research is blocked.")
    if not premium_available:
        warnings.append("Premium-index history is unavailable and must not be substituted with settled funding.")
    if not any(item.interval == "1m" for item in intervals):
        warnings.append("No 1m bars are available for completed-bar resampling and event replay.")
    if violations:
        warnings.append(f"Found {violations} OHLC/volume violations in the latest 10,000-row sample.")

    latest = max((item.end_at for item in intervals if item.end_at), default=None)
    stale = latest is None or (now - latest).total_seconds() > 6 * 3600
    fingerprint_payload = {
        "path": str(path.resolve()),
        "size": size,
        "mtime_ns": path.stat().st_mtime_ns,
        "intervals": [item.model_dump(mode="json") for item in intervals],
        "funding_rows": funding_rows,
        "tables": sorted(tables),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return DataAssetSummary(
        asset_id=f"sqlite:{fingerprint[:16]}",
        path=str(path.resolve()),
        source="BINANCE_USDM_PUBLIC_CACHE",
        data_tier=tier,
        bytes=size,
        fingerprint=fingerprint,
        intervals=intervals,
        funding_rows=funding_rows,
        funding_symbols=funding_symbols,
        funding_start_at=funding_start,
        funding_end_at=funding_end,
        oi_available=oi_available,
        premium_available=premium_available,
        sampled_ohlc_violations=violations,
        is_stale=stale,
        observed_at=now,
        warnings=warnings,
    )
