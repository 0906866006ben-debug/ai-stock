from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.technical_analyzer.v1.contracts.enums import FactorCategory, Horizon, TechnicalState, TrendDirection
from backend.technical_analyzer.v1.contracts.feature_contract import FeatureBundle
from backend.technical_analyzer.v1.contracts.input_contract import ContextBundle, OHLCVBar, OHLCVSeries
from backend.technical_analyzer.v1.contracts.output_contract import FactorVote, InvalidationSignal
from backend.technical_analyzer.v1.data.data_inventory import DataInventory
from backend.technical_analyzer.v1.decision.confidence_cap_engine import apply_confidence_caps, collect_cap_candidates
from backend.technical_analyzer.v1.decision.score_engine import compute_three_axis_scores
from backend.technical_analyzer.v1.hypothesis.hypothesis_registry import BacktestMetrics, HypothesisRegistry
from backend.technical_analyzer.v1.orchestration.ai_analysis_result_builder import AIAnalysisResultBuilder, ai_analysis_result_json_schema
from backend.technical_analyzer.v1.special_rules.taiwan_market_rules import evaluate_market_gate
from backend.technical_analyzer.v1.traceability.trace import ReasonTrace


def _bar(day: int, close: str, previous: str | None = None, source: str = "live", turnover: str = "800000000") -> OHLCVBar:
    c = Decimal(close)
    return OHLCVBar(
        date=date(2026, 5, day),
        open=c - Decimal("1"),
        high=c + Decimal("2"),
        low=c - Decimal("2"),
        close=c,
        volume=1_000_000,
        turnover_value=Decimal(turnover),
        is_adjusted=True,
        data_source=source,
        previous_close=Decimal(previous) if previous else None,
    )


def _series(source: str = "live", closes: list[str] | None = None) -> OHLCVSeries:
    values = closes or ["100", "102", "104", "106", "108"]
    bars = []
    previous = None
    for index, close in enumerate(values, start=1):
        bars.append(_bar(index, close, previous, source))
        previous = close
    return OHLCVSeries("2330", bars)


def _reason(value: str = "1") -> ReasonTrace:
    return ReasonTrace("測試理由", "field", date(2026, 5, 1), "calc", Decimal(value))


def _vote(category: FactorCategory, direction: TrendDirection, strength: str) -> FactorVote:
    return FactorVote(category, direction, Decimal(strength), (_reason(strength),))


def _votes(direction: TrendDirection = TrendDirection.BULLISH, strength: str = "0.6") -> list[FactorVote]:
    return [
        _vote(FactorCategory.PRICE_POSITION, direction, strength),
        _vote(FactorCategory.MA_GEOMETRY, direction, strength),
        _vote(FactorCategory.VOLUME_QUALITY, direction, strength),
        _vote(FactorCategory.STRUCTURE, direction, strength),
        _vote(FactorCategory.MOMENTUM, direction, strength),
        _vote(FactorCategory.VOLATILITY, direction, strength),
        _vote(FactorCategory.CHIP_FLOW, direction, strength),
    ]


def _features(source: str = "live", state: TechnicalState = TechnicalState.STRONG_UPTREND) -> FeatureBundle:
    return FeatureBundle(
        series=_series(source),
        horizon=Horizon.SHORT_TERM,
        current_state=state,
        rsi_series=(Decimal("82"),),
        kd_k=(Decimal("85"),),
        atr_ratio_percentile_60d=Decimal("92"),
        bollinger_bandwidth_series=(Decimal("0.13"),),
        turnover_value_20d_avg=Decimal("800000000"),
    )


def test_topic_p_signal_weighting_and_modifiers() -> None:
    result = compute_three_axis_scores(
        symbol="2330",
        analysis_date=date(2026, 5, 1),
        horizon=Horizon.SHORT_TERM,
        factor_votes=_votes(TrendDirection.BULLISH, "0.6"),
        features=_features(),
        categories_in_agreement=list(FactorCategory)[:7],
    )
    assert result.scores.signal == 80

    mixed = compute_three_axis_scores(
        symbol="2330",
        analysis_date=date(2026, 5, 1),
        horizon=Horizon.SHORT_TERM,
        factor_votes=[
            *_votes(TrendDirection.BULLISH, "0.5")[:4],
            *_votes(TrendDirection.BEARISH, "0.5")[4:],
        ],
        features=_features(),
    )
    assert 50 <= mixed.scores.signal <= 60

    modifiers = compute_three_axis_scores(
        symbol="2330",
        analysis_date=date(2026, 5, 1),
        horizon=Horizon.SWING,
        factor_votes=_votes(TrendDirection.NEUTRAL, "0.5"),
        signal_modifiers={"H": 15, "N": 10, "K": -10, "L": -25},
    )
    assert modifiers.scores.signal_total_modifier == -10
    assert modifiers.scores.signal == 40

    clipped = compute_three_axis_scores(
        symbol="2330",
        analysis_date=date(2026, 5, 1),
        horizon=Horizon.SWING,
        factor_votes=_votes(TrendDirection.NEUTRAL, "0.5"),
        signal_modifiers={"H": 15, "N": 15, "L": 25},
    )
    assert clipped.scores.signal_total_modifier == 30
    assert clipped.scores.signal == 80


def test_topic_p_cross_horizon_and_confidence_inputs() -> None:
    discount = compute_three_axis_scores(
        symbol="2330",
        analysis_date=date(2026, 5, 1),
        horizon=Horizon.SHORT_TERM,
        factor_votes=_votes(TrendDirection.BULLISH, "0.8"),
        cross_horizon_modifier_value=Decimal("0.6"),
    )
    assert discount.cross_horizon_modifier_applied is True
    assert discount.scores.signal < discount.scores.signal_base

    resonance = compute_three_axis_scores(
        symbol="2330",
        analysis_date=date(2026, 5, 1),
        horizon=Horizon.SWING,
        factor_votes=_votes(TrendDirection.BULLISH, "0.8"),
        cross_horizon_state="triple_resonance_confluence",
        cross_horizon_modifier_value=Decimal("1.1"),
        categories_in_agreement=list(FactorCategory)[:6],
    )
    assert resonance.scores.signal > resonance.scores.signal_base
    assert resonance.scores.confidence_adjustments["cross_horizon_alignment_bonus"] == 15
    assert resonance.scores.confidence_adjustments["factor_agreement_bonus"] == 15

    mock = compute_three_axis_scores(
        symbol="2330",
        analysis_date=date(2026, 5, 1),
        horizon=Horizon.SWING,
        factor_votes=_votes(TrendDirection.BULLISH, "0.5"),
        features=_features("mock"),
    )
    assert mock.scores.confidence_adjustments["mock_data"] == -25


def test_topic_p_risk_formula_is_independent() -> None:
    risk = compute_three_axis_scores(
        symbol="2330",
        analysis_date=date(2026, 5, 1),
        horizon=Horizon.SWING,
        factor_votes=_votes(TrendDirection.NEUTRAL, "0.1"),
        features=_features(),
        context=ContextBundle(market_regime="bear", sector_strength="weak", day_trading_ratio=Decimal("0.7")),
        bias_20_zscore=Decimal("2.3"),
        distance_to_nearest_support_pct=Decimal("16"),
        distribution_flags=["parabolic_overheat", "confirmed_double_top"],
    )
    assert risk.scores.signal == 50
    assert risk.scores.risk >= 85
    assert risk.scores.risk_factors["deviation_risk"] == 18
    assert risk.scores.risk_factors["volatility_expansion"] == 15

    reduced = compute_three_axis_scores(
        symbol="2330",
        analysis_date=date(2026, 5, 1),
        horizon=Horizon.SWING,
        factor_votes=_votes(TrendDirection.BULLISH, "0.6"),
        features=FeatureBundle(
            series=_series(),
            horizon=Horizon.SWING,
            current_state=TechnicalState.STEADY_UPTREND,
            rsi_series=(Decimal("58"),),
            atr_ratio_percentile_60d=Decimal("45"),
            turnover_value_20d_avg=Decimal("800000000"),
        ),
        distance_to_nearest_support_pct=Decimal("1"),
        nearest_support_strength_tier="strong",
        healthy_pullback=True,
        confirmed_institutional_defense=True,
    )
    assert reduced.scores.risk < 30
    assert reduced.scores.risk_factors["support_proximity_reduction"] == -10


def test_topic_q_hard_caps_and_strictest_selection() -> None:
    candidates = collect_cap_candidates(data_source="mock", categories_in_agreement=5)
    result = apply_confidence_caps(85, candidates)
    assert result.confidence_final == 50
    assert result.was_capped is True

    result = apply_confidence_caps(80, collect_cap_candidates(
        categories_in_agreement=5,
        module_event_caps=[("H", 70, "module_event_cap"), ("J", 50, "parabolic_overheat")],
    ))
    assert result.confidence_final == 50
    assert result.strictest_cap and result.strictest_cap.source_module == "J"

    unchanged = apply_confidence_caps(45, [])
    assert unchanged.confidence_final == 45
    assert unchanged.was_capped is False


def test_topic_q_rule_scenarios() -> None:
    assert apply_confidence_caps(90, collect_cap_candidates(categories_in_agreement=2)).confidence_final == 50
    assert apply_confidence_caps(90, collect_cap_candidates(
        categories_in_agreement=4,
        direction=TrendDirection.BULLISH,
        invalidation_signals=[],
    )).confidence_final == 60
    assert apply_confidence_caps(90, collect_cap_candidates(
        categories_in_agreement=4,
        context=ContextBundle(day_trading_ratio=Decimal("0.65")),
    )).confidence_final == 50
    assert apply_confidence_caps(90, collect_cap_candidates(
        categories_in_agreement=4,
        context=ContextBundle(liquidity_bucket="illiquid"),
        horizon=Horizon.SHORT_TERM,
    )).confidence_final == 50
    assert apply_confidence_caps(90, collect_cap_candidates(
        categories_in_agreement=4,
        context=ContextBundle(disposition_status="stage_2"),
    )).confidence_final == 25

    gate = evaluate_market_gate(
        "2330",
        FeatureBundle(series=OHLCVSeries("2330", [_bar(1, "100"), _bar(2, "110", "100"), _bar(3, "121", "110"), _bar(4, "133", "121")]), horizon=Horizon.SWING),
        ContextBundle(),
    )
    assert apply_confidence_caps(90, collect_cap_candidates(categories_in_agreement=4, market_gate=gate)).confidence_final == 30


def test_topic_r_hypothesis_registry() -> None:
    registry = HypothesisRegistry.load_default()
    assert len(registry.entries) >= 60
    assert registry.get_by_module("H")
    assert len(registry.get_not_tested()) == len(registry.entries)
    updated = registry.update_backtest_status(
        "H001",
        "validated",
        BacktestMetrics(hit_rate=0.57, sample_size=120),
        date(2026, 5, 13),
    )
    assert updated.backtest_status == "validated"
    assert updated.metrics.sample_size == 120
    assert "Hypothesis Registry" in registry.export_report()


def test_topic_s_data_inventory() -> None:
    inventory = DataInventory.load_default()
    assert len(inventory.entries) >= 80
    n_fields = inventory.get_by_module("N")
    assert any(field.field_name == "large_order_buy_ratio" for field in n_fields)
    missing = inventory.get_v1_missing_fields()
    assert any(field.field_name == "large_order_buy_ratio" for field in missing)
    assert inventory.get("large_order_buy_ratio").degradation_behavior
    assert "Data Inventory" in inventory.export_report()


def test_topic_t_builder_normal_and_mock_contracts() -> None:
    builder = AIAnalysisResultBuilder()
    result = builder.build("2330", _series("live"), ContextBundle(market_cap_bucket="large"), symbol_name="台積電")
    assert result.symbol == "2330"
    assert result.symbol_name == "台積電"
    assert result.overall_scores.signal > 0
    assert result.horizons[Horizon.SHORT_TERM].scores.confidence <= 100
    assert result.evidence_ledger == sorted(result.evidence_ledger, key=lambda item: abs(item.weight), reverse=True)
    assert result.structure_panel.wyckoff_phase
    assert result.primary_unified_signal.signal.value
    assert result.to_dict()["symbol"] == "2330"

    mock = builder.build("2330", _series("mock"), ContextBundle(market_cap_bucket="large"))
    assert mock.data_quality == "mock"
    assert mock.overall_scores.confidence <= 50


def test_topic_t_builder_market_gate_and_cross_horizon_scenarios() -> None:
    builder = AIAnalysisResultBuilder()
    suspended = builder.build(
        "2330",
        _series("live"),
        ContextBundle(disposition_status="stage_2", market_cap_bucket="small"),
    )
    assert suspended.market_gate.gate_status.value == "disposition_suspended"
    assert suspended.overall_scores.confidence <= 25

    triple = builder.build(
        "2330",
        _series("live"),
        ContextBundle(market_cap_bucket="large"),
        direction_by_horizon={
            Horizon.SHORT_TERM: TrendDirection.BULLISH,
            Horizon.SWING: TrendDirection.BULLISH,
            Horizon.LONG_TERM: TrendDirection.BULLISH,
        },
    )
    assert triple.cross_horizon_state == "triple_resonance_confluence"

    mixed = builder.build(
        "2330",
        _series("live"),
        ContextBundle(market_cap_bucket="large"),
        direction_by_horizon={
            Horizon.SHORT_TERM: TrendDirection.BULLISH,
            Horizon.SWING: TrendDirection.NEUTRAL,
            Horizon.LONG_TERM: TrendDirection.BEARISH,
        },
    )
    assert mixed.cross_horizon_state == "mixed_uncertain"
    assert mixed.horizons[Horizon.SHORT_TERM].score_engine_audit.cross_horizon_modifier_value == Decimal("0.6000")


def test_topic_t_schema_and_audit_sections() -> None:
    schema = ai_analysis_result_json_schema()
    assert schema["title"] == "AIAnalysisResult"
    assert "score_engine_audit" in schema["properties"]
    result = AIAnalysisResultBuilder().build("2330", _series("live"), ContextBundle())
    assert result.score_engine_audit
    assert result.cap_engine_audit
    assert result.models_used == ["technical-rule-v1", "score-engine-p", "confidence-cap-q", "quant-v2-preview"]
    assert result.v2_quant_analysis.version == "v2.0-preview"
