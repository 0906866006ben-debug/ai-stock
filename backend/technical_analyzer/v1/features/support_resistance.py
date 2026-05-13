"""Topic G: multi-source support and resistance mapping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from ..common import HUNDRED, ONE, ZERO, clamp, pct_change, quantize
from ..contracts.enums import FactorCategory, TrendDirection
from ..contracts.feature_contract import FeatureBundle
from ..contracts.input_contract import ContextBundle, OHLCVSeries
from ..contracts.output_contract import FactorVote
from ..registry.rule_registry import RuleRegistry
from ..traceability.trace import ReasonTrace


@dataclass(frozen=True)
class SRLevel:
    price_level: Decimal
    level_type: Literal["support", "resistance", "flipped_support", "flipped_resistance"]
    merged_sources: list[str]
    confluence_count: int
    strength_score: int
    strength_tier: Literal["strong", "medium", "weak"]
    flipped: bool
    test_count: int
    last_test_date: Optional[date]
    effective_status: Literal["effective", "failed", "untested"]
    distance_from_close_pct: Decimal


@dataclass(frozen=True)
class SupportResistanceMap:
    symbol: str
    analysis_date: date
    current_close: Decimal
    above_levels: list[SRLevel]
    below_levels: list[SRLevel]
    nearest_resistance: Optional[SRLevel]
    nearest_support: Optional[SRLevel]
    distance_to_nearest_resistance_pct: Optional[Decimal]
    distance_to_nearest_support_pct: Optional[Decimal]
    position_in_range: Literal["near_resistance", "midrange", "near_support", "above_all_resistance", "below_all_support"]
    vote: FactorVote
    reasons: list[ReasonTrace]


@dataclass
class _RawLevel:
    price: Decimal
    source: str
    source_date: Optional[date]
    is_psychological: bool = False
    is_ma: bool = False
    is_volume_profile: bool = False
    base_strength: int = 10


def analyze_support_resistance(
    symbol: str,
    features: FeatureBundle,
    context: ContextBundle,
    registry: RuleRegistry | None = None,
) -> SupportResistanceMap:
    """Build a clustered support/resistance map from multiple sources."""
    rules = RuleRegistry.load_default() if registry is None else registry
    section = rules.section("support_resistance")
    current_close = features.latest_close()
    raw_levels = _collect_raw_levels(features, section)
    clusters = _cluster_levels(raw_levels, current_close, section)
    below: list[SRLevel] = []
    above: list[SRLevel] = []
    for cluster in clusters:
        level = _materialize_level(cluster, features.series, features, section)
        if level.price_level < current_close:
            below.append(level)
        elif level.price_level > current_close:
            above.append(level)

    below = sorted(below, key=lambda level: (level.strength_score, level.price_level), reverse=True)[: int(section["max_levels_per_side"])]
    above = sorted(above, key=lambda level: (level.strength_score, -level.price_level), reverse=True)[: int(section["max_levels_per_side"])]
    below_sorted = sorted(below, key=lambda level: level.price_level, reverse=True)
    above_sorted = sorted(above, key=lambda level: level.price_level)

    nearest_support = below_sorted[0] if below_sorted else None
    nearest_resistance = above_sorted[0] if above_sorted else None
    near_threshold = Decimal(str(section["near_level_threshold_pct"]))
    if nearest_resistance is None and nearest_support is None:
        position = "midrange"
    elif nearest_resistance is None:
        position = "above_all_resistance"
    elif nearest_support is None:
        position = "below_all_support"
    elif abs(nearest_resistance.distance_from_close_pct) <= near_threshold:
        position = "near_resistance"
    elif abs(nearest_support.distance_from_close_pct) <= near_threshold:
        position = "near_support"
    else:
        position = "midrange"

    vote_direction, vote_strength = {
        "above_all_resistance": (TrendDirection.BULLISH, Decimal("0.7")),
        "near_resistance": (TrendDirection.BEARISH, Decimal("0.5")),
        "midrange": (TrendDirection.NEUTRAL, ZERO),
        "near_support": (TrendDirection.BULLISH, Decimal("0.5")),
        "below_all_support": (TrendDirection.BEARISH, Decimal("0.7")),
    }[position]
    reasons = [
        ReasonTrace(
            reason_text=f"位置判讀為 {position}",
            source_field="support_resistance",
            timestamp=features.series.latest().date,
            calculation="support/resistance distance mapping",
            calculation_value=nearest_support.distance_from_close_pct if nearest_support else (nearest_resistance.distance_from_close_pct if nearest_resistance else ZERO),
        )
    ]
    vote = FactorVote(
        category=FactorCategory.STRUCTURE,
        direction=vote_direction,
        strength=vote_strength,
        reasons=tuple(reasons),
    )
    return SupportResistanceMap(
        symbol=symbol,
        analysis_date=features.series.latest().date,
        current_close=current_close,
        above_levels=above_sorted,
        below_levels=below_sorted,
        nearest_resistance=nearest_resistance,
        nearest_support=nearest_support,
        distance_to_nearest_resistance_pct=nearest_resistance.distance_from_close_pct if nearest_resistance else None,
        distance_to_nearest_support_pct=nearest_support.distance_from_close_pct if nearest_support else None,
        position_in_range=position,
        vote=vote,
        reasons=reasons,
    )


def _collect_raw_levels(features: FeatureBundle, rules: dict) -> list[_RawLevel]:
    series = features.series
    current_close = features.latest_close()
    levels: list[_RawLevel] = []
    if features.swing_structure:
        for pivot in features.swing_structure.swing_highs[-6:]:
            levels.append(_RawLevel(price=pivot.price, source=f"swing_high_{pivot.date.isoformat()}", source_date=pivot.date))
        for pivot in features.swing_structure.swing_lows[-6:]:
            levels.append(_RawLevel(price=pivot.price, source=f"swing_low_{pivot.date.isoformat()}", source_date=pivot.date))

    for name in ("ma20", "ma60", "ma120", "ma240"):
        ma_value = features.ma_values.get(name)
        if ma_value is not None:
            levels.append(_RawLevel(price=ma_value, source=name.upper(), source_date=series.latest().date, is_ma=True))

    levels.extend(_gap_levels(series))

    for label, price in (
        ("high_5d", features.recent_high_5d),
        ("low_5d", features.recent_low_5d),
        ("high_20d", features.recent_high_20d),
        ("low_20d", features.recent_low_20d),
        ("high_60d", features.recent_high_60d),
        ("low_60d", features.recent_low_60d),
    ):
        if price is not None:
            levels.append(_RawLevel(price=price, source=label, source_date=series.latest().date))

    upper = features.latest_value("bb_upper")
    lower = features.latest_value("bb_lower")
    if upper is not None:
        levels.append(_RawLevel(price=upper, source="BOLLINGER_UPPER", source_date=series.latest().date))
    if lower is not None:
        levels.append(_RawLevel(price=lower, source="BOLLINGER_LOWER", source_date=series.latest().date))

    for round_level in _psychological_round_levels(current_close, rules):
        levels.append(_RawLevel(price=round_level, source=f"整數_{round_level}", source_date=series.latest().date, is_psychological=True, base_strength=5))

    for volume_level in _volume_profile_levels(series, rules):
        levels.append(_RawLevel(price=volume_level, source=f"VP_{volume_level}", source_date=series.latest().date, is_volume_profile=True, base_strength=10))

    return levels


def _cluster_levels(raw_levels: list[_RawLevel], current_close: Decimal, rules: dict) -> list[list[_RawLevel]]:
    if not raw_levels:
        return []
    ordered = sorted(raw_levels, key=lambda level: level.price)
    clusters: list[list[_RawLevel]] = [[ordered[0]]]
    for raw_level in ordered[1:]:
        last_cluster = clusters[-1]
        anchor = sum(level.price for level in last_cluster) / Decimal(len(last_cluster))
        threshold = _cluster_threshold(anchor, rules)
        if abs(raw_level.price - anchor) <= threshold:
            last_cluster.append(raw_level)
        else:
            clusters.append([raw_level])
    return clusters


def _materialize_level(cluster: list[_RawLevel], series: OHLCVSeries, features: FeatureBundle, rules: dict) -> SRLevel:
    current_close = features.latest_close()
    weight_sum = sum(level.base_strength for level in cluster)
    weighted_price = sum(level.price * Decimal(level.base_strength) for level in cluster) / Decimal(weight_sum or 1)
    merged_sources = sorted({level.source for level in cluster})
    source_dates = [level.source_date for level in cluster if level.source_date is not None]
    source_age_days = (series.latest().date - min(source_dates)).days if source_dates else 0
    test_count, last_test_date = _test_stats(series, weighted_price)
    break_count = _break_count(series, weighted_price)
    flipped, flipped_type = _flip_status(series, weighted_price, current_close, rules)
    effective = _effective_status(series, weighted_price, current_close, rules)
    distance_pct = pct_change(weighted_price, current_close, default=ZERO) or ZERO
    score = len(merged_sources) * int(rules["strength_per_confluence_source"])
    score += min(test_count, int(rules["strength_max_tests"])) * int(rules["strength_per_test"])
    if any(level.is_ma for level in cluster) and sum(1 for level in cluster if level.is_ma) >= int(rules["ma_overlap_min_count"]):
        score += int(rules["ma_overlap_strength"])
    if any(level.is_psychological for level in cluster):
        score += int(rules["psychological_round_strength"])
    if any(level.is_volume_profile for level in cluster):
        score += int(rules["volume_profile_strength"]["top_5_percentile"])
    score += max(int(rules["age_decay_max"]), (source_age_days // 30) * int(rules["age_decay_per_30_days"]))
    if break_count > int(rules["break_count_penalty_threshold"]):
        score += int(rules["break_count_penalty"])
    score += int(rules["flip_bonus"]) if flipped else 0
    score = max(0, min(100, score))
    strength_tier = "strong" if score >= int(rules["strength_tier"]["strong"]) else ("medium" if score >= int(rules["strength_tier"]["medium"]) else "weak")
    level_type: Literal["support", "resistance", "flipped_support", "flipped_resistance"]
    if flipped:
        level_type = flipped_type
    else:
        level_type = "support" if weighted_price < current_close else "resistance"
    return SRLevel(
        price_level=quantize(weighted_price),
        level_type=level_type,
        merged_sources=merged_sources,
        confluence_count=len(merged_sources),
        strength_score=score,
        strength_tier=strength_tier,
        flipped=flipped,
        test_count=test_count,
        last_test_date=last_test_date,
        effective_status=effective,
        distance_from_close_pct=quantize(distance_pct),
    )


def _cluster_threshold(price: Decimal, rules: dict) -> Decimal:
    value = rules["clustering_distance"]
    if price < Decimal("50"):
        return Decimal("0.5")
    if price <= Decimal("200"):
        return price * Decimal("0.01")
    if price <= Decimal("500"):
        return price * Decimal("0.01")
    if price <= Decimal("1000"):
        return price * Decimal("0.007")
    return price * Decimal("0.005")


def _gap_levels(series: OHLCVSeries) -> list[_RawLevel]:
    out: list[_RawLevel] = []
    for previous, current in zip(series.bars[-61:-1], series.bars[-60:]):
        if current.low > previous.high:
            out.append(_RawLevel(price=previous.high, source=f"gap_top_{current.date.isoformat()}", source_date=current.date))
            out.append(_RawLevel(price=current.low, source=f"gap_bottom_{current.date.isoformat()}", source_date=current.date))
        elif current.high < previous.low:
            out.append(_RawLevel(price=current.high, source=f"gap_top_{current.date.isoformat()}", source_date=current.date))
            out.append(_RawLevel(price=previous.low, source=f"gap_bottom_{current.date.isoformat()}", source_date=current.date))
    return out


def _psychological_round_levels(current_close: Decimal, rules: dict) -> list[Decimal]:
    step = Decimal(str(
        rules["psychological_round"]["below_50"]
        if current_close < Decimal("50")
        else rules["psychological_round"]["50_to_200"]
        if current_close <= Decimal("200")
        else rules["psychological_round"]["200_to_500"]
        if current_close <= Decimal("500")
        else rules["psychological_round"]["500_to_1000"]
        if current_close <= Decimal("1000")
        else rules["psychological_round"]["above_1000"]
    ))
    center = (current_close / step).quantize(Decimal("1"))
    rounds = []
    for offset in range(-2, 3):
        rounds.append((center + Decimal(offset)) * step)
    return [level for level in rounds if level > ZERO]


def _volume_profile_levels(series: OHLCVSeries, rules: dict) -> list[Decimal]:
    lookback = int(rules["volume_profile"]["lookback_days"])
    bins_per_bar = int(rules["volume_profile"]["bins_per_bar"])
    histogram: dict[Decimal, Decimal] = {}
    for bar in series.bars[-lookback:]:
        bar_range = bar.high - bar.low
        if bar_range <= ZERO:
            histogram[bar.close] = histogram.get(bar.close, ZERO) + bar.turnover_value
            continue
        step = bar_range / Decimal(bins_per_bar)
        share = bar.turnover_value / Decimal(bins_per_bar)
        for index in range(bins_per_bar):
            center = bar.low + step * Decimal(index) + step / Decimal("2")
            key = quantize(center, "0.01")
            histogram[key] = histogram.get(key, ZERO) + share
    ranked = sorted(histogram.items(), key=lambda item: item[1], reverse=True)
    return [price for price, _ in ranked[: int(rules["volume_profile"]["top_levels_to_extract"])]]


def _test_stats(series: OHLCVSeries, level: Decimal) -> tuple[int, Optional[date]]:
    test_count = 0
    last_date: Optional[date] = None
    for bar in series.bars[-60:]:
        if bar.low <= level <= bar.high:
            test_count += 1
            last_date = bar.date
    return test_count, last_date


def _break_count(series: OHLCVSeries, level: Decimal) -> int:
    break_count = 0
    prev_side = None
    for bar in series.bars[-60:]:
        side = "above" if bar.close > level else "below" if bar.close < level else "on"
        if prev_side and side not in {prev_side, "on"} and prev_side != "on":
            break_count += 1
        prev_side = side
    return break_count


def _flip_status(series: OHLCVSeries, level: Decimal, current_close: Decimal, rules: dict) -> tuple[bool, Literal["flipped_support", "flipped_resistance"]]:
    confirmation_days = int(rules["flip_confirmation_days"])
    proximity = Decimal(str(rules["flip_retest_proximity_pct"])) / HUNDRED
    recent = series.bars[-max(confirmation_days + 2, 5):]
    closes = [bar.close for bar in recent]
    if len(closes) >= confirmation_days and all(close > level for close in closes[-confirmation_days:]):
        retest = any(bar.low <= level * (ONE + proximity) and bar.close >= level for bar in recent[-confirmation_days:])
        if retest:
            return True, "flipped_support"
    if len(closes) >= confirmation_days and all(close < level for close in closes[-confirmation_days:]):
        retest = any(bar.high >= level * (ONE - proximity) and bar.close <= level for bar in recent[-confirmation_days:])
        if retest:
            return True, "flipped_resistance"
    return False, "flipped_support" if level < current_close else "flipped_resistance"


def _effective_status(series: OHLCVSeries, level: Decimal, current_close: Decimal, rules: dict) -> Literal["effective", "failed", "untested"]:
    touches = [index for index, bar in enumerate(series.bars[-60:]) if bar.low <= level <= bar.high]
    if not touches:
        return "untested"
    idx = touches[-1]
    window = series.bars[-60:][idx : idx + int(rules["effective_recovery_days"]) + 1]
    if level < current_close:
        recovered = any(bar.close > level for bar in window[1:])
        high_volume_break = any(bar.close < level and _turnover_ratio(bar, series, rules) > Decimal(str(rules["failed_break_volume_ratio"])) for bar in window)
        if high_volume_break:
            return "failed"
        return "effective" if recovered else "untested"
    recovered = any(bar.close < level for bar in window[1:])
    high_volume_break = any(bar.close > level and _turnover_ratio(bar, series, rules) > Decimal(str(rules["failed_break_volume_ratio"])) for bar in window)
    if high_volume_break:
        return "failed"
    return "effective" if recovered else "untested"


def _turnover_ratio(bar, series: OHLCVSeries, rules: dict) -> Decimal:
    window = series.bars[-20:]
    avg = sum(item.turnover_value for item in window) / Decimal(len(window))
    if avg == ZERO:
        return ZERO
    return bar.turnover_value / avg
