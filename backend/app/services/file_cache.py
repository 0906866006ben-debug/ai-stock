"""Tiny on-disk JSON cache to avoid re-fetching/re-computing the same data.

Used to skip repeated network fetches and paid/rate-limited model calls when the
same (symbol, as-of-day) is requested again. Day scoping is encoded by the caller
in the key. All operations fail soft: a cache problem never breaks a request.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "cache"


def _root() -> Path:
    override = os.getenv("AISTOCK_CACHE_DIR")
    return Path(override) if override else _DEFAULT_ROOT


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value))


def _path(namespace: str, key: str) -> Path:
    return _root() / _safe(namespace) / f"{_safe(key)}.json"


def load(namespace: str, key: str) -> Any | None:
    try:
        with _path(namespace, key).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, ValueError, OSError):
        return None


def save(namespace: str, key: str, data: Any) -> None:
    path = _path(namespace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        tmp.replace(path)  # atomic on the same filesystem
    except OSError:
        pass


def clear(namespace: str | None = None) -> None:
    target = _root() / _safe(namespace) if namespace else _root()
    try:
        shutil.rmtree(target)
    except (FileNotFoundError, OSError):
        pass
