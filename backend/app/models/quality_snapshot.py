from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SnapshotStock(BaseModel):
    symbol: str
    name: str
    durability_score: float
    durability_components: dict[str, float] = Field(default_factory=dict)
    confidence: float = 0.0
    sector: Optional[str] = None
    price_at_snapshot: Optional[float] = None
    market_cap_ntd: Optional[float] = None


class QuarterlySnapshot(BaseModel):
    quarter: str
    as_of_date: str
    generated_at: str
    status: str = "ok"
    warnings: list[str] = Field(default_factory=list)
    snapshot_stocks: list[SnapshotStock] = Field(default_factory=list)


class QualityWatchHistoryItem(BaseModel):
    quarter: str
    as_of_date: str
    generated_at: str
    stock_count: int
