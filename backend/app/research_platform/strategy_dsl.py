from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CoreFactor(StrEnum):
    FUNDING = "FUNDING"
    OPEN_INTEREST = "OPEN_INTEREST"
    EMA = "EMA"
    VOLUME = "VOLUME"
    RSI = "RSI"


class RuleCondition(BaseModel):
    rule_id: str
    factor: CoreFactor
    field: str
    operator: Literal["lt", "lte", "gt", "gte", "eq", "crosses_above", "crosses_below", "changed"]
    threshold: float | str | bool | None = None
    timeframe: str
    max_age_bars: int = Field(ge=0)
    missing_behavior: Literal["BLOCK", "SKIP_FACTOR", "LOWER_CONFIDENCE"] = "BLOCK"
    invalidation: str


class PositionSizingRule(BaseModel):
    method: Literal["FIXED_RISK"] = "FIXED_RISK"
    risk_per_trade_pct: float = Field(default=0.25, gt=0, le=0.5)
    hard_max_risk_per_trade_pct: float = Field(default=0.5, gt=0, le=0.5)
    maximum_leverage: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def risk_does_not_exceed_hard_limit(self) -> "PositionSizingRule":
        if self.risk_per_trade_pct > self.hard_max_risk_per_trade_pct:
            raise ValueError("risk_per_trade_pct exceeds the hard maximum")
        return self


class StrategyDefinition(BaseModel):
    strategy_id: str
    strategy_family: str
    version: str
    parent_version: str | None = None
    research_hypothesis_id: str
    horizon: Literal["INTRADAY", "SWING", "LONG_TERM"]
    long_enabled: bool
    short_enabled: bool
    core_factors: list[CoreFactor]
    setup_conditions: list[RuleCondition]
    armed_conditions: list[RuleCondition]
    trigger_conditions: list[RuleCondition]
    cancel_conditions: list[RuleCondition]
    entry_rule: dict[str, Any]
    stop_rule: dict[str, Any]
    target_rule: dict[str, Any]
    time_exit_rule: dict[str, Any]
    position_sizing: PositionSizingRule
    market_regime_filter: dict[str, Any]
    liquidity_filter: dict[str, Any]
    data_requirements: list[str]
    parameter_space: dict[str, Any]
    invalidation_signal: str
    created_by: Literal["human", "codex", "openai_patch"]
    created_at: datetime

    @model_validator(mode="after")
    def validate_definition(self) -> "StrategyDefinition":
        if not self.long_enabled and not self.short_enabled:
            raise ValueError("at least one direction must be enabled")
        if len(set(self.core_factors)) != len(self.core_factors):
            raise ValueError("core_factors must be unique")
        if not self.trigger_conditions:
            raise ValueError("at least one trigger condition is required")
        if not self.invalidation_signal.strip():
            raise ValueError("an invalidation signal is required")
        return self


def baseline_five_factor_v1() -> StrategyDefinition:
    now = datetime.now(timezone.utc)
    setup = [
        RuleCondition(
            rule_id="rsi_extreme_1h",
            factor=CoreFactor.RSI,
            field="rsi_14",
            operator="changed",
            threshold="long<=25,short>=75",
            timeframe="1h",
            max_age_bars=6,
            invalidation="RSI setup TTL expires before confirmation",
        ),
        RuleCondition(
            rule_id="oi_accumulation",
            factor=CoreFactor.OPEN_INTEREST,
            field="oi_change_pct_1h",
            operator="gt",
            threshold=0.0,
            timeframe="1h",
            max_age_bars=1,
            missing_behavior="BLOCK",
            invalidation="OI is missing, stale, or no longer increasing",
        ),
    ]
    trigger = [
        RuleCondition(
            rule_id="ema_volume_break",
            factor=CoreFactor.EMA,
            field="completed_bar_body_cross_ema_12",
            operator="eq",
            threshold=True,
            timeframe="1m",
            max_age_bars=0,
            invalidation="confirmation bar closes back across EMA12",
        ),
        RuleCondition(
            rule_id="rvol_confirmation",
            factor=CoreFactor.VOLUME,
            field="rvol_mean_20",
            operator="gte",
            threshold=1.5,
            timeframe="1m",
            max_age_bars=0,
            invalidation="breakout has no volume confirmation",
        ),
        RuleCondition(
            rule_id="settled_funding_flip",
            factor=CoreFactor.FUNDING,
            field="funding_flip_direction",
            operator="eq",
            threshold="toward_position_carry",
            timeframe="8h",
            max_age_bars=2,
            invalidation="funding is estimated, missing, or flips back before entry",
        ),
    ]
    return StrategyDefinition(
        strategy_id="BASELINE_FUNDING_OI_MEAN_REVERSION_V1",
        strategy_family="FULL_FIVE_FACTOR",
        version="1.0.0",
        research_hypothesis_id="HYP-FIVE-FACTOR-MEAN-REVERSION-001",
        horizon="INTRADAY",
        long_enabled=True,
        short_enabled=True,
        core_factors=list(CoreFactor),
        setup_conditions=setup,
        armed_conditions=[],
        trigger_conditions=trigger,
        cancel_conditions=[],
        entry_rule={"timing": "NEXT_1M_OPEN", "completed_bars_only": True},
        stop_rule={"type": "SWING_PLUS_ATR", "atr_buffer": 0.25},
        target_rule={"type": "EMA_MEAN_REVERSION", "timeframe": "15m", "period": 12},
        time_exit_rule={"max_hold_hours": 48},
        position_sizing=PositionSizingRule(),
        market_regime_filter={"enabled": True, "missing_behavior": "LOWER_CONFIDENCE"},
        liquidity_filter={"quote_volume_24h_min_usdt": 15_000_000},
        data_requirements=["OHLCV_1M", "SETTLED_FUNDING", "OPEN_INTEREST", "PREMIUM_INDEX"],
        parameter_space={
            "rsi_period": [5, 7, 9, 14, 21],
            "ema_period": [5, 8, 9, 12, 13, 20, 21, 34, 50, 100, 200],
            "rvol_threshold": [1.0, 3.0],
        },
        invalidation_signal="Any required factor is missing/stale, setup TTL expires, or trigger confirmation fails.",
        created_by="codex",
        created_at=now,
    )

