"""Topic J: divergence, bias overheat, and state override hints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import sqrt
from typing import Optional

from ..common import HUNDRED, ONE, ZERO, clamp, mean, percentile_rank, quantize
from ..contracts.enums import FactorCategory, TechnicalState, TrendDirection
from ..contracts.feature_contract import FeatureBundle, Pivot
from ..contracts.input_contract import ContextBundle
from ..contracts.output_contract import FactorVote
from ..registry.rule_registry import RuleRegistry
from ..traceability.trace import ReasonTrace
from .momentum_contextual import MomentumContextualResult
from .support_resistance import SupportResistanceMap
from .volume_price_quadrant import VolumePriceQuadrantResult, VolumePriceSubClass


@dataclass(frozen=True)
class OverheatAssessment:
    overheat_level: str
    triggered_dimensions: list[str]
    triggered_count: int
    bias_20_pct: Decimal
    bias_20_zscore: Decimal
    bias_20_percentile_1y: Decimal
    beta_factor: Decimal
    is_beta_estimated: bool
    dynamic_thresholds: dict[str, Decimal]


@dataclass(frozen=True)
class DivergenceEvent:
    divergence_type: str
    confirmation_level: str
    earlier_pivot_date: date
    earlier_pivot_price: Decimal
    later_pivot_date: date
    later_pivot_price: Decimal
    indicators_diverging: list[str]
    earlier_momentum_values: dict
    later_momentum_values: dict
    intensity: Decimal
    intensity_tier: str
    confirmed_by_subsequent_action: Optional[bool]
    pivot_distance_days: int
    is_distance_too_large: bool


@dataclass(frozen=True)
class DivergenceOverheatResult:
    symbol: str
    analysis_date: date
    horizon: str
    overheat: OverheatAssessment
    divergence_events: list[DivergenceEvent]
    state_signal_score_modifier: int
    confidence_cap: Optional[int]
    state_override_required: bool
    state_override_target: Optional[TechnicalState]
    vote: FactorVote
    reasons: list[ReasonTrace]


def analyze_divergence_overheat(
    symbol: str,
    features: FeatureBundle,
    context: ContextBundle,
    momentum_result: MomentumContextualResult,
    quadrant_result: Optional[VolumePriceQuadrantResult] = None,
    sr_map: Optional[SupportResistanceMap] = None,
    registry: RuleRegistry | None = None,
) -> DivergenceOverheatResult:
    """Assess overheat, bias, and confirmed pivot divergences."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("divergence_overheat")
    overheat = _assess_overheat(features, context, momentum_result, quadrant_result, section)
    divergences = _detect_divergences(features, section)
    vote, reasons = _volatility_vote(features, overheat, divergences, section)
    modifier, cap, override_required, override_target = _state_modifier(features.current_state, overheat, divergences, section)
    cap = _apply_consistency_cap(features.current_state, overheat, cap, section)
    return DivergenceOverheatResult(
        symbol=symbol,
        analysis_date=features.series.latest().date,
        horizon=features.horizon.value,
        overheat=overheat,
        divergence_events=divergences,
        state_signal_score_modifier=modifier,
        confidence_cap=cap,
        state_override_required=override_required,
        state_override_target=override_target,
        vote=vote,
        reasons=reasons,
    )


def _assess_overheat(
    features: FeatureBundle,
    context: ContextBundle,
    momentum_result: MomentumContextualResult,
    quadrant_result: Optional[VolumePriceQuadrantResult],
    section: dict,
) -> OverheatAssessment:
    bias_section = section["bias"]
    current_bias = features.bias_20_pct
    if current_bias is None:
        ma20 = features.ma_values.get("ma20")
        current_bias = ((features.latest_close() - ma20) / ma20 * HUNDRED) if ma20 else ZERO
    bias_series = list(features.bias_20_series)[- int(bias_section["zscore_lookback_days"]):]
    bias_mean = mean(bias_series) or ZERO
    variance = mean([(value - bias_mean) ** 2 for value in bias_series]) if bias_series else ZERO
    bias_std = Decimal(str(sqrt(float(variance)))) if variance and variance > ZERO else Decimal("1")
    zscore = (current_bias - bias_mean) / bias_std if bias_std != ZERO else ZERO
    percentile = percentile_rank(current_bias, bias_series) or Decimal("50")
    beta_rules = section["beta_adjustment"]
    is_beta_estimated = context.beta_60d is None
    beta_factor = clamp(context.beta_60d or Decimal(str(beta_rules["default_beta_when_missing"])), Decimal(str(beta_rules["beta_factor_min"])), Decimal(str(beta_rules["beta_factor_max"])))
    thresholds = section["overheat_dimensions"]["bias_extreme"]
    dynamic_thresholds = {
        "mild": Decimal(str(thresholds["threshold_zscore_mild"])) * beta_factor,
        "moderate": Decimal(str(thresholds["threshold_zscore_moderate"])) * beta_factor,
        "severe": Decimal(str(thresholds["threshold_zscore_severe"])) * beta_factor,
        "parabolic": Decimal(str(thresholds["threshold_zscore_parabolic"])) * beta_factor,
    }
    triggered: list[str] = []
    if abs(zscore) >= dynamic_thresholds["mild"]:
        triggered.append("bias_extreme")
    if momentum_result.rsi_reading.value > Decimal(str(section["overheat_dimensions"]["momentum_extreme"]["rsi_threshold"])) or momentum_result.kd_reading.high_dulling_days >= int(section["overheat_dimensions"]["momentum_extreme"]["kd_dulling_days"]):
        triggered.append("momentum_extreme")
    if (features.atr_ratio_percentile_60d or ZERO) >= Decimal(str(section["overheat_dimensions"]["volatility_expanding"]["atr_ratio_percentile"])) and momentum_result.bollinger_reading.band_expansion:
        triggered.append("volatility_expanding")
    if quadrant_result and quadrant_result.turnover_value_ratio_20_adjusted > Decimal(str(section["overheat_dimensions"]["volume_abnormal"]["volume_ratio_threshold"])) and quadrant_result.sub_classification == VolumePriceSubClass.DISTRIBUTION_VOLUME_RISK:
        triggered.append("volume_abnormal")
    if (context.day_trading_ratio or ZERO) > Decimal(str(section["overheat_dimensions"]["chip_overheat"]["day_trading_threshold"])) or (context.margin_balance_change_pct_3d or ZERO) > Decimal(str(section["overheat_dimensions"]["chip_overheat"]["margin_balance_3d_change_pct"])):
        triggered.append("chip_overheat")

    count = len(triggered)
    thresholds_count = section["overheat_level_thresholds"]
    if count >= int(thresholds_count["parabolic"]):
        level = "parabolic_overheat"
    elif count >= int(thresholds_count["severe"]):
        level = "severe_overheat"
    elif count >= int(thresholds_count["moderate"]):
        level = "moderate_overheat"
    elif count >= int(thresholds_count["mild"]):
        level = "mild_overheat"
    else:
        level = "normal"
    return OverheatAssessment(
        overheat_level=level,
        triggered_dimensions=triggered,
        triggered_count=count,
        bias_20_pct=quantize(current_bias),
        bias_20_zscore=quantize(zscore),
        bias_20_percentile_1y=quantize(percentile),
        beta_factor=quantize(beta_factor),
        is_beta_estimated=is_beta_estimated,
        dynamic_thresholds={key: quantize(value) for key, value in dynamic_thresholds.items()},
    )


def _detect_divergences(features: FeatureBundle, section: dict) -> list[DivergenceEvent]:
    structure = features.swing_structure
    if not structure:
        return []
    events: list[DivergenceEvent] = []
    divergence_rules = section["divergence"]
    max_distance = int(divergence_rules["pivot_distance_max_days_swing"])
    if len(structure.swing_highs) >= 2:
        earlier, later = structure.swing_highs[-2], structure.swing_highs[-1]
        event = _compare_price_vs_indicators(features, earlier, later, bearish=True, max_distance=max_distance, section=divergence_rules)
        if event:
            events.append(event)
        volume_event = _compare_volume_divergence(features, earlier, later, bearish=True, max_distance=max_distance, section=divergence_rules)
        if volume_event:
            events.append(volume_event)
    if len(structure.swing_lows) >= 2:
        earlier, later = structure.swing_lows[-2], structure.swing_lows[-1]
        event = _compare_price_vs_indicators(features, earlier, later, bearish=False, max_distance=max_distance, section=divergence_rules)
        if event:
            events.append(event)
        volume_event = _compare_volume_divergence(features, earlier, later, bearish=False, max_distance=max_distance, section=divergence_rules)
        if volume_event:
            events.append(volume_event)
    return events


def _compare_price_vs_indicators(features: FeatureBundle, earlier: Pivot, later: Pivot, bearish: bool, max_distance: int, section: dict) -> Optional[DivergenceEvent]:
    if bearish and later.price <= earlier.price:
        return None
    if not bearish and later.price >= earlier.price:
        return None
    earlier_values = _indicator_values_at(features, earlier.index)
    later_values = _indicator_values_at(features, later.index)
    diverging: list[str] = []
    for name in ("RSI", "MACD_histogram", "KD_K"):
        earlier_value = earlier_values.get(name)
        later_value = later_values.get(name)
        if earlier_value is None or later_value is None:
            continue
        if bearish and later_value < earlier_value:
            diverging.append(name)
        if not bearish and later_value > earlier_value:
            diverging.append(name)
    if not diverging:
        return None
    distance_days = (later.date - earlier.date).days
    confirmation_level = _confirmation_level(len(diverging), section["confirmation_levels"])
    intensity = _divergence_intensity(earlier.price, later.price, earlier_values, later_values, diverging)
    too_far = distance_days > max_distance
    if too_far:
        intensity *= Decimal(str(section["pivot_distance_too_large_strength_multiplier"]))
    return DivergenceEvent(
        divergence_type="bearish_divergence" if bearish else "bullish_divergence",
        confirmation_level=confirmation_level,
        earlier_pivot_date=earlier.date,
        earlier_pivot_price=earlier.price,
        later_pivot_date=later.date,
        later_pivot_price=later.price,
        indicators_diverging=diverging,
        earlier_momentum_values=earlier_values,
        later_momentum_values=later_values,
        intensity=quantize(intensity),
        intensity_tier=_intensity_tier(intensity, section["intensity_tier"]),
        confirmed_by_subsequent_action=None,
        pivot_distance_days=distance_days,
        is_distance_too_large=too_far,
    )


def _compare_volume_divergence(features: FeatureBundle, earlier: Pivot, later: Pivot, bearish: bool, max_distance: int, section: dict) -> Optional[DivergenceEvent]:
    if bearish and later.price <= earlier.price:
        return None
    if not bearish and later.price >= earlier.price:
        return None
    earlier_volume = _turnover_5d_avg_at(features, earlier.index)
    later_volume = _turnover_5d_avg_at(features, later.index)
    if earlier_volume is None or later_volume is None:
        return None
    diverged = later_volume < earlier_volume if bearish else later_volume > earlier_volume
    if not diverged:
        return None
    distance_days = (later.date - earlier.date).days
    intensity = abs((later.price - earlier.price) / earlier.price)
    intensity *= Decimal(str(section["volume_divergence_weight_multiplier"]))
    too_far = distance_days > max_distance
    if too_far:
        intensity *= Decimal(str(section["pivot_distance_too_large_strength_multiplier"]))
    return DivergenceEvent(
        divergence_type="volume_bearish_divergence" if bearish else "volume_bullish_divergence",
        confirmation_level="light_divergence",
        earlier_pivot_date=earlier.date,
        earlier_pivot_price=earlier.price,
        later_pivot_date=later.date,
        later_pivot_price=later.price,
        indicators_diverging=["TURNOVER_VALUE_5D"],
        earlier_momentum_values={"TURNOVER_VALUE_5D": earlier_volume},
        later_momentum_values={"TURNOVER_VALUE_5D": later_volume},
        intensity=quantize(intensity),
        intensity_tier=_intensity_tier(intensity, section["intensity_tier"]),
        confirmed_by_subsequent_action=None,
        pivot_distance_days=distance_days,
        is_distance_too_large=too_far,
    )


def _turnover_5d_avg_at(features: FeatureBundle, index: int) -> Optional[Decimal]:
    bars = features.series.bars
    start = max(0, index - 4)
    window = bars[start : index + 1]
    if not window:
        return None
    return sum(bar.turnover_value for bar in window) / Decimal(len(window))


def _indicator_values_at(features: FeatureBundle, index: int) -> dict:
    def _get(series):
        if 0 <= index < len(series):
            return series[index]
        return None
    return {
        "RSI": _get(features.rsi_series),
        "MACD_histogram": _get(features.macd_histogram),
        "KD_K": _get(features.kd_k),
    }


def _confirmation_level(count: int, rules: dict) -> str:
    if count >= int(rules["triple_confirmed_required_indicators"]):
        return "triple_confirmed_divergence"
    if count >= int(rules["confirmed_required_indicators"]):
        return "confirmed_divergence"
    return "light_divergence"


def _divergence_intensity(earlier_price: Decimal, later_price: Decimal, earlier_values: dict, later_values: dict, diverging: list[str]) -> Decimal:
    price_change_pct = abs((later_price - earlier_price) / earlier_price * HUNDRED) if earlier_price != ZERO else ZERO
    intensity_scores: list[Decimal] = []
    for name in diverging:
        earlier_value = Decimal(str(earlier_values[name]))
        later_value = Decimal(str(later_values[name]))
        denominator = max(abs(earlier_value), Decimal("1"))
        momentum_change_pct = abs((later_value - earlier_value) / denominator * HUNDRED)
        intensity_scores.append(abs(price_change_pct - momentum_change_pct) / max(abs(price_change_pct), Decimal("1")))
    return max(intensity_scores, default=ZERO)


def _intensity_tier(intensity: Decimal, rules: dict) -> str:
    if intensity > Decimal(str(rules["strong"])):
        return "strong"
    if intensity >= Decimal(str(rules["moderate"])):
        return "moderate"
    return "weak"


def _volatility_vote(features: FeatureBundle, overheat: OverheatAssessment, divergences: list[DivergenceEvent], section: dict) -> tuple[FactorVote, list[ReasonTrace]]:
    base_direction, base_strength = {
        "normal": (TrendDirection.NEUTRAL, ZERO),
        "mild_overheat": (TrendDirection.BEARISH, Decimal("0.3")),
        "moderate_overheat": (TrendDirection.BEARISH, Decimal("0.5")),
        "severe_overheat": (TrendDirection.BEARISH, Decimal("0.7")),
        "parabolic_overheat": (TrendDirection.BEARISH, Decimal("0.9")),
    }[overheat.overheat_level]
    strength = base_strength
    signed = Decimal("1") if base_direction == TrendDirection.BEARISH else Decimal("-1") if base_direction == TrendDirection.BULLISH else ZERO
    for event in divergences:
        if event.confirmation_level == "light_divergence":
            delta = Decimal("0.0")
        else:
            delta = Decimal("0.15")
            if event.confirmation_level == "triple_confirmed_divergence":
                delta += Decimal("0.1")
        if "bearish" in event.divergence_type:
            signed += delta
        elif "bullish" in event.divergence_type:
            signed -= delta
    if signed > ZERO:
        direction = TrendDirection.BEARISH
        strength = min(ONE, strength + signed)
    elif signed < ZERO:
        direction = TrendDirection.BULLISH
        strength = min(ONE, abs(signed))
    else:
        direction = TrendDirection.NEUTRAL
    reasons = [
        ReasonTrace(
            reason_text=f"過熱層級 {overheat.overheat_level}",
            source_field="divergence_overheat",
            timestamp=features.series.latest().date,
            calculation="overheat dimensions count",
            calculation_value=Decimal(overheat.triggered_count),
        )
    ]
    for event in divergences:
        reasons.append(
            ReasonTrace(
                reason_text=f"偵測到 {event.divergence_type}",
                source_field="swing_structure",
                timestamp=event.later_pivot_date,
                calculation="price vs momentum divergence",
                calculation_value=event.intensity,
            )
        )
    vote = FactorVote(
        category=FactorCategory.VOLATILITY,
        direction=direction,
        strength=quantize(clamp(strength, ZERO, ONE)),
        reasons=tuple(reasons),
    )
    return vote, reasons


def _state_modifier(current_state: TechnicalState, overheat: OverheatAssessment, divergences: list[DivergenceEvent], section: dict) -> tuple[int, Optional[int], bool, Optional[TechnicalState]]:
    modifiers = section["state_modifier"]
    bearish_confirmed = any(event.confirmation_level in {"confirmed_divergence", "triple_confirmed_divergence"} and "bearish" in event.divergence_type for event in divergences)
    bullish_confirmed = any(event.confirmation_level in {"confirmed_divergence", "triple_confirmed_divergence"} and "bullish" in event.divergence_type for event in divergences)
    if overheat.overheat_level == "parabolic_overheat":
        return int(modifiers["parabolic_overheat_modifier"]), int(modifiers["parabolic_overheat_cap"]), True, TechnicalState.PARABOLIC_OVERHEAT
    if overheat.overheat_level == "severe_overheat" and bearish_confirmed:
        target = TechnicalState.HIGH_LEVEL_DISTRIBUTION if current_state == TechnicalState.STRONG_UPTREND else None
        return int(modifiers["severe_with_divergence_modifier"]), int(modifiers["severe_with_divergence_cap"]), target is not None, target
    if overheat.overheat_level == "moderate_overheat":
        return int(modifiers["moderate_modifier"]), int(modifiers["moderate_cap"]), False, None
    if overheat.overheat_level == "mild_overheat":
        return int(modifiers["mild_modifier"]), int(modifiers["mild_cap"]), False, None
    if any(event.confirmation_level == "triple_confirmed_divergence" and "bearish" in event.divergence_type for event in divergences):
        return int(modifiers["triple_confirmed_divergence_modifier"]), int(modifiers["triple_confirmed_divergence_cap"]), False, None
    if bearish_confirmed:
        return int(modifiers["confirmed_divergence_modifier"]), int(modifiers["confirmed_divergence_cap"]), False, None
    if bullish_confirmed and current_state in {TechnicalState.SELLING_CLIMAX, TechnicalState.DOWNTREND_CONTINUATION}:
        return int(modifiers["bullish_divergence_low_modifier"]), None, False, None
    return 0, None, False, None


def _apply_consistency_cap(current_state: TechnicalState, overheat: OverheatAssessment, cap: Optional[int], section: dict) -> Optional[int]:
    checks = section["consistency_check"]
    inconsistency_cap = int(checks["inconsistency_confidence_cap"])
    if current_state == TechnicalState.PARABOLIC_OVERHEAT and overheat.overheat_level not in {"severe_overheat", "parabolic_overheat"}:
        return inconsistency_cap if cap is None else min(cap, inconsistency_cap)
    if current_state in {TechnicalState.TIGHT_CONSOLIDATION, TechnicalState.CONSOLIDATION} and overheat.overheat_level not in {"normal", "mild_overheat"}:
        return inconsistency_cap if cap is None else min(cap, inconsistency_cap)
    return cap
