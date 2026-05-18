"""v2.0 quant overlays for Taiwan equity analysis.

These modules turn the v2 knowledge-base additions into deterministic,
backtestable preview fields without requiring a new backend package yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, Optional

from ..common import HUNDRED, ONE, ZERO, clamp, mean, pct_change, quantize, safe_div
from ..contracts.input_contract import OHLCVBar, OHLCVSeries


FUNDAMENTAL_FIELDS = (
    "annual_revenue",
    "revenue_growth",
    "ebit_margin",
    "industry_ebit_zscore",
    "operating_cash_flow",
    "free_cash_flow",
    "relative_strength_vs_taiex_60d",
)


@dataclass(frozen=True)
class FundamentalSnapshot:
    """Optional v2 fundamental data used by the strategic gate."""

    annual_revenue: Optional[Decimal] = None
    revenue_growth: Optional[Decimal] = None
    ebit_margin: Optional[Decimal] = None
    industry_ebit_zscore: Optional[Decimal] = None
    operating_cash_flow: Optional[Decimal] = None
    free_cash_flow: Optional[Decimal] = None
    relative_strength_vs_taiex_60d: Optional[Decimal] = None


@dataclass(frozen=True)
class FundamentalGateResult:
    status: Literal["pass", "fail", "unknown"]
    passed: bool
    score: int
    failed_rules: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TimeBoxProjection:
    ma_window: int
    status: Literal["ready", "insufficient_data"]
    p_crit: Optional[Decimal]
    projection_date: Optional[date]
    deduction_min: Optional[Decimal]
    deduction_max: Optional[Decimal]
    current_close: Decimal
    distance_to_p_crit_pct: Optional[Decimal]
    ma_acceleration_flag: bool
    warning: Optional[str] = None


@dataclass(frozen=True)
class VolumeProfileResult:
    status: Literal["ready", "insufficient_data"]
    lookback_days: int
    poc_price: Optional[Decimal]
    vah_price: Optional[Decimal]
    val_price: Optional[Decimal]
    poc_distance_pct: Optional[Decimal]
    poc_breakdown_flag: bool
    bins_used: int
    value_area_pct: Decimal = Decimal("70")


@dataclass(frozen=True)
class TwoBReversalResult:
    status: Literal["confirmed", "watch", "none", "insufficient_data"]
    confirmed: bool
    prior_low_l1: Optional[Decimal]
    false_break_low_l2: Optional[Decimal]
    reclaim_days: Optional[int]
    bias_120_pct: Optional[Decimal]
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RiskExecutionPlan:
    take_profit_price: Optional[Decimal]
    stop_loss_price: Optional[Decimal]
    trailing_stop_price: Optional[Decimal]
    rr_ratio: Optional[Decimal]
    rr_pass: bool
    kelly_fraction: Decimal
    position_cap: Decimal
    forced_exit: bool
    forced_exit_reason: Optional[str]
    bottom_line_fields: list[str]


@dataclass(frozen=True)
class V2QuantAnalysisResult:
    version: str
    fundamental_gate: FundamentalGateResult
    time_boxes: dict[str, TimeBoxProjection]
    volume_profile: VolumeProfileResult
    two_b_reversal: TwoBReversalResult
    risk_execution: RiskExecutionPlan
    implemented_modules: list[str]
    missing_data_fields: list[str]
    hypothesis_ids: list[str]


def evaluate_fundamental_gate(snapshot: FundamentalSnapshot | None) -> FundamentalGateResult:
    """Evaluate the v2 strategic fundamental gate.

    Missing data keeps the gate in an unknown state instead of silently passing.
    """

    if snapshot is None:
        return FundamentalGateResult(
            status="unknown",
            passed=False,
            score=50,
            missing_fields=list(FUNDAMENTAL_FIELDS),
            warnings=["fundamental_data_missing"],
        )

    failed: list[str] = []
    missing: list[str] = []
    warnings: list[str] = []

    annual_revenue = snapshot.annual_revenue
    if annual_revenue is None:
        missing.append("annual_revenue")
    elif annual_revenue < Decimal("3200000000"):
        failed.append("annual_revenue_below_3_2b_twd")

    growth = snapshot.revenue_growth
    if growth is None:
        missing.append("revenue_growth")
    else:
        if growth < Decimal("0.15"):
            failed.append("revenue_growth_below_15_pct")
        elif growth > Decimal("0.30"):
            warnings.append("revenue_growth_above_30_pct_high_base_risk")

    ebit_margin = snapshot.ebit_margin
    if ebit_margin is None:
        missing.append("ebit_margin")
    elif ebit_margin <= ZERO:
        failed.append("ebit_margin_not_positive")

    zscore = snapshot.industry_ebit_zscore
    if zscore is None:
        missing.append("industry_ebit_zscore")
    elif zscore < ZERO:
        failed.append("industry_ebit_zscore_negative")

    ocf = snapshot.operating_cash_flow
    if ocf is None:
        missing.append("operating_cash_flow")
    elif ocf <= ZERO:
        failed.append("operating_cash_flow_not_positive")

    fcf = snapshot.free_cash_flow
    if fcf is None:
        missing.append("free_cash_flow")
    elif fcf <= ZERO:
        failed.append("free_cash_flow_not_positive")

    rs = snapshot.relative_strength_vs_taiex_60d
    if rs is None:
        missing.append("relative_strength_vs_taiex_60d")
    elif rs <= ZERO:
        failed.append("underperforming_taiex_60d")

    score = 100 - len(failed) * 15 - len(missing) * 5 - len(warnings) * 3
    score = int(clamp(Decimal(score), ZERO, HUNDRED))
    status: Literal["pass", "fail", "unknown"]
    if failed:
        status = "fail"
    elif missing:
        status = "unknown"
    else:
        status = "pass"
    return FundamentalGateResult(
        status=status,
        passed=status == "pass",
        score=score,
        failed_rules=failed,
        missing_fields=missing,
        warnings=warnings,
    )


def project_time_box(series: OHLCVSeries, ma_window: int = 60, lookahead_days: int = 20) -> TimeBoxProjection:
    """Project the MA deduction time box and critical price."""

    close = series.latest().close
    if len(series.bars) < ma_window:
        return TimeBoxProjection(
            ma_window=ma_window,
            status="insufficient_data",
            p_crit=None,
            projection_date=None,
            deduction_min=None,
            deduction_max=None,
            current_close=close,
            distance_to_p_crit_pct=None,
            ma_acceleration_flag=False,
            warning=f"need_{ma_window}_bars",
        )

    deductions = [bar.close for bar in series.bars[-ma_window:]][:lookahead_days]
    if not deductions:
        return TimeBoxProjection(ma_window, "insufficient_data", None, None, None, None, close, None, False, "no_deduction_values")

    deduction_min = min(deductions)
    deduction_max = max(deductions)
    p_crit = quantize(deduction_max * Decimal("1.01"), "0.01")
    min_offset = deductions.index(deduction_min) + 1
    projection_date = series.latest().date + timedelta(days=min_offset)
    distance = pct_change(p_crit, close, ZERO)
    return TimeBoxProjection(
        ma_window=ma_window,
        status="ready",
        p_crit=p_crit,
        projection_date=projection_date,
        deduction_min=quantize(deduction_min, "0.01"),
        deduction_max=quantize(deduction_max, "0.01"),
        current_close=close,
        distance_to_p_crit_pct=quantize(distance or ZERO, "0.01"),
        ma_acceleration_flag=close >= p_crit,
        warning=None if close >= p_crit else "price_below_p_crit",
    )


def calculate_volume_profile(
    series: OHLCVSeries,
    *,
    lookback_days: int = 60,
    bins_per_bar: int = 20,
    value_area_pct: Decimal = Decimal("70"),
) -> VolumeProfileResult:
    """Approximate 60-day Volume Profile using turnover-distributed price bins."""

    if len(series.bars) < 5:
        return VolumeProfileResult("insufficient_data", lookback_days, None, None, None, None, False, 0, value_area_pct)

    histogram: dict[Decimal, Decimal] = {}
    for bar in series.bars[-lookback_days:]:
        bar_range = bar.high - bar.low
        if bar_range <= ZERO:
            price = quantize(bar.close, "0.01")
            histogram[price] = histogram.get(price, ZERO) + bar.turnover_value
            continue
        step = bar_range / Decimal(bins_per_bar)
        share = bar.turnover_value / Decimal(bins_per_bar)
        for index in range(bins_per_bar):
            price = bar.low + step * Decimal(index) + step / Decimal("2")
            key = quantize(price, "0.01")
            histogram[key] = histogram.get(key, ZERO) + share

    if not histogram:
        return VolumeProfileResult("insufficient_data", lookback_days, None, None, None, None, False, 0, value_area_pct)

    ranked = sorted(histogram.items(), key=lambda item: item[1], reverse=True)
    poc = ranked[0][0]
    total_turnover = sum(histogram.values(), ZERO)
    target = total_turnover * value_area_pct / HUNDRED
    running = ZERO
    value_prices: list[Decimal] = []
    for price, turnover in ranked:
        value_prices.append(price)
        running += turnover
        if running >= target:
            break
    vah = max(value_prices)
    val = min(value_prices)
    close = series.latest().close
    distance = pct_change(close, poc, ZERO)
    breakdown = close < poc * Decimal("0.97")
    return VolumeProfileResult(
        status="ready",
        lookback_days=lookback_days,
        poc_price=quantize(poc, "0.01"),
        vah_price=quantize(vah, "0.01"),
        val_price=quantize(val, "0.01"),
        poc_distance_pct=quantize(distance or ZERO, "0.01"),
        poc_breakdown_flag=breakdown,
        bins_used=len(histogram),
        value_area_pct=value_area_pct,
    )


def detect_two_b_reversal(series: OHLCVSeries, *, lookback_days: int = 120, reclaim_window_days: int = 5) -> TwoBReversalResult:
    """Detect a v2 2B false-breakdown reversal preview."""

    if len(series.bars) < max(30, reclaim_window_days + 10):
        return TwoBReversalResult("insufficient_data", False, None, None, None, None, ["need_more_bars"])

    bars = series.bars[-lookback_days:]
    recent = bars[-reclaim_window_days:]
    prior = bars[:-reclaim_window_days]
    if not prior or not recent:
        return TwoBReversalResult("insufficient_data", False, None, None, None, None, ["need_prior_and_recent_windows"])

    l1_bar = min(prior, key=lambda bar: bar.low)
    l2_index, l2_bar = min(enumerate(recent), key=lambda item: item[1].low)
    latest = series.latest()
    break_low = l2_bar.low < l1_bar.low
    reclaim = latest.close > l1_bar.low
    reclaim_days = len(recent) - l2_index if break_low else None
    bias_120 = _bias_pct(series, 120)
    extreme = bias_120 is not None and bias_120 <= Decimal("-40")

    reasons: list[str] = []
    if break_low:
        reasons.append("broke_prior_low_l1")
    if reclaim:
        reasons.append("reclaimed_l1")
    if extreme:
        reasons.append("bias_120_extreme_oversold")
    elif bias_120 is None:
        reasons.append("bias_120_unavailable")

    confirmed = break_low and reclaim and reclaim_days is not None and reclaim_days <= reclaim_window_days and extreme
    if confirmed:
        status: Literal["confirmed", "watch", "none", "insufficient_data"] = "confirmed"
    elif break_low or (bias_120 is not None and bias_120 <= Decimal("-30")):
        status = "watch"
    else:
        status = "none"
    return TwoBReversalResult(
        status=status,
        confirmed=confirmed,
        prior_low_l1=quantize(l1_bar.low, "0.01"),
        false_break_low_l2=quantize(l2_bar.low, "0.01") if break_low else None,
        reclaim_days=reclaim_days,
        bias_120_pct=quantize(bias_120, "0.01") if bias_120 is not None else None,
        reasons=reasons,
    )


def build_risk_execution_plan(
    series: OHLCVSeries,
    volume_profile: VolumeProfileResult,
    time_boxes: dict[str, TimeBoxProjection],
    two_b: TwoBReversalResult,
    *,
    assumed_win_rate: Decimal = Decimal("0.60"),
    position_cap: Decimal = Decimal("0.25"),
) -> RiskExecutionPlan:
    """Build TP/SL/RR/Kelly and hard-exit preview."""

    close = series.latest().close
    ma20 = _ma(series.bars, 20)
    ma60 = _ma(series.bars, 60)
    ma60_prev = _ma(series.bars[:-1], 60) if len(series.bars) > 60 else None
    atr = _atr(series.bars, 14)

    stop_candidates: list[Decimal] = []
    for value in (ma20, ma60):
        if value is not None and value < close:
            stop_candidates.append(value)
    if volume_profile.poc_price is not None and volume_profile.poc_price * Decimal("0.97") < close:
        stop_candidates.append(volume_profile.poc_price * Decimal("0.97"))
    if atr is not None:
        stop_candidates.append(close - atr * Decimal("1.5"))
    recent_lows = [bar.low for bar in series.bars[-20:]]
    if recent_lows:
        stop_candidates.append(min(recent_lows))
    stop_candidates = [value for value in stop_candidates if value > ZERO and value < close]
    stop_loss = max(stop_candidates) if stop_candidates else close * Decimal("0.95")

    # 🚀 結合研究報告第十一章：基於 ATR 的移動防守位 (Trailing Stop)
    # 以收盤價減去 1.5 倍 ATR 作為跟隨停損點，保護波段既有獲利
    trailing_stop = quantize(close - atr * Decimal("1.5"), "0.01") if atr else stop_loss

    target_candidates: list[Decimal] = []
    if volume_profile.vah_price is not None and volume_profile.vah_price > close:
        target_candidates.append(volume_profile.vah_price)
    for value in (ma20, ma60):
        if value is not None and value > close:
            target_candidates.append(value)
    for box in time_boxes.values():
        if box.p_crit is not None and box.p_crit > close:
            target_candidates.append(box.p_crit)
    if two_b.confirmed and ma60 is not None and ma60 > close:
        target_candidates.append(ma60)
    if not target_candidates:
        recent_high = max((bar.high for bar in series.bars[-60:]), default=close)
        if recent_high > close:
            target_candidates.append(recent_high)

    take_profit = min(target_candidates) if target_candidates else None
    rr = None
    if take_profit is not None:
        risk = close - stop_loss
        reward = take_profit - close
        ratio = safe_div(reward, risk)
        rr = quantize(ratio, "0.01") if ratio is not None and ratio > ZERO else None

    kelly = _kelly_fraction(assumed_win_rate, rr, position_cap)
    forced_exit_reason = None
    if volume_profile.poc_breakdown_flag:
        forced_exit_reason = "poc_breakdown_3pct"
    elif ma60 is not None and ma60_prev is not None and close < ma60 and ma60 < ma60_prev:
        forced_exit_reason = "ma60_break_with_negative_slope"

    return RiskExecutionPlan(
        take_profit_price=quantize(take_profit, "0.01") if take_profit is not None else None,
        stop_loss_price=quantize(stop_loss, "0.01"),
        trailing_stop_price=trailing_stop,
        rr_ratio=rr,
        rr_pass=rr is not None and rr >= Decimal("3"),
        kelly_fraction=kelly,
        position_cap=position_cap,
        forced_exit=forced_exit_reason is not None,
        forced_exit_reason=forced_exit_reason,
        bottom_line_fields=["take_profit_price", "stop_loss_price", "trailing_stop_price", "rr_ratio", "forced_exit_reason"],
    )


def analyze_v2_quant(
    series: OHLCVSeries,
    fundamental: FundamentalSnapshot | None = None,
) -> V2QuantAnalysisResult:
    """Run all v2 preview overlays for a single Taiwan stock."""

    fundamental_gate = evaluate_fundamental_gate(fundamental)
    time_boxes = {
        "ma20": project_time_box(series, ma_window=20, lookahead_days=20),
        "ma60": project_time_box(series, ma_window=60, lookahead_days=20),
    }
    volume_profile = calculate_volume_profile(series, lookback_days=60)
    two_b = detect_two_b_reversal(series)
    risk_plan = build_risk_execution_plan(series, volume_profile, time_boxes, two_b)
    missing_fields = sorted(set(fundamental_gate.missing_fields))
    return V2QuantAnalysisResult(
        version="v2.0-preview",
        fundamental_gate=fundamental_gate,
        time_boxes=time_boxes,
        volume_profile=volume_profile,
        two_b_reversal=two_b,
        risk_execution=risk_plan,
        implemented_modules=[
            "fundamental_gate_v2",
            "time_box_projection_v2",
            "volume_profile_v2",
            "two_b_reversal_v2",
            "risk_execution_v2",
        ],
        missing_data_fields=missing_fields,
        hypothesis_ids=["V2001", "V2002", "V2003", "V2004", "V2005", "V2006", "V2007", "V2008"],
    )


def _ma(bars: list[OHLCVBar], window: int) -> Optional[Decimal]:
    if len(bars) < window:
        return None
    return mean(bar.close for bar in bars[-window:])


def _bias_pct(series: OHLCVSeries, window: int) -> Optional[Decimal]:
    ma = _ma(series.bars, window)
    if ma is None:
        return None
    return pct_change(series.latest().close, ma)


def _atr(bars: list[OHLCVBar], window: int) -> Optional[Decimal]:
    if len(bars) < 2:
        return None
    true_ranges: list[Decimal] = []
    start = max(1, len(bars) - window)
    for index in range(start, len(bars)):
        bar = bars[index]
        previous_close = bars[index - 1].close
        true_ranges.append(max(
            bar.high - bar.low,
            abs(bar.high - previous_close),
            abs(bar.low - previous_close),
        ))
    return mean(true_ranges)


def _kelly_fraction(win_rate: Decimal, rr_ratio: Optional[Decimal], cap: Decimal) -> Decimal:
    if rr_ratio is None or rr_ratio <= ZERO:
        return ZERO
    loss_rate = ONE - win_rate
    raw = ((rr_ratio * win_rate) - loss_rate) / rr_ratio
    return quantize(clamp(raw, ZERO, cap), "0.0001")
