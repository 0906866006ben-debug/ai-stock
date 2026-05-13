"""Topic M: Taiwan market gatekeeper rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..common import ZERO, pct_change, quantize
from ..contracts.feature_contract import FeatureBundle
from ..contracts.input_contract import ContextBundle
from ..registry.rule_registry import RuleRegistry
from ..traceability.trace import ReasonTrace


class MarketGateStatus(str, Enum):
    NORMAL = "normal"
    NOTICE_DEGRADED = "notice_degraded"
    DISPOSITION_SUSPENDED = "disposition_suspended"
    LIMIT_DISTORTED = "limit_distorted"
    SUSPENSION = "suspension"
    THIN_TRADING = "thin_trading"
    EX_RIGHTS = "ex_rights"


class LiquidityTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    VERY_LOW = "very_low"


@dataclass(frozen=True)
class MarketGate:
    gate_status: MarketGateStatus
    disposition_status: str
    is_limit_up: bool
    is_limit_down: bool
    consecutive_limit_days: int
    liquidity_tier: LiquidityTier
    is_ex_rights_today: bool
    is_ex_rights_adjacent: bool
    suppress_all_votes: bool
    suppress_event_detection: bool
    confidence_cap: Optional[int]
    indicator_distortion_flags: list[str]
    user_message: Optional[str]
    reasons: list[ReasonTrace]


def evaluate_market_gate(
    symbol: str,
    features: FeatureBundle,
    context: ContextBundle,
    registry: RuleRegistry | None = None,
) -> MarketGate:
    """Evaluate whether the stock can be analyzed normally today."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("taiwan_market_rules")
    latest = features.series.latest()
    reasons: list[ReasonTrace] = []
    flags: list[str] = []
    cap: Optional[int] = None
    suppress_all = False
    suppress_events = False
    message: Optional[str] = None
    status = MarketGateStatus.NORMAL

    disposition_status = context.disposition_status or "normal"
    if context.is_trading_suspended_today:
        status = MarketGateStatus.SUSPENSION
        suppress_all = True
        suppress_events = True
        message = "該股當日暫停交易，無法分析"
        reasons.append(_reason(features, "is_trading_suspended_today", "暫停交易，停止技術分析", "is_trading_suspended_today == True", Decimal("1")))
    elif disposition_status in {"stage_1", "stage_2"}:
        status = MarketGateStatus.DISPOSITION_SUSPENDED
        suppress_all = bool(section["disposition"]["stage_1_suppress_all"])
        suppress_events = True
        cap = int(section["disposition"]["stage_2_confidence_cap"]) if disposition_status == "stage_2" else cap
        flags.append("disposition_distorted")
        message = f"該股處於處置股{disposition_status}，技術分析暫停輸出"
        reasons.append(_reason(features, "disposition_status", "處置股期間暫停技術評分", "disposition_status in stage_1/stage_2", Decimal("1")))
    elif disposition_status == "attention":
        status = MarketGateStatus.NOTICE_DEGRADED
        cap = int(section["disposition"]["attention_confidence_cap"])
        flags.append("attention_stock")
        message = "該股為注意股，技術分析信心上限降低"
        reasons.append(_reason(features, "disposition_status", "注意股信心上限降低", "disposition_status == attention", Decimal("1")))

    consecutive_limits = _consecutive_limit_days(features)
    is_limit_up = latest.is_limit_up
    is_limit_down = latest.is_limit_down
    if is_limit_up or is_limit_down:
        status = MarketGateStatus.LIMIT_DISTORTED if status == MarketGateStatus.NORMAL else status
        flags.extend(["shadow_distorted", "price_discovery_distorted"])
        if consecutive_limits >= 3:
            cap = _min_cap(cap, int(section["limit"]["consecutive_3_days_cap"]))
        elif consecutive_limits >= 2:
            cap = _min_cap(cap, int(section["limit"]["consecutive_2_days_cap"]))
        message = message or "今日漲跌停使價格發現失真，建議等待恢復正常交易"
        reasons.append(_reason(features, "is_limit_up,is_limit_down", "漲跌停造成 K 棒與動能失真", "limit flag is true", Decimal(consecutive_limits)))

    liquidity = _liquidity_tier(features, section)
    if liquidity in {LiquidityTier.LOW, LiquidityTier.VERY_LOW} and status == MarketGateStatus.NORMAL:
        status = MarketGateStatus.THIN_TRADING
        cap = _min_cap(cap, int(section["liquidity"]["short_term_thin_cap"] if liquidity == LiquidityTier.LOW else section["liquidity"]["swing_thin_cap"]))
        flags.append("thin_trading")
        message = "流動性偏低，短線訊號可信度降低"
        reasons.append(_reason(features, "turnover_value_20d_avg", "流動性偏低，信心上限降低", "20d turnover below threshold", _avg_turnover(features)))

    if context.is_ex_rights_today:
        status = MarketGateStatus.EX_RIGHTS if status == MarketGateStatus.NORMAL else status
        cap = _min_cap(cap, int(section["ex_rights"]["confidence_cap"]))
        suppress_events = True
        flags.append("ex_rights_price_gap")
        message = message or "除權息日價格不連續，暫停 K 棒與型態事件偵測"
        reasons.append(_reason(features, "is_ex_rights_today", "除權息日價格不連續", "is_ex_rights_today == True", Decimal("1")))
    elif context.is_ex_rights_adjacent:
        flags.append("ex_rights_adjacent")

    return MarketGate(
        gate_status=status,
        disposition_status=disposition_status,
        is_limit_up=is_limit_up,
        is_limit_down=is_limit_down,
        consecutive_limit_days=consecutive_limits,
        liquidity_tier=liquidity,
        is_ex_rights_today=bool(context.is_ex_rights_today),
        is_ex_rights_adjacent=bool(context.is_ex_rights_adjacent),
        suppress_all_votes=suppress_all,
        suppress_event_detection=suppress_events,
        confidence_cap=cap,
        indicator_distortion_flags=flags,
        user_message=message,
        reasons=reasons,
    )


def _liquidity_tier(features: FeatureBundle, rules: dict) -> LiquidityTier:
    avg_turnover = _avg_turnover(features)
    liquidity = rules["liquidity"]
    if avg_turnover >= Decimal(str(liquidity["high_threshold_value"])):
        return LiquidityTier.HIGH
    if avg_turnover >= Decimal(str(liquidity["medium_threshold_value"])):
        return LiquidityTier.MEDIUM
    if avg_turnover >= Decimal(str(liquidity["low_threshold_value"])):
        return LiquidityTier.LOW
    return LiquidityTier.VERY_LOW


def _avg_turnover(features: FeatureBundle) -> Decimal:
    if features.turnover_value_20d_avg is not None:
        return features.turnover_value_20d_avg
    bars = features.series.bars[-20:]
    return sum((bar.turnover_value for bar in bars), ZERO) / Decimal(len(bars)) if bars else ZERO


def _consecutive_limit_days(features: FeatureBundle) -> int:
    count = 0
    latest_direction = None
    for bar in reversed(features.series.bars):
        direction = "up" if bar.is_limit_up else "down" if bar.is_limit_down else None
        if direction is None:
            break
        if latest_direction is None:
            latest_direction = direction
        if direction != latest_direction:
            break
        count += 1
    return count


def _min_cap(current: Optional[int], candidate: int) -> int:
    return candidate if current is None else min(current, candidate)


def _reason(features: FeatureBundle, source_field: str, text: str, calculation: str, value: Decimal) -> ReasonTrace:
    return ReasonTrace(
        reason_text=text,
        source_field=source_field,
        timestamp=features.series.latest().date,
        calculation=calculation,
        calculation_value=quantize(value),
    )
