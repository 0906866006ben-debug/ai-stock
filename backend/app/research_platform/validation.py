from __future__ import annotations

from datetime import datetime, timezone

from .schemas import ExperimentSummary, FactorFinding, ValidationGate


MIN_ABLATION_TRADES = 100
MIN_PARAMETER_SEARCH_TRADES = 200
MIN_WALK_FORWARD_TRADES = 300
MIN_CANDIDATE_TRADES = 300


def _strict_train(experiments: list[ExperimentSummary]) -> list[ExperimentSummary]:
    return [
        item
        for item in experiments
        if item.higher_timeframe_policy == "closed_only"
        and item.dataset_role == "TRAIN"
        and not item.is_mock
    ]


def funding_ablation_finding(experiments: list[ExperimentSummary]) -> FactorFinding:
    now = datetime.now(timezone.utc)
    strict = _strict_train(experiments)
    by_period: dict[tuple[datetime | None, datetime | None], dict[str, list[ExperimentSummary]]] = {}
    for item in strict:
        by_period.setdefault((item.period_start, item.period_end), {}).setdefault(item.variant, []).append(item)

    matches: list[tuple[ExperimentSummary, ExperimentSummary, ExperimentSummary]] = []
    for variants in by_period.values():
        if not {"baseline", "no_squeeze", "funding_sign"}.issubset(variants):
            continue
        # Prefer coverage, not performance, when duplicate legacy artifacts exist.
        matches.append(
            (
                max(variants["baseline"], key=lambda item: (item.trades, item.imported_at)),
                max(variants["no_squeeze"], key=lambda item: (item.trades, item.imported_at)),
                max(variants["funding_sign"], key=lambda item: (item.trades, item.imported_at)),
            )
        )
    matched = max(
        matches,
        key=lambda group: (
            min(item.trades for item in group),
            group[0].period_end or datetime.min.replace(tzinfo=timezone.utc),
        ),
        default=None,
    )

    if not matched:
        return FactorFinding(
            factor="FUNDING",
            status="INSUFFICIENT_EVIDENCE",
            evidence_strength="NONE",
            applicable_scope="No matched strict closed-bar ablation",
            reason="Baseline, Funding Disabled and Funding Required runs with identical periods are required.",
            invalidation="A matched strict ablation is completed with traceable artifacts.",
            observed_at=now,
        )

    baseline, off, on = matched
    marginal = None
    if baseline.average_r is not None and off.average_r is not None:
        marginal = baseline.average_r - off.average_r
    observed = min(baseline.trades, off.trades, on.trades)
    adequate = observed >= MIN_ABLATION_TRADES
    status = "MIXED" if adequate else "INSUFFICIENT_EVIDENCE"
    strength = "MEDIUM" if adequate else "LOW"
    reason = (
        f"Matched strict train ablation: baseline {baseline.trades} trades at {baseline.average_r or 0:.2f}R, "
        f"Funding Disabled {off.trades} at {off.average_r or 0:.2f}R, Funding Required {on.trades} at {on.average_r or 0:.2f}R. "
        f"Minimum group sample is {observed}/{MIN_ABLATION_TRADES}."
    )
    return FactorFinding(
        factor="FUNDING",
        status=status,
        marginal_expectancy=marginal,
        evidence_strength=strength,
        applicable_scope="Strict closed-bar, pre-OOS matched train sample",
        reason=reason,
        invalidation="Funding loses positive marginal expectancy in purged walk-forward OOS or under 1.5x costs.",
        source_experiment_ids=[baseline.experiment_id, off.experiment_id, on.experiment_id],
        observed_at=now,
    )


def validation_gates(experiments: list[ExperimentSummary]) -> list[ValidationGate]:
    now = datetime.now(timezone.utc)
    strict = _strict_train(experiments)
    baseline_trades = max((item.trades for item in strict if item.variant == "baseline"), default=0)
    definitions = [
        ("FACTOR_ABLATION", MIN_ABLATION_TRADES),
        ("PARAMETER_SEARCH", MIN_PARAMETER_SEARCH_TRADES),
        ("WALK_FORWARD", MIN_WALK_FORWARD_TRADES),
        ("CANDIDATE_PROMOTION", MIN_CANDIDATE_TRADES),
    ]
    return [
        ValidationGate(
            gate=gate,
            allowed=baseline_trades >= required,
            status="OPEN" if baseline_trades >= required else "BLOCKED_INSUFFICIENT_SAMPLE",
            required_trades=required,
            observed_trades=baseline_trades,
            reason=(
                "Minimum strict pre-OOS sample reached."
                if baseline_trades >= required
                else f"Strict baseline has {baseline_trades} trades; {required} are required before this stage."
            ),
            observed_at=now,
        )
        for gate, required in definitions
    ]
