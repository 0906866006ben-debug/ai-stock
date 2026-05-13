"""Topic N: institutional chip-flow resonance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from ..common import HUNDRED, ONE, ZERO, clamp, quantize
from ..contracts.enums import BreakoutStatus, FactorCategory, TechnicalState, TrendDirection
from ..contracts.feature_contract import FeatureBundle
from ..contracts.input_contract import ContextBundle
from ..contracts.output_contract import FactorVote
from ..features.breakout_quality import BreakoutAnalysisResult
from ..features.candle_patterns import CandlePatternResult
from ..features.volume_price_quadrant import VolumePriceQuadrantResult, VolumePriceSubClass
from ..registry.rule_registry import RuleRegistry
from ..traceability.trace import ReasonTrace


class ChipResonancePattern(str, Enum):
    GOLDEN_RESONANCE_WEAK = "golden_resonance_weak"
    GOLDEN_RESONANCE_STANDARD = "golden_resonance_standard"
    GOLDEN_RESONANCE_STRONG = "golden_resonance_strong"
    FALSE_RALLY_WARNING = "false_rally_warning"
    FALSE_RALLY_HIGH_CONFIDENCE = "false_rally_high_confidence"
    ACCUMULATION_CANDIDATE = "accumulation_candidate"
    CONFIRMED_ACCUMULATION = "confirmed_accumulation"
    INSTITUTIONAL_DEFENSE_CANDIDATE = "institutional_defense_candidate"
    CONFIRMED_INSTITUTIONAL_DEFENSE = "confirmed_institutional_defense"
    CHIP_NEUTRAL = "chip_neutral"
    CHIP_CONFLICTING = "chip_conflicting"


@dataclass(frozen=True)
class ChipFlowResult:
    symbol: str
    analysis_date: date
    resonance_patterns: list[ChipResonancePattern]
    primary_pattern: ChipResonancePattern
    foreign_direction: Literal["buying", "selling", "neutral"]
    trust_direction: Literal["buying", "selling", "neutral"]
    dealer_direction: Literal["buying", "selling", "neutral"]
    are_majors_aligned: bool
    longest_consecutive_streak: int
    longest_streak_party: Literal["foreign", "trust", "dealer"]
    margin_signal: Literal["healthy", "retail_chasing_warning", "neutral"]
    short_interest_signal: Literal["healthy", "short_squeeze_candidate", "neutral"]
    is_chip_data_partial: bool
    state_signal_score_modifier: int
    confidence_cap: Optional[int]
    state_override_required: bool
    state_override_target: Optional[TechnicalState]
    vote: FactorVote
    reasons: list[ReasonTrace]


VOTE_MAP: dict[ChipResonancePattern, tuple[TrendDirection, Decimal]] = {
    ChipResonancePattern.GOLDEN_RESONANCE_STRONG: (TrendDirection.BULLISH, Decimal("0.85")),
    ChipResonancePattern.GOLDEN_RESONANCE_STANDARD: (TrendDirection.BULLISH, Decimal("0.7")),
    ChipResonancePattern.GOLDEN_RESONANCE_WEAK: (TrendDirection.BULLISH, Decimal("0.5")),
    ChipResonancePattern.FALSE_RALLY_HIGH_CONFIDENCE: (TrendDirection.BEARISH, Decimal("0.85")),
    ChipResonancePattern.FALSE_RALLY_WARNING: (TrendDirection.BEARISH, Decimal("0.6")),
    ChipResonancePattern.ACCUMULATION_CANDIDATE: (TrendDirection.NEUTRAL_BULLISH, Decimal("0.4")),
    ChipResonancePattern.CONFIRMED_ACCUMULATION: (TrendDirection.BULLISH, Decimal("0.6")),
    ChipResonancePattern.INSTITUTIONAL_DEFENSE_CANDIDATE: (TrendDirection.BULLISH, Decimal("0.5")),
    ChipResonancePattern.CONFIRMED_INSTITUTIONAL_DEFENSE: (TrendDirection.BULLISH, Decimal("0.6")),
    ChipResonancePattern.CHIP_NEUTRAL: (TrendDirection.NEUTRAL, ZERO),
    ChipResonancePattern.CHIP_CONFLICTING: (TrendDirection.NEUTRAL, ZERO),
}


def analyze_chip_resonance(
    symbol: str,
    features: FeatureBundle,
    context: ContextBundle,
    breakout_result: Optional[BreakoutAnalysisResult] = None,
    candle_result: Optional[CandlePatternResult] = None,
    quadrant_result: Optional[VolumePriceQuadrantResult] = None,
    registry: RuleRegistry | None = None,
) -> ChipFlowResult:
    """Classify institutional resonance using public chip fields from ContextBundle."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("chip_resonance")
    patterns: list[ChipResonancePattern] = []
    reasons: list[ReasonTrace] = []
    is_partial = _is_chip_data_partial(context)

    if _is_conflicting(context):
        patterns.append(ChipResonancePattern.CHIP_CONFLICTING)
        reasons.append(_reason(features, "foreign/trust/dealer", "三大法人方向不一致", "major directions are mixed", ZERO))
    golden = _golden_resonance(features, context, breakout_result, candle_result, quadrant_result, section)
    if golden:
        patterns.append(golden)
        reasons.append(_reason(features, "institutional_net", f"偵測到 {golden.value}", "breakout + institutional buy", Decimal("1")))
    false_rally = _false_rally(features, context, section)
    if false_rally:
        patterns.append(false_rally)
        reasons.append(_reason(features, "margin_balance_change_pct_3d", f"偵測到 {false_rally.value}", "new high + margin chasing + institutional sell", context.margin_balance_change_pct_3d or ZERO))
    accumulation = _accumulation(features, context, section)
    if accumulation:
        patterns.append(accumulation)
        reasons.append(_reason(features, "ownership_change_5d_pct", f"偵測到 {accumulation.value}", "consolidation + institutional accumulation", Decimal("1")))
    defense = _institutional_defense(features, context, quadrant_result, section)
    if defense:
        patterns.append(defense)
        reasons.append(_reason(features, "foreign_net_5d", f"偵測到 {defense.value}", "MA20 pullback + institutional buy", context.foreign_net_5d or ZERO))

    if not patterns:
        patterns = [ChipResonancePattern.CHIP_NEUTRAL]
        reasons.append(_reason(features, "chip_flow", "籌碼未出現明確共振", "no chip resonance pattern", ZERO))

    primary = _choose_primary(patterns)
    direction, strength = VOTE_MAP[primary]
    if is_partial:
        strength *= Decimal(str(section["partial_data_strength_multiplier"]))
        reasons.append(_reason(features, "large_order_ratio", "籌碼資料不完整，強度下修", "partial data strength multiplier", strength))

    modifier, cap, override, override_target = _state_effect(primary, features.current_state, is_partial, section)
    vote = FactorVote(
        category=FactorCategory.CHIP_FLOW,
        direction=direction,
        strength=quantize(clamp(strength, ZERO, ONE)),
        reasons=tuple(reasons),
    )
    return ChipFlowResult(
        symbol=symbol,
        analysis_date=features.series.latest().date,
        resonance_patterns=patterns,
        primary_pattern=primary,
        foreign_direction=_direction(context.foreign_net_today),
        trust_direction=_direction(context.trust_net_today),
        dealer_direction=_direction(context.dealer_net_today),
        are_majors_aligned=_are_aligned(context),
        longest_consecutive_streak=_longest_streak(context)[0],
        longest_streak_party=_longest_streak(context)[1],
        margin_signal="retail_chasing_warning" if (context.margin_balance_change_pct_3d or ZERO) > Decimal(str(section["false_rally"]["margin_balance_3d_change_pct"])) else "neutral",
        short_interest_signal="short_squeeze_candidate" if (context.short_to_long_ratio or ZERO) > Decimal("0.5") else "neutral",
        is_chip_data_partial=is_partial,
        state_signal_score_modifier=modifier,
        confidence_cap=cap,
        state_override_required=override,
        state_override_target=override_target,
        vote=vote,
        reasons=reasons,
    )


def _golden_resonance(features: FeatureBundle, context: ContextBundle, breakout: Optional[BreakoutAnalysisResult], candle: Optional[CandlePatternResult], quadrant: Optional[VolumePriceQuadrantResult], rules: dict) -> Optional[ChipResonancePattern]:
    valid_breakout = breakout and breakout.status in {BreakoutStatus.CONFIRMED_HEALTHY_BREAKOUT, BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION}
    valid_candle = candle and any(event.pattern_name in {"long_bullish_candle", "marubozu_bullish"} for event in candle.events_today)
    valid_quadrant = quadrant and quadrant.sub_classification == VolumePriceSubClass.HEALTHY_BREAKOUT_VOLUME
    double_buy = (context.foreign_net_today or ZERO) > ZERO and (context.trust_net_today or ZERO) > ZERO
    if not (valid_breakout and valid_candle and valid_quadrant and double_buy):
        return None
    if (context.foreign_consecutive_days or 0) < int(rules["golden_resonance"]["min_foreign_consecutive_days"]):
        return ChipResonancePattern.GOLDEN_RESONANCE_WEAK
    if (context.foreign_net_value_5d or ZERO) > Decimal(str(rules["golden_resonance"]["strong_foreign_5d_value_threshold"])) or (context.trust_consecutive_days or 0) >= int(rules["golden_resonance"]["strong_trust_consecutive_days"]):
        return ChipResonancePattern.GOLDEN_RESONANCE_STRONG
    return ChipResonancePattern.GOLDEN_RESONANCE_STANDARD


def _false_rally(features: FeatureBundle, context: ContextBundle, rules: dict) -> Optional[ChipResonancePattern]:
    new_high = features.latest_close() >= (features.recent_high_20d or features.latest_close()) or features.latest_close() >= (features.recent_high_60d or features.latest_close())
    margin_chasing = (context.margin_balance_change_pct_3d or ZERO) > Decimal(str(rules["false_rally"]["margin_balance_3d_change_pct"]))
    foreign_sell = (context.foreign_net_today or ZERO) < ZERO or (context.three_majors_net_today or ZERO) < ZERO
    if not (new_high and margin_chasing and foreign_sell):
        return None
    if (context.foreign_net_5d or ZERO) < ZERO and abs(context.foreign_net_value_5d or ZERO) >= Decimal(str(rules["false_rally"]["high_confidence_5d_value_threshold"])):
        return ChipResonancePattern.FALSE_RALLY_HIGH_CONFIDENCE
    return ChipResonancePattern.FALSE_RALLY_WARNING


def _accumulation(features: FeatureBundle, context: ContextBundle, rules: dict) -> Optional[ChipResonancePattern]:
    if features.current_state not in {TechnicalState.TIGHT_CONSOLIDATION, TechnicalState.CONSOLIDATION, TechnicalState.EARLY_STRENGTHENING}:
        return None
    atr_values = [value for value in features.atr_series if value is not None]
    atr_dryup = len(atr_values) >= 10 and sum(atr_values[-5:], ZERO) / Decimal("5") < sum(atr_values[-10:-5], ZERO) / Decimal("5")
    if rules["accumulation"]["require_atr_dryup"] and not atr_dryup:
        return None
    streak = max(context.foreign_consecutive_days or 0, context.trust_consecutive_days or 0)
    ownership_up = (context.foreign_ownership_change_5d_pct or ZERO) > ZERO or (context.trust_ownership_change_5d_pct or ZERO) > ZERO
    if streak < int(rules["accumulation"]["min_institutional_consecutive_days"]) or not ownership_up:
        return None
    if features.recent_high_60d and features.recent_high_60d > ZERO:
        distance_from_high = (features.recent_high_60d - features.latest_close()) / features.recent_high_60d * HUNDRED
        if distance_from_high <= Decimal(str(rules["accumulation"]["forbidden_distance_from_60d_high_pct"])):
            return None
    if (context.foreign_net_value_20d or ZERO) >= Decimal(str(rules["accumulation"]["confirmed_foreign_20d_value_threshold"])):
        return ChipResonancePattern.CONFIRMED_ACCUMULATION
    return ChipResonancePattern.ACCUMULATION_CANDIDATE


def _institutional_defense(features: FeatureBundle, context: ContextBundle, quadrant: Optional[VolumePriceQuadrantResult], rules: dict) -> Optional[ChipResonancePattern]:
    if features.current_state not in {TechnicalState.STRONG_UPTREND, TechnicalState.STEADY_UPTREND}:
        return None
    ma20 = features.ma_values.get("ma20")
    near_ma20 = ma20 is not None and abs((features.latest_close() - ma20) / ma20 * HUNDRED) <= Decimal(str(rules["institutional_defense"]["near_ma20_pct"]))
    q4_pullback = quadrant and quadrant.quadrant == "Q4"
    institution_buy = (context.foreign_net_today or ZERO) > ZERO or (context.trust_net_today or ZERO) > ZERO
    if not ((near_ma20 or q4_pullback) and institution_buy):
        return None
    if (context.foreign_net_5d or ZERO) > ZERO or (context.trust_net_5d or ZERO) > ZERO:
        return ChipResonancePattern.CONFIRMED_INSTITUTIONAL_DEFENSE
    return ChipResonancePattern.INSTITUTIONAL_DEFENSE_CANDIDATE


def _choose_primary(patterns: list[ChipResonancePattern]) -> ChipResonancePattern:
    priority = [
        ChipResonancePattern.FALSE_RALLY_HIGH_CONFIDENCE,
        ChipResonancePattern.GOLDEN_RESONANCE_STRONG,
        ChipResonancePattern.FALSE_RALLY_WARNING,
        ChipResonancePattern.GOLDEN_RESONANCE_STANDARD,
        ChipResonancePattern.CONFIRMED_ACCUMULATION,
        ChipResonancePattern.CONFIRMED_INSTITUTIONAL_DEFENSE,
        ChipResonancePattern.GOLDEN_RESONANCE_WEAK,
        ChipResonancePattern.ACCUMULATION_CANDIDATE,
        ChipResonancePattern.INSTITUTIONAL_DEFENSE_CANDIDATE,
        ChipResonancePattern.CHIP_CONFLICTING,
        ChipResonancePattern.CHIP_NEUTRAL,
    ]
    return min(patterns, key=lambda pattern: priority.index(pattern) if pattern in priority else len(priority))


def _state_effect(primary: ChipResonancePattern, current_state: TechnicalState, is_partial: bool, rules: dict) -> tuple[int, Optional[int], bool, Optional[TechnicalState]]:
    cap = int(rules["partial_data_confidence_cap"]) if is_partial else None
    if primary == ChipResonancePattern.FALSE_RALLY_HIGH_CONFIDENCE:
        return -20, cap or 55, current_state == TechnicalState.STRONG_UPTREND, TechnicalState.HIGH_LEVEL_DISTRIBUTION if current_state == TechnicalState.STRONG_UPTREND else None
    if primary == ChipResonancePattern.FALSE_RALLY_WARNING:
        return -10, cap or 70, False, None
    if primary in {ChipResonancePattern.GOLDEN_RESONANCE_STRONG, ChipResonancePattern.GOLDEN_RESONANCE_STANDARD}:
        return 15, cap, False, None
    if primary == ChipResonancePattern.CONFIRMED_INSTITUTIONAL_DEFENSE:
        return 8, cap, False, None
    if primary in {ChipResonancePattern.CONFIRMED_ACCUMULATION, ChipResonancePattern.ACCUMULATION_CANDIDATE}:
        return 5, cap, False, None
    return 0, cap, False, None


def _direction(value: Optional[Decimal]) -> Literal["buying", "selling", "neutral"]:
    if (value or ZERO) > ZERO:
        return "buying"
    if (value or ZERO) < ZERO:
        return "selling"
    return "neutral"


def _are_aligned(context: ContextBundle) -> bool:
    directions = [_direction(context.foreign_net_today), _direction(context.trust_net_today), _direction(context.dealer_net_today)]
    non_neutral = [direction for direction in directions if direction != "neutral"]
    return bool(non_neutral) and len(set(non_neutral)) == 1


def _is_conflicting(context: ContextBundle) -> bool:
    directions = [_direction(context.foreign_net_today), _direction(context.trust_net_today), _direction(context.dealer_net_today)]
    return "buying" in directions and "selling" in directions


def _longest_streak(context: ContextBundle) -> tuple[int, Literal["foreign", "trust", "dealer"]]:
    streaks = {
        "foreign": abs(context.foreign_consecutive_days or 0),
        "trust": abs(context.trust_consecutive_days or 0),
        "dealer": abs(context.dealer_consecutive_days or 0),
    }
    party = max(streaks, key=streaks.get)
    return streaks[party], party  # type: ignore[return-value]


def _is_chip_data_partial(context: ContextBundle) -> bool:
    required = [
        context.foreign_net_today,
        context.trust_net_today,
        context.dealer_net_today,
        context.foreign_net_value_today,
        context.trust_net_value_today,
        context.margin_balance_change_pct_3d,
    ]
    optional_market_microstructure_missing = context.large_order_buy_ratio is None or context.large_order_sell_ratio is None
    return any(value is None for value in required) or optional_market_microstructure_missing


def _reason(features: FeatureBundle, source_field: str, text: str, calculation: str, value: Decimal) -> ReasonTrace:
    return ReasonTrace(
        reason_text=text,
        source_field=source_field,
        timestamp=features.series.latest().date,
        calculation=calculation,
        calculation_value=quantize(value),
    )
