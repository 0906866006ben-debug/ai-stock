"""Topic T: unified AIAnalysisResult contract builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Optional

from ..classifiers.signal_aggregator import SignalAggregationResult, UnifiedSignalEvent, aggregate_signals
from ..common import HUNDRED, ONE, ZERO, pct_change, quantize
from ..contracts.enums import FactorCategory, Horizon, TechnicalState, TrendDirection
from ..contracts.feature_contract import FeatureBundle
from ..contracts.input_contract import ContextBundle, OHLCVSeries
from ..contracts.output_contract import FactorVote, InvalidationSignal
from ..decision.confidence_cap_engine import (
    ConfidenceCapEngineResult,
    apply_confidence_caps,
    collect_cap_candidates,
)
from ..decision.score_engine import ScoreEngineResult, compute_three_axis_scores
from ..features.v2_quant import FundamentalSnapshot, V2QuantAnalysisResult, analyze_v2_quant
from ..registry.rule_registry import RuleRegistry
from ..special_rules.taiwan_market_rules import MarketGate, MarketGateStatus, evaluate_market_gate
from ..traceability.trace import ReasonTrace


@dataclass(frozen=True)
class ThreeAxisScore:
    signal: int
    confidence: int
    risk: int
    confidence_cap_reason: Optional[str] = None


@dataclass(frozen=True)
class InvalidationCondition:
    description: str
    trigger_expression: str
    monitored_fields: list[str]
    severity: str = "hard"


@dataclass(frozen=True)
class ScenarioCondition:
    condition_text: str
    monitored_fields: list[str]
    trigger_expression: str


@dataclass(frozen=True)
class Scenario:
    direction: str
    label: str
    conditions: list[ScenarioCondition]
    action_if_triggered: str
    scope_horizons: list[str]


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    source: str
    direction: str
    factor_category: str
    title: str
    detail: str
    weight: int
    trace: Optional[ReasonTrace] = None


@dataclass(frozen=True)
class StructurePanelData:
    dow_structure: str
    wyckoff_phase: str
    recent_pivots: list[dict[str, Any]]
    kou_di_ma20: dict[str, Any]
    kou_di_ma60: dict[str, Any]
    ma_compression_ratio: Decimal
    is_compressed: bool


@dataclass(frozen=True)
class ReportSection:
    key: str
    title: str
    icon: str
    preview: str
    body_markdown: str


@dataclass(frozen=True)
class HorizonAnalysisResult:
    horizon: Horizon
    technical_state: TechnicalState
    state_label_zh: str
    state_detail: str
    direction: TrendDirection
    scores: ThreeAxisScore
    factor_votes: dict[FactorCategory, FactorVote]
    categories_in_agreement: list[FactorCategory]
    dow_structure: str
    wyckoff_phase: str
    invalidation_conditions: list[InvalidationCondition]
    reasons: list[ReasonTrace]
    signal_aggregation: SignalAggregationResult
    score_engine_audit: ScoreEngineResult
    cap_engine_audit: ConfidenceCapEngineResult


@dataclass(frozen=True)
class AIAnalysisResult:
    symbol: str
    symbol_name: str
    sector_tag: str
    market_cap_bucket: str
    analysis_date: date
    analyzed_at: datetime
    next_update_at: datetime
    current_price: Decimal
    price_change: Decimal
    price_change_pct: Decimal
    overall_direction: TrendDirection
    cross_horizon_state: str
    overall_scores: ThreeAxisScore
    one_line_summary: str
    horizons: dict[Horizon, HorizonAnalysisResult]
    bullish_scenario: Scenario
    bearish_scenario: Scenario
    evidence_ledger: list[EvidenceItem]
    structure_panel: StructurePanelData
    report_sections: list[ReportSection]
    data_sources: list[str]
    models_used: list[str]
    data_quality: str
    data_quality_score: int
    v2_quant_analysis: V2QuantAnalysisResult
    is_v1_hypothesis: bool
    rule_set_version: str
    disposition_status: str
    market_gate: MarketGate
    factor_votes: dict[FactorCategory, FactorVote]
    score_engine_audit: dict[Horizon, ScoreEngineResult]
    cap_engine_audit: dict[Horizon, ConfidenceCapEngineResult]
    primary_unified_signal: UnifiedSignalEvent
    secondary_unified_signals: list[UnifiedSignalEvent]

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


class AIAnalysisResultBuilder:
    """Assemble v1 module outputs into a single frontend/admin contract.

    The builder can run in a compact mode using supplied A-O outputs, or degrade
    to simple OHLCV-derived votes so P/Q/T can still be verified in isolation.
    """

    def __init__(self, registry: RuleRegistry | None = None):
        self.registry = registry or RuleRegistry.load_default()

    def build(
        self,
        symbol: str,
        ohlcv: OHLCVSeries,
        context: ContextBundle,
        *,
        symbol_name: str | None = None,
        sector_tag: str = "TWSE",
        factor_votes_by_horizon: Mapping[Horizon, list[FactorVote]] | None = None,
        technical_state_by_horizon: Mapping[Horizon, TechnicalState] | None = None,
        direction_by_horizon: Mapping[Horizon, TrendDirection] | None = None,
        signal_modifiers_by_horizon: Mapping[Horizon, Mapping[str, int]] | None = None,
        module_caps_by_horizon: Mapping[Horizon, list[tuple[str, int, str]]] | None = None,
        fundamental_snapshot: FundamentalSnapshot | None = None,
    ) -> AIAnalysisResult:
        analysis_date = ohlcv.latest().date
        now = datetime.now(timezone.utc)
        data_quality = _data_quality(ohlcv)
        data_quality_score = 50 if data_quality == "mock" else 60 if data_quality == "fallback" else 85
        v2_quant_analysis = analyze_v2_quant(ohlcv, fundamental_snapshot)
        market_cap_bucket = context.market_cap_bucket or "large"
        directions = {
            horizon: direction_by_horizon.get(horizon) if direction_by_horizon else None
            for horizon in Horizon
        }
        for horizon in Horizon:
            if directions[horizon] is None:
                directions[horizon] = _direction_from_series(ohlcv)
        cross_horizon_state = _cross_horizon_state(directions)

        base_features = FeatureBundle(
            series=ohlcv,
            horizon=Horizon.SWING,
            current_state=(technical_state_by_horizon or {}).get(Horizon.SWING, _state_from_direction(directions[Horizon.SWING])),
            turnover_value_20d_avg=_avg_turnover(ohlcv),
        )
        market_gate = evaluate_market_gate(symbol, base_features, context, self.registry)
        if market_gate.gate_status in {MarketGateStatus.SUSPENSION, MarketGateStatus.DISPOSITION_SUSPENDED} and market_gate.suppress_all_votes:
            return self._build_suspended_result(symbol, symbol_name or symbol, sector_tag, market_cap_bucket, ohlcv, context, market_gate, data_quality, data_quality_score, now, v2_quant_analysis)

        horizons: dict[Horizon, HorizonAnalysisResult] = {}
        score_audits: dict[Horizon, ScoreEngineResult] = {}
        cap_audits: dict[Horizon, ConfidenceCapEngineResult] = {}
        all_factor_votes: dict[FactorCategory, FactorVote] = {}

        for horizon in Horizon:
            direction = directions[horizon] or TrendDirection.NEUTRAL
            state = (technical_state_by_horizon or {}).get(horizon, _state_from_direction(direction))
            features = FeatureBundle(
                series=ohlcv,
                horizon=horizon,
                current_state=state,
                turnover_value_20d_avg=_avg_turnover(ohlcv),
                rsi_series=(Decimal("55"),),
                atr_ratio_percentile_60d=Decimal("50"),
            )
            votes = (factor_votes_by_horizon or {}).get(horizon) or _default_votes(ohlcv, direction, analysis_date)
            categories = _categories_in_agreement(votes)
            invalidations = _default_invalidations(direction)
            signal_aggregation = aggregate_signals(
                symbol,
                analysis_date,
                horizon,
                state,
                market_gate=market_gate,
                registry=self.registry,
            )
            modifiers = dict((signal_modifiers_by_horizon or {}).get(horizon, {}))
            if signal_aggregation.aggregated_signal_score_modifier:
                modifiers["O"] = signal_aggregation.aggregated_signal_score_modifier

            cross_modifier = Decimal("1.1") if cross_horizon_state == "triple_resonance_confluence" else ONE
            if horizon == Horizon.SHORT_TERM and directions[Horizon.SHORT_TERM] == TrendDirection.BULLISH and directions[Horizon.LONG_TERM] == TrendDirection.BEARISH:
                cross_modifier = Decimal("0.6")

            score_result = compute_three_axis_scores(
                symbol=symbol,
                analysis_date=analysis_date,
                horizon=horizon,
                factor_votes=votes,
                features=features,
                context=context,
                signal_modifiers=modifiers,
                categories_in_agreement=categories,
                cross_horizon_state=cross_horizon_state,
                cross_horizon_modifier_value=cross_modifier,
                market_gate=market_gate,
                reasons=[reason for vote in votes for reason in vote.reasons],
                registry=self.registry,
            )
            module_caps = list((module_caps_by_horizon or {}).get(horizon, []))
            if signal_aggregation.aggregated_confidence < 100:
                module_caps.append(("O", signal_aggregation.aggregated_confidence, "module_event_cap"))
            cap_candidates = collect_cap_candidates(
                data_source=data_quality,
                data_quality_score=data_quality_score,
                categories_in_agreement=len(categories),
                factor_votes=votes,
                direction=direction,
                invalidation_signals=[
                    InvalidationSignal(item.description, item.trigger_expression, item.monitored_fields)
                    for item in invalidations
                ],
                context=context,
                horizon=horizon,
                market_gate=market_gate,
                module_event_caps=module_caps,
                cross_horizon_state=cross_horizon_state,
            )
            cap_result = apply_confidence_caps(score_result.scores.confidence_raw, cap_candidates)
            cap_reason = cap_result.strictest_cap.user_message if cap_result.strictest_cap and cap_result.was_capped else None
            horizon_result = HorizonAnalysisResult(
                horizon=horizon,
                technical_state=state,
                state_label_zh=_state_label(state),
                state_detail=f"{_direction_label(direction)}，signal {score_result.scores.signal} / confidence {cap_result.confidence_final} / risk {score_result.scores.risk}",
                direction=direction,
                scores=ThreeAxisScore(score_result.scores.signal, cap_result.confidence_final, score_result.scores.risk, cap_reason),
                factor_votes={vote.category: vote for vote in votes},
                categories_in_agreement=categories,
                dow_structure=_dow_structure(direction),
                wyckoff_phase=_wyckoff_phase(direction),
                invalidation_conditions=invalidations,
                reasons=score_result.scores.reasons,
                signal_aggregation=signal_aggregation,
                score_engine_audit=score_result,
                cap_engine_audit=cap_result,
            )
            horizons[horizon] = horizon_result
            score_audits[horizon] = score_result
            cap_audits[horizon] = cap_result
            for vote in votes:
                all_factor_votes.setdefault(vote.category, vote)

        overall = _overall_scores(horizons)
        primary_horizon = horizons[Horizon.SWING]
        evidence = _evidence_ledger(horizons)
        return AIAnalysisResult(
            symbol=symbol,
            symbol_name=symbol_name or symbol,
            sector_tag=sector_tag,
            market_cap_bucket=market_cap_bucket,
            analysis_date=analysis_date,
            analyzed_at=now,
            next_update_at=now + timedelta(minutes=30),
            current_price=ohlcv.latest().close,
            price_change=_price_change_value(ohlcv),
            price_change_pct=_price_change_pct(ohlcv),
            overall_direction=_overall_direction(horizons),
            cross_horizon_state=cross_horizon_state,
            overall_scores=overall,
            one_line_summary=_summary(overall, cross_horizon_state, primary_horizon),
            horizons=horizons,
            bullish_scenario=_bullish_scenario(),
            bearish_scenario=_bearish_scenario(),
            evidence_ledger=evidence,
            structure_panel=_structure_panel(primary_horizon, ohlcv),
            report_sections=_report_sections(primary_horizon, v2_quant_analysis),
            data_sources=sorted({bar.data_source for bar in ohlcv.bars}),
            models_used=["technical-rule-v1", "score-engine-p", "confidence-cap-q", "quant-v2-preview"],
            data_quality=data_quality,
            data_quality_score=data_quality_score,
            v2_quant_analysis=v2_quant_analysis,
            is_v1_hypothesis=True,
            rule_set_version=self.registry.version,
            disposition_status=market_gate.disposition_status,
            market_gate=market_gate,
            factor_votes=all_factor_votes,
            score_engine_audit=score_audits,
            cap_engine_audit=cap_audits,
            primary_unified_signal=primary_horizon.signal_aggregation.primary_signal,
            secondary_unified_signals=primary_horizon.signal_aggregation.secondary_signals,
        )

    def _build_suspended_result(
        self,
        symbol: str,
        symbol_name: str,
        sector_tag: str,
        market_cap_bucket: str,
        ohlcv: OHLCVSeries,
        context: ContextBundle,
        market_gate: MarketGate,
        data_quality: str,
        data_quality_score: int,
        now: datetime,
        v2_quant_analysis: V2QuantAnalysisResult,
    ) -> AIAnalysisResult:
        direction = TrendDirection.NEUTRAL
        state = TechnicalState.DATA_INSUFFICIENT
        horizons: dict[Horizon, HorizonAnalysisResult] = {}
        score_audits: dict[Horizon, ScoreEngineResult] = {}
        cap_audits: dict[Horizon, ConfidenceCapEngineResult] = {}
        for horizon in Horizon:
            vote = FactorVote(FactorCategory.PRICE_POSITION, TrendDirection.NEUTRAL, ZERO)
            score_result = compute_three_axis_scores(
                symbol=symbol,
                analysis_date=ohlcv.latest().date,
                horizon=horizon,
                factor_votes=[vote],
                features=FeatureBundle(series=ohlcv, horizon=horizon, current_state=state),
                context=context,
                categories_in_agreement=[],
                market_gate=market_gate,
                registry=self.registry,
            )
            cap_result = apply_confidence_caps(
                score_result.scores.confidence_raw,
                collect_cap_candidates(
                    data_source=data_quality,
                    data_quality_score=data_quality_score,
                    categories_in_agreement=0,
                    factor_votes=[vote],
                    direction=direction,
                    context=context,
                    horizon=horizon,
                    market_gate=market_gate,
                    module_event_caps=[("M", market_gate.confidence_cap or 25, "disposition_stage_2")],
                ),
            )
            signal_aggregation = aggregate_signals(symbol, ohlcv.latest().date, horizon, state, market_gate=market_gate, registry=self.registry)
            horizons[horizon] = HorizonAnalysisResult(
                horizon=horizon,
                technical_state=state,
                state_label_zh=_state_label(state),
                state_detail=market_gate.user_message or "技術分析暫停",
                direction=direction,
                scores=ThreeAxisScore(50, cap_result.confidence_final, 50, cap_result.strictest_cap.user_message if cap_result.strictest_cap else None),
                factor_votes={vote.category: vote},
                categories_in_agreement=[],
                dow_structure="undefined",
                wyckoff_phase="unclear",
                invalidation_conditions=[],
                reasons=market_gate.reasons,
                signal_aggregation=signal_aggregation,
                score_engine_audit=score_result,
                cap_engine_audit=cap_result,
            )
            score_audits[horizon] = score_result
            cap_audits[horizon] = cap_result

        primary = horizons[Horizon.SWING]
        return AIAnalysisResult(
            symbol=symbol,
            symbol_name=symbol_name,
            sector_tag=sector_tag,
            market_cap_bucket=market_cap_bucket,
            analysis_date=ohlcv.latest().date,
            analyzed_at=now,
            next_update_at=now + timedelta(minutes=30),
            current_price=ohlcv.latest().close,
            price_change=_price_change_value(ohlcv),
            price_change_pct=_price_change_pct(ohlcv),
            overall_direction=direction,
            cross_horizon_state="mixed_uncertain",
            overall_scores=ThreeAxisScore(50, primary.scores.confidence, 50, primary.scores.confidence_cap_reason),
            one_line_summary=market_gate.user_message or "技術分析暫停",
            horizons=horizons,
            bullish_scenario=_bullish_scenario(),
            bearish_scenario=_bearish_scenario(),
            evidence_ledger=[],
            structure_panel=_structure_panel(primary, ohlcv),
            report_sections=_report_sections(primary, v2_quant_analysis),
            data_sources=sorted({bar.data_source for bar in ohlcv.bars}),
            models_used=["technical-rule-v1", "market-gate-m", "quant-v2-preview"],
            data_quality=data_quality,
            data_quality_score=data_quality_score,
            v2_quant_analysis=v2_quant_analysis,
            is_v1_hypothesis=True,
            rule_set_version=self.registry.version,
            disposition_status=market_gate.disposition_status,
            market_gate=market_gate,
            factor_votes=primary.factor_votes,
            score_engine_audit=score_audits,
            cap_engine_audit=cap_audits,
            primary_unified_signal=primary.signal_aggregation.primary_signal,
            secondary_unified_signals=primary.signal_aggregation.secondary_signals,
        )


def _default_votes(ohlcv: OHLCVSeries, direction: TrendDirection, analysis_date: date) -> list[FactorVote]:
    pct = _price_change_pct(ohlcv)
    strength = min(abs(pct) / Decimal("5"), ONE)
    reason = ReasonTrace("收盤漲跌幅推導價格位置票", "close", analysis_date, "pct_change(close, previous_close)", quantize(pct))
    ma_direction = direction if direction != TrendDirection.NEUTRAL else TrendDirection.NEUTRAL
    return [
        FactorVote(FactorCategory.PRICE_POSITION, direction, quantize(strength), (reason,)),
        FactorVote(FactorCategory.MA_GEOMETRY, ma_direction, Decimal("0.5"), (reason,)),
        FactorVote(FactorCategory.VOLUME_QUALITY, TrendDirection.NEUTRAL, Decimal("0.4"), (reason,), exclude_from_consensus=True),
        FactorVote(FactorCategory.STRUCTURE, ma_direction, Decimal("0.45"), (reason,)),
        FactorVote(FactorCategory.MOMENTUM, ma_direction, Decimal("0.4"), (reason,)),
        FactorVote(FactorCategory.VOLATILITY, TrendDirection.NEUTRAL, Decimal("0.3"), (reason,), exclude_from_consensus=True),
        FactorVote(FactorCategory.CHIP_FLOW, TrendDirection.NEUTRAL, Decimal("0.3"), (reason,), exclude_from_consensus=True),
    ]


def _default_invalidations(direction: TrendDirection) -> list[InvalidationCondition]:
    if direction == TrendDirection.NEUTRAL:
        return []
    if direction in {TrendDirection.BULLISH, TrendDirection.NEUTRAL_BULLISH}:
        return [
            InvalidationCondition("收盤跌破 MA20", "close < ma20", ["close", "ma20"]),
            InvalidationCondition("跌破最近 swing low", "close < last_swing_low", ["close", "last_swing_low"]),
        ]
    return [
        InvalidationCondition("重新站回 MA20", "close > ma20", ["close", "ma20"]),
        InvalidationCondition("突破最近 swing high", "close > last_swing_high", ["close", "last_swing_high"]),
    ]


def _categories_in_agreement(votes: list[FactorVote]) -> list[FactorCategory]:
    return sorted(
        {
            vote.category
            for vote in votes
            if vote.direction != TrendDirection.NEUTRAL and not vote.exclude_from_consensus
        },
        key=lambda category: category.value,
    )


def _cross_horizon_state(directions: Mapping[Horizon, TrendDirection | None]) -> str:
    values = [directions[horizon] for horizon in Horizon]
    if all(value == TrendDirection.BULLISH for value in values):
        return "triple_resonance_confluence"
    if all(value in {TrendDirection.BULLISH, TrendDirection.NEUTRAL_BULLISH} for value in values):
        return "aligned_bullish"
    if all(value in {TrendDirection.BEARISH, TrendDirection.NEUTRAL_BEARISH} for value in values):
        return "aligned_bearish"
    if directions[Horizon.SHORT_TERM] == TrendDirection.BULLISH and directions[Horizon.LONG_TERM] == TrendDirection.BEARISH:
        return "mixed_uncertain"
    return "mixed_uncertain"


def _direction_from_series(ohlcv: OHLCVSeries) -> TrendDirection:
    pct = _price_change_pct(ohlcv)
    if pct >= Decimal("2"):
        return TrendDirection.BULLISH
    if pct <= Decimal("-2"):
        return TrendDirection.BEARISH
    if pct > Decimal("0.3"):
        return TrendDirection.NEUTRAL_BULLISH
    if pct < Decimal("-0.3"):
        return TrendDirection.NEUTRAL_BEARISH
    return TrendDirection.NEUTRAL


def _state_from_direction(direction: TrendDirection | None) -> TechnicalState:
    if direction == TrendDirection.BULLISH:
        return TechnicalState.STRONG_UPTREND
    if direction == TrendDirection.NEUTRAL_BULLISH:
        return TechnicalState.EARLY_STRENGTHENING
    if direction == TrendDirection.NEUTRAL_BEARISH:
        return TechnicalState.EARLY_WEAKENING
    if direction == TrendDirection.BEARISH:
        return TechnicalState.DOWNTREND_CONTINUATION
    return TechnicalState.MIXED_SIGNALS


def _overall_scores(horizons: Mapping[Horizon, HorizonAnalysisResult]) -> ThreeAxisScore:
    signal = round(sum(item.scores.signal for item in horizons.values()) / len(horizons))
    confidence = round(sum(item.scores.confidence for item in horizons.values()) / len(horizons))
    risk = round(sum(item.scores.risk for item in horizons.values()) / len(horizons))
    reason = next((item.scores.confidence_cap_reason for item in horizons.values() if item.scores.confidence_cap_reason), None)
    return ThreeAxisScore(signal, confidence, risk, reason)


def _overall_direction(horizons: Mapping[Horizon, HorizonAnalysisResult]) -> TrendDirection:
    score = sum(_direction_score(item.direction) for item in horizons.values())
    if score >= 2:
        return TrendDirection.BULLISH
    if score > 0:
        return TrendDirection.NEUTRAL_BULLISH
    if score <= -2:
        return TrendDirection.BEARISH
    if score < 0:
        return TrendDirection.NEUTRAL_BEARISH
    return TrendDirection.NEUTRAL


def _direction_score(direction: TrendDirection) -> int:
    return {
        TrendDirection.BULLISH: 1,
        TrendDirection.NEUTRAL_BULLISH: 1,
        TrendDirection.NEUTRAL: 0,
        TrendDirection.NEUTRAL_BEARISH: -1,
        TrendDirection.BEARISH: -1,
    }[direction]


def _evidence_ledger(horizons: Mapping[Horizon, HorizonAnalysisResult]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for horizon, result in horizons.items():
        for vote in result.factor_votes.values():
            weight = int(round(vote.strength * Decimal("10") * Decimal(_direction_score(vote.direction))))
            items.append(EvidenceItem(
                id=f"{horizon.value}-{vote.category.value}",
                source="technical",
                direction=vote.direction.value,
                factor_category=vote.category.value,
                title=f"{horizon.value} {vote.category.value}",
                detail=vote.reasons[0].reason_text if vote.reasons else "factor vote",
                weight=weight,
                trace=vote.reasons[0] if vote.reasons else None,
            ))
    return sorted(items, key=lambda item: abs(item.weight), reverse=True)[:12]


def _structure_panel(horizon: HorizonAnalysisResult, ohlcv: OHLCVSeries) -> StructurePanelData:
    close = ohlcv.latest().close
    pivots = [
        {"date": bar.date.isoformat(), "type": "low" if index % 2 == 0 else "high", "price": str(bar.low if index % 2 == 0 else bar.high), "is_confirmed": True}
        for index, bar in enumerate(ohlcv.bars[-6:])
    ]
    return StructurePanelData(
        dow_structure=horizon.dow_structure,
        wyckoff_phase=horizon.wyckoff_phase,
        recent_pivots=pivots,
        kou_di_ma20=_kou_di(20, close),
        kou_di_ma60=_kou_di(60, close),
        ma_compression_ratio=Decimal("0.035"),
        is_compressed=False,
    )


def _kou_di(window: int, close: Decimal) -> dict[str, Any]:
    ma = close * (Decimal("0.975") if window == 20 else Decimal("0.935"))
    return {
        "ma_window": window,
        "current_ma_value": str(quantize(ma, "0.01")),
        "current_close": str(close),
        "expected_direction_next_5d": "up" if close > ma else "flat",
        "expected_slope_change_pct": str(quantize((close - ma) / ma * HUNDRED, "0.01")),
    }


def _report_sections(primary: HorizonAnalysisResult, v2_quant: V2QuantAnalysisResult | None = None) -> list[ReportSection]:
    sections = [
        ReportSection("technical_chips", "技術與籌碼延伸", "activity", primary.signal_aggregation.user_facing_label, primary.signal_aggregation.user_facing_description),
        ReportSection("scenarios", "情境分析", "route", "依失效條件管理部位", "多空劇本皆需等待觸發條件。"),
        ReportSection("rating", "評級摘要", "rating", primary.state_label_zh, primary.state_detail),
    ]
    if v2_quant is not None:
        risk = v2_quant.risk_execution
        profile = v2_quant.volume_profile
        preview = "v2.0 時空推演與硬風控"
        body = (
            f"基本面 Gate：{v2_quant.fundamental_gate.status}；"
            f"POC：{profile.poc_price or 'N/A'}；"
            f"RR：{risk.rr_ratio or 'N/A'}；"
            f"強制離場：{risk.forced_exit_reason or 'none'}。"
        )
        sections.append(ReportSection("quant_v2", "v2.0 量化預覽", "target", preview, body))
    return sections


def _bullish_scenario() -> Scenario:
    return Scenario(
        direction="bullish",
        label="多方成立條件",
        conditions=[ScenarioCondition("收盤站回 MA20 且量能不低於均量", ["close", "ma20", "volume"], "close > ma20 AND volume >= vma20")],
        action_if_triggered="列入觀察並採分批策略。",
        scope_horizons=[Horizon.SHORT_TERM.value, Horizon.SWING.value],
    )


def _bearish_scenario() -> Scenario:
    return Scenario(
        direction="bearish",
        label="失效與風險條件",
        conditions=[ScenarioCondition("跌破 MA20 且量能放大", ["close", "ma20", "volume"], "close < ma20 AND volume > vma20 * 1.5")],
        action_if_triggered="降低部位或停止加碼。",
        scope_horizons=[Horizon.SHORT_TERM.value, Horizon.SWING.value],
    )


def _summary(scores: ThreeAxisScore, cross_horizon_state: str, primary: HorizonAnalysisResult) -> str:
    return f"{primary.signal_aggregation.user_facing_label}，{cross_horizon_state}；signal {scores.signal} / confidence {scores.confidence} / risk {scores.risk}。"


def _price_change_value(ohlcv: OHLCVSeries) -> Decimal:
    previous = ohlcv.previous()
    if not previous:
        return ZERO
    return quantize(ohlcv.latest().close - previous.close, "0.01")


def _price_change_pct(ohlcv: OHLCVSeries) -> Decimal:
    previous = ohlcv.previous()
    if not previous:
        return ZERO
    return quantize(pct_change(ohlcv.latest().close, previous.close, ZERO) or ZERO, "0.01")


def _avg_turnover(ohlcv: OHLCVSeries) -> Decimal:
    bars = ohlcv.bars[-20:]
    return sum((bar.turnover_value for bar in bars), ZERO) / Decimal(len(bars))


def _data_quality(ohlcv: OHLCVSeries) -> str:
    sources = {bar.data_source for bar in ohlcv.bars}
    if "mock" in sources:
        return "mock"
    if "fallback" in sources:
        return "fallback"
    return "live"


def _direction_label(direction: TrendDirection) -> str:
    return {
        TrendDirection.BULLISH: "偏多",
        TrendDirection.NEUTRAL_BULLISH: "中性偏多",
        TrendDirection.NEUTRAL: "中性",
        TrendDirection.NEUTRAL_BEARISH: "中性偏空",
        TrendDirection.BEARISH: "偏空",
    }[direction]


def _state_label(state: TechnicalState) -> str:
    return {
        TechnicalState.STRONG_UPTREND: "強勢多頭態",
        TechnicalState.STEADY_UPTREND: "穩健增長態",
        TechnicalState.TIGHT_CONSOLIDATION: "窄幅整理態",
        TechnicalState.CONSOLIDATION: "盤整態",
        TechnicalState.EARLY_STRENGTHENING: "早期轉強態",
        TechnicalState.OVERHEATED_HIGH_LEVEL: "高檔過熱態",
        TechnicalState.PARABOLIC_OVERHEAT: "極端噴發態",
        TechnicalState.HIGH_LEVEL_DISTRIBUTION: "高位派發態",
        TechnicalState.EARLY_WEAKENING: "初步轉弱態",
        TechnicalState.WEAK_REBOUND: "弱勢反彈態",
        TechnicalState.SELLING_CLIMAX: "恐慌衰竭態",
        TechnicalState.DOWNTREND_CONTINUATION: "空頭延續態",
        TechnicalState.MIXED_SIGNALS: "多空混雜",
        TechnicalState.DATA_INSUFFICIENT: "資料不足",
    }[state]


def _dow_structure(direction: TrendDirection) -> str:
    if direction in {TrendDirection.BULLISH, TrendDirection.NEUTRAL_BULLISH}:
        return "bullish_intact"
    if direction in {TrendDirection.BEARISH, TrendDirection.NEUTRAL_BEARISH}:
        return "bearish_intact"
    return "undefined"


def _wyckoff_phase(direction: TrendDirection) -> str:
    if direction == TrendDirection.BULLISH:
        return "markup"
    if direction == TrendDirection.NEUTRAL_BULLISH:
        return "accumulation_d"
    if direction == TrendDirection.NEUTRAL_BEARISH:
        return "distribution_a"
    if direction == TrendDirection.BEARISH:
        return "markdown"
    return "unclear"


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {_serialize(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def ai_analysis_result_json_schema() -> dict[str, Any]:
    """Lightweight JSON schema for frontend type generation."""

    return {
        "title": "AIAnalysisResult",
        "type": "object",
        "required": ["symbol", "overall_scores", "horizons", "evidence_ledger", "data_quality"],
        "properties": {
            "symbol": {"type": "string"},
            "symbol_name": {"type": "string"},
            "current_price": {"type": "string", "description": "Decimal string"},
            "overall_direction": {"type": "string"},
            "cross_horizon_state": {"type": "string"},
            "overall_scores": {"$ref": "#/$defs/ThreeAxisScore"},
            "horizons": {"type": "object"},
            "evidence_ledger": {"type": "array", "items": {"type": "object"}},
            "data_quality": {"type": "string"},
            "v2_quant_analysis": {"type": "object"},
            "score_engine_audit": {"type": "object"},
            "cap_engine_audit": {"type": "object"},
        },
        "$defs": {
            "ThreeAxisScore": {
                "type": "object",
                "required": ["signal", "confidence", "risk"],
                "properties": {
                    "signal": {"type": "integer", "minimum": 0, "maximum": 100},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "risk": {"type": "integer", "minimum": 0, "maximum": 100},
                    "confidence_cap_reason": {"type": ["string", "null"]},
                },
            }
        },
    }
