"""Topic I: contextual momentum interpretation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from ..common import HUNDRED, ZERO, clamp, pct_change, percentile_rank, quantize
from ..contracts.enums import FactorCategory, Horizon, TechnicalState, TrendDirection
from ..contracts.feature_contract import FeatureBundle
from ..contracts.output_contract import FactorVote
from ..registry.rule_registry import RuleRegistry
from ..traceability.trace import ReasonTrace
from .candle_features import compute_candle_features


@dataclass(frozen=True)
class RSIContextualReading:
    value: Decimal
    base_label: str
    contextual_state: str
    warning_level: str
    crossed_50_event: Optional[str]
    days_since_crossover: Optional[int]


@dataclass(frozen=True)
class MACDContextualReading:
    dif: Decimal
    dea: Decimal
    histogram: Decimal
    contextual_state: str
    warning_level: str
    crossover_event: Optional[str]
    crossover_recency_days: Optional[int]
    zero_axis_event: Optional[str]
    histogram_trend: str
    histogram_consecutive_change_days: int


@dataclass(frozen=True)
class KDContextualReading:
    k_value: Decimal
    d_value: Decimal
    contextual_state: str
    warning_level: str
    high_dulling_days: int
    low_dulling_days: int
    crossover_event: Optional[str]


@dataclass(frozen=True)
class BollingerContextualReading:
    upper_band: Decimal
    middle_band: Decimal
    lower_band: Decimal
    bandwidth: Decimal
    bandwidth_percentile_120d: Decimal
    contextual_state: str
    band_compression: bool
    band_expansion: bool


@dataclass(frozen=True)
class MomentumContextualResult:
    symbol: str
    analysis_date: date
    horizon: Horizon
    rsi_reading: RSIContextualReading
    macd_reading: MACDContextualReading
    kd_reading: KDContextualReading
    bollinger_reading: BollingerContextualReading
    vote: FactorVote
    reasons: list[ReasonTrace]


def analyze_momentum_contextual(
    symbol: str,
    features: FeatureBundle,
    registry: RuleRegistry | None = None,
) -> MomentumContextualResult:
    """Interpret RSI/MACD/KD/Bollinger in the context of the current price state."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("momentum_contextual")
    current_state = features.current_state
    rsi_reading = _analyze_rsi(features, current_state, section)
    macd_reading = _analyze_macd(features, current_state, section)
    kd_reading = _analyze_kd(features, current_state, section)
    bollinger_reading = _analyze_bollinger(features, current_state, section)
    vote, reasons = _assemble_vote(features, rsi_reading, macd_reading, kd_reading, bollinger_reading, section)
    return MomentumContextualResult(
        symbol=symbol,
        analysis_date=features.series.latest().date,
        horizon=features.horizon,
        rsi_reading=rsi_reading,
        macd_reading=macd_reading,
        kd_reading=kd_reading,
        bollinger_reading=bollinger_reading,
        vote=vote,
        reasons=reasons,
    )


def _analyze_rsi(features: FeatureBundle, state: TechnicalState, section: dict) -> RSIContextualReading:
    thresholds = section["rsi_thresholds"]
    value = features.latest_value("rsi") or Decimal("50")
    if value < Decimal(str(thresholds["extreme_oversold"])):
        base = "extreme_oversold"
    elif value < Decimal(str(thresholds["oversold"])):
        base = "oversold"
    elif value < Decimal(str(thresholds["weak_zone"])):
        base = "weak_zone"
    elif value < Decimal(str(thresholds["healthy_bullish_zone"])):
        base = "healthy_bullish_zone"
    elif value < Decimal(str(thresholds["momentum_hot_zone"])):
        base = "momentum_hot_zone"
    else:
        base = "extreme_overbought"
    contextual_state, warning = _rsi_contextual_state(base, state)
    crossed_event, days_since = _rsi_50_event(features.rsi_series, section["rsi_50_axis"])
    return RSIContextualReading(
        value=quantize(value),
        base_label=base,
        contextual_state=contextual_state,
        warning_level=warning,
        crossed_50_event=crossed_event,
        days_since_crossover=days_since,
    )


def _rsi_contextual_state(base: str, state: TechnicalState) -> tuple[str, str]:
    if base == "momentum_hot_zone":
        if state in {TechnicalState.STRONG_UPTREND, TechnicalState.STEADY_UPTREND}:
            return "momentum_hot_zone_in_uptrend", "low"
        if state in {TechnicalState.TIGHT_CONSOLIDATION, TechnicalState.CONSOLIDATION}:
            return "momentum_breakout_attempt", "medium"
        if state == TechnicalState.WEAK_REBOUND:
            return "momentum_resistance_test_in_downtrend", "high"
        if state == TechnicalState.HIGH_LEVEL_DISTRIBUTION:
            return "momentum_distribution_warning", "high"
    if base == "extreme_overbought":
        if state == TechnicalState.PARABOLIC_OVERHEAT:
            return "parabolic_top_warning", "critical"
        return "extreme_overbought", "high"
    if base == "healthy_bullish_zone":
        if state in {TechnicalState.STRONG_UPTREND, TechnicalState.STEADY_UPTREND, TechnicalState.EARLY_STRENGTHENING}:
            return "healthy_momentum_supporting_trend", "low"
        if state in {TechnicalState.DOWNTREND_CONTINUATION, TechnicalState.WEAK_REBOUND, TechnicalState.EARLY_WEAKENING}:
            return "momentum_rebound_unconfirmed", "medium"
    if base == "weak_zone":
        if state == TechnicalState.STRONG_UPTREND:
            return "momentum_divergence_warning", "high"
        if state == TechnicalState.DOWNTREND_CONTINUATION:
            return "momentum_aligned_bearish", "low"
    if base == "oversold":
        if state == TechnicalState.DOWNTREND_CONTINUATION:
            return "oversold_in_downtrend", "medium"
        if state == TechnicalState.SELLING_CLIMAX:
            return "oversold_climax_candidate", "low"
    if base == "extreme_oversold" and state == TechnicalState.SELLING_CLIMAX:
        return "panic_oversold_climax", "low"
    return "momentum_unclassified", "medium"


def _rsi_50_event(series: tuple[Optional[Decimal], ...], rules: dict) -> tuple[Optional[str], Optional[int]]:
    valid = [value for value in series if value is not None]
    if len(valid) < 2:
        return None, None
    recency = int(rules["crossover_recency_days"])
    held_days = int(rules["held_min_days"])
    last_values = valid[-max(recency + 1, held_days):]
    for offset in range(1, min(recency, len(last_values) - 1) + 1):
        previous = last_values[-offset - 1]
        current = last_values[-offset]
        if previous < Decimal("50") <= current:
            return "crossed_above_50", offset - 1
        if previous > Decimal("50") >= current:
            return "crossed_below_50", offset - 1
    if len(last_values) >= held_days and all(value >= Decimal("50") for value in last_values[-held_days:]):
        return "held_above_50", 0
    if len(last_values) >= held_days and all(value <= Decimal("50") for value in last_values[-held_days:]):
        return "held_below_50", 0
    return None, None


def _analyze_macd(features: FeatureBundle, state: TechnicalState, section: dict) -> MACDContextualReading:
    dif = features.latest_value("macd") or ZERO
    dea = features.latest_value("macd_signal") or ZERO
    histogram = features.latest_value("macd_histogram") or ZERO
    hist_values = [value for value in features.macd_histogram if value is not None]
    consecutive = _consecutive_histogram_change(hist_values, int(section["macd"]["histogram_consecutive_change_days"]))
    histogram_trend = _histogram_trend(hist_values, consecutive)
    crossover_event, crossover_days = _macd_crossover(features.macd_line, features.macd_signal)
    zero_axis_event = _macd_zero_axis(features.macd_line)
    contextual_state, warning = _macd_contextual_state(dif, dea, histogram, histogram_trend, state, crossover_event, zero_axis_event, consecutive, section)
    return MACDContextualReading(
        dif=quantize(dif),
        dea=quantize(dea),
        histogram=quantize(histogram),
        contextual_state=contextual_state,
        warning_level=warning,
        crossover_event=crossover_event,
        crossover_recency_days=crossover_days,
        zero_axis_event=zero_axis_event,
        histogram_trend=histogram_trend,
        histogram_consecutive_change_days=consecutive,
    )


def _macd_contextual_state(
    dif: Decimal,
    dea: Decimal,
    histogram: Decimal,
    histogram_trend: str,
    state: TechnicalState,
    crossover_event: Optional[str],
    zero_axis_event: Optional[str],
    consecutive: int,
    section: dict,
) -> tuple[str, str]:
    compression_max = Decimal(str(section["macd"]["compression_max_dif_dea_diff"]))
    if crossover_event == "golden_cross_below_zero" and state == TechnicalState.WEAK_REBOUND:
        return "weak_golden_cross", "medium"
    if crossover_event == "golden_cross_above_zero" and state == TechnicalState.EARLY_STRENGTHENING:
        return "confirmation_golden_cross", "low"
    if crossover_event == "death_cross_above_zero" and state == TechnicalState.STRONG_UPTREND:
        return "momentum_cooling_not_reversal", "medium"
    if crossover_event == "death_cross_below_zero" and state == TechnicalState.EARLY_WEAKENING:
        return "confirmation_death_cross", "high"
    if dif > dea > ZERO and histogram > ZERO and histogram_trend == "expanding_positive" and state in {TechnicalState.STRONG_UPTREND, TechnicalState.STEADY_UPTREND}:
        return "macd_aligned_bullish_with_trend", "low"
    if dif > dea > ZERO and histogram_trend == "shrinking_positive" and state == TechnicalState.STRONG_UPTREND:
        return "macd_momentum_cooling_in_uptrend", "medium"
    if dif > dea and dif < ZERO and state == TechnicalState.WEAK_REBOUND:
        return "macd_weak_rebound_below_zero", "high"
    if zero_axis_event == "zero_axis_crossed_up":
        return "macd_zero_axis_crossed_up", "low"
    if zero_axis_event == "zero_axis_crossed_down":
        return "macd_zero_axis_crossed_down", "high"
    if dif < dea < ZERO and histogram_trend == "expanding_negative" and state == TechnicalState.DOWNTREND_CONTINUATION:
        return "macd_aligned_bearish_with_trend", "low"
    if histogram_trend == "shrinking_positive" and consecutive >= 3 and state == TechnicalState.STRONG_UPTREND:
        return "macd_histogram_weakening_in_uptrend", "medium"
    if histogram_trend == "shrinking_negative" and state == TechnicalState.EARLY_WEAKENING:
        return "macd_histogram_rebounding_from_weak", "low"
    if abs(dif - dea) < compression_max and state in {TechnicalState.TIGHT_CONSOLIDATION, TechnicalState.CONSOLIDATION}:
        return "macd_compression_pending_direction", "low"
    return "macd_unclassified", "medium"


def _macd_crossover(macd_line: tuple[Optional[Decimal], ...], signal_line: tuple[Optional[Decimal], ...]) -> tuple[Optional[str], Optional[int]]:
    if len(macd_line) < 2 or len(signal_line) < 2:
        return None, None
    pairs = [(m, s) for m, s in zip(macd_line, signal_line) if m is not None and s is not None]
    if len(pairs) < 2:
        return None, None
    prev_dif, prev_dea = pairs[-2]
    curr_dif, curr_dea = pairs[-1]
    if prev_dif < prev_dea and curr_dif >= curr_dea:
        return ("golden_cross_above_zero" if curr_dif > ZERO else "golden_cross_below_zero"), 0
    if prev_dif > prev_dea and curr_dif <= curr_dea:
        return ("death_cross_above_zero" if curr_dif > ZERO else "death_cross_below_zero"), 0
    return None, None


def _macd_zero_axis(macd_line: tuple[Optional[Decimal], ...]) -> Optional[str]:
    valid = [value for value in macd_line if value is not None]
    if len(valid) < 2:
        return None
    if valid[-2] < ZERO <= valid[-1]:
        return "zero_axis_crossed_up"
    if valid[-2] > ZERO >= valid[-1]:
        return "zero_axis_crossed_down"
    return None


def _consecutive_histogram_change(values: list[Decimal], min_days: int) -> int:
    if len(values) < 2:
        return 0
    streak = 0
    direction = "up" if values[-1] > values[-2] else "down" if values[-1] < values[-2] else "flat"
    if direction == "flat":
        return 0
        
    # 從最新的一天往前推，計算當前趨勢維持了幾天
    for i in range(len(values) - 1, 0, -1):
        curr = values[i]
        prev = values[i - 1]
        current_direction = "up" if curr > prev else "down" if curr < prev else "flat"
        if current_direction == direction:
            streak += 1
        else:
            break
    return streak


def _histogram_trend(values: list[Decimal], consecutive: int) -> str:
    if len(values) < 2:
        return "flat"
    if values[-1] >= ZERO and values[-2] >= ZERO:
        return "expanding_positive" if values[-1] > values[-2] else "shrinking_positive"
    if values[-1] < ZERO and values[-2] < ZERO:
        return "expanding_negative" if values[-1] < values[-2] else "shrinking_negative"
    return "flat"


def _analyze_kd(features: FeatureBundle, state: TechnicalState, section: dict) -> KDContextualReading:
    kd_rules = section["kd"]
    k_value = features.latest_value("kd_k") or Decimal("50")
    d_value = features.latest_value("kd_d") or Decimal("50")
    high_dulling_days = _consecutive_threshold_days(features.kd_k, Decimal(str(kd_rules["high_dulling_threshold"])), above=True)
    low_dulling_days = _consecutive_threshold_days(features.kd_k, Decimal(str(kd_rules["low_dulling_threshold"])), above=False)
    crossover_event = _kd_crossover(features.kd_k, features.kd_d)
    contextual_state, warning = _kd_contextual_state(
        state,
        k_value,
        high_dulling_days,
        low_dulling_days,
        crossover_event,
        kd_rules,
    )
    return KDContextualReading(
        k_value=quantize(k_value),
        d_value=quantize(d_value),
        contextual_state=contextual_state,
        warning_level=warning,
        high_dulling_days=high_dulling_days,
        low_dulling_days=low_dulling_days,
        crossover_event=crossover_event,
    )


def _consecutive_threshold_days(series: tuple[Optional[Decimal], ...], threshold: Decimal, above: bool) -> int:
    days = 0
    for value in reversed(series):
        if value is None:
            break
        if (above and value > threshold) or (not above and value < threshold):
            days += 1
        else:
            break
    return days


def _kd_crossover(k_series: tuple[Optional[Decimal], ...], d_series: tuple[Optional[Decimal], ...]) -> Optional[str]:
    pairs = [(k, d) for k, d in zip(k_series, d_series) if k is not None and d is not None]
    if len(pairs) < 2:
        return None
    prev_k, prev_d = pairs[-2]
    curr_k, curr_d = pairs[-1]
    if prev_k < prev_d and curr_k >= curr_d:
        return "kd_golden_cross_low" if curr_k < Decimal("50") else "kd_golden_cross_high"
    if prev_k > prev_d and curr_k <= curr_d:
        return "kd_death_cross_high" if curr_k > Decimal("50") else "kd_death_cross_low"
    return None


def _kd_contextual_state(
    state: TechnicalState,
    k_value: Decimal,
    high_dulling_days: int,
    low_dulling_days: int,
    crossover_event: Optional[str],
    kd_rules: dict,
) -> tuple[str, str]:
    dulling_min = int(kd_rules["dulling_min_days"])
    if high_dulling_days >= dulling_min:
        if state in {TechnicalState.STRONG_UPTREND, TechnicalState.STEADY_UPTREND}:
            return "kd_high_dulling_healthy", "low"
        if state in {TechnicalState.TIGHT_CONSOLIDATION, TechnicalState.CONSOLIDATION}:
            return "kd_high_dulling_breakout_candidate", "medium"
        if state == TechnicalState.HIGH_LEVEL_DISTRIBUTION:
            return "kd_high_dulling_distribution_warning", "high"
    if low_dulling_days >= dulling_min:
        if state == TechnicalState.DOWNTREND_CONTINUATION:
            return "kd_low_dulling_bearish_continuation", "low"
        if state == TechnicalState.SELLING_CLIMAX:
            return "kd_low_dulling_climax_candidate", "medium"
    if crossover_event == "kd_golden_cross_low":
        return "kd_golden_cross_low_level", "low"
    if crossover_event == "kd_golden_cross_high":
        return "kd_golden_cross_redundant", "low"
    if crossover_event == "kd_death_cross_high" and state == TechnicalState.HIGH_LEVEL_DISTRIBUTION:
        return "kd_death_cross_distribution", "high"
    if crossover_event == "kd_death_cross_low" and state == TechnicalState.WEAK_REBOUND:
        return "kd_death_cross_weak_rebound_fail", "high"
    return "kd_unclassified", "medium"


def _analyze_bollinger(features: FeatureBundle, state: TechnicalState, section: dict) -> BollingerContextualReading:
    upper = features.latest_value("bb_upper") or features.latest_close()
    middle = features.latest_value("bb_middle") or features.latest_close()
    lower = features.latest_value("bb_lower") or features.latest_close()
    bandwidth = ((upper - lower) / middle * HUNDRED) if middle != ZERO else ZERO
    series = [value for value in features.bollinger_bandwidth_series if value is not None]
    latest_bandwidth = series[-1] if series else bandwidth
    percentile = percentile_rank(latest_bandwidth, series) or Decimal("50")
    bollinger_rules = section["bollinger"]
    compression = percentile <= Decimal(str(bollinger_rules["bandwidth_compression_percentile"]))
    expansion = percentile >= Decimal(str(bollinger_rules["bandwidth_expansion_percentile"]))
    candle = compute_candle_features(features.series.latest())
    close = features.latest_close()
    if compression and state in {TechnicalState.TIGHT_CONSOLIDATION, TechnicalState.CONSOLIDATION} and abs(close - middle) / middle * HUNDRED < Decimal("2"):
        contextual_state = "volatility_squeeze_pending_breakout"
    elif expansion and close > upper:
        contextual_state = "volatility_expansion_upward"
    elif expansion and close < lower:
        contextual_state = "volatility_expansion_downward"
    elif close >= upper and (candle["upper_shadow_ratio"] or ZERO) > Decimal(str(bollinger_rules["upper_band_rejection_shadow_threshold"])):
        contextual_state = "upper_band_rejection"
    elif close <= lower and (candle["lower_shadow_ratio"] or ZERO) > Decimal(str(bollinger_rules["lower_band_absorption_shadow_threshold"])):
        contextual_state = "lower_band_absorption"
    else:
        contextual_state = "bollinger_unclassified"
    return BollingerContextualReading(
        upper_band=quantize(upper),
        middle_band=quantize(middle),
        lower_band=quantize(lower),
        bandwidth=quantize(bandwidth),
        bandwidth_percentile_120d=quantize(percentile),
        contextual_state=contextual_state,
        band_compression=compression,
        band_expansion=expansion,
    )


def _assemble_vote(
    features: FeatureBundle,
    rsi: RSIContextualReading,
    macd: MACDContextualReading,
    kd: KDContextualReading,
    bollinger: BollingerContextualReading,
    section: dict,
) -> tuple[FactorVote, list[ReasonTrace]]:
    mapping = section["contextual_vote_mapping"]
    weights = section["vote_weights"]
    kd_weight = Decimal(str(weights["kd_short_term"] if features.horizon == Horizon.SHORT_TERM else weights["kd_swing"] if features.horizon == Horizon.SWING else weights["kd_long_term"]))
    weighted_parts = [
        (rsi.contextual_state, Decimal(str(weights["rsi"]))),
        (macd.contextual_state, Decimal(str(weights["macd"]))),
        (kd.contextual_state, kd_weight),
        (bollinger.contextual_state, Decimal(str(weights["bollinger"]))),
    ]
    score = ZERO
    reasons: list[ReasonTrace] = []
    forced_direction: Optional[TrendDirection] = None
    forced_strength = ZERO
    for state_name, weight in weighted_parts:
        if state_name not in mapping or weight == ZERO:
            continue
        vote_rule = mapping[state_name]
        direction = TrendDirection(vote_rule["direction"])
        strength = Decimal(str(vote_rule["strength"]))
        score += _signed(direction) * strength * weight
        if vote_rule.get("critical"):
            forced_direction = direction
            forced_strength = max(forced_strength, Decimal(str(section["critical_warning_min_strength"])))
        reasons.append(
            ReasonTrace(
                reason_text=f"動能狀態 {state_name}",
                source_field="momentum_contextual",
                timestamp=features.series.latest().date,
                calculation="contextual vote mapping",
                calculation_value=strength,
            )
        )
    if forced_direction is not None:
        vote_direction = forced_direction
        vote_strength = forced_strength
    elif abs(score) < Decimal("0.2"):
        vote_direction = TrendDirection.NEUTRAL
        vote_strength = abs(score)
    else:
        vote_direction = TrendDirection.BULLISH if score > ZERO else TrendDirection.BEARISH
        vote_strength = abs(score)
    vote = FactorVote(
        category=FactorCategory.MOMENTUM,
        direction=vote_direction,
        strength=quantize(clamp(vote_strength, ZERO, Decimal("1"))),
        reasons=tuple(reasons),
    )
    return vote, reasons


def _signed(direction: TrendDirection) -> Decimal:
    if direction == TrendDirection.BULLISH:
        return Decimal("1")
    if direction == TrendDirection.BEARISH:
        return Decimal("-1")
    return ZERO
