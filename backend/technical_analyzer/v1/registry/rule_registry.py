"""YAML-backed rule registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..contracts.enums import Horizon
from ..contracts.exceptions import RuleRegistryError


class RuleRegistry:
    """Simple YAML-backed config accessor."""

    def __init__(self, raw: dict[str, Any], path: Path):
        self.raw = raw
        self.path = path

    @classmethod
    def load_default(cls) -> "RuleRegistry":
        path = Path(__file__).with_name("rules_v1.yaml")
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        if not isinstance(raw, dict):
            raise RuleRegistryError("rules_v1.yaml must parse to a mapping")
        return cls(raw=raw, path=path)

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self.raw
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                if default is not None:
                    return default
                raise RuleRegistryError(f"missing rule path: {'/'.join(keys)}")
            current = current[key]
        return current

    def section(self, name: str) -> dict[str, Any]:
        section = self.get(name)
        if not isinstance(section, dict):
            raise RuleRegistryError(f"section {name} must be a mapping")
        return section

    def thresholds_for(self, horizon: Horizon) -> dict[str, Any]:
        return self.get("horizons", horizon.value)

    @property
    def version(self) -> str:
        return str(self.get("version"))
