"""Topic S: data field inventory and degradation plan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class FieldInventoryEntry:
    field_name: str
    used_by_modules: list[str]
    primary_source: str
    fallback_sources: list[str]
    is_v1_implemented: bool
    v1_implementation_note: Optional[str]
    degradation_behavior: Optional[str]
    last_audit_date: Optional[date]


class DataInventory:
    """YAML-backed data source inventory for the A-T pipeline."""

    def __init__(self, entries: dict[str, FieldInventoryEntry], path: Path):
        self.entries = entries
        self.path = path

    @classmethod
    def load_default(cls) -> "DataInventory":
        return cls.load(Path(__file__).with_name("data_pipeline_config.yaml"))

    @classmethod
    def load(cls, yaml_path: str | Path) -> "DataInventory":
        path = Path(yaml_path)
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        raw_fields = raw.get("fields", []) if isinstance(raw, dict) else []
        entries: dict[str, FieldInventoryEntry] = {}
        for item in raw_fields:
            audited = item.get("last_audit_date")
            if isinstance(audited, str):
                audited = date.fromisoformat(audited)
            entry = FieldInventoryEntry(
                field_name=str(item["field_name"]),
                used_by_modules=list(item.get("used_by_modules", [])),
                primary_source=str(item.get("primary_source", "UNKNOWN")),
                fallback_sources=list(item.get("fallback_sources", [])),
                is_v1_implemented=bool(item.get("is_v1_implemented", False)),
                v1_implementation_note=item.get("v1_implementation_note"),
                degradation_behavior=item.get("degradation_behavior"),
                last_audit_date=audited,
            )
            entries[entry.field_name] = entry
        return cls(entries=entries, path=path)

    def get(self, field_name: str) -> FieldInventoryEntry:
        return self.entries[field_name]

    def get_by_module(self, module: str) -> list[FieldInventoryEntry]:
        return [entry for entry in self.entries.values() if module in entry.used_by_modules]

    def get_v1_missing_fields(self) -> list[FieldInventoryEntry]:
        return [entry for entry in self.entries.values() if not entry.is_v1_implemented]

    def export_report(self) -> str:
        lines = [
            "# Technical Analyzer v1 Data Inventory",
            "",
            f"Total fields: {len(self.entries)}",
            "",
            "| Field | Modules | Source | v1 | Degradation |",
            "|---|---|---|---|---|",
        ]
        for entry in sorted(self.entries.values(), key=lambda item: item.field_name):
            modules = ", ".join(entry.used_by_modules)
            implemented = "yes" if entry.is_v1_implemented else "missing"
            lines.append(
                f"| {entry.field_name} | {modules} | {entry.primary_source} | "
                f"{implemented} | {entry.degradation_behavior or ''} |"
            )
        return "\n".join(lines)
