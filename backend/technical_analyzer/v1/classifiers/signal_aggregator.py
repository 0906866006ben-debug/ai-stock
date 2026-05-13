"""Topic O: unified signal aggregation layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..chip_flow.chip_resonance import ChipFlowResult, ChipResonancePattern
from ..common import ONE, ZERO, clamp, quantize
from ..contracts.enums import BreakoutStatus, Horizon, TechnicalState, TrendDirection
from ..features.breakout_quality import BreakoutAnalysisResult
from ..features.candle_patterns import CandlePatternResult
from ..features.chart_patterns import ChartPatternResult
from ..features.divergence_overheat import DivergenceOverheatResult
from ..features.support_resistance import SupportResistanceMap
from ..features.volume_price_quadrant import VolumePriceQuadrantResult, VolumePriceSubClass
from ..registry.rule_registry import RuleRegistry
from ..special_rules.taiwan_market_rules import MarketGate, MarketGateStatus
from ..traceability.trace import ReasonTrace


class UnifiedSignal(str, Enum):
    HEALTHY_BREAKOUT_CONFIRMED = "healthy_breakout_confirmed"
    BREAKOUT_PENDING_CONFIRMATION = "breakout_pending_confirmation"
    PULLBACK_TO_SUPPORT = "pullback_to_support"
    BOTTOM_REVERSAL_CANDIDATE = "bottom_reversal_candidate"
    ACCUMULATION_DETECTED = "accumulation_detected"
    INSTITUTIONAL_DEFENSE = "institutional_defense"
    CONSOLIDATION_PENDING_DIRECTION = "consolidation_pending_direction"
    VOLATILITY_SQUEEZE = "volatility_squeeze"
    MIXED_SIGNALS = "mixed_signals"
    DISTRIBUTION_DETECTED = "distribution_detected"
    BREAKDOWN_CONFIRMED = "breakdown_confirmed"
    BREAKDOWN_PENDING_CONFIRMATION = "breakdown_pending_confirmation"
    FALSE_BREAKOUT_HIGH_RISK = "false_breakout_high_risk"
    PARABOLIC_OVERHEAT_WARNING = "parabolic_overheat_warning"
    BEARISH_PATTERN_CONFIRMED = "bearish_pattern_confirmed"
    DISPOSITION_SUSPENDED = "disposition_suspended"
    DATA_INSUFFICIENT = "data_insufficient"
    LIMIT_DISTORTED = "limit_distorted"


@dataclass(frozen=True)
class UnifiedSignalEvent:
    signal: UnifiedSignal
    strength: Decimal
    contributing_modules: list[str]
    priority: int
    short_description: str
    detailed_reasons: list[ReasonTrace]


@dataclass(frozen=True)
class SignalAggregationResult:
    symbol: str
    analysis_date: date
    horizon: Horizon
    primary_signal: UnifiedSignalEvent
    secondary_signals: list[UnifiedSignalEvent]
    are_signals_aligned: bool
    signal_direction: TrendDirection
    aggregated_confidence: int
    aggregated_signal_score_modifier: int
    requires_state_override: bool
    override_target: Optional[TechnicalState]
    override_source_module: Optional[str]
    user_facing_label: str
    user_facing_description: str
    reasons: list[ReasonTrace]


def aggregate_signals(
    symbol: str,
    analysis_date: date,
    horizon: Horizon,
    technical_state: TechnicalState,
    market_gate: Optional[MarketGate] = None,
    breakout_result: Optional[BreakoutAnalysisResult] = None,
    candle_result: Optional[CandlePatternResult] = None,
    chart_result: Optional[ChartPatternResult] = None,
    divergence_result: Optional[DivergenceOverheatResult] = None,
    chip_result: Optional[ChipFlowResult] = None,
    quadrant_result: Optional[VolumePriceQuadrantResult] = None,
    sr_map: Optional[SupportResistanceMap] = None,
    registry: RuleRegistry | None = None,
) -> SignalAggregationResult:
    """Map module statuses to unified, prioritized trading signals."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("signal_aggregator")
    priority = {name: idx + 1 for idx, name in enumerate(section["priority_order"])}
    zh = section["unified_signal_zh"]
    candidates: dict[UnifiedSignal, UnifiedSignalEvent] = {}

    def add(signal: UnifiedSignal, strength: Decimal, module: str, reasons: list[ReasonTrace]) -> None:
        if signal in candidates:
            old = candidates[signal]
            candidates[signal] = UnifiedSignalEvent(
                signal=signal,
                strength=quantize(clamp(max(old.strength, strength) + Decimal("0.1"), ZERO, ONE)),
                contributing_modules=sorted(set(old.contributing_modules + [module])),
                priority=priority[signal.value],
                short_description=zh[signal.value]["label"],
                detailed_reasons=old.detailed_reasons + reasons,
            )
            return
        candidates[signal] = UnifiedSignalEvent(
            signal=signal,
            strength=quantize(clamp(strength, ZERO, ONE)),
            contributing_modules=[module],
            priority=priority[signal.value],
            short_description=zh[signal.value]["label"],
            detailed_reasons=reasons,
        )

    if market_gate:
        if market_gate.gate_status == MarketGateStatus.DISPOSITION_SUSPENDED:
            add(UnifiedSignal.DISPOSITION_SUSPENDED, ONE, "M", market_gate.reasons)
        elif market_gate.gate_status == MarketGateStatus.LIMIT_DISTORTED:
            add(UnifiedSignal.LIMIT_DISTORTED, Decimal("0.9"), "M", market_gate.reasons)
    if technical_state == TechnicalState.DATA_INSUFFICIENT:
        add(UnifiedSignal.DATA_INSUFFICIENT, ONE, "A-E", [])
    elif technical_state == TechnicalState.PARABOLIC_OVERHEAT:
        add(UnifiedSignal.PARABOLIC_OVERHEAT_WARNING, Decimal("0.9"), "A-E", [])
    elif technical_state == TechnicalState.HIGH_LEVEL_DISTRIBUTION:
        add(UnifiedSignal.DISTRIBUTION_DETECTED, Decimal("0.75"), "A-E", [])
    elif technical_state == TechnicalState.SELLING_CLIMAX:
        add(UnifiedSignal.BOTTOM_REVERSAL_CANDIDATE, Decimal("0.6"), "A-E", [])
    elif technical_state == TechnicalState.TIGHT_CONSOLIDATION:
        add(UnifiedSignal.VOLATILITY_SQUEEZE, Decimal("0.5"), "A-E", [])
    elif technical_state == TechnicalState.CONSOLIDATION:
        add(UnifiedSignal.CONSOLIDATION_PENDING_DIRECTION, Decimal("0.4"), "A-E", [])
    elif technical_state == TechnicalState.MIXED_SIGNALS:
        add(UnifiedSignal.MIXED_SIGNALS, Decimal("0.4"), "A-E", [])

    if breakout_result:
        breakout_map = {
            BreakoutStatus.CONFIRMED_HEALTHY_BREAKOUT: UnifiedSignal.HEALTHY_BREAKOUT_CONFIRMED,
            BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION: UnifiedSignal.BREAKOUT_PENDING_CONFIRMATION,
            BreakoutStatus.FALSE_BREAKOUT_HIGH_CONFIDENCE: UnifiedSignal.FALSE_BREAKOUT_HIGH_RISK,
            BreakoutStatus.CONFIRMED_EFFECTIVE_BREAKDOWN: UnifiedSignal.BREAKDOWN_CONFIRMED,
            BreakoutStatus.BREAKDOWN_PENDING_CONFIRMATION: UnifiedSignal.BREAKDOWN_PENDING_CONFIRMATION,
        }
        if breakout_result.status in breakout_map:
            add(breakout_map[breakout_result.status], breakout_result.vote.strength, "H", breakout_result.reasons)

    if candle_result:
        for event in candle_result.events_today:
            if event.contextual_label in {"distribution_at_high", "distribution_dump"}:
                add(UnifiedSignal.DISTRIBUTION_DETECTED, Decimal("0.7"), "K", candle_result.reasons)
            elif event.contextual_label in {"selling_climax_candidate", "support_absorption"}:
                add(UnifiedSignal.BOTTOM_REVERSAL_CANDIDATE, Decimal("0.5"), "K", candle_result.reasons)
            elif event.contextual_label == "gap_up_exhaustion":
                add(UnifiedSignal.PARABOLIC_OVERHEAT_WARNING, Decimal("0.6"), "K", candle_result.reasons)

    if chart_result:
        for pattern in chart_result.detected_patterns:
            key = f"{pattern.pattern_status}_{pattern.pattern_name}"
            if key in {"confirmed_double_top", "confirmed_head_and_shoulders"}:
                add(UnifiedSignal.BEARISH_PATTERN_CONFIRMED, Decimal("0.85"), "L", chart_result.reasons)
            elif key in {"confirmed_double_bottom", "confirmed_inverse_head_and_shoulders"}:
                add(UnifiedSignal.BOTTOM_REVERSAL_CANDIDATE, Decimal("0.75"), "L", chart_result.reasons)
            elif key == "confirmed_vcp" or pattern.pattern_name == "vcp":
                add(UnifiedSignal.VOLATILITY_SQUEEZE, Decimal("0.6"), "L", chart_result.reasons)

    if divergence_result:
        if divergence_result.overheat.overheat_level in {"severe_overheat", "parabolic_overheat"}:
            add(UnifiedSignal.PARABOLIC_OVERHEAT_WARNING, Decimal("0.8"), "J", divergence_result.reasons)
        for event in divergence_result.divergence_events:
            if "bearish" in event.divergence_type and event.confirmation_level in {"confirmed_divergence", "triple_confirmed_divergence"}:
                add(UnifiedSignal.DISTRIBUTION_DETECTED, Decimal("0.75"), "J", divergence_result.reasons)
            if "bullish" in event.divergence_type and event.confirmation_level in {"confirmed_divergence", "triple_confirmed_divergence"}:
                add(UnifiedSignal.BOTTOM_REVERSAL_CANDIDATE, Decimal("0.65"), "J", divergence_result.reasons)

    if chip_result:
        if chip_result.primary_pattern == ChipResonancePattern.GOLDEN_RESONANCE_STRONG:
            add(UnifiedSignal.HEALTHY_BREAKOUT_CONFIRMED, chip_result.vote.strength, "N", chip_result.reasons)
        elif chip_result.primary_pattern == ChipResonancePattern.FALSE_RALLY_HIGH_CONFIDENCE:
            add(UnifiedSignal.DISTRIBUTION_DETECTED, chip_result.vote.strength, "N", chip_result.reasons)
        elif chip_result.primary_pattern == ChipResonancePattern.CONFIRMED_ACCUMULATION:
            add(UnifiedSignal.ACCUMULATION_DETECTED, chip_result.vote.strength, "N", chip_result.reasons)
        elif chip_result.primary_pattern == ChipResonancePattern.CONFIRMED_INSTITUTIONAL_DEFENSE:
            add(UnifiedSignal.INSTITUTIONAL_DEFENSE, chip_result.vote.strength, "N", chip_result.reasons)

    if quadrant_result and sr_map and quadrant_result.sub_classification == VolumePriceSubClass.HEALTHY_PULLBACK and sr_map.position_in_range == "near_support":
        add(UnifiedSignal.PULLBACK_TO_SUPPORT, Decimal("0.55"), "F+G", quadrant_result.reasons + sr_map.reasons)

    if not candidates:
        add(UnifiedSignal.MIXED_SIGNALS, Decimal("0.3"), "O", [])

    ordered = sorted(candidates.values(), key=lambda event: event.priority)
    primary = ordered[0]
    secondary = ordered[1:4]
    caps = [
        cap
        for cap in [
            market_gate.confidence_cap if market_gate else None,
            breakout_result.confidence_cap if breakout_result else None,
            candle_result.confidence_cap if candle_result else None,
            chart_result.confidence_cap if chart_result else None,
            divergence_result.confidence_cap if divergence_result else None,
            chip_result.confidence_cap if chip_result else None,
        ]
        if cap is not None
    ]
    modifiers = [
        breakout_result.state_signal_score_modifier if breakout_result else 0,
        candle_result.state_signal_score_modifier if candle_result else 0,
        chart_result.state_signal_score_modifier if chart_result else 0,
        divergence_result.state_signal_score_modifier if divergence_result else 0,
        chip_result.state_signal_score_modifier if chip_result else 0,
    ]
    override_required, override_target, override_source = _override(chart_result, divergence_result, chip_result, breakout_result)
    label = zh[primary.signal.value]["label"]
    description = zh[primary.signal.value]["description"]
    reasons = [reason for event in ordered for reason in event.detailed_reasons]
    direction = _signal_direction(primary.signal)
    aligned = all(_signal_direction(event.signal) in {direction, TrendDirection.NEUTRAL} for event in ordered)
    return SignalAggregationResult(
        symbol=symbol,
        analysis_date=analysis_date,
        horizon=horizon,
        primary_signal=primary,
        secondary_signals=secondary,
        are_signals_aligned=aligned,
        signal_direction=direction,
        aggregated_confidence=min(caps) if caps else 100,
        aggregated_signal_score_modifier=sum(modifiers),
        requires_state_override=override_required,
        override_target=override_target,
        override_source_module=override_source,
        user_facing_label=label,
        user_facing_description=description,
        reasons=reasons,
    )


def _override(chart, divergence, chip, breakout) -> tuple[bool, Optional[TechnicalState], Optional[str]]:
    for name, result in (("L", chart), ("J", divergence), ("N", chip)):
        if result and result.state_override_required:
            return True, result.state_override_target, name
    if breakout and breakout.state_downgrade_required:
        return True, None, "H"
    return False, None, None


def _signal_direction(signal: UnifiedSignal) -> TrendDirection:
    bullish = {
        UnifiedSignal.HEALTHY_BREAKOUT_CONFIRMED,
        UnifiedSignal.PULLBACK_TO_SUPPORT,
        UnifiedSignal.BOTTOM_REVERSAL_CANDIDATE,
        UnifiedSignal.ACCUMULATION_DETECTED,
        UnifiedSignal.INSTITUTIONAL_DEFENSE,
    }
    bearish = {
        UnifiedSignal.DISTRIBUTION_DETECTED,
        UnifiedSignal.BREAKDOWN_CONFIRMED,
        UnifiedSignal.FALSE_BREAKOUT_HIGH_RISK,
        UnifiedSignal.PARABOLIC_OVERHEAT_WARNING,
        UnifiedSignal.BEARISH_PATTERN_CONFIRMED,
    }
    if signal in bullish:
        return TrendDirection.BULLISH
    if signal in bearish:
        return TrendDirection.BEARISH
    return TrendDirection.NEUTRAL
