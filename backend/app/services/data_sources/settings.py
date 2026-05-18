from __future__ import annotations

import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def data_mode() -> str:
    mode = (os.getenv("DATA_MODE") or "production").strip().lower()
    return mode if mode in {"production", "development", "test"} else "production"


def is_production_mode() -> bool:
    return data_mode() == "production"


def allow_mock_data() -> bool:
    if is_production_mode():
        return False
    return _env_bool("ALLOW_MOCK_DATA", False)


def is_yfinance_only_mode() -> bool:
    if is_production_mode():
        return False
    return _env_bool("YFINANCE_ONLY_MODE", False)


def prefer_official_sources() -> bool:
    return _env_bool("PREFER_OFFICIAL_SOURCES", True)


def effective_data_mode() -> str:
    return "yfinance_only" if is_yfinance_only_mode() else data_mode()

