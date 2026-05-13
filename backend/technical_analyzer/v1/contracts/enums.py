"""Enum contracts for technical analyzer v1."""

from __future__ import annotations

from enum import Enum


class TechnicalState(str, Enum):
    STRONG_UPTREND = "strong_uptrend"
    STEADY_UPTREND = "steady_uptrend"
    TIGHT_CONSOLIDATION = "tight_consolidation"
    CONSOLIDATION = "consolidation"
    EARLY_STRENGTHENING = "early_strengthening"
    OVERHEATED_HIGH_LEVEL = "overheated_high_level"
    PARABOLIC_OVERHEAT = "parabolic_overheat"
    HIGH_LEVEL_DISTRIBUTION = "high_level_distribution"
    EARLY_WEAKENING = "early_weakening"
    WEAK_REBOUND = "weak_rebound"
    SELLING_CLIMAX = "selling_climax"
    DOWNTREND_CONTINUATION = "downtrend_continuation"
    MIXED_SIGNALS = "mixed_signals"
    DATA_INSUFFICIENT = "data_insufficient"


class TrendDirection(str, Enum):
    BULLISH = "bullish"
    NEUTRAL_BULLISH = "neutral_bullish"
    NEUTRAL = "neutral"
    NEUTRAL_BEARISH = "neutral_bearish"
    BEARISH = "bearish"


class BreakoutStatus(str, Enum):
    CONFIRMED_HEALTHY_BREAKOUT = "confirmed_healthy_breakout"
    BREAKOUT_PENDING_CONFIRMATION = "breakout_pending_confirmation"
    FALSE_BREAKOUT_INTRADAY = "false_breakout_intraday"
    FALSE_BREAKOUT_T1 = "false_breakout_t1"
    FALSE_BREAKOUT_RISK = "false_breakout_risk"
    FALSE_BREAKOUT_HIGH_CONFIDENCE = "false_breakout_high_confidence"
    CONFIRMED_EFFECTIVE_BREAKDOWN = "confirmed_effective_breakdown"
    BREAKDOWN_PENDING_CONFIRMATION = "breakdown_pending_confirmation"
    FALSE_BREAKDOWN_INTRADAY = "false_breakdown_intraday"
    FALSE_BREAKDOWN_T1 = "false_breakdown_t1"
    EFFECTIVE_BREAKDOWN_RISK = "effective_breakdown_risk"
    EFFECTIVE_BREAKDOWN_HIGH_CONFIDENCE = "effective_breakdown_high_confidence"
    NO_BREAKOUT = "no_breakout"


class VolumeQuality(str, Enum):
    SUPPORTIVE = "supportive"
    NEUTRAL = "neutral"
    WEAK = "weak"
    DIVERGENT = "divergent"
    NOISY = "noisy"
    ABNORMAL_EVENT_DRIVEN = "abnormal_event_driven"


class VolatilityStatus(str, Enum):
    NORMAL = "normal_volatility"
    COMPRESSED = "compressed_volatility"
    EXPANDING = "expanding_volatility"
    HIGH_RISK = "high_risk_volatility"


class Horizon(str, Enum):
    SHORT_TERM = "short_term"
    SWING = "swing"
    LONG_TERM = "long_term"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM_HIGH = "medium_high"
    MEDIUM = "medium"
    MEDIUM_LOW = "medium_low"
    LOW = "low"


class FactorCategory(str, Enum):
    PRICE_POSITION = "price_position"
    MA_GEOMETRY = "ma_geometry"
    VOLUME_QUALITY = "volume_quality"
    STRUCTURE = "structure"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    CHIP_FLOW = "chip_flow"
    BREAKOUT_QUALITY = "breakout_quality"
