"""Topic K: contextual candle patterns and gap tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from ..common import HUNDRED, ZERO, pct_change, quantize
from ..contracts.enums import Horizon, TechnicalState
from ..contracts.feature_contract import FeatureBundle
from ..registry.rule_registry import RuleRegistry
from ..special_rules.taiwan_market_rules import MarketGate
from ..traceability.trace import ReasonTrace
from .candle_features import compute_candle_features
from .support_resistance import SupportResistanceMap
from .volume_price_quadrant import VolumePriceQuadrantResult


class CandlePosition(str, Enum):
    NEAR_20D_HIGH = "near_20d_high"
    NEAR_60D_HIGH = "near_60d_high"
    NEAR_20D_LOW = "near_20d_low"
    NEAR_60D_LOW = "near_60d_low"
    NEAR_MA20 = "near_ma20"
    NEAR_MA60 = "near_ma60"
    NEAR_RESISTANCE = "near_resistance"
    NEAR_SUPPORT = "near_support"
    MIDRANGE = "midrange"


class CandleVolumeContext(str, Enum):
    EXTREME_HIGH = "extreme_high_volume"
    HIGH = "high_volume"
    NORMAL = "normal_volume"
    LOW = "low_volume"
    EXTREME_LOW = "extreme_low_volume"


@dataclass(frozen=True)
class CandleEvent:
    event_date: date
    pattern_name: str
    pattern_type: Literal["single", "double", "triple", "gap"]
    positions: list[CandlePosition]
    volume_context: CandleVolumeContext
    contextual_label: str
    warning_level: Literal["low", "medium", "high", "critical"]
    body_ratio: Decimal
    upper_shadow_ratio: Decimal
    lower_shadow_ratio: Decimal
    close_position_in_range: Decimal
    is_limit_distorted: bool


@dataclass(frozen=True)
class GapEvent:
    event_date: date
    gap_type: str
    gap_top: Decimal
    gap_bottom: Decimal
    is_filled: bool
    filled_date: Optional[date]
    days_unfilled: int
    contextual_label: str
    warning_level: Literal["low", "medium", "high"]


@dataclass(frozen=True)
class CandlePatternResult:
    symbol: str
    analysis_date: date
    horizon: Horizon
    events_today: list[CandleEvent]
    recent_gap_events: list[GapEvent]
    state_signal_score_modifier: int
    confidence_cap: Optional[int]
    reasons: list[ReasonTrace]


def analyze_candle_patterns(
    symbol: str,
    features: FeatureBundle,
    quadrant_result: VolumePriceQuadrantResult,
    sr_map: Optional[SupportResistanceMap] = None,
    market_gate: Optional[MarketGate] = None,
    registry: RuleRegistry | None = None,
) -> CandlePatternResult:
    """Detect today's contextual candle events and recent gaps."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("candle_patterns")
    latest = features.series.latest()
    metrics = compute_candle_features(latest, registry=rules)
    recent_gap_events = _recent_gap_events(features, section)

    if market_gate and market_gate.suppress_event_detection:
        reason = _reason(features, "market_gate", "市場閘門暫停 K 棒事件偵測", "suppress_event_detection == True", Decimal("1"))
        return CandlePatternResult(symbol, latest.date, features.horizon, [], recent_gap_events, 0, market_gate.confidence_cap, [reason])

    positions = _positions(features, sr_map, section)
    volume_context = _volume_context(quadrant_result.turnover_value_ratio_20_adjusted, section)
    pattern_specs = _detect_patterns(features, metrics, recent_gap_events, section)
    events: list[CandleEvent] = []
    reasons: list[ReasonTrace] = []
    for pattern_name, pattern_type in pattern_specs:
        label, warning = _contextual_label(pattern_name, positions, volume_context, section)
        event = CandleEvent(
            event_date=latest.date,
            pattern_name=pattern_name,
            pattern_type=pattern_type,
            positions=positions,
            volume_context=volume_context,
            contextual_label=label,
            warning_level=warning,
            body_ratio=quantize(metrics["body_ratio"] or ZERO),
            upper_shadow_ratio=quantize(metrics["upper_shadow_ratio"] or ZERO),
            lower_shadow_ratio=quantize(metrics["lower_shadow_ratio"] or ZERO),
            close_position_in_range=quantize(metrics["close_position_in_range"] or ZERO),
            is_limit_distorted=latest.is_limit_up or latest.is_limit_down,
        )
        events.append(event)
        reasons.append(
            _reason(features, "candle_features", f"偵測到 K 棒事件 {pattern_name}: {label}", "pattern metrics + position + volume", event.body_ratio)
        )

    modifier, cap = _state_effect(events, section)
    if latest.is_limit_up or latest.is_limit_down:
        cap = min(cap, 50) if cap is not None else 50
    return CandlePatternResult(
        symbol=symbol,
        analysis_date=latest.date,
        horizon=features.horizon,
        events_today=events,
        recent_gap_events=recent_gap_events,
        state_signal_score_modifier=modifier,
        confidence_cap=cap,
        reasons=reasons,
    )


def _detect_patterns(features: FeatureBundle, metrics: dict, gaps: list[GapEvent], rules: dict) -> list[tuple[str, Literal["single", "double", "triple", "gap"]]]:
    bars = features.series.bars
    latest = bars[-1]
    out: list[tuple[str, Literal["single", "double", "triple", "gap"]]] = []
    body_ratio = metrics["body_ratio"] or ZERO
    upper_shadow = metrics["upper_shadow_ratio"] or ZERO
    lower_shadow = metrics["lower_shadow_ratio"] or ZERO
    atr = features.atr_value or Decimal("0")
    total_range = latest.high - latest.low
    if body_ratio >= Decimal(str(rules["long_body_ratio_threshold"])) and total_range >= atr * Decimal(str(rules["atr_range_multiplier"])):
        out.append(("long_bullish_candle" if latest.close > latest.open else "long_bearish_candle", "single"))
    if body_ratio >= Decimal(str(rules["marubozu_body_ratio_threshold"])) and upper_shadow <= Decimal(str(rules["short_shadow_ratio_threshold"])) and lower_shadow <= Decimal(str(rules["short_shadow_ratio_threshold"])):
        out.append(("marubozu_bullish" if latest.close > latest.open else "marubozu_bearish", "single"))
    if body_ratio < Decimal(str(rules["doji_body_ratio_threshold"])) and (atr == ZERO or total_range >= atr * Decimal(str(rules["doji_min_atr_multiplier"]))):
        out.append(("doji", "single"))
    if upper_shadow >= Decimal(str(rules["long_shadow_ratio_threshold"])) and body_ratio < Decimal("0.4"):
        out.append(("long_upper_shadow", "single"))
    if lower_shadow >= Decimal(str(rules["long_shadow_ratio_threshold"])) and body_ratio < Decimal("0.4"):
        out.append(("long_lower_shadow", "single"))
    if lower_shadow >= Decimal(str(rules["hammer_lower_shadow_min"])) and body_ratio <= Decimal(str(rules["hammer_body_max"])) and upper_shadow <= Decimal(str(rules["short_shadow_ratio_threshold"])):
        out.append(("hammer" if latest.close > latest.open else "hanging_man", "single"))
    if upper_shadow >= Decimal(str(rules["long_shadow_ratio_threshold"])) and body_ratio <= Decimal(str(rules["hammer_body_max"])) and lower_shadow <= Decimal(str(rules["short_shadow_ratio_threshold"])):
        out.append(("inverted_hammer" if latest.close > latest.open else "shooting_star", "single"))
    if body_ratio < Decimal("0.3") and upper_shadow > Decimal("0.3") and lower_shadow > Decimal("0.3"):
        out.append(("spinning_top", "single"))
    out.extend(_two_three_bar_patterns(bars, rules))
    if gaps and gaps[-1].event_date == latest.date:
        gap_name = gaps[-1].gap_type if not gaps[-1].is_filled else "gap_filled"
        out.append((gap_name, "gap"))
    return out


def _two_three_bar_patterns(bars, rules: dict) -> list[tuple[str, Literal["double", "triple"]]]:
    out: list[tuple[str, Literal["double", "triple"]]] = []
    if len(bars) >= 2:
        prev, curr = bars[-2], bars[-1]
        prev_black = prev.close < prev.open
        prev_red = prev.close > prev.open
        curr_red = curr.close > curr.open
        curr_black = curr.close < curr.open
        if prev_black and curr_red and curr.open <= prev.close and curr.close >= prev.open:
            out.append(("bullish_engulfing", "double"))
        if prev_red and curr_black and curr.open >= prev.close and curr.close <= prev.open:
            out.append(("bearish_engulfing", "double"))
        prev_mid = (prev.open + prev.close) / Decimal("2")
        if prev_black and curr.open < prev.low and curr.close > prev_mid:
            out.append(("piercing_line", "double"))
        if prev_red and curr.open > prev.high and curr.close < prev_mid:
            out.append(("dark_cloud_cover", "double"))
    if len(bars) >= 3:
        first, middle, third = bars[-3], bars[-2], bars[-1]
        first_body = abs(first.close - first.open)
        mid_body = abs(middle.close - middle.open)
        third_body = abs(third.close - third.open)
        first_mid = (first.open + first.close) / Decimal("2")
        if first.close < first.open and mid_body < first_body * Decimal("0.4") and third.close > third.open and third.close > first_mid and third_body >= first_body * Decimal("0.6"):
            out.append(("morning_star", "triple"))
        if first.close > first.open and mid_body < first_body * Decimal("0.4") and third.close < third.open and third.close < first_mid and third_body >= first_body * Decimal("0.6"):
            out.append(("evening_star", "triple"))
    return out


def _positions(features: FeatureBundle, sr_map: Optional[SupportResistanceMap], rules: dict) -> list[CandlePosition]:
    close = features.latest_close()
    threshold = Decimal(str(rules["position_thresholds"]["near_n_day_high_pct"]))
    ma_threshold = Decimal(str(rules["position_thresholds"]["near_ma_pct"]))
    sr_threshold = Decimal(str(rules["position_thresholds"]["near_sr_level_pct"]))
    out: list[CandlePosition] = []
    for value, position in (
        (features.recent_high_20d, CandlePosition.NEAR_20D_HIGH),
        (features.recent_high_60d, CandlePosition.NEAR_60D_HIGH),
        (features.recent_low_20d, CandlePosition.NEAR_20D_LOW),
        (features.recent_low_60d, CandlePosition.NEAR_60D_LOW),
    ):
        if value and value > ZERO and abs((close - value) / value * HUNDRED) <= threshold:
            out.append(position)
    for ma_name, position in (("ma20", CandlePosition.NEAR_MA20), ("ma60", CandlePosition.NEAR_MA60)):
        ma_value = features.ma_values.get(ma_name)
        if ma_value and ma_value > ZERO and abs((close - ma_value) / ma_value * HUNDRED) <= ma_threshold:
            out.append(position)
    if sr_map and sr_map.nearest_resistance and abs(sr_map.nearest_resistance.distance_from_close_pct) <= sr_threshold:
        out.append(CandlePosition.NEAR_RESISTANCE)
    if sr_map and sr_map.nearest_support and abs(sr_map.nearest_support.distance_from_close_pct) <= sr_threshold:
        out.append(CandlePosition.NEAR_SUPPORT)
    if not out:
        out.append(CandlePosition.MIDRANGE)
    return out


def _volume_context(ratio: Decimal, rules: dict) -> CandleVolumeContext:
    thresholds = rules["volume_context_thresholds"]
    if ratio >= Decimal(str(thresholds["extreme_high"])):
        return CandleVolumeContext.EXTREME_HIGH
    if ratio >= Decimal(str(thresholds["high"])):
        return CandleVolumeContext.HIGH
    if ratio < Decimal(str(thresholds["extreme_low"])):
        return CandleVolumeContext.EXTREME_LOW
    if ratio < Decimal(str(thresholds["low"])):
        return CandleVolumeContext.LOW
    return CandleVolumeContext.NORMAL


def _contextual_label(pattern_name: str, positions: list[CandlePosition], volume: CandleVolumeContext, rules: dict) -> tuple[str, Literal["low", "medium", "high", "critical"]]:
    mapping = rules["contextual_mapping"]
    for position in positions:
        key = f"{pattern_name}|{position.value}|{volume.value}"
        if key in mapping:
            item = mapping[key]
            return item["label"], item["warning"]
    for position in positions:
        key = f"{pattern_name}|{position.value}|normal_volume"
        if key in mapping:
            item = mapping[key]
            return item["label"], item["warning"]
    return "noise_no_signal", "low"


def _recent_gap_events(features: FeatureBundle, rules: dict) -> list[GapEvent]:
    bars = features.series.bars
    lookback = int(rules["gap_lookback_days"])
    events: list[GapEvent] = []
    gap_up_count = 0
    gap_down_count = 0
    for index in range(max(1, len(bars) - lookback), len(bars)):
        prev, curr = bars[index - 1], bars[index]
        gap_type: Optional[str] = None
        top: Optional[Decimal] = None
        bottom: Optional[Decimal] = None
        if curr.low > prev.high:
            gap_up_count += 1
            top, bottom = curr.low, prev.high
            if features.current_state in {TechnicalState.TIGHT_CONSOLIDATION, TechnicalState.EARLY_STRENGTHENING}:
                gap_type = "gap_up_breakaway"
            elif gap_up_count >= int(rules["gap_exhaustion_min_count"]):
                gap_type = "gap_up_exhaustion"
            else:
                gap_type = "gap_up_continuation"
        elif curr.high < prev.low:
            gap_down_count += 1
            top, bottom = prev.low, curr.high
            if features.current_state in {TechnicalState.HIGH_LEVEL_DISTRIBUTION, TechnicalState.EARLY_WEAKENING}:
                gap_type = "gap_down_breakaway"
            elif gap_down_count >= int(rules["gap_exhaustion_min_count"]):
                gap_type = "gap_down_exhaustion"
            else:
                gap_type = "gap_down_continuation"
        if gap_type and top is not None and bottom is not None:
            filled, filled_date = _gap_filled(bars[index:], top, bottom)
            days_unfilled = (bars[-1].date - curr.date).days if not filled else (filled_date - curr.date).days if filled_date else 0
            warning = "high" if "exhaustion" in gap_type else "low"
            events.append(
                GapEvent(
                    event_date=curr.date,
                    gap_type=gap_type,
                    gap_top=top,
                    gap_bottom=bottom,
                    is_filled=filled,
                    filled_date=filled_date,
                    days_unfilled=days_unfilled,
                    contextual_label=gap_type,
                    warning_level=warning,
                )
            )
    return events


def _gap_filled(bars, top: Decimal, bottom: Decimal) -> tuple[bool, Optional[date]]:
    for bar in bars[1:]:
        if bar.low <= top and bar.high >= bottom and bottom <= bar.close <= top:
            return True, bar.date
    return False, None


def _state_effect(events: list[CandleEvent], rules: dict) -> tuple[int, Optional[int]]:
    table = rules["state_modifier_table"]
    chosen_modifier = 0
    chosen_cap: Optional[int] = None
    for event in events:
        if event.contextual_label not in table:
            continue
        item = table[event.contextual_label]
        modifier = int(item["modifier"])
        if abs(modifier) > abs(chosen_modifier):
            chosen_modifier = modifier
            chosen_cap = item.get("cap")
    return chosen_modifier, chosen_cap


def _reason(features: FeatureBundle, source_field: str, text: str, calculation: str, value: Decimal) -> ReasonTrace:
    return ReasonTrace(
        reason_text=text,
        source_field=source_field,
        timestamp=features.series.latest().date,
        calculation=calculation,
        calculation_value=quantize(value),
    )
