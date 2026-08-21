from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.research_platform.schemas import ExperimentSummary
from backend.app.research_platform.validation import funding_ablation_finding, validation_gates


def _experiment(variant: str, trades: int, average_r: float, *, policy: str = "closed_only") -> ExperimentSummary:
    return ExperimentSummary(
        experiment_id=f"test:{variant}:{trades}",
        variant=variant,
        hypothesis="matched ablation",
        period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 6, 1, tzinfo=timezone.utc),
        dataset_role="TRAIN",
        tuning_allowed=True,
        trades=trades,
        win_rate=0.7,
        total_r=average_r * trades,
        average_r=average_r,
        profit_factor=2.0,
        net_pnl=average_r * trades * 5,
        cagr=0.1,
        max_drawdown_r=1.2,
        sharpe=1.0,
        exposure=0.02,
        turnover=3.0,
        source_path=f"/{variant}/report.txt",
        artifact_hash=variant,
        data_version="test-data",
        engine_version="test-engine",
        imported_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        higher_timeframe_policy=policy,
    )


def test_funding_ablation_reports_marginal_value_but_rejects_small_sample() -> None:
    experiments = [
        _experiment("baseline", 9, 0.42),
        _experiment("no_squeeze", 10, 0.27),
        _experiment("funding_sign", 7, 0.71),
    ]

    finding = funding_ablation_finding(experiments)

    assert finding.status == "INSUFFICIENT_EVIDENCE"
    assert finding.evidence_strength == "LOW"
    assert finding.marginal_expectancy == pytest.approx(0.15)
    assert len(finding.source_experiment_ids) == 3
    assert "7/100" in finding.reason


def test_validation_gates_block_search_and_promotion_below_sample_floor() -> None:
    gates = validation_gates([_experiment("baseline", 9, 0.42)])

    assert {gate.gate for gate in gates} == {
        "FACTOR_ABLATION", "PARAMETER_SEARCH", "WALK_FORWARD", "CANDIDATE_PROMOTION"
    }
    assert all(not gate.allowed for gate in gates)
    assert all(gate.status == "BLOCKED_INSUFFICIENT_SAMPLE" for gate in gates)
    assert all(gate.observed_trades == 9 for gate in gates)


def test_partial_live_mirror_evidence_cannot_open_validation_gates() -> None:
    gates = validation_gates([_experiment("baseline", 500, 0.42, policy="partial_live_mirror")])

    assert all(not gate.allowed for gate in gates)
    assert all(gate.observed_trades == 0 for gate in gates)
