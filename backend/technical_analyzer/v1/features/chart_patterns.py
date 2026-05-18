"""Topic L: quantified chart-pattern detection from confirmed pivots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from ..common import HUNDRED, ZERO, pct_change, quantize
from ..contracts.enums import Horizon, TechnicalState
from ..contracts.feature_contract import FeatureBundle, Pivot
from ..registry.rule_registry import RuleRegistry
from ..traceability.trace import ReasonTrace
from .breakout_quality import BreakoutAnalysisResult


@dataclass(frozen=True)
class ChartPattern:
    pattern_name: str
    pattern_status: str
    anchor_pivots: list[date]
    neckline_level: Optional[Decimal]
    target_price: Optional[Decimal]
    volume_verification_passed: bool
    pattern_span_days: int
    is_neckline_broken: bool
    neckline_break_date: Optional[date]


@dataclass(frozen=True)
class ChartPatternResult:
    symbol: str
    analysis_date: date
    horizon: Horizon
    detected_patterns: list[ChartPattern]
    state_signal_score_modifier: int
    confidence_cap: Optional[int]
    state_override_required: bool
    state_override_target: Optional[TechnicalState]
    reasons: list[ReasonTrace]


def analyze_chart_patterns(
    symbol: str,
    features: FeatureBundle,
    breakout_result: Optional[BreakoutAnalysisResult] = None,
    registry: RuleRegistry | None = None,
) -> ChartPatternResult:
    """Detect v1 chart patterns using confirmed swing pivots."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("chart_patterns")
    patterns: list[ChartPattern] = []
    structure = features.swing_structure
    if structure:
        patterns.extend(_double_patterns(features, section))
        patterns.extend(_head_shoulders(features, section))
        patterns.extend(_triangles(features, section))
        patterns.extend(_vcp(features, breakout_result, section))

    modifier, cap, override_required, override_target = _state_effect(patterns, features.current_state, breakout_result, section)
    reasons = [
        ReasonTrace(
            reason_text=f"偵測到型態 {pattern.pattern_status}_{pattern.pattern_name}",
            source_field="swing_structure",
            timestamp=features.series.latest().date,
            calculation="chart pattern pivot rules",
            calculation_value=pattern.neckline_level or ZERO,
        )
        for pattern in patterns
    ]
    return ChartPatternResult(
        symbol=symbol,
        analysis_date=features.series.latest().date,
        horizon=features.horizon,
        detected_patterns=patterns,
        state_signal_score_modifier=modifier,
        confidence_cap=cap,
        state_override_required=override_required,
        state_override_target=override_target,
        reasons=reasons,
    )


def _double_patterns(features: FeatureBundle, rules: dict) -> list[ChartPattern]:
    structure = features.swing_structure
    if not structure:
        return []
    out: list[ChartPattern] = []
    if len(structure.swing_highs) >= 2:
        first, second = structure.swing_highs[-2], structure.swing_highs[-1]
        max_diff = Decimal(str(rules["double_top"]["max_high_price_diff_pct"]))
        interval_days = (second.date - first.date).days
        if _pct_diff(first.price, second.price) <= max_diff and interval_days >= int(rules["double_top"]["min_interval_days"]):
            lows_between = [low for low in structure.swing_lows if first.date < low.date < second.date]
            if lows_between:
                neckline = min(lows_between, key=lambda pivot: pivot.price)
                volume_ok = _turnover_at(features, second.index) < _turnover_at(features, first.index)
                broken = features.latest_close() < neckline.price
                if broken and features.volume_ratio_20d is not None:
                    volume_ok = volume_ok and features.volume_ratio_20d >= Decimal(str(rules["double_top"]["neckline_break_volume_ratio"]))
                status = "confirmed" if broken and volume_ok else "pending" if volume_ok else "weak_candidate"
                target = neckline.price - (max(first.price, second.price) - neckline.price) * Decimal(str(rules["double_top"]["target_multiplier"])) if broken else None
                out.append(_pattern("double_top", status, [first, neckline, second], neckline.price, target, volume_ok, broken, features.series.latest().date if broken else None))
    if len(structure.swing_lows) >= 2:
        first, second = structure.swing_lows[-2], structure.swing_lows[-1]
        max_diff = Decimal(str(rules["double_top"]["max_high_price_diff_pct"]))
        interval_days = (second.date - first.date).days
        if _pct_diff(first.price, second.price) <= max_diff and interval_days >= int(rules["double_top"]["min_interval_days"]):
            highs_between = [high for high in structure.swing_highs if first.date < high.date < second.date]
            if highs_between:
                neckline = max(highs_between, key=lambda pivot: pivot.price)
                volume_ok = _turnover_at(features, second.index) < _turnover_at(features, first.index)
                broken = features.latest_close() > neckline.price
                status = "confirmed" if broken and volume_ok else "pending" if volume_ok else "weak_candidate"
                target = neckline.price + (neckline.price - min(first.price, second.price)) * Decimal(str(rules["double_top"]["target_multiplier"])) if broken else None
                out.append(_pattern("double_bottom", status, [first, neckline, second], neckline.price, target, volume_ok, broken, features.series.latest().date if broken else None))
    return out


def _head_shoulders(features: FeatureBundle, rules: dict) -> list[ChartPattern]:
    structure = features.swing_structure
    if not structure:
        return []
    out: list[ChartPattern] = []
    hs_rules = rules["head_and_shoulders"]
    if len(structure.swing_highs) >= 3 and len(structure.swing_lows) >= 2:
        left, head, right = structure.swing_highs[-3], structure.swing_highs[-2], structure.swing_highs[-1]
        lows = [low for low in structure.swing_lows if left.date < low.date < right.date]
        if len(lows) >= 2 and head.price > left.price and head.price > right.price:
            shoulder_diff = _pct_diff(left.price, right.price)
            head_above = (head.price - max(left.price, right.price)) / max(left.price, right.price) * HUNDRED
            neckline_a, neckline_b = lows[-2], lows[-1]
            neckline_diff = _pct_diff(neckline_a.price, neckline_b.price)
            volume_ok = _turnover_at(features, left.index) > _turnover_at(features, head.index) > _turnover_at(features, right.index)
            neckline = min(neckline_a.price, neckline_b.price)
            broken = features.latest_close() < neckline
            if shoulder_diff <= Decimal(str(hs_rules["max_shoulder_diff_pct"])) and head_above >= Decimal(str(hs_rules["min_head_above_shoulders_pct"])) and neckline_diff <= Decimal(str(hs_rules["max_neckline_slope_pct"])):
                status = "confirmed" if broken and volume_ok else "pending" if volume_ok else "weak_candidate"
                target = neckline - (head.price - neckline) * Decimal("0.8") if broken else None
                out.append(_pattern("head_and_shoulders", status, [left, neckline_a, head, neckline_b, right], neckline, target, volume_ok, broken, features.series.latest().date if broken else None))
    if len(structure.swing_lows) >= 3 and len(structure.swing_highs) >= 2:
        left, head, right = structure.swing_lows[-3], structure.swing_lows[-2], structure.swing_lows[-1]
        highs = [high for high in structure.swing_highs if left.date < high.date < right.date]
        if len(highs) >= 2 and head.price < left.price and head.price < right.price:
            shoulder_diff = _pct_diff(left.price, right.price)
            head_below = (min(left.price, right.price) - head.price) / min(left.price, right.price) * HUNDRED
            neckline_a, neckline_b = highs[-2], highs[-1]
            neckline_diff = _pct_diff(neckline_a.price, neckline_b.price)
            volume_ok = _turnover_at(features, right.index) >= _turnover_at(features, head.index)
            neckline = max(neckline_a.price, neckline_b.price)
            broken = features.latest_close() > neckline
            if shoulder_diff <= Decimal(str(hs_rules["max_shoulder_diff_pct"])) and head_below >= Decimal(str(hs_rules["min_head_above_shoulders_pct"])) and neckline_diff <= Decimal(str(hs_rules["max_neckline_slope_pct"])):
                status = "confirmed" if broken and volume_ok else "pending" if volume_ok else "weak_candidate"
                target = neckline + (neckline - head.price) * Decimal("0.8") if broken else None
                out.append(_pattern("inverse_head_and_shoulders", status, [left, neckline_a, head, neckline_b, right], neckline, target, volume_ok, broken, features.series.latest().date if broken else None))
    return out


def _triangles(features: FeatureBundle, rules: dict) -> list[ChartPattern]:
    structure = features.swing_structure
    if not structure:
        return []
    tri_rules = rules["triangle"]
    highs = [pivot for pivot in structure.swing_highs if (features.series.latest().date - pivot.date).days <= int(tri_rules["swing_lookback_days"])]
    lows = [pivot for pivot in structure.swing_lows if (features.series.latest().date - pivot.date).days <= int(tri_rules["swing_lookback_days"])]
    out: list[ChartPattern] = []
    if len(highs) >= 2 and len(lows) >= 2:
        high_diff = _pct_diff(highs[-2].price, highs[-1].price)
        support_rise = (lows[-1].price - lows[-2].price) / lows[-2].price * HUNDRED if lows[-2].price else ZERO
        if high_diff <= Decimal(str(tri_rules["max_resistance_diff_pct"])) and support_rise >= Decimal(str(tri_rules["min_support_rise_pct"])):
            out.append(_pattern("ascending_triangle", "forming", [highs[-2], lows[-2], highs[-1], lows[-1]], highs[-1].price, None, True, False, None))
        low_diff = _pct_diff(lows[-2].price, lows[-1].price)
        resistance_fall = (highs[-2].price - highs[-1].price) / highs[-2].price * HUNDRED if highs[-2].price else ZERO
        if low_diff <= Decimal(str(tri_rules["max_resistance_diff_pct"])) and resistance_fall >= Decimal(str(tri_rules["min_support_rise_pct"])):
            out.append(_pattern("descending_triangle", "forming", [highs[-2], lows[-2], highs[-1], lows[-1]], lows[-1].price, None, True, False, None))
    return out


def _vcp(features: FeatureBundle, breakout_result: Optional[BreakoutAnalysisResult], rules: dict) -> list[ChartPattern]:
    structure = features.swing_structure
    if not structure or len(structure.swing_highs) < 3 or len(structure.swing_lows) < 3:
        return []
    highs = list(structure.swing_highs[-4:])
    lows = list(structure.swing_lows[-4:])
    pullbacks: list[Decimal] = []
    volume_ok = True
    volumes: list[Decimal] = []
    for high, low in zip(highs[-3:], lows[-3:]):
        if low.date >= high.date:
            pullbacks.append(abs((high.price - low.price) / high.price * HUNDRED))
            volumes.append(_turnover_5d_avg_at(features, low.index))
    if len(pullbacks) < int(rules["vcp"]["min_pullback_count"]):
        return []
    contraction_ratio = Decimal(str(rules["vcp"]["pullback_contraction_ratio"]))
    contractions_ok = all(later < earlier * contraction_ratio for earlier, later in zip(pullbacks, pullbacks[1:]))
    if len(volumes) >= 2:
        volume_ok = all(later < earlier for earlier, later in zip(volumes, volumes[1:]))
    range_20 = _range_pct(features.series.bars[-20:]) if len(features.series.bars) >= 20 else ZERO
    range_60 = _range_pct(features.series.bars[-60:]) if len(features.series.bars) >= 60 else range_20
    range_ok = range_60 == ZERO or range_20 < range_60 * Decimal(str(rules["vcp"]["range_contraction_ratio"]))
    atr_values = [value for value in features.atr_series if value is not None]
    atr_ok = len(atr_values) >= 10 and sum(atr_values[-5:], ZERO) / Decimal("5") < sum(atr_values[-10:-5], ZERO) / Decimal("5")
    if not contractions_ok or not volume_ok:
        return []

    # 🚀 結合研究報告第六章：VCP 必須符合 SEPA 長期多頭特徵 (Stage 2)
    # 透過檢測 股價 > MA120 > MA240 來確保大趨勢向上，過濾弱勢區間的無效收斂
    ma120 = features.ma_values.get("ma120")
    ma240 = features.ma_values.get("ma240")
    close = features.latest_close()
    if ma120 and ma240 and not (close > ma120 > ma240):
        return []

    status = "confirmed" if range_ok and atr_ok else "forming"
    if breakout_result and breakout_result.status.value == "confirmed_healthy_breakout" and status == "forming":
        status = "confirmed"
    return [_pattern("vcp", status, highs[-3:] + lows[-3:], None, None, volume_ok, False, None)]


def _state_effect(patterns: list[ChartPattern], current_state: TechnicalState, breakout_result: Optional[BreakoutAnalysisResult], rules: dict) -> tuple[int, Optional[int], bool, Optional[TechnicalState]]:
    table = rules["state_modifier_table"]
    chosen_modifier = 0
    chosen_cap: Optional[int] = None
    override_target: Optional[TechnicalState] = None
    for pattern in patterns:
        key = f"{pattern.pattern_status}_{pattern.pattern_name}"
        if key not in table:
            key = pattern.pattern_name
        if key not in table:
            continue
        item = table[key]
        modifier = int(item["modifier"])
        if pattern.pattern_name == "vcp" and pattern.pattern_status == "confirmed" and current_state != TechnicalState.EARLY_STRENGTHENING:
            modifier = min(modifier, 5)
        if abs(modifier) > abs(chosen_modifier):
            chosen_modifier = modifier
            chosen_cap = item.get("cap")
            override_value = item.get("override")
            override_target = TechnicalState(override_value) if override_value else None
    return chosen_modifier, chosen_cap, override_target is not None, override_target


def _pattern(
    name: str,
    status: str,
    pivots: list[Pivot],
    neckline: Optional[Decimal],
    target: Optional[Decimal],
    volume_ok: bool,
    broken: bool,
    break_date: Optional[date],
) -> ChartPattern:
    dates = [pivot.date for pivot in pivots]
    return ChartPattern(
        pattern_name=name,
        pattern_status=status,
        anchor_pivots=dates,
        neckline_level=quantize(neckline) if neckline is not None else None,
        target_price=quantize(target) if target is not None else None,
        volume_verification_passed=volume_ok,
        pattern_span_days=(max(dates) - min(dates)).days if dates else 0,
        is_neckline_broken=broken,
        neckline_break_date=break_date,
    )


def _pct_diff(a: Decimal, b: Decimal) -> Decimal:
    base = (a + b) / Decimal("2")
    return abs(a - b) / base * HUNDRED if base else ZERO


def _turnover_at(features: FeatureBundle, index: int) -> Decimal:
    if 0 <= index < len(features.series.bars):
        return features.series.bars[index].turnover_value
    return ZERO


def _turnover_5d_avg_at(features: FeatureBundle, index: int) -> Decimal:
    start = max(0, index - 4)
    window = features.series.bars[start : index + 1]
    return sum((bar.turnover_value for bar in window), ZERO) / Decimal(len(window)) if window else ZERO


def _range_pct(bars) -> Decimal:
    if not bars:
        return ZERO
    high = max(bar.high for bar in bars)
    low = min(bar.low for bar in bars)
    return (high - low) / low * HUNDRED if low else ZERO
