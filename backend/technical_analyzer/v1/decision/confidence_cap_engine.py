"""Topic Q: hard confidence cap engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional

from ..contracts.enums import Horizon, TrendDirection
from ..contracts.input_contract import ContextBundle
from ..contracts.output_contract import FactorVote, InvalidationSignal
from ..special_rules.taiwan_market_rules import MarketGate, LiquidityTier


CAP_USER_MESSAGES = {
    "mock_data": "示範資料 — 非真實分析結果",
    "fallback_data": "備援資料源 — 信心略降",
    "estimated_data": "估算資料 — 信心保守",
    "data_quality_low": "資料完整度偏低 — 信心已自動下修",
    "categories_insufficient": "因子共識不足（少於 3 個類別同意）",
    "single_factor_dominance": "單一因子主導 — 信心受限",
    "no_invalidation": "缺乏失效條件 — 信心受限",
    "partial_invalidation": "失效條件不足 — 信心受限",
    "low_liquidity": "流動性偏低 — 短線分析信心受限",
    "very_low_liquidity": "流動性極低 — 分析信心受限",
    "high_day_trading": "當沖比偏高 — 量能可信度打折",
    "disposition_attention": "該股為注意股 — 信心已自動下修",
    "disposition_stage_1": "該股處於處置股第一階段 — 技術分析失真",
    "disposition_stage_2": "該股處於處置股第二階段 — 技術分析暫停輸出",
    "limit_distorted": "漲跌停板 — 價格發現失效",
    "consecutive_limits": "連續多日漲跌停 — 指標扭曲",
    "module_event_cap": "模組事件風險 — 信心受限",
    "internal_inconsistency": "模組內部不一致 — 信心受限",
    "cross_horizon_mixed": "跨時序訊號矛盾 — 觀望",
}


@dataclass(frozen=True)
class CapCandidate:
    source_module: str
    cap_value: int
    reason: str
    is_hard_cap: bool = True
    user_message: str | None = None


@dataclass(frozen=True)
class ConfidenceCapEngineResult:
    confidence_raw: int
    cap_candidates: list[CapCandidate] = field(default_factory=list)
    strictest_cap: Optional[CapCandidate] = None
    confidence_final: int = 0
    was_capped: bool = False
    cap_reduction: int = 0


def collect_cap_candidates(
    *,
    data_source: str | None = None,
    data_quality_score: int | None = None,
    categories_in_agreement: int = 0,
    factor_votes: Iterable[FactorVote] = (),
    direction: TrendDirection = TrendDirection.NEUTRAL,
    invalidation_signals: Iterable[InvalidationSignal] = (),
    context: ContextBundle | None = None,
    horizon: Horizon = Horizon.SWING,
    market_gate: MarketGate | None = None,
    module_event_caps: Iterable[tuple[str, int, str] | int] = (),
    internal_inconsistency: bool = False,
    cross_horizon_state: str | None = None,
) -> list[CapCandidate]:
    """Collect all Q cap candidates without applying them."""

    candidates: list[CapCandidate] = []

    def add(source: str, cap: int, reason: str) -> None:
        candidates.append(CapCandidate(source, int(cap), reason, True, CAP_USER_MESSAGES.get(reason)))

    source = (data_source or "").lower()
    if source == "mock":
        add("data_quality", 50, "mock_data")
    elif source == "fallback":
        add("data_quality", 60, "fallback_data")
    elif source == "estimated":
        add("data_quality", 70, "estimated_data")
    if data_quality_score is not None:
        if data_quality_score < 40:
            add("data_quality", 50, "data_quality_low")
        elif data_quality_score < 60:
            add("data_quality", 65, "data_quality_low")

    votes = list(factor_votes)
    if categories_in_agreement < 3:
        add("single_factor_dominance", 50, "categories_insufficient")
    elif categories_in_agreement == 3 and _is_single_factor_dominant(votes):
        add("single_factor_dominance", 60, "single_factor_dominance")

    invalidations = list(invalidation_signals)
    if direction != TrendDirection.NEUTRAL and not invalidations:
        add("missing_invalidation", 60, "no_invalidation")
    elif direction != TrendDirection.NEUTRAL and len(invalidations) < 2:
        add("missing_invalidation", 70, "partial_invalidation")

    liquidity = _liquidity_value(context, market_gate)
    if liquidity == "low" and horizon == Horizon.SHORT_TERM:
        add("liquidity", 60, "low_liquidity")
    if liquidity in {"very_low", "illiquid"} and horizon in {Horizon.SHORT_TERM, Horizon.SWING}:
        add("liquidity", 50, "very_low_liquidity")

    day_trading_ratio = context.day_trading_ratio if context else None
    if day_trading_ratio is not None:
        if day_trading_ratio > Decimal("0.60"):
            add("day_trading_noise", 50, "high_day_trading")
        elif day_trading_ratio > Decimal("0.50"):
            add("day_trading_noise", 65, "high_day_trading")

    disposition_status = _disposition_value(context, market_gate)
    if disposition_status == "attention":
        add("disposition", 70, "disposition_attention")
    elif disposition_status == "stage_1":
        add("disposition", 30, "disposition_stage_1")
    elif disposition_status == "stage_2":
        add("disposition", 25, "disposition_stage_2")

    if market_gate:
        if market_gate.is_limit_up or market_gate.is_limit_down:
            add("limit_distortion", 60, "limit_distorted")
        if market_gate.consecutive_limit_days >= 3:
            add("limit_distortion", 30, "consecutive_limits")
        elif market_gate.consecutive_limit_days >= 2:
            add("limit_distortion", 50, "consecutive_limits")
        if market_gate.confidence_cap is not None:
            add("M", market_gate.confidence_cap, "module_event_cap")

    for raw in module_event_caps:
        if isinstance(raw, tuple):
            source_module, cap, reason = raw
            add(source_module, cap, reason)
        else:
            add("module_event", raw, "module_event_cap")

    if internal_inconsistency:
        add("internal_inconsistency", 40, "internal_inconsistency")
    if cross_horizon_state in {"mixed_uncertain", "mixed"}:
        add("cross_horizon", 60, "cross_horizon_mixed")
    return candidates


def apply_confidence_caps(confidence_raw: int, cap_candidates: Iterable[CapCandidate]) -> ConfidenceCapEngineResult:
    """Apply Q hard caps by taking the strictest candidate."""

    candidates = list(cap_candidates)
    if candidates:
        strictest = min(candidates, key=lambda candidate: candidate.cap_value)
        final = min(int(confidence_raw), strictest.cap_value)
    else:
        strictest = None
        final = int(confidence_raw)
    return ConfidenceCapEngineResult(
        confidence_raw=int(confidence_raw),
        cap_candidates=candidates,
        strictest_cap=strictest,
        confidence_final=final,
        was_capped=final < int(confidence_raw),
        cap_reduction=max(0, int(confidence_raw) - final),
    )


def _is_single_factor_dominant(votes: list[FactorVote]) -> bool:
    non_neutral = [vote for vote in votes if vote.direction != TrendDirection.NEUTRAL]
    if not non_neutral:
        return False
    strengths = sorted((vote.strength for vote in non_neutral), reverse=True)
    return strengths[0] > Decimal("0.9") and all(strength < Decimal("0.4") for strength in strengths[1:])


def _liquidity_value(context: ContextBundle | None, market_gate: MarketGate | None) -> str | None:
    if market_gate:
        if market_gate.liquidity_tier == LiquidityTier.VERY_LOW:
            return "very_low"
        return market_gate.liquidity_tier.value
    return context.liquidity_bucket if context else None


def _disposition_value(context: ContextBundle | None, market_gate: MarketGate | None) -> str:
    if market_gate:
        return market_gate.disposition_status
    return context.disposition_status if context and context.disposition_status else "normal"
