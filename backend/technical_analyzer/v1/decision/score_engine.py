"""Topic P: independent signal, confidence, and risk scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping, Optional

from ..common import ONE, ZERO, clamp, quantize
from ..contracts.enums import FactorCategory, Horizon, TechnicalState, TrendDirection
from ..contracts.feature_contract import FeatureBundle
from ..contracts.input_contract import ContextBundle
from ..contracts.output_contract import FactorVote
from ..registry.rule_registry import RuleRegistry
from ..special_rules.taiwan_market_rules import MarketGate
from ..traceability.trace import ReasonTrace


HUNDRED_INT = Decimal("100")
DEFAULT_SIGNAL_BASE = 50
DEFAULT_CONFIDENCE_BASE = 60
DEFAULT_RISK_BASE = 30
MODIFIER_LIMIT = 30

DEFAULT_FACTOR_WEIGHTS: dict[FactorCategory, Decimal] = {
    FactorCategory.PRICE_POSITION: Decimal("0.18"),
    FactorCategory.MA_GEOMETRY: Decimal("0.18"),
    FactorCategory.VOLUME_QUALITY: Decimal("0.18"),
    FactorCategory.STRUCTURE: Decimal("0.15"),
    FactorCategory.MOMENTUM: Decimal("0.13"),
    FactorCategory.VOLATILITY: Decimal("0.08"),
    FactorCategory.CHIP_FLOW: Decimal("0.10"),
}


@dataclass(frozen=True)
class ThreeAxisScores:
    signal: int
    confidence_raw: int
    risk: int
    signal_base: int
    signal_modifiers: dict[str, int] = field(default_factory=dict)
    signal_total_modifier: int = 0
    confidence_base: int = DEFAULT_CONFIDENCE_BASE
    confidence_adjustments: dict[str, int] = field(default_factory=dict)
    risk_base: int = DEFAULT_RISK_BASE
    risk_factors: dict[str, int] = field(default_factory=dict)
    reasons: list[ReasonTrace] = field(default_factory=list)


@dataclass(frozen=True)
class ScoreEngineResult:
    symbol: str
    analysis_date: date
    horizon: Horizon
    scores: ThreeAxisScores
    cross_horizon_modifier_applied: bool
    cross_horizon_modifier_value: Decimal


def compute_three_axis_scores(
    *,
    symbol: str,
    analysis_date: date,
    horizon: Horizon,
    factor_votes: Iterable[FactorVote],
    features: FeatureBundle | None = None,
    context: ContextBundle | None = None,
    signal_modifiers: Mapping[str, int] | None = None,
    categories_in_agreement: Iterable[FactorCategory] | None = None,
    cross_horizon_state: str | None = None,
    cross_horizon_modifier_value: Decimal = ONE,
    reasons: Iterable[ReasonTrace] = (),
    market_gate: MarketGate | None = None,
    internal_inconsistency_flags: Mapping[str, bool] | None = None,
    chip_resonance_pattern: str | None = None,
    bias_20_zscore: Decimal | None = None,
    distance_to_nearest_support_pct: Decimal | None = None,
    nearest_support_strength_tier: str | None = None,
    healthy_pullback: bool = False,
    confirmed_institutional_defense: bool = False,
    distribution_flags: Iterable[str] = (),
    registry: RuleRegistry | None = None,
) -> ScoreEngineResult:
    """Compute P's three axes with independent formulas.

    Signal uses factor vote weights plus event modifiers. Confidence uses data
    completeness/agreement/traceability. Risk uses volatility, overheat,
    support distance, market context, and Taiwan-specific distortion flags.
    """

    votes = list(factor_votes)
    reason_list = list(reasons) or [reason for vote in votes for reason in vote.reasons]
    weights = _load_weights(registry)

    signal_base = _compute_signal_base(votes, weights)
    modifiers = {k: int(v) for k, v in (signal_modifiers or {}).items()}
    total_modifier = _clip_int(sum(modifiers.values()), -MODIFIER_LIMIT, MODIFIER_LIMIT)
    signal_before_cross = _clip_int(signal_base + total_modifier, 0, 100)
    signal = _clip_int(round(Decimal(signal_before_cross) * cross_horizon_modifier_value), 0, 100)

    agreement_count = _agreement_count(votes, categories_in_agreement)
    confidence_adjustments = _confidence_adjustments(
        agreement_count=agreement_count,
        cross_horizon_state=cross_horizon_state,
        context=context,
        reasons=reason_list,
        features=features,
        market_gate=market_gate,
        internal_inconsistency_flags=internal_inconsistency_flags or {},
        chip_resonance_pattern=chip_resonance_pattern,
    )
    confidence_raw = _clip_int(DEFAULT_CONFIDENCE_BASE + sum(confidence_adjustments.values()), 0, 100)

    risk_factors = _risk_factors(
        features=features,
        context=context,
        market_gate=market_gate,
        bias_20_zscore=bias_20_zscore,
        distance_to_nearest_support_pct=distance_to_nearest_support_pct,
        nearest_support_strength_tier=nearest_support_strength_tier,
        healthy_pullback=healthy_pullback,
        confirmed_institutional_defense=confirmed_institutional_defense,
        distribution_flags=list(distribution_flags),
    )
    risk = _clip_int(DEFAULT_RISK_BASE + sum(risk_factors.values()), 0, 100)

    return ScoreEngineResult(
        symbol=symbol,
        analysis_date=analysis_date,
        horizon=horizon,
        scores=ThreeAxisScores(
            signal=signal,
            confidence_raw=confidence_raw,
            risk=risk,
            signal_base=signal_base,
            signal_modifiers=modifiers,
            signal_total_modifier=total_modifier,
            confidence_adjustments=confidence_adjustments,
            risk_factors=risk_factors,
            reasons=reason_list,
        ),
        cross_horizon_modifier_applied=cross_horizon_modifier_value != ONE,
        cross_horizon_modifier_value=quantize(cross_horizon_modifier_value),
    )


def _load_weights(registry: RuleRegistry | None) -> dict[FactorCategory, Decimal]:
    if registry is None:
        try:
            registry = RuleRegistry.load_default()
        except Exception:
            return DEFAULT_FACTOR_WEIGHTS
    section = registry.raw.get("score_engine", {}) if isinstance(registry.raw, dict) else {}
    raw = section.get("factor_weights", {}).get("default", {}) if isinstance(section, dict) else {}
    if not raw:
        return DEFAULT_FACTOR_WEIGHTS

    aliases = {
        FactorCategory.PRICE_POSITION: ("price_position", "price_vs_ma", "PRICE_VS_MA"),
        FactorCategory.MA_GEOMETRY: ("ma_geometry", "MA_GEOMETRY"),
        FactorCategory.VOLUME_QUALITY: ("volume_quality", "VOLUME_QUALITY"),
        FactorCategory.STRUCTURE: ("structure", "STRUCTURE"),
        FactorCategory.MOMENTUM: ("momentum", "MOMENTUM"),
        FactorCategory.VOLATILITY: ("volatility", "VOLATILITY"),
        FactorCategory.CHIP_FLOW: ("chip_flow", "CHIP_FLOW"),
    }
    weights = DEFAULT_FACTOR_WEIGHTS.copy()
    for category, keys in aliases.items():
        for key in keys:
            if key in raw:
                weights[category] = Decimal(str(raw[key]))
                break
    total = sum(weights.values(), ZERO)
    if total == ZERO:
        return DEFAULT_FACTOR_WEIGHTS
    return {category: weight / total for category, weight in weights.items()}


def _compute_signal_base(votes: list[FactorVote], weights: Mapping[FactorCategory, Decimal]) -> int:
    strongest_by_category: dict[FactorCategory, Decimal] = {}
    for vote in votes:
        if vote.category not in weights:
            continue
        signed = vote.strength * _direction_sign(vote.direction)
        current = strongest_by_category.get(vote.category)
        if current is None or abs(signed) > abs(current):
            strongest_by_category[vote.category] = signed

    weighted = sum(
        strongest_by_category.get(category, ZERO) * weight
        for category, weight in weights.items()
    )
    score = Decimal(DEFAULT_SIGNAL_BASE) + weighted * Decimal("50")
    return _clip_int(round(score), 0, 100)


def _direction_sign(direction: TrendDirection) -> Decimal:
    if direction == TrendDirection.BULLISH:
        return ONE
    if direction == TrendDirection.NEUTRAL_BULLISH:
        return Decimal("0.5")
    if direction == TrendDirection.NEUTRAL_BEARISH:
        return Decimal("-0.5")
    if direction == TrendDirection.BEARISH:
        return Decimal("-1")
    return ZERO


def _agreement_count(votes: list[FactorVote], categories: Iterable[FactorCategory] | None) -> int:
    if categories is not None:
        return len(set(categories))
    return len({
        vote.category
        for vote in votes
        if vote.direction != TrendDirection.NEUTRAL and not vote.exclude_from_consensus
    })


def _confidence_adjustments(
    *,
    agreement_count: int,
    cross_horizon_state: str | None,
    context: ContextBundle | None,
    reasons: list[ReasonTrace],
    features: FeatureBundle | None,
    market_gate: MarketGate | None,
    internal_inconsistency_flags: Mapping[str, bool],
    chip_resonance_pattern: str | None,
) -> dict[str, int]:
    adjustments: dict[str, int] = {}
    if agreement_count >= 6:
        adjustments["factor_agreement_bonus"] = 15
    elif agreement_count == 5:
        adjustments["factor_agreement_bonus"] = 10
    elif agreement_count == 4:
        adjustments["factor_agreement_bonus"] = 5
    elif agreement_count < 3:
        adjustments["factor_agreement_bonus"] = -15
    else:
        adjustments["factor_agreement_bonus"] = 0

    if cross_horizon_state == "triple_resonance_confluence":
        adjustments["cross_horizon_alignment_bonus"] = 15
    elif cross_horizon_state in {"aligned_bullish", "aligned_bearish"}:
        adjustments["cross_horizon_alignment_bonus"] = 10
    elif cross_horizon_state in {"mixed_uncertain", "mixed"}:
        adjustments["cross_horizon_alignment_bonus"] = -10

    completeness = context.completeness() if context else ZERO
    if completeness == ONE:
        adjustments["context_completeness_bonus"] = 5
    elif completeness < Decimal("0.5"):
        adjustments["context_completeness_bonus"] = -10
    else:
        adjustments["context_completeness_bonus"] = 0

    if reasons and all(reason.calculation_value is not None for reason in reasons):
        adjustments["traceability_bonus"] = 5
    elif reasons and sum(1 for reason in reasons if reason.calculation_value is None) <= len(reasons) // 2:
        adjustments["traceability_bonus"] = 0
    else:
        adjustments["traceability_bonus"] = -10

    if features and any(bar.data_source == "mock" for bar in features.series.bars):
        adjustments["mock_data"] = -25
    elif features and any(bar.data_source == "fallback" for bar in features.series.bars):
        adjustments["fallback_data"] = -15
    if context and _chip_context_partial(context):
        adjustments["partial_chip_fields"] = -10

    if internal_inconsistency_flags.get("j_ae_parabolic_mismatch"):
        adjustments["j_ae_inconsistency"] = -20
    if internal_inconsistency_flags.get("k_l_modifier_conflict"):
        adjustments["k_l_conflict"] = -10
    if internal_inconsistency_flags.get("f_h_direction_conflict"):
        adjustments["f_h_conflict"] = -5

    if market_gate:
        flags = set(market_gate.indicator_distortion_flags)
        if "price_discovery_distorted" in flags or market_gate.is_limit_up or market_gate.is_limit_down:
            adjustments["limit_distortion"] = -10
        if "disposition_distorted" in flags:
            adjustments["disposition_distortion"] = -30
        if market_gate.is_ex_rights_adjacent:
            adjustments["ex_rights_adjacent"] = -5

    if chip_resonance_pattern == "golden_resonance_strong":
        adjustments["chip_resonance_bonus"] = 10
    elif chip_resonance_pattern == "false_rally_high_confidence":
        adjustments["chip_resonance_bonus"] = -10
    return adjustments


def _chip_context_partial(context: ContextBundle) -> bool:
    chip_fields = (
        context.foreign_net_today,
        context.trust_net_today,
        context.dealer_net_today,
        context.large_order_buy_ratio,
        context.large_order_sell_ratio,
    )
    return any(value is None for value in chip_fields)


def _risk_factors(
    *,
    features: FeatureBundle | None,
    context: ContextBundle | None,
    market_gate: MarketGate | None,
    bias_20_zscore: Decimal | None,
    distance_to_nearest_support_pct: Decimal | None,
    nearest_support_strength_tier: str | None,
    healthy_pullback: bool,
    confirmed_institutional_defense: bool,
    distribution_flags: list[str],
) -> dict[str, int]:
    factors: dict[str, int] = {}
    z = abs(bias_20_zscore) if bias_20_zscore is not None else None
    if z is not None:
        if z > Decimal("2.5"):
            factors["deviation_risk"] = 25
        elif z >= Decimal("2.0"):
            factors["deviation_risk"] = 18
        elif z >= Decimal("1.5"):
            factors["deviation_risk"] = 12
        elif z >= Decimal("1.0"):
            factors["deviation_risk"] = 6

    rsi = features.latest_value("rsi") if features else None
    if rsi is not None:
        if rsi > Decimal("80"):
            factors["momentum_overheat"] = 12
        elif rsi > Decimal("75") and features and features.current_state in {TechnicalState.STRONG_UPTREND, TechnicalState.STEADY_UPTREND}:
            factors["momentum_overheat"] = 5
        elif rsi > Decimal("75"):
            factors["momentum_overheat"] = 12
    kd_k = features.latest_value("kd_k") if features else None
    if kd_k is not None and kd_k > Decimal("80"):
        factors["kd_high_dulling"] = 5

    atr_pct = features.atr_ratio_percentile_60d if features else None
    if atr_pct is not None:
        if atr_pct > Decimal("90"):
            factors["volatility_expansion"] = 15
        elif atr_pct > Decimal("75"):
            factors["volatility_expansion"] = 8
    if features and features.bollinger_bandwidth_series:
        latest_bandwidth = next((v for v in reversed(features.bollinger_bandwidth_series) if v is not None), None)
        if latest_bandwidth is not None and latest_bandwidth > Decimal("0.12"):
            factors["bollinger_expansion"] = 5

    distribution_risk = 0
    flag_set = set(distribution_flags)
    if flag_set & {"distribution_at_high", "distribution_dump"}:
        distribution_risk += 12
    if "severe_overheat" in flag_set:
        distribution_risk += 15
    if "parabolic_overheat" in flag_set:
        distribution_risk += 20
    if flag_set & {"confirmed_double_top", "confirmed_head_and_shoulders"}:
        distribution_risk += 18
    if "false_rally_high_confidence" in flag_set:
        distribution_risk += 20
    if distribution_risk:
        factors["distribution_risk"] = min(distribution_risk, 35)

    if distance_to_nearest_support_pct is not None:
        if distance_to_nearest_support_pct > Decimal("15"):
            factors["support_proximity_risk"] = 18
        elif distance_to_nearest_support_pct > Decimal("10"):
            factors["support_proximity_risk"] = 10
        elif distance_to_nearest_support_pct < Decimal("2"):
            factors["support_proximity_reduction"] = -10
        if nearest_support_strength_tier == "strong" and distance_to_nearest_support_pct < Decimal("3"):
            factors["strong_support_reduction"] = factors.get("strong_support_reduction", 0) - 5

    if context:
        if context.market_regime == "bear":
            factors["market_context_risk"] = factors.get("market_context_risk", 0) + 10
        if context.sector_strength == "weak":
            factors["sector_context_risk"] = 5
        if context.liquidity_bucket == "low":
            factors["liquidity_risk"] = 8
        elif context.liquidity_bucket == "illiquid":
            factors["liquidity_risk"] = 15
        if context.day_trading_ratio is not None and context.day_trading_ratio > Decimal("0.60"):
            factors["day_trading_noise"] = 10
        if context.disposition_status and context.disposition_status != "normal":
            factors["disposition_risk"] = 15

    if market_gate and market_gate.disposition_status != "normal":
        factors["disposition_risk"] = max(factors.get("disposition_risk", 0), 15)
    if market_gate and market_gate.is_limit_up:
        factors["limit_up_distortion"] = max(factors.get("limit_up_distortion", 0), 8)
    if market_gate and market_gate.is_limit_down:
        factors["limit_down_distortion"] = max(factors.get("limit_down_distortion", 0), 12)

    if healthy_pullback and features and features.current_state in {TechnicalState.STRONG_UPTREND, TechnicalState.STEADY_UPTREND}:
        factors["healthy_pullback_reduction"] = -5
    if confirmed_institutional_defense:
        factors["institutional_defense_reduction"] = -8
    if features and features.current_state == TechnicalState.STEADY_UPTREND and (features.atr_ratio_percentile_60d or ZERO) < Decimal("75"):
        factors["steady_uptrend_reduction"] = -5
    return factors


def _clip_int(value: int | Decimal, low: int, high: int) -> int:
    return int(clamp(Decimal(value), Decimal(low), Decimal(high)))
