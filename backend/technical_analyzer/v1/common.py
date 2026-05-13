"""Shared helpers for technical analyzer v1."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional


ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def to_decimal(value: object | None, default: Optional[Decimal] = None) -> Optional[Decimal]:
    """Convert a numeric-ish input to Decimal."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize(value: Decimal, places: str = "0.0001") -> Decimal:
    """Quantize a Decimal using bankers-safe half-up rounding."""
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def safe_div(numerator: Decimal, denominator: Decimal, default: Optional[Decimal] = None) -> Optional[Decimal]:
    """Return numerator / denominator or default when denominator is zero."""
    if denominator == ZERO:
        return default
    return numerator / denominator


def pct_change(current: Decimal, reference: Decimal, default: Optional[Decimal] = None) -> Optional[Decimal]:
    """Return percentage change in Decimal points."""
    if reference == ZERO:
        return default
    return ((current - reference) / reference) * HUNDRED


def mean(values: Iterable[Decimal]) -> Optional[Decimal]:
    items = list(values)
    if not items:
        return None
    return sum(items, ZERO) / Decimal(len(items))


def median(values: Iterable[Decimal]) -> Optional[Decimal]:
    items = sorted(values)
    if not items:
        return None
    mid = len(items) // 2
    if len(items) % 2:
        return items[mid]
    return (items[mid - 1] + items[mid]) / Decimal("2")


def clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def percentile_rank(value: Decimal, history: Iterable[Decimal]) -> Optional[Decimal]:
    items = list(history)
    if not items:
        return None
    count = sum(1 for item in items if item <= value)
    return Decimal(count) / Decimal(len(items)) * HUNDRED
