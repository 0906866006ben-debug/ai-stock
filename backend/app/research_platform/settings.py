from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _default_market_db() -> Path:
    configured = os.getenv("CRYPTO_BACKTEST_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    external = Path.home() / ".crypto_backtest" / "klines.db"
    if external.exists() and external.stat().st_size > 0:
        return external
    return REPO_ROOT / "backend" / "data" / "crypto_backtest" / "klines.db"


@dataclass(frozen=True)
class ResearchSettings:
    market_db_path: Path
    runs_path: Path
    metadata_db_path: Path
    api_token: str
    require_read_auth: bool
    live_trading_enabled: bool
    openai_model: str
    openai_auto_calls_limit: int
    openai_manual_calls_limit: int
    openai_total_calls_limit: int
    openai_monthly_target_usd: float
    openai_monthly_hard_stop_usd: float
    openai_min_days_between_auto: int
    openai_min_new_valid_backtests: int

    @classmethod
    def from_env(cls) -> "ResearchSettings":
        metadata = os.getenv("RESEARCH_METADATA_DB", "").strip()
        runs = os.getenv("CRYPTO_BACKTEST_RUNS", "").strip()
        return cls(
            market_db_path=_default_market_db(),
            runs_path=Path(runs) if runs else REPO_ROOT / "backend" / "data" / "crypto_backtest" / "runs",
            metadata_db_path=(
                Path(metadata)
                if metadata
                else REPO_ROOT / "backend" / "data" / "research_platform" / "research.db"
            ),
            api_token=os.getenv("AI_STOCK_BACKEND_TOKEN", "").strip(),
            require_read_auth=_bool_env("RESEARCH_API_REQUIRE_AUTH", False),
            live_trading_enabled=_bool_env("LIVE_TRADING_ENABLED", False),
            openai_model=os.getenv("OPENAI_RESEARCH_MODEL", "gpt-5.6-sol").strip(),
            openai_auto_calls_limit=_int_env("OPENAI_MAX_AUTOMATIC_CALLS_PER_MONTH", 2),
            openai_manual_calls_limit=_int_env("OPENAI_MAX_MANUAL_CALLS_PER_MONTH", 2),
            openai_total_calls_limit=_int_env("OPENAI_MAX_TOTAL_CALLS_PER_MONTH", 4),
            openai_monthly_target_usd=_float_env("OPENAI_MONTHLY_TARGET_USD", 1.50),
            openai_monthly_hard_stop_usd=_float_env("OPENAI_MONTHLY_HARD_STOP_USD", 4.50),
            openai_min_days_between_auto=_int_env("OPENAI_MIN_DAYS_BETWEEN_AUTOMATIC_CALLS", 7),
            openai_min_new_valid_backtests=_int_env("OPENAI_MIN_NEW_VALID_BACKTESTS", 10_000),
        )

