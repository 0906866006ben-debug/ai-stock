"""Optimizer configuration dataclasses.

Defines:
- GateConfig: 4-gate evaluation thresholds
- OptimizerConfig: search method, target, train/val split, output paths
- TrialResult: one trial outcome (per category metrics, gates, objective)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


UNBOUNDED_PF_SENTINEL = 20.0
MIN_TRADES_FOR_UNBOUNDED_PF = 10


# ── Default 4 Gates (matches user spec) ────────────────────────────────────

@dataclass
class GateConfig:
    """4-gate thresholds for backtest validation.

    Gate 1: trade_count >= min_trades
    Gate 2: win_rate >= min_win_rate
    Gate 3: profit_factor >= min_profit_factor
    Gate 4: max_drawdown >= max_drawdown_pct (max_drawdown is negative)
    """
    min_trades: int = 30
    min_win_rate: float = 0.45
    min_avg_return_pct: float = 0.0
    min_profit_factor: float = 1.05
    max_drawdown_pct: float = -0.15   # max_drawdown >= this (so -0.10 passes, -0.20 fails)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OptimizerConfig:
    target: str = "cat3"            # "cat3" | "all"
    method: str = "random"          # "random" | "grid" | "adaptive"
    max_trials: int = 200
    train_split: float = 0.7        # fraction of dates for training
    top_k: int = 5                  # number of best trials to keep in validation_report
    seed: int = 42
    start_date: str = "2022-11-01"
    end_date: str = "2026-05-15"
    db_path: str = "backend/historical_data.db"
    output_dir: str = "artifacts/strategy_optimization"
    universe: list[str] = field(default_factory=list)        # if empty, use AI tech whitelist
    candidate_types: list[str] = field(default_factory=lambda: ["起漲前觀察"])
    gates: GateConfig = field(default_factory=GateConfig)
    # Speedup knobs (default behavior unchanged when these are at defaults).
    n_workers: int = 1                                       # multiprocess parallel trials
    universe_categories: list[str] = field(default_factory=list)  # narrow universe to these AI tech cat keys
    min_entry_tier: int = 1                                  # Phase 11 tiered entry filter

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class CategoryMetrics:
    """Per-category metrics snapshot."""
    category: str
    n_trades: int
    win_rate: float
    avg_return_pct: float
    profit_factor: float
    max_drawdown: float
    expectancy: float
    gates_passed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SplitMetrics:
    """Aggregated metrics for either train or validation set."""
    n_trades: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    expectancy: float = 0.0
    gates_passed: int = 0
    cat_metrics: dict[str, CategoryMetrics] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cat_metrics"] = {k: v.to_dict() if not isinstance(v, dict) else v for k, v in self.cat_metrics.items()}
        return d


@dataclass
class TrialResult:
    trial_id: int
    params_hash: str
    params: dict[str, Any]
    train: SplitMetrics
    validation: SplitMetrics
    objective_score: float
    overfit_warning: bool
    success: bool                  # whether target gates are all passed
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "trial_id": self.trial_id,
            "params_hash": self.params_hash,
            "params": self.params,
            "train": self.train.to_dict(),
            "validation": self.validation.to_dict(),
            "objective_score": self.objective_score,
            "overfit_warning": self.overfit_warning,
            "success": self.success,
            "notes": self.notes,
        }


# ── Helpers ────────────────────────────────────────────────────────────────

def gates_passed_count(m, gates: GateConfig) -> int:
    """Count how many of the 4 gates pass given a SplitMetrics or PerformanceMetrics-like object.

    Accepts any object with attributes: n_trades, win_rate, profit_factor, max_drawdown.
    """
    passed = 0
    n_trades = getattr(m, "n_trades", 0)
    win_rate = getattr(m, "win_rate", 0.0)
    profit_factor = getattr(m, "profit_factor", 0.0)
    max_drawdown = getattr(m, "max_drawdown", 0.0)

    if n_trades >= gates.min_trades:
        passed += 1
    if win_rate >= gates.min_win_rate:
        passed += 1
    is_unbounded_thin_pf = (
        profit_factor is not None
        and profit_factor >= UNBOUNDED_PF_SENTINEL
        and n_trades < MIN_TRADES_FOR_UNBOUNDED_PF
    )
    if (
        profit_factor is not None
        and profit_factor >= gates.min_profit_factor
        and not is_unbounded_thin_pf
    ):
        passed += 1
    if max_drawdown >= gates.max_drawdown_pct:
        passed += 1
    return passed


def detect_overfit(train: SplitMetrics, val: SplitMetrics) -> tuple[bool, str]:
    """Return (overfit_warning, reason_str)."""
    if train.n_trades == 0 or val.n_trades == 0:
        return False, ""

    wr_gap = abs(train.win_rate - val.win_rate)
    ret_gap = abs(train.avg_return_pct - val.avg_return_pct)

    if wr_gap > 0.20:
        return True, f"win_rate gap {wr_gap:.2f} > 0.20"
    if train.win_rate > 0 and val.win_rate < train.win_rate * 0.5:
        return True, "val win_rate < half of train win_rate"
    if train.profit_factor > 2.0 and val.profit_factor < train.profit_factor * 0.5:
        return True, f"profit_factor degraded from {train.profit_factor:.2f} to {val.profit_factor:.2f}"
    if ret_gap > 0.04:
        return True, f"avg_return gap {ret_gap*100:.2f}% > 4%"
    return False, ""
