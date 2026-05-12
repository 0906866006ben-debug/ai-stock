"""Aggregate daily OHLCV candles into weekly / monthly / yearly buckets."""
from __future__ import annotations

from datetime import datetime


# Mapping: range_code -> (granularity, lookback_days, max_candles)
RANGE_CONFIG = {
    "D":  ("daily",   200,  None),   # ~140 trading days
    "W":  ("weekly",  365 * 2,  120),  # ~104 weeks
    "M":  ("monthly", 365 * 5,  72),   # ~60 months
    "Y":  ("yearly",  365 * 12, 12),   # ~12 years
}

# Legacy aliases — some clients might still pass old labels
LEGACY_ALIASES = {
    "1D": "D",
    "5D": "D",
    "1W": "W",
    "1M": "M",
    "1Y": "Y",
}


def normalize_range(value: str) -> str:
    if value in RANGE_CONFIG:
        return value
    return LEGACY_ALIASES.get(value, "D")


def _bucket_key(date_str: str, granularity: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    if granularity == "weekly":
        # ISO week: monday of that week
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "monthly":
        return f"{d.year}-{d.month:02d}"
    if granularity == "yearly":
        return f"{d.year}"
    return date_str  # daily — each candle in own bucket


def _bucket_label(key: str, granularity: str, last_date: str) -> str:
    """Produce a YYYY-MM-DD label that lightweight-charts accepts."""
    if granularity == "weekly":
        # Use the friday of that week as a stable label (last trading day-ish)
        # We only have last_date which is the last daily date in the bucket.
        return last_date
    if granularity == "monthly":
        # Use the last day actually seen in the bucket
        return last_date
    if granularity == "yearly":
        return last_date
    return key


def aggregate_candles(daily: list[dict], granularity: str) -> list[dict]:
    """Bucket a sorted list of daily candles into the given granularity.

    Each output candle has open=first, close=last, high=max, low=min,
    volume=sum, time=last-day-in-bucket.
    """
    if granularity == "daily" or not daily:
        return list(daily)

    buckets: dict[str, list[dict]] = {}
    order: list[str] = []
    for c in daily:
        key = _bucket_key(c["time"], granularity)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(c)

    out: list[dict] = []
    for key in order:
        rows = buckets[key]
        first = rows[0]
        last = rows[-1]
        out.append({
            "time": _bucket_label(key, granularity, last["time"]),
            "open": float(first["open"]),
            "high": max(float(r["high"]) for r in rows),
            "low":  min(float(r["low"]) for r in rows),
            "close": float(last["close"]),
            "volume": sum(int(r["volume"]) for r in rows),
        })
    return out


def trim_to_max(candles: list[dict], max_candles: int | None) -> list[dict]:
    if not max_candles or len(candles) <= max_candles:
        return candles
    return candles[-max_candles:]
