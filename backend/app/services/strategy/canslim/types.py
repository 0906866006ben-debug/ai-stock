"""Core CAN SLIM strategy types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    triggered: bool
    signal_delta: int = 0
    risk_delta: int = 0
    confidence_delta: int = 0
    reason: str | None = None
    data_warning: str | None = None
    hard_block: bool = False


class HorizonObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon: Literal["short_term", "swing_term", "long_term"]
    status: Literal["neutral", "watching", "trigger_proximity", "invalidating"]
    direction_hint: Literal["up", "down", "sideways", "unclear"]
    evidence_based_reasons: list[str] = Field(default_factory=list)
    triggered_rule_ids: list[str] = Field(default_factory=list)
    suitable_strategy_examples: list[str] = Field(default_factory=list)
    key_observation_conditions: list[str] = Field(default_factory=list)
    invalidation_signals: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "moderate", "elevated", "high"]
    confidence_level: Literal["low", "moderate", "high"]
    scores: dict[str, Any] = Field(default_factory=dict)
    data_warnings: list[str] = Field(default_factory=list)


class MarketFeatures(BaseModel):
    model_config = ConfigDict(frozen=True)

    taiex_close: float | None = None
    taiex_ma150: float | None = None
    taiex_ma150_slope: float | None = None
    tpex_close: float | None = None
    tpex_ma150: float | None = None
    tpex_ma150_slope: float | None = None
    breadth_above_ma60_pct: float | None = None
    sox_above_ma60: bool | None = None
    nasdaq_above_ma60: bool | None = None
    distribution_day_count: int | None = None
    follow_through_day: bool | None = None
    taiex_ex_tsmc_close: float | None = None
    taiex_ex_tsmc_ma150: float | None = None
    taiex_ex_tsmc_ma150_slope: float | None = None
    missing_fields: list[str] = Field(default_factory=list)
    data_warnings: list[str] = Field(default_factory=list)
