from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend.technical_analyzer.v1.classifiers.price_state import PriceStateClassifier
from backend.technical_analyzer.v1.contracts.enums import (
    BreakoutStatus,
    Horizon,
    TechnicalState,
    TrendDirection,
)
from backend.technical_analyzer.v1.contracts.feature_contract import FeatureBundle, Pivot, SwingStructure
from backend.technical_analyzer.v1.contracts.input_contract import ContextBundle, OHLCVBar, OHLCVSeries
from backend.technical_analyzer.v1.features.breakout_quality import BreakoutEventHistory, analyze_breakout_quality
from backend.technical_analyzer.v1.features.divergence_overheat import analyze_divergence_overheat
from backend.technical_analyzer.v1.features.momentum_contextual import analyze_momentum_contextual
from backend.technical_analyzer.v1.features.support_resistance import SRLevel, SupportResistanceMap, analyze_support_resistance
from backend.technical_analyzer.v1.features.volume_price_quadrant import (
    VolumePriceSubClass,
    analyze_volume_price_quadrant,
)
from backend.technical_analyzer.v1.registry.rule_registry import RuleRegistry


def _make_bars(closes: list[str], *, start: date = date(2026, 1, 1), high_offset: str = "1.5", low_offset: str = "1.0", turnover_base: str = "1000") -> list[OHLCVBar]:
    bars: list[OHLCVBar] = []
    previous_close: Decimal | None = None
    for idx, close_str in enumerate(closes):
        close = Decimal(close_str)
        open_price = Decimal(closes[idx - 1]) if idx else close - Decimal("0.5")
        high = max(open_price, close) + Decimal(high_offset)
        low = min(open_price, close) - Decimal(low_offset)
        turnover = Decimal(turnover_base) + Decimal(idx * 10)
        bars.append(
            OHLCVBar(
                date=start + timedelta(days=idx),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000 + idx * 10,
                turnover_value=turnover,
                is_adjusted=False,
                data_source="mock",
                previous_close=previous_close,
            )
        )
        previous_close = close
    return bars


def _make_feature_bundle(
    closes: list[str],
    *,
    current_state: TechnicalState = TechnicalState.MIXED_SIGNALS,
    ma20: str = "100",
    ma60: str = "95",
    ma20_slope: str = "1.0",
    ma60_slope: str = "0.5",
    volume_ratio_20d: str = "1.2",
    turnover_value_20d_avg: str = "1000",
    deviation_from_ma20_pct: str = "5",
    rsi_values: list[str] | None = None,
    macd_values: list[str] | None = None,
    macd_signal_values: list[str] | None = None,
    macd_hist_values: list[str] | None = None,
    kd_k_values: list[str] | None = None,
    kd_d_values: list[str] | None = None,
    atr_values: list[str] | None = None,
    atr_percentile: str = "0.5",
    bb_upper_values: list[str] | None = None,
    bb_middle_values: list[str] | None = None,
    bb_lower_values: list[str] | None = None,
    bb_bandwidth_values: list[str] | None = None,
    swing_structure: SwingStructure | None = None,
    close_crosses_ma20_20d: int = 0,
    volume_median_up_days_5: str = "1.3",
    volume_median_down_days_5: str = "1.0",
    recent_high_20d: str | None = None,
    recent_low_20d: str | None = None,
    recent_high_60d: str | None = None,
    recent_low_60d: str | None = None,
    consecutive_down_closes_5d: int = 0,
    bias_20_pct: str | None = None,
    bias_20_series: list[str] | None = None,
    high_offset: str = "1.5",
    low_offset: str = "1.0",
) -> FeatureBundle:
    bars = _make_bars(closes, high_offset=high_offset, low_offset=low_offset)
    latest_turnover = Decimal(turnover_value_20d_avg) * Decimal(volume_ratio_20d)
    latest_bar = bars[-1]
    bars[-1] = OHLCVBar(
        date=latest_bar.date,
        open=latest_bar.open,
        high=latest_bar.high,
        low=latest_bar.low,
        close=latest_bar.close,
        volume=latest_bar.volume,
        turnover_value=latest_turnover,
        is_adjusted=latest_bar.is_adjusted,
        data_source=latest_bar.data_source,
        previous_close=bars[-2].close if len(bars) > 1 else None,
    )
    series = OHLCVSeries("2330", bars)
    n = len(bars)

    def _series(values: list[str] | None, fallback: str) -> tuple[Decimal | None, ...]:
        if values is None:
            return tuple(Decimal(fallback) for _ in range(n))
        return tuple(Decimal(value) for value in values)

    return FeatureBundle(
        series=series,
        horizon=Horizon.SHORT_TERM,
        current_state=current_state,
        ma_values={
            "ma20": Decimal(ma20),
            "ma60": Decimal(ma60),
            "ma120": Decimal(ma60) - Decimal("5"),
            "ma240": Decimal(ma60) - Decimal("10"),
        },
        ma_slopes_pct={"ma20": Decimal(ma20_slope), "ma60": Decimal(ma60_slope)},
        close_crosses_ma20_20d=close_crosses_ma20_20d,
        volume_ratio_20d=Decimal(volume_ratio_20d),
        volume_ratio_5d=Decimal(volume_ratio_20d),
        volume_median_up_days_5=Decimal(volume_median_up_days_5),
        volume_median_down_days_5=Decimal(volume_median_down_days_5),
        turnover_value_ratio_20d=Decimal(volume_ratio_20d),
        turnover_value_5d_avg=Decimal(turnover_value_20d_avg),
        turnover_value_20d_avg=Decimal(turnover_value_20d_avg),
        deviation_from_ma20_pct=Decimal(deviation_from_ma20_pct),
        deviation_from_ma60_pct=Decimal("3"),
        atr_value=Decimal("2"),
        atr_series=_series(atr_values, "2"),
        atr_ratio_percentile_60d=Decimal(atr_percentile),
        bias_20_pct=Decimal(bias_20_pct) if bias_20_pct is not None else None,
        bias_20_series=tuple(Decimal(value) for value in (bias_20_series or ["1", "1.2", "1.1", "1.3", "1.4"])),
        bias_20_percentile_1y=None,
        rsi_series=_series(rsi_values, "60"),
        macd_line=_series(macd_values, "1.0"),
        macd_signal=_series(macd_signal_values, "0.8"),
        macd_histogram=_series(macd_hist_values, "0.2"),
        kd_k=_series(kd_k_values, "70"),
        kd_d=_series(kd_d_values, "65"),
        bollinger_upper=_series(bb_upper_values, str(Decimal(closes[-1]) + Decimal("5"))),
        bollinger_middle=_series(bb_middle_values, closes[-1]),
        bollinger_lower=_series(bb_lower_values, str(Decimal(closes[-1]) - Decimal("5"))),
        bollinger_bandwidth_series=_series(bb_bandwidth_values, "10"),
        swing_structure=swing_structure,
        recent_high_5d=Decimal(closes[-1]) + Decimal("1"),
        recent_low_5d=Decimal(closes[-1]) - Decimal("4"),
        recent_high_20d=Decimal(recent_high_20d) if recent_high_20d is not None else Decimal(closes[-1]) + Decimal("1"),
        recent_low_20d=Decimal(recent_low_20d) if recent_low_20d is not None else Decimal(closes[0]),
        recent_high_60d=Decimal(recent_high_60d) if recent_high_60d is not None else Decimal(closes[-1]) + Decimal("2"),
        recent_low_60d=Decimal(recent_low_60d) if recent_low_60d is not None else Decimal(closes[0]),
        consecutive_down_closes_5d=consecutive_down_closes_5d,
    )


def _swing_structure() -> SwingStructure:
    return SwingStructure(
        swing_highs=(
            Pivot(date=date(2026, 1, 10), price=Decimal("101"), pivot_type="high", index=9),
            Pivot(date=date(2026, 1, 20), price=Decimal("106"), pivot_type="high", index=19),
        ),
        swing_lows=(
            Pivot(date=date(2026, 1, 8), price=Decimal("95"), pivot_type="low", index=7),
            Pivot(date=date(2026, 1, 18), price=Decimal("99"), pivot_type="low", index=17),
        ),
        bos_up=True,
    )


def test_price_state_classifier_strong_uptrend():
    features = _make_feature_bundle(
        ["96", "97", "98", "99", "101", "103"],
        current_state=TechnicalState.MIXED_SIGNALS,
        ma20="98",
        ma60="95",
        ma20_slope="2.0",
        ma60_slope="0.8",
        rsi_values=["56", "58", "60", "62", "65", "68"],
        swing_structure=_swing_structure(),
    )
    classifier = PriceStateClassifier(RuleRegistry.load_default(), Horizon.SHORT_TERM)
    state, reasons, categories = classifier.classify(features, ContextBundle())
    assert state == TechnicalState.STRONG_UPTREND
    assert len(categories) >= 3
    assert reasons


def test_volume_price_quadrant_healthy_breakout():
    features = _make_feature_bundle(
        ["100", "100", "100", "101", "102", "103"],
        current_state=TechnicalState.EARLY_STRENGTHENING,
        ma20="98",
        ma60="96",
        deviation_from_ma20_pct="4",
        turnover_value_20d_avg="1000",
        volume_ratio_20d="1.7",
        swing_structure=_swing_structure(),
        recent_high_60d="110",
        high_offset="0.3",
    )
    context = ContextBundle(day_trading_ratio=Decimal("0.20"), foreign_net_buy_3d=Decimal("100"))
    result = analyze_volume_price_quadrant(features, context)
    assert result.quadrant == "Q1"
    assert result.sub_classification == VolumePriceSubClass.HEALTHY_BREAKOUT_VOLUME
    assert result.vote.direction == TrendDirection.BULLISH


def test_volume_price_quadrant_day_trading_distortion_neutralizes_vote():
    features = _make_feature_bundle(
        ["100", "100", "101", "102", "103", "104"],
        current_state=TechnicalState.EARLY_STRENGTHENING,
        ma20="99",
        ma60="97",
        deviation_from_ma20_pct="4",
        turnover_value_20d_avg="1000",
        volume_ratio_20d="2.0",
        swing_structure=_swing_structure(),
    )
    context = ContextBundle(day_trading_ratio=Decimal("0.70"), foreign_net_buy_3d=Decimal("100"))
    result = analyze_volume_price_quadrant(features, context)
    assert result.is_day_trading_distorted is True
    assert result.vote.direction == TrendDirection.NEUTRAL


def test_support_resistance_clusters_multiple_sources():
    structure = SwingStructure(
        swing_highs=(Pivot(date=date(2026, 1, 20), price=Decimal("112"), pivot_type="high", index=19),),
        swing_lows=(Pivot(date=date(2026, 1, 18), price=Decimal("105"), pivot_type="low", index=17),),
    )
    features = _make_feature_bundle(
        ["103", "104", "104.5", "105", "106", "110"],
        ma20="105",
        ma60="105.2",
        recent_low_20d="104.9",
        recent_low_60d="104.7",
        recent_high_20d="112",
        recent_high_60d="114",
        swing_structure=structure,
    )
    result = analyze_support_resistance("2330", features, ContextBundle())
    assert result.nearest_support is not None
    assert result.nearest_support.confluence_count >= 2
    assert any("MA20" in source or "swing_low" in source for source in result.nearest_support.merged_sources)


def test_breakout_quality_enforces_pending_then_confirms_t1():
    structure = _swing_structure()
    features_t = _make_feature_bundle(
        ["99", "100", "100", "101", "102", "106"],
        current_state=TechnicalState.EARLY_STRENGTHENING,
        ma20="100",
        ma60="97",
        volume_ratio_20d="1.8",
        turnover_value_20d_avg="1000",
        deviation_from_ma20_pct="5",
        swing_structure=structure,
    )
    sr_level = SRLevel(
        price_level=Decimal("101.5"),
        level_type="resistance",
        merged_sources=["high_20d"],
        confluence_count=1,
        strength_score=70,
        strength_tier="strong",
        flipped=False,
        test_count=2,
        last_test_date=date(2026, 1, 5),
        effective_status="effective",
        distance_from_close_pct=Decimal("2.0"),
    )
    sr_map = SupportResistanceMap(
        symbol="2330",
        analysis_date=features_t.series.latest().date,
        current_close=features_t.latest_close(),
        above_levels=[sr_level],
        below_levels=[],
        nearest_resistance=sr_level,
        nearest_support=None,
        distance_to_nearest_resistance_pct=Decimal("2.0"),
        distance_to_nearest_support_pct=None,
        position_in_range="midrange",
        vote=None,  # type: ignore[arg-type]
        reasons=[],
    )
    quadrant = analyze_volume_price_quadrant(features_t, ContextBundle(day_trading_ratio=Decimal("0.1"), foreign_net_buy_3d=Decimal("50"), foreign_net_buy_today=Decimal("30"), three_majors_net_today=Decimal("20")))
    history = BreakoutEventHistory()
    result_t = analyze_breakout_quality("2330", features_t, ContextBundle(day_trading_ratio=Decimal("0.1"), foreign_net_buy_today=Decimal("30"), three_majors_net_today=Decimal("20")), sr_map, quadrant, history)
    assert result_t.status == BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION
    assert history.events

    features_t1 = _make_feature_bundle(
        ["99", "100", "100", "101", "102", "106", "107.5"],
        current_state=TechnicalState.EARLY_STRENGTHENING,
        ma20="101",
        ma60="98",
        volume_ratio_20d="1.6",
        turnover_value_20d_avg="1000",
        deviation_from_ma20_pct="5",
        swing_structure=structure,
    )
    result_t1 = analyze_breakout_quality("2330", features_t1, ContextBundle(day_trading_ratio=Decimal("0.1"), foreign_net_buy_today=Decimal("30"), three_majors_net_today=Decimal("20")), sr_map, quadrant, history)
    assert result_t1.status == BreakoutStatus.CONFIRMED_HEALTHY_BREAKOUT


def test_breakout_quality_false_breakout_intraday():
    features = _make_feature_bundle(
        ["100", "100", "101", "102", "103", "101"],
        current_state=TechnicalState.EARLY_STRENGTHENING,
        ma20="100",
        ma60="97",
        volume_ratio_20d="0.8",
        turnover_value_20d_avg="1000",
        swing_structure=_swing_structure(),
    )
    sr_level = SRLevel(
        price_level=Decimal("102"),
        level_type="resistance",
        merged_sources=["high_20d"],
        confluence_count=1,
        strength_score=60,
        strength_tier="medium",
        flipped=False,
        test_count=1,
        last_test_date=None,
        effective_status="untested",
        distance_from_close_pct=Decimal("1.0"),
    )
    sr_map = SupportResistanceMap(
        symbol="2330",
        analysis_date=features.series.latest().date,
        current_close=features.latest_close(),
        above_levels=[sr_level],
        below_levels=[],
        nearest_resistance=sr_level,
        nearest_support=None,
        distance_to_nearest_resistance_pct=Decimal("1.0"),
        distance_to_nearest_support_pct=None,
        position_in_range="near_resistance",
        vote=None,  # type: ignore[arg-type]
        reasons=[],
    )
    quadrant = analyze_volume_price_quadrant(features, ContextBundle(day_trading_ratio=Decimal("0.2")))
    result = analyze_breakout_quality("2330", features, ContextBundle(day_trading_ratio=Decimal("0.2")), sr_map, quadrant)
    assert result.status == BreakoutStatus.FALSE_BREAKOUT_INTRADAY


def test_momentum_contextual_rsi_hot_zone_in_uptrend():
    features = _make_feature_bundle(
        ["100", "101", "102", "103", "104", "105"],
        current_state=TechnicalState.STRONG_UPTREND,
        rsi_values=["66", "68", "70", "71", "72", "73"],
        macd_values=["0.8", "0.9", "1.0", "1.1", "1.2", "1.3"],
        macd_signal_values=["0.5", "0.6", "0.7", "0.8", "0.9", "1.0"],
        macd_hist_values=["0.10", "0.12", "0.15", "0.18", "0.22", "0.30"],
        kd_k_values=["82", "84", "86", "87", "88", "89"],
        kd_d_values=["79", "80", "81", "82", "83", "84"],
    )
    result = analyze_momentum_contextual("2330", features)
    assert result.rsi_reading.contextual_state == "momentum_hot_zone_in_uptrend"
    assert result.vote.direction == TrendDirection.BULLISH


def test_momentum_contextual_macd_weak_rebound_below_zero():
    features = _make_feature_bundle(
        ["90", "91", "92", "93", "94", "95"],
        current_state=TechnicalState.WEAK_REBOUND,
        rsi_values=["45", "46", "47", "48", "49", "50"],
        macd_values=["-1.5", "-1.3", "-1.0", "-0.8", "-0.6", "-0.4"],
        macd_signal_values=["-1.6", "-1.4", "-1.2", "-1.0", "-0.8", "-0.6"],
        macd_hist_values=["0.1", "0.1", "0.2", "0.2", "0.2", "0.2"],
    )
    result = analyze_momentum_contextual("2330", features)
    assert result.macd_reading.contextual_state == "macd_weak_rebound_below_zero"


def test_divergence_overheat_detects_bearish_divergence():
    structure = SwingStructure(
        swing_highs=(
            Pivot(date=date(2026, 1, 10), price=Decimal("100"), pivot_type="high", index=2),
            Pivot(date=date(2026, 1, 20), price=Decimal("110"), pivot_type="high", index=5),
        ),
        swing_lows=(),
    )
    features = _make_feature_bundle(
        ["95", "98", "100", "104", "108", "110"],
        current_state=TechnicalState.STRONG_UPTREND,
        swing_structure=structure,
        rsi_values=["65", "70", "78", "76", "73", "70"],
        macd_hist_values=["1.0", "1.1", "1.3", "1.2", "1.0", "0.8"],
        kd_k_values=["75", "80", "88", "86", "84", "82"],
        kd_d_values=["70", "74", "80", "81", "80", "79"],
        bias_20_pct="18",
        bias_20_series=["3", "4", "5", "6", "7", "8", "9", "10"],
        atr_percentile="0.8",
    )
    momentum = analyze_momentum_contextual("2330", features)
    result = analyze_divergence_overheat(
        "2330",
        features,
        ContextBundle(beta_60d=Decimal("1.0"), day_trading_ratio=Decimal("0.65"), margin_balance_change_pct_3d=Decimal("20")),
        momentum,
        quadrant_result=type("Q", (), {"turnover_value_ratio_20_adjusted": Decimal("1.8"), "sub_classification": VolumePriceSubClass.DISTRIBUTION_VOLUME_RISK})(),  # type: ignore[call-arg]
    )
    assert any(event.divergence_type == "bearish_divergence" for event in result.divergence_events)
    assert result.vote.direction == TrendDirection.BEARISH


def test_divergence_overheat_beta_adjustment_and_override():
    structure = SwingStructure(
        swing_highs=(
            Pivot(date=date(2026, 1, 10), price=Decimal("100"), pivot_type="high", index=2),
            Pivot(date=date(2026, 1, 20), price=Decimal("112"), pivot_type="high", index=5),
        ),
        swing_lows=(),
    )
    features = _make_feature_bundle(
        ["95", "98", "100", "105", "109", "112"],
        current_state=TechnicalState.STRONG_UPTREND,
        swing_structure=structure,
        rsi_values=["72", "74", "76", "78", "80", "82"],
        macd_hist_values=["1.1", "1.2", "1.3", "1.2", "1.0", "0.8"],
        kd_k_values=["82", "84", "86", "88", "90", "92"],
        kd_d_values=["78", "80", "82", "84", "85", "86"],
        bias_20_pct="22",
        bias_20_series=["1", "2", "3", "4", "5", "6", "7", "8"],
        atr_percentile="0.85",
    )
    momentum = analyze_momentum_contextual("2330", features)
    context = ContextBundle(beta_60d=Decimal("1.0"), day_trading_ratio=Decimal("0.70"), margin_balance_change_pct_3d=Decimal("20"))
    quadrant = type("Q", (), {"turnover_value_ratio_20_adjusted": Decimal("1.9"), "sub_classification": VolumePriceSubClass.DISTRIBUTION_VOLUME_RISK})()
    result = analyze_divergence_overheat("2330", features, context, momentum, quadrant_result=quadrant)
    assert result.overheat.beta_factor == Decimal("1.0000")
    assert result.state_override_target in {TechnicalState.PARABOLIC_OVERHEAT, TechnicalState.HIGH_LEVEL_DISTRIBUTION}
