"""Topic R: structured registry for v1 backtest hypotheses."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Literal, Optional

import yaml


BacktestStatus = Literal["not_tested", "in_progress", "validated", "deprecated"]


@dataclass(frozen=True)
class BacktestMetrics:
    hit_rate: Optional[float] = None
    sample_size: Optional[int] = None
    average_return_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None


@dataclass(frozen=True)
class HypothesisEntry:
    hypothesis_id: str
    module: str
    topic: str
    description: str
    source: str
    default_value: Any
    backtest_status: BacktestStatus
    last_validated_at: Optional[date]
    metrics: BacktestMetrics
    notes: Optional[str] = None


class HypothesisRegistry:
    """YAML-backed inventory of all v1 unvalidated assumptions."""

    def __init__(self, entries: dict[str, HypothesisEntry], path: Path):
        self.entries = entries
        self.path = path

    @classmethod
    def load_default(cls) -> "HypothesisRegistry":
        return cls.load(Path(__file__).with_name("hypothesis_backtest_v1.yaml"))

    @classmethod
    def load(cls, yaml_path: str | Path) -> "HypothesisRegistry":
        path = Path(yaml_path)
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        raw_entries = raw.get("hypotheses", []) if isinstance(raw, dict) else []
        entries: dict[str, HypothesisEntry] = {}
        for item in raw_entries:
            metrics_raw = item.get("metrics") or {}
            last_validated = item.get("last_validated_at")
            if isinstance(last_validated, str):
                last_validated = date.fromisoformat(last_validated)
            entry = HypothesisEntry(
                hypothesis_id=str(item["hypothesis_id"]),
                module=str(item["module"]),
                topic=str(item.get("topic", "")),
                description=str(item["description"]),
                source=str(item.get("source", "v1")),
                default_value=item.get("default_value"),
                backtest_status=item.get("backtest_status", "not_tested"),
                last_validated_at=last_validated,
                metrics=BacktestMetrics(**metrics_raw),
                notes=item.get("notes"),
            )
            entries[entry.hypothesis_id] = entry
        return cls(entries=entries, path=path)

    def get(self, hypothesis_id: str) -> HypothesisEntry:
        return self.entries[hypothesis_id]

    def get_by_module(self, module: str) -> list[HypothesisEntry]:
        return [entry for entry in self.entries.values() if entry.module == module]

    def get_not_tested(self) -> list[HypothesisEntry]:
        return [entry for entry in self.entries.values() if entry.backtest_status == "not_tested"]

    def update_backtest_status(
        self,
        hypothesis_id: str,
        status: BacktestStatus,
        metrics: BacktestMetrics | None = None,
        validated_at: date | None = None,
    ) -> HypothesisEntry:
        entry = self.entries[hypothesis_id]
        updated = replace(
            entry,
            backtest_status=status,
            metrics=metrics or entry.metrics,
            last_validated_at=validated_at if status == "validated" else entry.last_validated_at,
        )
        self.entries[hypothesis_id] = updated
        return updated

    def export_report(self) -> str:
        lines = [
            "# Technical Analyzer v1 Hypothesis Registry",
            "",
            f"Total hypotheses: {len(self.entries)}",
            "",
            "| ID | Module | Topic | Status | Description |",
            "|---|---|---|---|---|",
        ]
        for entry in sorted(self.entries.values(), key=lambda item: item.hypothesis_id):
            lines.append(
                f"| {entry.hypothesis_id} | {entry.module} | {entry.topic} | "
                f"{entry.backtest_status} | {entry.description} |"
            )
        return "\n".join(lines)
