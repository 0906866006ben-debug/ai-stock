"""Traceability dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class ReasonTrace:
    """Human-readable reason plus machine-auditable numeric evidence."""

    reason_text: str
    source_field: str
    timestamp: date
    calculation: str
    calculation_value: Optional[Decimal]
