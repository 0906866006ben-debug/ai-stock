from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from backend.technical_analyzer.v1.chip_flow.chip_resonance import ChipResonancePattern, analyze_chip_resonance
from backend.technical_analyzer.v1.classifiers.signal_aggregator import UnifiedSignal, aggregate_signals
from backend.technical_analyzer.v1.contracts.enums import BreakoutStatus, FactorCategory, Horizon, TechnicalState, TrendDirection
from backend.technical_analyzer.v1.contracts.feature_contract import FeatureBundle, Pivot, SwingStructure
from backend.technical_analyzer.v1.contracts.input_contract import ContextBundle, OHLCVBar, OHLCVSeries
from backend.technical_analyzer.v1.contracts.output_contract import FactorVote
from backend.technical_analyzer.v1.features.breakout_quality import BreakoutAnalysisResult
from backend.technical_analyzer.v1.features.candle_patterns import CandleEvent, CandlePatternResult, CandlePosition, CandleVolumeContext, analyze_candle_patterns
from backend.technical_analyzer.v1.features.chart_patterns import analyze_chart_patterns
from backend.technical_analyzer.v1.features.divergence_overheat import DivergenceOverheatResult, OverheatAssessment
from backend.technical_analyzer.v1.features.support_resistance import SRLevel, SupportResistanceMap
from backend.technical_analyzer.v1.features.volume_price_quadrant import VolumePriceQuadrantResult, VolumePriceSubClass
from backend.technical_analyzer.v1.special_rules.taiwan_market_rules import MarketGateStatus, evaluate_market_gate
from backend.technical_analyzer.v1.traceability.trace import ReasonTrace


def _bars(closes: list[str], *, start: date = date(2026, 2, 1), turnover: str = "200000000") -> list[OHLCVBar]:
    out: list[OHLCVBar] = []
    prev_close: Decimal | None = None
    for idx, close_text in enumerate(closes):
        close = Decimal(close_text)
        open_price = Decimal(closes[idx - 1]) if idx else close
        high = max(open_price, close) + Decimal("1")
        low = min(open_price, close) - Decimal("1")
        out.append(
            OHLCVBar(
                date=start + timedelta(days=idx),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000 + idx,
                turnover_value=Decimal(turnover) + Decimal(idx * 1000000),
                is_adjusted=False,
                data_source="mock",
                previous_close=prev_close,
            )
        )
        prev_close = close
    return out


def _bundle(
    closes: list[str],
    *,
    state: TechnicalState = TechnicalState.MIXED_SIGNALS,
    swing: SwingStructure | None = None,
    turnover_avg: str = "200000000",
    recent_high_60d: str | None = None,
    recent_low_60d: str | None = None,
    ma20: str = "100",
    atr: list[str] | None = None,
) -> FeatureBundle:
    series = OHLCVSeries("2330", _bars(closes, turnover=turnover_avg))
    n = len(series.bars)
    return FeatureBundle(
        series=series,
        horizon=Horizon.SHORT_TERM,
        current_state=state,
        ma_values={"ma20": Decimal(ma20), "ma60": Decimal("95"), "ma120": Decimal("90"), "ma240": Decimal("80")},
        ma_slopes_pct={"ma20": Decimal("1"), "ma60": Decimal("0.5")},
        volume_ratio_20d=Decimal("1.6"),
        turnover_value_ratio_20d=Decimal("1.6"),
        turnover_value_20d_avg=Decimal(turnover_avg),
        atr_value=Decimal("2"),
        atr_series=tuple(Decimal(value) for value in (atr or ["4", "4", "4", "4", "4", "2", "2", "2", "2", "2"])),
        atr_ratio_percentile_60d=Decimal("0.5"),
        rsi_series=tuple(Decimal("60") for _ in range(n)),
        macd_line=tuple(Decimal("1") for _ in range(n)),
        macd_signal=tuple(Decimal("0.8") for _ in range(n)),
        macd_histogram=tuple(Decimal("0.2") for _ in range(n)),
        kd_k=tuple(Decimal("70") for _ in range(n)),
        kd_d=tuple(Decimal("65") for _ in range(n)),
        bollinger_upper=tuple(Decimal(closes[-1]) + Decimal("5") for _ in range(n)),
        bollinger_middle=tuple(Decimal(closes[-1]) for _ in range(n)),
        bollinger_lower=tuple(Decimal(closes[-1]) - Decimal("5") for _ in range(n)),
        bollinger_bandwidth_series=tuple(Decimal("10") for _ in range(n)),
        swing_structure=swing,
        recent_high_20d=Decimal(recent_high_60d or closes[-1]),
        recent_low_20d=Decimal(recent_low_60d or closes[0]),
        recent_high_60d=Decimal(recent_high_60d or closes[-1]),
        recent_low_60d=Decimal(recent_low_60d or closes[0]),
    )


def _reason() -> ReasonTrace:
    return ReasonTrace("test", "field", date(2026, 2, 1), "calc", Decimal("1"))


def _vote(category: FactorCategory, direction: TrendDirection = TrendDirection.BULLISH, strength: str = "0.8") -> FactorVote:
    return FactorVote(category=category, direction=direction, strength=Decimal(strength), reasons=(_reason(),))


def _quadrant(sub: VolumePriceSubClass = VolumePriceSubClass.HEALTHY_BREAKOUT_VOLUME, quadrant: str = "Q1", ratio: str = "1.8") -> VolumePriceQuadrantResult:
    return VolumePriceQuadrantResult(
        quadrant=quadrant,  # type: ignore[arg-type]
        sub_classification=sub,
        today_turnover_value=Decimal("180000000"),
        adjusted_turnover_value=Decimal("180000000"),
        turnover_value_ratio_20_raw=Decimal(ratio),
        turnover_value_ratio_20_adjusted=Decimal(ratio),
        day_trading_ratio=Decimal("0.1"),
        day_trading_distortion_level="normal",
        is_day_trading_distorted=False,
        vote=_vote(FactorCategory.VOLUME_QUALITY),
        reasons=[_reason()],
    )


def _breakout(status: BreakoutStatus = BreakoutStatus.CONFIRMED_HEALTHY_BREAKOUT) -> BreakoutAnalysisResult:
    return BreakoutAnalysisResult(
        symbol="2330",
        analysis_date=date(2026, 2, 1),
        event_detected=True,
        event_type="breakout",
        related_level=None,
        status=status,
        quality_dimensions=None,
        false_signal_warnings=[],
        is_limit_distorted=False,
        event_record=None,
        vote=_vote(FactorCategory.BREAKOUT_QUALITY),
        state_signal_score_modifier=10,
        confidence_cap=70 if status == BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION else None,
        state_downgrade_required=False,
        reasons=[_reason()],
    )


def _candle(pattern: str = "long_bullish_candle", label: str = "breakout_bullish_candle") -> CandlePatternResult:
    event = CandleEvent(
        event_date=date(2026, 2, 1),
        pattern_name=pattern,
        pattern_type="single",
        positions=[CandlePosition.NEAR_RESISTANCE],
        volume_context=CandleVolumeContext.HIGH,
        contextual_label=label,
        warning_level="low",
        body_ratio=Decimal("0.8"),
        upper_shadow_ratio=Decimal("0.1"),
        lower_shadow_ratio=Decimal("0.1"),
        close_position_in_range=Decimal("0.9"),
        is_limit_distorted=False,
    )
    return CandlePatternResult("2330", date(2026, 2, 1), Horizon.SHORT_TERM, [event], [], 5, None, [_reason()])


def test_market_gate_attention_caps_confidence():
    gate = evaluate_market_gate("2330", _bundle(["100", "101", "102"]), ContextBundle(disposition_status="attention"))
    assert gate.gate_status == MarketGateStatus.NOTICE_DEGRADED
    assert gate.confidence_cap == 70


def test_market_gate_stage2_suppresses_all_votes():
    gate = evaluate_market_gate("2330", _bundle(["100", "101", "102"]), ContextBundle(disposition_status="stage_2"))
    assert gate.gate_status == MarketGateStatus.DISPOSITION_SUSPENDED
    assert gate.suppress_all_votes is True
    assert gate.confidence_cap == 30


def test_market_gate_limit_distortion_caps_confidence():
    features = _bundle(["100", "110", "121", "133.1"], turnover_avg="200000000")
    gate = evaluate_market_gate("2330", features, ContextBundle())
    assert gate.gate_status == MarketGateStatus.LIMIT_DISTORTED
    assert gate.confidence_cap == 30


def test_market_gate_ex_rights_suppresses_event_detection():
    gate = evaluate_market_gate("2330", _bundle(["100", "99", "100"]), ContextBundle(is_ex_rights_today=True))
    assert gate.gate_status == MarketGateStatus.EX_RIGHTS
    assert gate.suppress_event_detection is True
    assert gate.confidence_cap == 60


def test_chip_flow_golden_resonance_strong():
    context = ContextBundle(
        foreign_net_today=Decimal("100"),
        trust_net_today=Decimal("50"),
        dealer_net_today=Decimal("10"),
        foreign_net_value_today=Decimal("10000000"),
        trust_net_value_today=Decimal("5000000"),
        margin_balance_change_pct_3d=Decimal("1"),
        foreign_consecutive_days=4,
        trust_consecutive_days=5,
        foreign_net_value_5d=Decimal("150000000"),
        large_order_buy_ratio=Decimal("0.7"),
        large_order_sell_ratio=Decimal("0.3"),
    )
    result = analyze_chip_resonance("2330", _bundle(["100", "101", "105"], state=TechnicalState.EARLY_STRENGTHENING), context, _breakout(), _candle(), _quadrant())
    assert result.primary_pattern == ChipResonancePattern.GOLDEN_RESONANCE_STRONG
    assert result.vote.category == FactorCategory.CHIP_FLOW


def test_chip_flow_false_rally_high_confidence_overrides_distribution():
    context = ContextBundle(
        foreign_net_today=Decimal("-100"),
        trust_net_today=Decimal("0"),
        dealer_net_today=Decimal("0"),
        three_majors_net_today=Decimal("-100"),
        foreign_net_value_today=Decimal("-10000000"),
        trust_net_value_today=Decimal("0"),
        margin_balance_change_pct_3d=Decimal("20"),
        foreign_net_5d=Decimal("-500"),
        foreign_net_value_5d=Decimal("-80000000"),
        large_order_buy_ratio=Decimal("0.3"),
        large_order_sell_ratio=Decimal("0.7"),
    )
    result = analyze_chip_resonance("2330", _bundle(["100", "101", "105"], state=TechnicalState.STRONG_UPTREND, recent_high_60d="105"), context)
    assert result.primary_pattern == ChipResonancePattern.FALSE_RALLY_HIGH_CONFIDENCE
    assert result.state_override_target == TechnicalState.HIGH_LEVEL_DISTRIBUTION


def test_chip_flow_confirmed_accumulation():
    context = ContextBundle(
        foreign_net_today=Decimal("10"),
        trust_net_today=Decimal("10"),
        dealer_net_today=Decimal("0"),
        foreign_net_value_today=Decimal("1000000"),
        trust_net_value_today=Decimal("1000000"),
        margin_balance_change_pct_3d=Decimal("1"),
        foreign_consecutive_days=6,
        foreign_ownership_change_5d_pct=Decimal("0.3"),
        foreign_net_value_20d=Decimal("120000000"),
        large_order_buy_ratio=Decimal("0.6"),
        large_order_sell_ratio=Decimal("0.4"),
    )
    result = analyze_chip_resonance("2330", _bundle(["100", "100", "101"], state=TechnicalState.TIGHT_CONSOLIDATION, recent_high_60d="115"), context)
    assert result.primary_pattern == ChipResonancePattern.CONFIRMED_ACCUMULATION


def test_chip_flow_partial_data_caps_confidence():
    result = analyze_chip_resonance("2330", _bundle(["100", "101", "102"]), ContextBundle(foreign_net_today=Decimal("1")))
    assert result.is_chip_data_partial is True
    assert result.confidence_cap == 70


def test_candle_pattern_long_upper_high_volume_distribution():
    features = _bundle(["100", "103", "105"], state=TechnicalState.STRONG_UPTREND, recent_high_60d="106")
    latest = features.series.bars[-1]
    features.series.bars[-1] = OHLCVBar(latest.date, Decimal("104"), Decimal("106"), Decimal("103.8"), Decimal("104.1"), latest.volume, latest.turnover_value, False, "mock", previous_close=features.series.bars[-2].close)
    result = analyze_candle_patterns("2330", features, _quadrant(ratio="2.2"))
    assert any(event.contextual_label == "distribution_at_high" for event in result.events_today)


def test_candle_pattern_hammer_near_low_selling_climax():
    features = _bundle(["100", "96", "95"], state=TechnicalState.SELLING_CLIMAX, recent_low_60d="94")
    latest = features.series.bars[-1]
    features.series.bars[-1] = OHLCVBar(latest.date, Decimal("94"), Decimal("95"), Decimal("92"), Decimal("94.8"), latest.volume, latest.turnover_value, False, "mock", previous_close=features.series.bars[-2].close)
    result = analyze_candle_patterns("2330", features, _quadrant(ratio="2.1"))
    assert any(event.contextual_label == "selling_climax_candidate" for event in result.events_today)


def test_candle_pattern_gap_up_breakaway():
    features = _bundle(["100", "101", "110"], state=TechnicalState.TIGHT_CONSOLIDATION)
    features.series.bars[-1] = OHLCVBar(features.series.bars[-1].date, Decimal("109"), Decimal("111"), Decimal("108"), Decimal("110"), 1000, Decimal("300000000"), False, "mock", previous_close=Decimal("101"))
    result = analyze_candle_patterns("2330", features, _quadrant(ratio="1.8"))
    assert any(gap.gap_type == "gap_up_breakaway" for gap in result.recent_gap_events)


def test_candle_pattern_market_gate_suppresses_events():
    features = _bundle(["100", "101", "102"])
    gate = evaluate_market_gate("2330", features, ContextBundle(is_ex_rights_today=True))
    result = analyze_candle_patterns("2330", features, _quadrant(), market_gate=gate)
    assert result.events_today == []


def test_chart_pattern_confirmed_double_top():
    swing = SwingStructure(
        swing_highs=(Pivot(date(2026, 2, 5), Decimal("110"), "high", 4), Pivot(date(2026, 2, 20), Decimal("111"), "high", 19)),
        swing_lows=(Pivot(date(2026, 2, 12), Decimal("100"), "low", 11),),
    )
    features = _bundle(["108"] * 25 + ["98"], swing=swing)
    features.series.bars[4] = _replace_turnover(features.series.bars[4], "300000000")
    features.series.bars[19] = _replace_turnover(features.series.bars[19], "120000000")
    result = analyze_chart_patterns("2330", features)
    assert any(pattern.pattern_name == "double_top" and pattern.pattern_status == "confirmed" for pattern in result.detected_patterns)


def test_chart_pattern_confirmed_double_bottom():
    swing = SwingStructure(
        swing_highs=(Pivot(date(2026, 2, 12), Decimal("110"), "high", 11),),
        swing_lows=(Pivot(date(2026, 2, 5), Decimal("100"), "low", 4), Pivot(date(2026, 2, 20), Decimal("99"), "low", 19)),
    )
    features = _bundle(["101"] * 25 + ["112"], swing=swing)
    features.series.bars[4] = _replace_turnover(features.series.bars[4], "300000000")
    features.series.bars[19] = _replace_turnover(features.series.bars[19], "120000000")
    result = analyze_chart_patterns("2330", features)
    assert any(pattern.pattern_name == "double_bottom" and pattern.pattern_status == "confirmed" for pattern in result.detected_patterns)


def test_chart_pattern_ascending_triangle():
    swing = SwingStructure(
        swing_highs=(Pivot(date(2026, 2, 5), Decimal("110"), "high", 4), Pivot(date(2026, 2, 20), Decimal("111"), "high", 19)),
        swing_lows=(Pivot(date(2026, 2, 8), Decimal("100"), "low", 7), Pivot(date(2026, 2, 22), Decimal("103"), "low", 21)),
    )
    result = analyze_chart_patterns("2330", _bundle(["106"] * 30, swing=swing))
    assert any(pattern.pattern_name == "ascending_triangle" for pattern in result.detected_patterns)


def test_chart_pattern_vcp_forming():
    swing = SwingStructure(
        swing_highs=(Pivot(date(2026, 2, 1), Decimal("120"), "high", 0), Pivot(date(2026, 2, 8), Decimal("116"), "high", 7), Pivot(date(2026, 2, 15), Decimal("113"), "high", 14)),
        swing_lows=(Pivot(date(2026, 2, 5), Decimal("100"), "low", 4), Pivot(date(2026, 2, 12), Decimal("105"), "low", 11), Pivot(date(2026, 2, 20), Decimal("109"), "low", 19)),
    )
    features = _bundle(["110"] * 30, swing=swing)
    features.series.bars[4] = _replace_turnover(features.series.bars[4], "300000000")
    features.series.bars[11] = _replace_turnover(features.series.bars[11], "180000000")
    features.series.bars[19] = _replace_turnover(features.series.bars[19], "90000000")
    result = analyze_chart_patterns("2330", features)
    assert any(pattern.pattern_name == "vcp" for pattern in result.detected_patterns)


def test_signal_aggregator_market_gate_priority():
    features = _bundle(["100", "101", "102"])
    gate = evaluate_market_gate("2330", features, ContextBundle(disposition_status="stage_1"))
    result = aggregate_signals("2330", date(2026, 2, 1), Horizon.SHORT_TERM, TechnicalState.STRONG_UPTREND, market_gate=gate, breakout_result=_breakout())
    assert result.primary_signal.signal == UnifiedSignal.DISPOSITION_SUSPENDED


def test_signal_aggregator_breakout_and_chip_strength_merge():
    context = ContextBundle(
        foreign_net_today=Decimal("100"),
        trust_net_today=Decimal("50"),
        dealer_net_today=Decimal("10"),
        foreign_net_value_today=Decimal("10000000"),
        trust_net_value_today=Decimal("5000000"),
        margin_balance_change_pct_3d=Decimal("1"),
        foreign_consecutive_days=4,
        trust_consecutive_days=5,
        foreign_net_value_5d=Decimal("150000000"),
        large_order_buy_ratio=Decimal("0.7"),
        large_order_sell_ratio=Decimal("0.3"),
    )
    chip = analyze_chip_resonance("2330", _bundle(["100", "101", "105"], state=TechnicalState.EARLY_STRENGTHENING), context, _breakout(), _candle(), _quadrant())
    result = aggregate_signals("2330", date(2026, 2, 1), Horizon.SHORT_TERM, TechnicalState.EARLY_STRENGTHENING, breakout_result=_breakout(), chip_result=chip)
    assert result.primary_signal.signal == UnifiedSignal.HEALTHY_BREAKOUT_CONFIRMED
    assert result.primary_signal.strength > Decimal("0.8")


def test_signal_aggregator_bearish_pattern_priority():
    swing = SwingStructure(
        swing_highs=(Pivot(date(2026, 2, 5), Decimal("110"), "high", 4), Pivot(date(2026, 2, 20), Decimal("111"), "high", 19)),
        swing_lows=(Pivot(date(2026, 2, 12), Decimal("100"), "low", 11),),
    )
    features = _bundle(["108"] * 25 + ["98"], swing=swing)
    features.series.bars[4] = _replace_turnover(features.series.bars[4], "300000000")
    features.series.bars[19] = _replace_turnover(features.series.bars[19], "120000000")
    chart = analyze_chart_patterns("2330", features)
    result = aggregate_signals("2330", date(2026, 2, 1), Horizon.SHORT_TERM, TechnicalState.EARLY_STRENGTHENING, chart_result=chart, breakout_result=_breakout(BreakoutStatus.BREAKDOWN_PENDING_CONFIRMATION))
    assert result.primary_signal.signal == UnifiedSignal.BEARISH_PATTERN_CONFIRMED


def test_signal_aggregator_confidence_cap_and_modifier_sum():
    overheat = OverheatAssessment("parabolic_overheat", ["bias_extreme"], 1, Decimal("20"), Decimal("3"), Decimal("99"), Decimal("1"), False, {})
    divergence = DivergenceOverheatResult("2330", date(2026, 2, 1), "short_term", overheat, [], -25, 40, True, TechnicalState.PARABOLIC_OVERHEAT, _vote(FactorCategory.VOLATILITY, TrendDirection.BEARISH, "0.9"), [_reason()])
    result = aggregate_signals("2330", date(2026, 2, 1), Horizon.SHORT_TERM, TechnicalState.STRONG_UPTREND, breakout_result=_breakout(BreakoutStatus.BREAKOUT_PENDING_CONFIRMATION), divergence_result=divergence)
    assert result.aggregated_confidence == 40
    assert result.aggregated_signal_score_modifier == -15
    assert result.requires_state_override is True


def _replace_turnover(bar: OHLCVBar, turnover: str) -> OHLCVBar:
    return OHLCVBar(
        date=bar.date,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        turnover_value=Decimal(turnover),
        is_adjusted=bar.is_adjusted,
        data_source=bar.data_source,
        previous_close=bar.previous_close,
    )
