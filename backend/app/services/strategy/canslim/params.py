"""Parameter loader for CAN SLIM strategy thresholds."""
from __future__ import annotations

from pathlib import Path
import os
from types import MappingProxyType
from typing import Any

import yaml

CanslimParams = MappingProxyType

_DEFAULT_PATH = Path(__file__).resolve().parents[4] / "data" / "strategy" / "canslim_thresholds_v1.yaml"
_CACHE: dict[str, CanslimParams] = {}


def load_params(path: str | None = None) -> CanslimParams:
    """Load CAN SLIM thresholds from YAML once and return an immutable mapping."""
    selected = path or os.environ.get("CANSLIM_PARAMS_YAML_PATH")
    resolved = str(Path(selected).resolve()) if selected else str(_DEFAULT_PATH)
    if resolved not in _CACHE:
        with Path(resolved).open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not isinstance(raw, dict):
            raise ValueError("CAN SLIM params YAML must parse to a mapping")
        _CACHE[resolved] = _freeze(raw)
    return _CACHE[resolved]


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value
