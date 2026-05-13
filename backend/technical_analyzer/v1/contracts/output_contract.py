"""Output contracts for technical analyzer v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from ..traceability.trace import ReasonTrace
from .enums import (
    BreakoutStatus,
    ConfidenceLevel,
    FactorCategory,
    Horizon,
    TechnicalState,
    TrendDirection,
    VolatilityStatus,
    VolumeQuality,
)
from .exceptions import MissingInvalidationError


@dataclass(frozen=True)
class FactorVote:
    """One factor-category vote emitted by a feature supplier."""

    category: FactorCategory
    direction: TrendDirection
    strength: Decimal
    reasons: tuple[ReasonTrace, ...] = ()
    event_driven: bool = False
    exclude_from_consensus: bool = False


@dataclass(frozen=True)
class InvalidationSignal:
    description: str
    trigger_condition: str
    monitored_fields: list[str]


@dataclass(frozen=True)
class ObservationCondition:
    description: str
    trigger_condition: str


@dataclass(frozen=True)
class HorizonResult:
    horizon: Horizon
    technical_state: TechnicalState
    trend_direction: TrendDirection
    secondary_flags: list[str]
    signal_score: int
    confidence_score: int
    risk_score: int
    confidence_level: ConfidenceLevel
    reasons: list[ReasonTrace]
    invalidation_signals: list[InvalidationSignal]
    observation_conditions: list[ObservationCondition]
    ma_structure: Optional[dict] = None
    volume_quality: Optional[VolumeQuality] = None
    breakout_status: Optional[BreakoutStatus] = None
    volatility_status: Optional[VolatilityStatus] = None

    def __post_init__(self) -> None:
        if self.trend_direction != TrendDirection.NEUTRAL and not self.invalidation_signals:
            raise MissingInvalidationError(
                f"{self.horizon} has non-neutral direction {self.trend_direction} but empty invalidation_signals"
            )


@dataclass(frozen=True)
class TechnicalAnalysisResult:
    symbol: str
    analysis_date: date
    short_term: HorizonResult
    swing: HorizonResult
    long_term: HorizonResult
    horizon_agreement: Literal["aligned_bullish", "aligned_bearish", "mixed", "transitioning"]
    data_source: str
    data_quality_score: int
    bars_used: int
    context_completeness: Decimal
    rule_set_version: str
    generated_at: datetime
    is_v1_hypothesis: bool = True
    backtest_status: Literal["not_tested", "in_progress", "validated", "deprecated"] = "not_tested"

    def __post_init__(self) -> None:
        for horizon_result in (self.short_term, self.swing, self.long_term):
            if horizon_result.trend_direction != TrendDirection.NEUTRAL and not horizon_result.invalidation_signals:
                raise MissingInvalidationError(
                    f"{horizon_result.horizon} has non-neutral direction but no invalidation_signals"
                )
