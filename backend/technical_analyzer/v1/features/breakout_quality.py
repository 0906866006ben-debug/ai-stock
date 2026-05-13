"""Topic H: breakout / breakdown quality and false-signal handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional
import json

from ..common import ONE, ZERO, clamp, quantize
from ..contracts.enums import BreakoutStatus, FactorCategory, TechnicalState, TrendDirection
from ..contracts.feature_contract import FeatureBundle
from ..contracts.input_contract import ContextBundle
from ..contracts.output_contract import FactorVote
from ..registry.rule_registry import RuleRegistry
from ..traceability.trace import ReasonTrace
from .candle_features import compute_candle_features
from .support_resistance import SRLevel, SupportResistanceMap
from .volume_price_quadrant import VolumePriceQuadrantResult


@dataclass(frozen=True)
class BreakoutEvent:
    event_date: date
    event_type: str
    related_level_price: Decimal
    initial_status: BreakoutStatus
    initial_quality: dict
    initial_warnings: list[str]


class BreakoutEventHistory:
    """Tiny JSON-backed pending-event history."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path
        self.events: list[BreakoutEvent] = []
        if storage_path and storage_path.exists():
            raw = json.loads(storage_path.read_text(encoding="utf-8"))
            self.events = [
                BreakoutEvent(
                    event_date=date.fromisoformat(item["event_date"]),
                    event_type=item["event_type"],
                    related_level_price=Decimal(item["related_level_price"]),
                    initial_status=BreakoutStatus(item["initial_status"]),
                    initial_quality=item["initial_quality"],
                    initial_warnings=item["initial_warnings"],
                )
                for item in raw
            ]

    def record(self, event: BreakoutEvent) -> None:
        self.events.append(event)
        self._persist()

    def get_pending_events_for_confirmation(self, today: date) -> list[BreakoutEvent]:
        return [
            event
            for event in self.events
            if event.initial_status in {BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION, BreakoutStatus.BREAKDOWN_PENDING_CONFIRMATION}
            and (today - event.event_date).days >= 1
        ]

    def update_status(self, event_date: date, new_status: BreakoutStatus) -> None:
        updated: list[BreakoutEvent] = []
        for event in self.events:
            if event.event_date == event_date:
                updated.append(
                    BreakoutEvent(
                        event_date=event.event_date,
                        event_type=event.event_type,
                        related_level_price=event.related_level_price,
                        initial_status=new_status,
                        initial_quality=event.initial_quality,
                        initial_warnings=event.initial_warnings,
                    )
                )
            else:
                updated.append(event)
        self.events = updated
        self._persist()

    def _persist(self) -> None:
        if not self.storage_path:
            return
        payload = [
            {
                "event_date": event.event_date.isoformat(),
                "event_type": event.event_type,
                "related_level_price": str(event.related_level_price),
                "initial_status": event.initial_status.value,
                "initial_quality": event.initial_quality,
                "initial_warnings": event.initial_warnings,
            }
            for event in self.events
        ]
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@dataclass(frozen=True)
class QualityDimensions:
    magnitude_pct: Decimal
    magnitude_passed: bool
    volume_ratio: Decimal
    volume_passed: bool
    body_ratio: Decimal
    upper_shadow_ratio: Decimal
    body_and_shadow_passed: bool
    chip_aligned: bool
    dimensions_passed_count: int


@dataclass(frozen=True)
class BreakoutAnalysisResult:
    symbol: str
    analysis_date: date
    event_detected: bool
    event_type: str
    related_level: Optional[SRLevel]
    status: BreakoutStatus
    quality_dimensions: Optional[QualityDimensions]
    false_signal_warnings: list[str]
    is_limit_distorted: bool
    event_record: Optional[BreakoutEvent]
    vote: FactorVote
    state_signal_score_modifier: int
    confidence_cap: Optional[int]
    state_downgrade_required: bool
    reasons: list[ReasonTrace]


VOTE_MAPPING = {
    BreakoutStatus.CONFIRMED_HEALTHY_BREAKOUT: (TrendDirection.BULLISH, Decimal("0.9")),
    BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION: (TrendDirection.BULLISH, Decimal("0.5")),
    BreakoutStatus.FALSE_BREAKOUT_RISK: (TrendDirection.BEARISH, Decimal("0.5")),
    BreakoutStatus.FALSE_BREAKOUT_HIGH_CONFIDENCE: (TrendDirection.BEARISH, Decimal("0.85")),
    BreakoutStatus.FALSE_BREAKOUT_INTRADAY: (TrendDirection.BEARISH, Decimal("0.6")),
    BreakoutStatus.FALSE_BREAKOUT_T1: (TrendDirection.BEARISH, Decimal("0.75")),
    BreakoutStatus.CONFIRMED_EFFECTIVE_BREAKDOWN: (TrendDirection.BEARISH, Decimal("0.9")),
    BreakoutStatus.BREAKDOWN_PENDING_CONFIRMATION: (TrendDirection.BEARISH, Decimal("0.5")),
    BreakoutStatus.FALSE_BREAKDOWN_INTRADAY: (TrendDirection.BULLISH, Decimal("0.6")),
    BreakoutStatus.FALSE_BREAKDOWN_T1: (TrendDirection.BULLISH, Decimal("0.75")),
    BreakoutStatus.NO_BREAKOUT: (TrendDirection.NEUTRAL, ZERO),
}


def analyze_breakout_quality(
    symbol: str,
    features: FeatureBundle,
    context: ContextBundle,
    sr_map: SupportResistanceMap,
    quadrant_result: VolumePriceQuadrantResult,
    history: Optional[BreakoutEventHistory] = None,
    registry: RuleRegistry | None = None,
) -> BreakoutAnalysisResult:
    """Assess breakout quality and maintain T+1 confirmation discipline."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("breakout_quality")
    history = BreakoutEventHistory() if history is None else history
    latest = features.series.latest()
    pending_events = history.get_pending_events_for_confirmation(latest.date)
    if pending_events:
        return _confirm_pending(symbol, features, pending_events[0], history, section)

    event_type, related_level = _detect_event(sr_map, latest)
    if related_level is None:
        neutral_vote = FactorVote(category=FactorCategory.BREAKOUT_QUALITY, direction=TrendDirection.NEUTRAL, strength=ZERO, reasons=(), event_driven=True, exclude_from_consensus=True)
        return BreakoutAnalysisResult(
            symbol=symbol,
            analysis_date=latest.date,
            event_detected=False,
            event_type="none",
            related_level=None,
            status=BreakoutStatus.NO_BREAKOUT,
            quality_dimensions=None,
            false_signal_warnings=[],
            is_limit_distorted=False,
            event_record=None,
            vote=neutral_vote,
            state_signal_score_modifier=0,
            confidence_cap=None,
            state_downgrade_required=False,
            reasons=[],
        )

    dimensions = _quality_dimensions(features, context, related_level, quadrant_result, section, event_type)
    warnings = _false_signal_warnings(features, context, related_level, quadrant_result, section, event_type)
    limit_distorted = latest.is_limit_up if event_type == "breakout" else latest.is_limit_down
    status = _determine_status(event_type, latest, related_level, dimensions, warnings, limit_distorted, section)
    event_record = None
    if status in {BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION, BreakoutStatus.BREAKDOWN_PENDING_CONFIRMATION}:
        event_record = BreakoutEvent(
            event_date=latest.date,
            event_type=event_type,
            related_level_price=related_level.price_level,
            initial_status=status,
            initial_quality={
                "magnitude_pct": str(dimensions.magnitude_pct),
                "volume_ratio": str(dimensions.volume_ratio),
                "dimensions_passed_count": dimensions.dimensions_passed_count,
            },
            initial_warnings=warnings,
        )
        history.record(event_record)

    direction, strength = VOTE_MAPPING[status]
    modifier, cap, downgrade = _state_modifier(status, section)
    reason = ReasonTrace(
        reason_text=f"{event_type} 狀態為 {status.value}",
        source_field="breakout_quality",
        timestamp=latest.date,
        calculation="four-dimension breakout scoring with warnings",
        calculation_value=Decimal(dimensions.dimensions_passed_count),
    )
    vote = FactorVote(
        category=FactorCategory.BREAKOUT_QUALITY,
        direction=direction,
        strength=quantize(clamp(strength, ZERO, ONE)),
        reasons=(reason,),
        event_driven=True,
        exclude_from_consensus=True,
    )
    return BreakoutAnalysisResult(
        symbol=symbol,
        analysis_date=latest.date,
        event_detected=True,
        event_type=event_type,
        related_level=related_level,
        status=status,
        quality_dimensions=dimensions,
        false_signal_warnings=warnings,
        is_limit_distorted=limit_distorted,
        event_record=event_record,
        vote=vote,
        state_signal_score_modifier=modifier,
        confidence_cap=cap,
        state_downgrade_required=downgrade,
        reasons=[reason],
    )


def _confirm_pending(symbol: str, features: FeatureBundle, pending: BreakoutEvent, history: BreakoutEventHistory, rules: dict) -> BreakoutAnalysisResult:
    latest = features.series.latest()
    price = pending.related_level_price
    proximity = Decimal(str(rules["t1_recovery_proximity_pct"])) / Decimal("100")
    if pending.event_type == "breakout":
        if latest.close > price:
            status = BreakoutStatus.CONFIRMED_HEALTHY_BREAKOUT if latest.close > price * (ONE + proximity) else BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION
        else:
            status = BreakoutStatus.FALSE_BREAKOUT_T1
    else:
        if latest.close < price:
            status = BreakoutStatus.CONFIRMED_EFFECTIVE_BREAKDOWN if latest.close < price * (ONE - proximity) else BreakoutStatus.BREAKDOWN_PENDING_CONFIRMATION
        else:
            status = BreakoutStatus.FALSE_BREAKDOWN_T1
    history.update_status(pending.event_date, status)
    direction, strength = VOTE_MAPPING[status]
    modifier, cap, downgrade = _state_modifier(status, rules)
    reason = ReasonTrace(
        reason_text=f"T+1 確認結果為 {status.value}",
        source_field="breakout_event_history",
        timestamp=latest.date,
        calculation="pending event confirmation",
        calculation_value=latest.close,
    )
    vote = FactorVote(
        category=FactorCategory.BREAKOUT_QUALITY,
        direction=direction,
        strength=strength,
        reasons=(reason,),
        event_driven=True,
        exclude_from_consensus=True,
    )
    return BreakoutAnalysisResult(
        symbol=symbol,
        analysis_date=latest.date,
        event_detected=True,
        event_type=pending.event_type,
        related_level=None,
        status=status,
        quality_dimensions=None,
        false_signal_warnings=pending.initial_warnings,
        is_limit_distorted=False,
        event_record=None,
        vote=vote,
        state_signal_score_modifier=modifier,
        confidence_cap=cap,
        state_downgrade_required=downgrade,
        reasons=[reason],
    )


def _detect_event(sr_map: SupportResistanceMap, latest) -> tuple[str, Optional[SRLevel]]:
    breakout = sr_map.nearest_resistance and latest.high > sr_map.nearest_resistance.price_level
    breakdown = sr_map.nearest_support and latest.low < sr_map.nearest_support.price_level
    if breakout and breakdown:
        resistance_strength = sr_map.nearest_resistance.strength_score if sr_map.nearest_resistance else 0
        support_strength = sr_map.nearest_support.strength_score if sr_map.nearest_support else 0
        if resistance_strength >= support_strength:
            return "breakout", sr_map.nearest_resistance
        return "breakdown", sr_map.nearest_support
    if breakout:
        return "breakout", sr_map.nearest_resistance
    if breakdown:
        return "breakdown", sr_map.nearest_support
    return "none", None


def _quality_dimensions(features: FeatureBundle, context: ContextBundle, level: SRLevel, quadrant_result: VolumePriceQuadrantResult, rules: dict, event_type: str) -> QualityDimensions:
    latest = features.series.latest()
    candle = compute_candle_features(latest)
    if event_type == "breakout":
        magnitude_pct = ((latest.close - level.price_level) / level.price_level) * Decimal("100")
    else:
        magnitude_pct = ((level.price_level - latest.close) / level.price_level) * Decimal("100")
    magnitude_passed = magnitude_pct >= Decimal(str(rules["magnitude_threshold_pct"]))
    volume_ratio = quadrant_result.turnover_value_ratio_20_adjusted
    volume_passed = volume_ratio >= Decimal(str(rules["volume_ratio_threshold"]))
    body_ratio = candle["body_ratio"] or ZERO
    upper_shadow_ratio = candle["upper_shadow_ratio"] or ZERO
    body_shadow_passed = body_ratio >= Decimal(str(rules["body_ratio_threshold"])) and upper_shadow_ratio <= Decimal(str(rules["upper_shadow_max_ratio"]))
    chip_aligned = (context.foreign_net_buy_today or ZERO) >= ZERO and (context.three_majors_net_today or ZERO) >= ZERO if event_type == "breakout" else (context.foreign_net_today or ZERO) <= ZERO and (context.three_majors_net_today or ZERO) <= ZERO
    passed = sum(int(flag) for flag in (magnitude_passed, volume_passed, body_shadow_passed, chip_aligned))
    return QualityDimensions(
        magnitude_pct=quantize(magnitude_pct),
        magnitude_passed=magnitude_passed,
        volume_ratio=quantize(volume_ratio),
        volume_passed=volume_passed,
        body_ratio=quantize(body_ratio),
        upper_shadow_ratio=quantize(upper_shadow_ratio),
        body_and_shadow_passed=body_shadow_passed,
        chip_aligned=chip_aligned,
        dimensions_passed_count=passed,
    )


def _false_signal_warnings(features: FeatureBundle, context: ContextBundle, level: SRLevel, quadrant_result: VolumePriceQuadrantResult, rules: dict, event_type: str) -> list[str]:
    latest = features.series.latest()
    candle = compute_candle_features(latest)
    warnings: list[str] = []
    if (candle["upper_shadow_ratio"] or ZERO) >= Decimal(str(rules["long_upper_shadow_threshold"])):
        warnings.append("長上影線")
    if (candle["close_position_in_range"] or ZERO) < Decimal(str(rules["weak_close_position_threshold"])):
        warnings.append("收盤回壓")
    if quadrant_result.turnover_value_ratio_20_adjusted < Decimal(str(rules["no_volume_threshold"])):
        warnings.append("無量突破")
    if (context.day_trading_ratio or ZERO) > Decimal(str(rules["day_trading_high_threshold"])):
        warnings.append("當沖比過高")
    if event_type == "breakout" and (context.foreign_net_today or ZERO) < ZERO:
        warnings.append("籌碼背離")
    if event_type == "breakdown" and (context.foreign_net_today or ZERO) > ZERO:
        warnings.append("籌碼背離")
    if event_type == "breakout" and latest.close <= level.price_level:
        warnings.append("日內突破收盤失守")
    if event_type == "breakdown" and latest.close >= level.price_level:
        warnings.append("日內跌破收盤收回")
    return warnings


def _determine_status(event_type: str, latest, level: SRLevel, dimensions: QualityDimensions, warnings: list[str], limit_distorted: bool, rules: dict) -> BreakoutStatus:
    if limit_distorted:
        return BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION if event_type == "breakout" else BreakoutStatus.BREAKDOWN_PENDING_CONFIRMATION
    if event_type == "breakout" and latest.close <= level.price_level:
        return BreakoutStatus.FALSE_BREAKOUT_INTRADAY
    if event_type == "breakdown" and latest.close >= level.price_level:
        return BreakoutStatus.FALSE_BREAKDOWN_INTRADAY
    if len(warnings) >= int(rules["warnings_high_confidence_min"]):
        return BreakoutStatus.FALSE_BREAKOUT_HIGH_CONFIDENCE if event_type == "breakout" else BreakoutStatus.EFFECTIVE_BREAKDOWN_HIGH_CONFIDENCE
    if int(rules["warnings_risk_min"]) <= len(warnings) <= int(rules["warnings_risk_max"]):
        return BreakoutStatus.FALSE_BREAKOUT_RISK if event_type == "breakout" else BreakoutStatus.EFFECTIVE_BREAKDOWN_RISK
    if dimensions.dimensions_passed_count >= 3:
        return BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION if event_type == "breakout" else BreakoutStatus.BREAKDOWN_PENDING_CONFIRMATION
    return BreakoutStatus.FALSE_BREAKOUT_RISK if event_type == "breakout" else BreakoutStatus.EFFECTIVE_BREAKDOWN_RISK


def _state_modifier(status: BreakoutStatus, rules: dict) -> tuple[int, Optional[int], bool]:
    mapping = {
        BreakoutStatus.CONFIRMED_HEALTHY_BREAKOUT: (int(rules["modifier_confirmed_healthy"]), None, False),
        BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION: (int(rules["modifier_pending"]), int(rules["cap_pending"]), False),
        BreakoutStatus.FALSE_BREAKOUT_INTRADAY: (int(rules["modifier_false_intraday"]), int(rules["cap_false_intraday"]), False),
        BreakoutStatus.FALSE_BREAKOUT_T1: (int(rules["modifier_false_t1"]), int(rules["cap_false_t1"]), True),
        BreakoutStatus.FALSE_BREAKOUT_HIGH_CONFIDENCE: (int(rules["modifier_false_high_confidence"]), int(rules["cap_false_high_confidence"]), True),
        BreakoutStatus.CONFIRMED_EFFECTIVE_BREAKDOWN: (int(rules["modifier_confirmed_breakdown"]), None, False),
    }
    return mapping.get(status, (0, None, False))
