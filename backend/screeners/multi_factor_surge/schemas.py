from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModuleScore(BaseModel):
    score: int
    reasons: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    data_quality_flags: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    is_neutral_fallback: bool = False


class MultiFactorScores(BaseModel):
    fundamental_score: int
    chip_score: int
    technical_score: int
    breakout_sustain_score: int
    liquidity_score: int


class MultiFactorResult(BaseModel):
    rank: int = 0
    stock_id: str
    stock_name: str
    candidate_type: str
    surge_score: int
    confidence_score: int
    risk_score: int
    scores: MultiFactorScores
    metrics: dict[str, Any]
    reasons: list[str]
    watch_conditions: list[str]
    invalidation: list[str]
    risk_flags: list[str]
    missing_data: list[str]
    data_quality_flags: list[str]


class MultiFactorResponse(BaseModel):
    strategy: str = "Taiwan Multi-Factor Surge Screener"
    generated_at: str
    rule_set_version: str = "v1.0.0"
    is_v1_hypothesis: bool = True
    backtest_required: bool = True
    universe_size: int
    matched_count: int
    parameters: dict[str, Any]
    data_warnings: list[str] = Field(default_factory=list)
    funnel_report: dict[str, Any] | None = None
    results: list[MultiFactorResult] = Field(default_factory=list)
