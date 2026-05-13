from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from backend.technical_analyzer.v1.contracts.input_contract import ContextBundle, OHLCVBar, OHLCVSeries
from backend.technical_analyzer.v1.data.data_inventory import DataInventory
from backend.technical_analyzer.v1.features.v2_quant import (
    FundamentalSnapshot,
    analyze_v2_quant,
    calculate_volume_profile,
    detect_two_b_reversal,
    evaluate_fundamental_gate,
    project_time_box,
)
from backend.technical_analyzer.v1.hypothesis.hypothesis_registry import HypothesisRegistry
from backend.technical_analyzer.v1.orchestration.ai_analysis_result_builder import AIAnalysisResultBuilder, ai_analysis_result_json_schema


def _bar(index: int, close: Decimal, *, low: Decimal | None = None, high: Decimal | None = None, turnover: Decimal = Decimal("800000000")) -> OHLCVBar:
    return OHLCVBar(
        date=date(2026, 1, 1) + timedelta(days=index),
        open=close,
        high=high or close + Decimal("2"),
        low=low or close - Decimal("2"),
        close=close,
        volume=1_000_000,
        turnover_value=turnover,
        is_adjusted=True,
        data_source="live",
        previous_close=None,
    )


def _series(closes: list[Decimal]) -> OHLCVSeries:
    return OHLCVSeries("2330", [_bar(index, close) for index, close in enumerate(closes)])


def _pass_snapshot() -> FundamentalSnapshot:
    return FundamentalSnapshot(
        annual_revenue=Decimal("5000000000"),
        revenue_growth=Decimal("0.18"),
        ebit_margin=Decimal("0.22"),
        industry_ebit_zscore=Decimal("0.6"),
        operating_cash_flow=Decimal("1000000000"),
        free_cash_flow=Decimal("500000000"),
        relative_strength_vs_taiex_60d=Decimal("0.08"),
    )


def test_v2_fundamental_gate_pass_fail_and_unknown() -> None:
    passed = evaluate_fundamental_gate(_pass_snapshot())
    assert passed.status == "pass"
    assert passed.passed is True

    failed = evaluate_fundamental_gate(FundamentalSnapshot(annual_revenue=Decimal("1000000000"), ebit_margin=Decimal("-0.1")))
    assert failed.status == "fail"
    assert "annual_revenue_below_3_2b_twd" in failed.failed_rules
    assert "ebit_margin_not_positive" in failed.failed_rules

    unknown = evaluate_fundamental_gate(None)
    assert unknown.status == "unknown"
    assert "annual_revenue" in unknown.missing_fields


def test_v2_time_box_and_volume_profile_are_computed_from_ohlcv() -> None:
    series = _series([Decimal(80 + index) for index in range(80)])

    box = project_time_box(series, ma_window=20)
    assert box.status == "ready"
    assert box.p_crit is not None
    assert box.projection_date is not None

    profile = calculate_volume_profile(series)
    assert profile.status == "ready"
    assert profile.poc_price is not None
    assert profile.vah_price is not None
    assert profile.val_price is not None
    assert profile.bins_used > 0


def test_v2_two_b_reversal_detects_false_breakdown_reclaim() -> None:
    bars = [_bar(index, Decimal("100"), low=Decimal("99"), high=Decimal("101")) for index in range(115)]
    bars[100] = _bar(100, Decimal("51"), low=Decimal("50"), high=Decimal("52"))
    recent = [
        _bar(115, Decimal("48"), low=Decimal("45"), high=Decimal("50")),
        _bar(116, Decimal("49"), low=Decimal("48"), high=Decimal("51")),
        _bar(117, Decimal("50"), low=Decimal("49"), high=Decimal("52")),
        _bar(118, Decimal("51"), low=Decimal("50"), high=Decimal("53")),
        _bar(119, Decimal("52"), low=Decimal("51"), high=Decimal("54")),
    ]
    series = OHLCVSeries("2330", bars + recent)

    two_b = detect_two_b_reversal(series)
    assert two_b.status == "confirmed"
    assert two_b.confirmed is True
    assert two_b.prior_low_l1 == Decimal("50.00")
    assert two_b.false_break_low_l2 == Decimal("45.00")


def test_v2_builder_contract_and_registries_include_overlay() -> None:
    result = AIAnalysisResultBuilder().build(
        "2330",
        _series([Decimal(100 + index) for index in range(80)]),
        ContextBundle(market_cap_bucket="large"),
        fundamental_snapshot=_pass_snapshot(),
    )

    assert result.v2_quant_analysis.version == "v2.0-preview"
    assert result.v2_quant_analysis.fundamental_gate.status == "pass"
    assert "quant-v2-preview" in result.models_used
    assert any(section.key == "quant_v2" for section in result.report_sections)
    assert result.to_dict()["v2_quant_analysis"]["version"] == "v2.0-preview"

    schema = ai_analysis_result_json_schema()
    assert "v2_quant_analysis" in schema["properties"]

    registry = HypothesisRegistry.load_default()
    assert len(registry.get_by_module("V2")) >= 8

    inventory = DataInventory.load_default()
    assert inventory.get("poc_price").is_v1_implemented is True
    assert inventory.get("annual_revenue").is_v1_implemented is False


def test_v2_combined_analysis_reports_missing_fundamental_data() -> None:
    result = analyze_v2_quant(_series([Decimal(95 + index) for index in range(70)]))
    assert result.fundamental_gate.status == "unknown"
    assert "annual_revenue" in result.missing_data_fields
    assert "volume_profile_v2" in result.implemented_modules
