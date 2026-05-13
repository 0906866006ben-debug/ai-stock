"""Topic F: volume-price quadrant and turnover-quality assessment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Literal

from ..common import HUNDRED, ONE, ZERO, clamp, pct_change, quantize
from ..contracts.enums import FactorCategory, Horizon, TechnicalState, TrendDirection
from ..contracts.feature_contract import FeatureBundle
from ..contracts.input_contract import ContextBundle
from ..contracts.output_contract import FactorVote
from ..registry.rule_registry import RuleRegistry
from ..traceability.trace import ReasonTrace
from .candle_features import compute_candle_features


class VolumePriceSubClass(str, Enum):
    HEALTHY_BREAKOUT_VOLUME = "healthy_breakout_volume"
    DISTRIBUTION_VOLUME_RISK = "distribution_volume_risk"
    NEUTRAL_VOLUME_RISE = "neutral_volume_rise"
    CONSOLIDATION_DRYING_UP = "consolidation_drying_up"
    BREAKOUT_NO_VOLUME_RISK = "breakout_no_volume_risk"
    NEUTRAL_VOLUME_DECLINE = "neutral_volume_decline"
    SELLING_PRESSURE = "selling_pressure"
    ABSORPTION_CANDIDATE = "absorption_candidate"
    NEUTRAL_DECLINE_WITH_VOLUME = "neutral_decline_with_volume"
    HEALTHY_PULLBACK = "healthy_pullback"
    WEAK_NO_VOLUME_DECLINE = "weak_no_volume_decline"
    NEUTRAL_DECLINE_NO_VOLUME = "neutral_decline_no_volume"
    FLAT_PRICE = "flat_price"
    FLAT_VOLUME = "flat_volume"


@dataclass(frozen=True)
class VolumePriceQuadrantResult:
    quadrant: Literal["Q1", "Q2", "Q3", "Q4", "FLAT", "FLAT_VOLUME"]
    sub_classification: VolumePriceSubClass
    today_turnover_value: Decimal
    adjusted_turnover_value: Decimal
    turnover_value_ratio_20_raw: Decimal
    turnover_value_ratio_20_adjusted: Decimal
    day_trading_ratio: Decimal
    day_trading_distortion_level: Literal["normal", "notice", "warning", "distorted"]
    is_day_trading_distorted: bool
    vote: FactorVote
    reasons: list[ReasonTrace]


VOTE_MAPPING: dict[VolumePriceSubClass, tuple[TrendDirection, Decimal]] = {
    VolumePriceSubClass.HEALTHY_BREAKOUT_VOLUME: (TrendDirection.BULLISH, Decimal("0.8")),
    VolumePriceSubClass.DISTRIBUTION_VOLUME_RISK: (TrendDirection.BEARISH, Decimal("0.7")),
    VolumePriceSubClass.CONSOLIDATION_DRYING_UP: (TrendDirection.NEUTRAL_BULLISH, Decimal("0.4")),
    VolumePriceSubClass.BREAKOUT_NO_VOLUME_RISK: (TrendDirection.BEARISH, Decimal("0.5")),
    VolumePriceSubClass.SELLING_PRESSURE: (TrendDirection.BEARISH, Decimal("0.85")),
    VolumePriceSubClass.ABSORPTION_CANDIDATE: (TrendDirection.NEUTRAL, Decimal("0.5")),
    VolumePriceSubClass.HEALTHY_PULLBACK: (TrendDirection.NEUTRAL_BULLISH, Decimal("0.4")),
    VolumePriceSubClass.WEAK_NO_VOLUME_DECLINE: (TrendDirection.BEARISH, Decimal("0.5")),
}


def analyze_volume_price_quadrant(
    features: FeatureBundle,
    context: ContextBundle,
    registry: RuleRegistry | None = None,
) -> VolumePriceQuadrantResult:
    """Assess price/turnover interaction with TW day-trading distortion control."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("volume_price_quadrant")
    latest = features.series.latest()
    previous = features.series.previous() or latest
    close_change = pct_change(latest.close, previous.close, default=ZERO) or ZERO
    vma20 = features.turnover_value_20d_avg or _rolling_turnover_average(features.series, 20)
    raw_ratio = latest.turnover_value / vma20 if vma20 and vma20 != ZERO else ZERO
    day_trading_ratio = context.day_trading_ratio or ZERO
    coefficient = Decimal(str(section["day_trading_offset_coefficient"]))
    adjusted_turnover = latest.turnover_value * (ONE - day_trading_ratio * coefficient)
    adjusted_ratio = adjusted_turnover / vma20 if vma20 and vma20 != ZERO else ZERO
    distortion_level = _distortion_level(day_trading_ratio, section)
    distorted = distortion_level == "distorted"

    if context.disposition_status in {"stage_1", "stage_2"}:
        neutral_vote = FactorVote(
            category=FactorCategory.VOLUME_QUALITY,
            direction=TrendDirection.NEUTRAL,
            strength=ZERO,
            reasons=(),
        )
        reason = _reason(features, "disposition_status", "處置股期間量價訊號暫停採信", "disposition_status in stage_1/2", ZERO)
        return VolumePriceQuadrantResult(
            quadrant="FLAT",
            sub_classification=VolumePriceSubClass.FLAT_PRICE,
            today_turnover_value=latest.turnover_value,
            adjusted_turnover_value=adjusted_turnover,
            turnover_value_ratio_20_raw=quantize(raw_ratio),
            turnover_value_ratio_20_adjusted=quantize(adjusted_ratio),
            day_trading_ratio=day_trading_ratio,
            day_trading_distortion_level=distortion_level,
            is_day_trading_distorted=distorted,
            vote=neutral_vote,
            reasons=[reason],
        )

    candle = compute_candle_features(latest, registry=rules)
    flat_threshold = Decimal(str(section["price_change_flat_threshold_pct"]))
    volume_increase = Decimal(str(section["volume_increase_ratio"]))
    volume_decline = Decimal(str(section["volume_decline_ratio"]))

    if -flat_threshold <= close_change <= flat_threshold:
        quadrant = "FLAT"
        sub_class = VolumePriceSubClass.FLAT_PRICE
    elif volume_decline <= adjusted_ratio <= volume_increase:
        quadrant = "FLAT_VOLUME"
        sub_class = VolumePriceSubClass.FLAT_VOLUME
    elif close_change > ZERO and adjusted_ratio > volume_increase:
        quadrant, sub_class = "Q1", _classify_q1(features, context, adjusted_ratio, candle, section)
    elif close_change > ZERO and adjusted_ratio < volume_decline:
        quadrant, sub_class = "Q2", _classify_q2(features, adjusted_ratio, section)
    elif close_change < ZERO and adjusted_ratio > volume_increase:
        quadrant, sub_class = "Q3", _classify_q3(features, context, adjusted_ratio, candle, section)
    else:
        quadrant, sub_class = "Q4", _classify_q4(features, adjusted_ratio)

    direction, strength = VOTE_MAPPING.get(sub_class, (TrendDirection.NEUTRAL, ZERO))
    reasons = [
        _reason(
            features,
            "turnover_value_ratio_20_adjusted",
            f"量價分類為 {sub_class.value}",
            "adjusted_turnover_ratio with candle and state filters",
            quantize(adjusted_ratio),
        )
    ]
    if distorted:
        multiplier = Decimal(str(section["distorted_strength_multiplier"]))
        strength *= multiplier
        if strength < Decimal(str(section["distorted_vote_neutral_threshold"])):
            direction = TrendDirection.NEUTRAL
            strength = ZERO
        reasons.append(
            _reason(
                features,
                "day_trading_ratio",
                "當沖比過高，量能訊號可信度下修",
                "day_trading_ratio > distortion threshold",
                quantize(day_trading_ratio),
            )
        )

    vote = FactorVote(
        category=FactorCategory.VOLUME_QUALITY,
        direction=direction,
        strength=quantize(clamp(strength, ZERO, ONE)),
        reasons=tuple(reasons),
    )
    return VolumePriceQuadrantResult(
        quadrant=quadrant,
        sub_classification=sub_class,
        today_turnover_value=latest.turnover_value,
        adjusted_turnover_value=quantize(adjusted_turnover),
        turnover_value_ratio_20_raw=quantize(raw_ratio),
        turnover_value_ratio_20_adjusted=quantize(adjusted_ratio),
        day_trading_ratio=quantize(day_trading_ratio),
        day_trading_distortion_level=distortion_level,
        is_day_trading_distorted=distorted,
        vote=vote,
        reasons=reasons,
    )


def _classify_q1(features: FeatureBundle, context: ContextBundle, adjusted_ratio: Decimal, candle: dict, rules: dict) -> VolumePriceSubClass:
    horizon_key = "max_deviation_short_term_pct" if features.horizon == Horizon.SHORT_TERM else "max_deviation_swing_pct"
    healthy_rules = rules["healthy_breakout"]
    distribution_rules = rules["distribution_volume_risk"]
    deviation_limit = Decimal(str(healthy_rules[horizon_key]))
    current_close = features.latest_close()
    near_60d_high = features.recent_high_60d and features.recent_high_60d > ZERO and ((features.recent_high_60d - current_close) / features.recent_high_60d * HUNDRED) < Decimal(str(distribution_rules["near_60d_high_threshold_pct"]))
    healthy = (
        features.current_state in {TechnicalState.TIGHT_CONSOLIDATION, TechnicalState.EARLY_STRENGTHENING, TechnicalState.STEADY_UPTREND}
        and (features.deviation_from_ma20_pct or ZERO) < deviation_limit
        and (candle["close_position_in_range"] or ZERO) > Decimal(str(healthy_rules["min_close_position_in_range"]))
        and (candle["upper_shadow_ratio"] or ZERO) < Decimal(str(healthy_rules["max_upper_shadow_ratio"]))
        and (context.foreign_net_buy_3d or ZERO) >= ZERO
        and (context.day_trading_ratio or ZERO) < Decimal(str(healthy_rules["max_day_trading_ratio"]))
    )
    if healthy:
        return VolumePriceSubClass.HEALTHY_BREAKOUT_VOLUME
    distribution = (
        near_60d_high
        and (candle["upper_shadow_ratio"] or ZERO) >= Decimal(str(distribution_rules["long_upper_shadow_threshold"]))
    ) or (
        (candle["close_position_in_range"] or ZERO) < Decimal(str(distribution_rules["weak_close_position_threshold"]))
        and adjusted_ratio > Decimal(str(distribution_rules["extreme_volume_for_distribution"]))
    ) or (
        (context.day_trading_ratio or ZERO) > Decimal("0.60")
    ) or (
        (context.foreign_net_buy_yesterday or ZERO) > ZERO and (context.foreign_net_today or ZERO) < ZERO
    ) or (
        (features.deviation_from_ma20_pct or ZERO) > Decimal(str(distribution_rules["extreme_deviation_short_term_pct"]))
    )
    if distribution:
        return VolumePriceSubClass.DISTRIBUTION_VOLUME_RISK
    return VolumePriceSubClass.NEUTRAL_VOLUME_RISE


def _classify_q2(features: FeatureBundle, adjusted_ratio: Decimal, rules: dict) -> VolumePriceSubClass:
    atr_series = [value for value in features.atr_series if value is not None]
    atr_shrinking = False
    if len(atr_series) >= 10:
        atr_shrinking = sum(atr_series[-5:], ZERO) / Decimal("5") < sum(atr_series[-10:-5], ZERO) / Decimal("5")
    if (
        features.current_state in {TechnicalState.TIGHT_CONSOLIDATION, TechnicalState.CONSOLIDATION}
        and Decimal("0.5") <= adjusted_ratio <= Decimal("0.8")
        and atr_shrinking
        and (features.recent_low_60d is None or (features.latest_close() - features.recent_low_60d) / features.recent_low_60d * HUNDRED > Decimal("5"))
    ):
        return VolumePriceSubClass.CONSOLIDATION_DRYING_UP
    if (
        (features.recent_high_20d is not None and features.latest_close() >= features.recent_high_20d)
        or (features.recent_high_60d is not None and features.latest_close() >= features.recent_high_60d)
    ) and adjusted_ratio < Decimal("0.8"):
        return VolumePriceSubClass.BREAKOUT_NO_VOLUME_RISK
    return VolumePriceSubClass.NEUTRAL_VOLUME_DECLINE


def _classify_q3(features: FeatureBundle, context: ContextBundle, adjusted_ratio: Decimal, candle: dict, rules: dict) -> VolumePriceSubClass:
    ma20 = features.ma_values.get("ma20")
    ma60 = features.ma_values.get("ma60")
    current = features.latest_close()
    selling = (
        (ma20 is not None and current < ma20 and adjusted_ratio > Decimal("1.5"))
        or (ma60 is not None and current < ma60 and adjusted_ratio > Decimal("1.5"))
        or (features.swing_structure is not None and features.swing_structure.swing_lows and current < features.swing_structure.swing_lows[-1].price and adjusted_ratio > Decimal("1.3"))
        or ((candle["close_position_in_range"] or ZERO) < Decimal("0.3") and adjusted_ratio > Decimal("1.5"))
        or ((context.foreign_net_sell_3d or ZERO) > ZERO)
    )
    if selling:
        return VolumePriceSubClass.SELLING_PRESSURE
    absorption_rules = rules["absorption_candidate"]
    near_low = (
        features.recent_low_60d is not None
        and features.recent_low_60d > ZERO
        and ((current - features.recent_low_60d) / features.recent_low_60d * HUNDRED) < Decimal(str(absorption_rules["near_60d_low_threshold_pct"]))
    )
    if (
        (near_low or (features.bias_20_pct or ZERO) < Decimal(str(absorption_rules["bias_zscore_threshold"])))
        and (candle["lower_shadow_ratio"] or ZERO) >= Decimal(str(absorption_rules["min_lower_shadow_ratio"]))
        and (candle["close_position_in_range"] or ZERO) > Decimal(str(absorption_rules["min_close_position"]))
        and adjusted_ratio > Decimal(str(absorption_rules["min_volume_ratio"]))
    ):
        return VolumePriceSubClass.ABSORPTION_CANDIDATE
    return VolumePriceSubClass.NEUTRAL_DECLINE_WITH_VOLUME


def _classify_q4(features: FeatureBundle, adjusted_ratio: Decimal) -> VolumePriceSubClass:
    slope20 = features.ma_slopes_pct.get("ma20", ZERO)
    slope60 = features.ma_slopes_pct.get("ma60", ZERO)
    ma20 = features.ma_values.get("ma20")
    current = features.latest_close()
    if (
        slope20 > ZERO
        and slope60 > ZERO
        and ma20 is not None
        and abs((current - ma20) / ma20 * HUNDRED) < Decimal("5")
        and adjusted_ratio < Decimal("0.8")
        and not (features.swing_structure and features.swing_structure.swing_lows and current < features.swing_structure.swing_lows[-1].price)
    ):
        return VolumePriceSubClass.HEALTHY_PULLBACK
    if slope20 < ZERO or (features.swing_structure and features.swing_structure.bos_down) or features.consecutive_down_closes_5d >= 5:
        return VolumePriceSubClass.WEAK_NO_VOLUME_DECLINE
    return VolumePriceSubClass.NEUTRAL_DECLINE_NO_VOLUME


def _rolling_turnover_average(series, window: int) -> Decimal:
    values = [bar.turnover_value for bar in series.bars[-window:]]
    if not values:
        return ZERO
    return sum(values, ZERO) / Decimal(len(values))


def _distortion_level(day_trading_ratio: Decimal, rules: dict) -> Literal["normal", "notice", "warning", "distorted"]:
    if day_trading_ratio >= Decimal(str(rules["day_trading_distortion_threshold"])):
        return "distorted"
    if day_trading_ratio >= Decimal(str(rules["day_trading_warning_threshold"])):
        return "warning"
    if day_trading_ratio >= Decimal(str(rules["day_trading_notice_threshold"])):
        return "notice"
    return "normal"


def _reason(features: FeatureBundle, source_field: str, reason_text: str, calculation: str, value: Decimal) -> ReasonTrace:
    return ReasonTrace(
        reason_text=reason_text,
        source_field=source_field,
        timestamp=features.series.latest().date,
        calculation=calculation,
        calculation_value=value,
    )
