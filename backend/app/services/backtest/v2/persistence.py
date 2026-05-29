"""Persistence helpers for optimization v2."""
from __future__ import annotations

import csv
import json
import pickle
from pathlib import Path
from typing import Any

import yaml


class FeatureCache:
    """Tiny disk-backed feature cache keyed by arbitrary strings."""

    def __init__(self, cache_dir: Path | str, *, shape_hash: str) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / f"feature_cache_{shape_hash}.pkl"
        self._data: dict[Any, Any] = {}
        if self.cache_file.exists():
            with self.cache_file.open("rb") as fh:
                self._data = pickle.load(fh)

    def get(self, key: Any) -> Any | None:
        return self._data.get(key)

    def put(self, key: Any, features: Any) -> None:
        self._data[key] = features

    def flush(self) -> None:
        with self.cache_file.open("wb") as fh:
            pickle.dump(self._data, fh)


def save_json(path: Path | str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)


def save_yaml(path: Path | str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)


def save_csv(path: Path | str, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        target.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

