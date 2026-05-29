"""Configuration dataclasses for optimization v2."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SEARCH_SPACE_PATH = Path("backend/app/services/backtest/v1/optimizer_search_space.yaml")
DEFAULT_OUTPUT_DIR = Path("artifacts/strategy_optimization_v2")


@dataclass
class LoopConfigV2:
    target: str = "all"
    max_iterations: int = 1
    trials_per_iter: int = 20
    workers: int = 1
    walk_forward_windows: int = 5
    train_ratio: float = 0.8
    sampler_method: str = "adaptive"
    min_entry_tier: str | int = "C"
    objective_method: str = "pareto"
    start_date: str = "2022-11-01"
    end_date: str = "2026-05-15"
    output_dir: str | Path = DEFAULT_OUTPUT_DIR
    db_path: str | Path = "backend/historical_data.db"
    search_space_path: str | Path = DEFAULT_SEARCH_SPACE_PATH
    universe: list[str] = field(default_factory=list)
    universe_categories: list[str] = field(default_factory=list)
    candidate_types: list[str] = field(default_factory=lambda: ["起漲前觀察"])
    seed: int = 42
    include_tw_price_limit: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("output_dir", "db_path", "search_space_path"):
            data[key] = str(data[key])
        return data

