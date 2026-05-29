"""Trial evaluator for optimization v2."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import yaml

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.backtest.metrics import compute_metrics
from backend.app.services.backtest.signal_replay import ReplayConfig, load_signals, replay_signals
from backend.app.services.backtest.trade_simulator import TradeRules, load_trades, simulate_trades
from backend.app.services.backtest.v2.tier_classifier import parse_entry_tier
from backend.app.services.backtest.v2.tier_classifier import classify_tier
from backend.app.services.backtest.v2.walk_forward import Split
from backend.app.services.screener_rules import load_surge_candidate_rules


DEFAULT_CANDIDATE_TYPES = ["起漲前觀察"]


@dataclass
class TrialMetrics:
    n_trades: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    expectancy: float = 0.0
    net_return_pct: float = 0.0
    avg_hold_days: float = 0.0
    tier_distribution: dict[int, int] | None = None
    avg_position_multiplier: float = 0.0
    by_candidate_type: dict[str, dict[str, float]] | None = None
    by_sector_category: dict[str, dict[str, float]] | None = None

    def __post_init__(self) -> None:
        self.tier_distribution = self.tier_distribution or {}
        self.by_candidate_type = self.by_candidate_type or {}
        self.by_sector_category = self.by_sector_category or {}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SegmentRunner = Callable[[Split, TradeRules, str], pd.DataFrame]


def evaluate(
    params: Mapping[str, Any],
    splits: list[Split],
    *,
    universe: list[str],
    data_store: HistoricalDataStore | None = None,
    data_store_factory: Callable[[], HistoricalDataStore] | None = None,
    rules: TradeRules | None = None,
    db_path: Path | str | None = None,
    candidate_types: list[str] | None = None,
    base_rules: dict[str, Any] | None = None,
    run_id_prefix: str = "v2",
    segment_runner: SegmentRunner | None = None,
) -> dict[str, TrialMetrics]:
    """Evaluate one parameter set across every walk-forward split."""
    if not splits:
        return {}
    if not universe and segment_runner is None:
        raise ValueError("universe must not be empty")

    db_file = Path(db_path) if db_path else Path(tempfile.gettempdir()) / "ai_stock_v2_backtest.db"
    data_store = data_store or (data_store_factory() if data_store_factory else HistoricalDataStore())
    candidate_types = candidate_types or DEFAULT_CANDIDATE_TYPES
    screener_params, effective_rules = split_trade_rule_overrides(dict(params), rules or TradeRules())

    with _temporary_rule_override(screener_params, base_rules):
        metrics_by_split: dict[str, TrialMetrics] = {}
        for idx, split in enumerate(splits):
            run_id = f"{run_id_prefix}_{idx:02d}_{split.name}"
            if segment_runner:
                trades = segment_runner(split, effective_rules, run_id)
            else:
                trades = _run_segment(
                    split=split,
                    run_id=run_id,
                    universe=universe,
                    candidate_types=candidate_types,
                    data_store=data_store,
                    db_path=db_file,
                    rules=effective_rules,
                )
            metrics_by_split[split.name] = metrics_from_trades(trades)
    return metrics_by_split


def metrics_from_trades(trades_df: pd.DataFrame | list[dict[str, Any]]) -> TrialMetrics:
    """Compute v2 metrics from simulator trade rows."""
    trades = pd.DataFrame(trades_df)
    if trades.empty:
        return TrialMetrics()
    if "entry_status" not in trades:
        trades["entry_status"] = "filled"
    if "hold_days" not in trades:
        trades["hold_days"] = 1

    metrics = compute_metrics(trades)
    filled = trades[trades["entry_status"] == "filled"].copy()
    if filled.empty:
        return TrialMetrics()

    tier_distribution: dict[int, int] = {}
    if "entry_tier" in filled:
        tier_counts = filled["entry_tier"].fillna(0).astype(int).value_counts().to_dict()
        tier_distribution = {int(key): int(value) for key, value in tier_counts.items()}

    avg_multiplier = 1.0
    if "position_multiplier" in filled:
        avg_multiplier = float(filled["position_multiplier"].fillna(1.0).mean())

    returns = filled["net_return_pct"].dropna() if "net_return_pct" in filled else pd.Series(dtype=float)
    return TrialMetrics(
        n_trades=int(metrics.n_trades),
        win_rate=float(metrics.win_rate),
        avg_return_pct=float(metrics.avg_return),
        profit_factor=float(metrics.profit_factor),
        max_drawdown=float(metrics.max_drawdown),
        sharpe=float(metrics.sharpe),
        sortino=float(metrics.sortino),
        expectancy=float(metrics.expectancy),
        net_return_pct=float(returns.sum()) if not returns.empty else 0.0,
        avg_hold_days=float(metrics.avg_hold_days),
        tier_distribution=tier_distribution,
        avg_position_multiplier=avg_multiplier,
        by_candidate_type=_group_metrics(filled, "candidate_type"),
        by_sector_category=_group_metrics(filled, "sector_category"),
    )


def split_trade_rule_overrides(
    sampled_params: dict[str, Any],
    base_trade_rules: TradeRules,
) -> tuple[dict[str, Any], TradeRules]:
    """Split screener params from `trade_rules.*` overrides."""
    screener_params = {k: v for k, v in sampled_params.items() if not k.startswith("trade_rules.")}
    tr_overrides = {
        key.removeprefix("trade_rules."): value
        for key, value in sampled_params.items()
        if key.startswith("trade_rules.")
    }
    kwargs = {field.name: getattr(base_trade_rules, field.name) for field in fields(TradeRules)}
    for key, value in tr_overrides.items():
        if key not in kwargs:
            continue
        if key == "min_entry_tier":
            kwargs[key] = int(parse_entry_tier(value))
        elif isinstance(kwargs[key], int) and not isinstance(kwargs[key], bool):
            kwargs[key] = int(value)
        elif isinstance(kwargs[key], float):
            kwargs[key] = float(value)
        elif isinstance(kwargs[key], bool):
            kwargs[key] = _as_bool(value)
        else:
            kwargs[key] = value
    return screener_params, TradeRules(**kwargs)


def _run_segment(
    *,
    split: Split,
    run_id: str,
    universe: list[str],
    candidate_types: list[str],
    data_store: HistoricalDataStore,
    db_path: Path | str,
    rules: TradeRules,
) -> pd.DataFrame:
    cfg = ReplayConfig(
        run_id=run_id,
        start_date=split.start_date,
        end_date=split.end_date,
        stock_universe=universe,
        target_candidate_types=candidate_types,
    )
    replay_summary = replay_signals(cfg, data_store=data_store, db_path=db_path)
    signal_rows = getattr(replay_summary, "signal_rows", None)
    signals_df = pd.DataFrame(signal_rows) if signal_rows is not None else load_signals(db_path, run_id)
    if signals_df.empty:
        return pd.DataFrame()
    signals_df = apply_v2_entry_tiers(signals_df)
    sim_summary = simulate_trades(signals_df=signals_df, data_store=data_store, rules=rules, run_id=run_id, db_path=db_path)
    trade_rows = getattr(sim_summary, "trade_rows", None)
    return pd.DataFrame(trade_rows) if trade_rows is not None else load_trades(db_path, run_id)


def apply_v2_entry_tiers(signals_df: pd.DataFrame) -> pd.DataFrame:
    """Reclassify replay signals with the Phase 12 S/A/B/C tier system."""
    if signals_df.empty:
        return signals_df
    out = signals_df.copy()
    tiers: list[int] = []
    for _, row in out.iterrows():
        row_dict = row.to_dict()
        risk_score = row_dict.get("risk_score", 100)
        tier = classify_tier(row_dict, row_dict, risk_score=risk_score)
        tiers.append(int(tier))
    out["entry_tier"] = tiers
    return out


@contextmanager
def _temporary_rule_override(params: dict[str, Any], base_rules: dict[str, Any] | None):
    if not params:
        yield
        return

    previous_path = os.environ.get("RULES_V1_YAML_PATH")
    current_rules = base_rules or load_surge_candidate_rules()
    merged_rules = _deep_merge(current_rules, _expand_dotted(params))

    with tempfile.TemporaryDirectory(prefix="v2_rules_") as tmp:
        override_path = Path(tmp) / "rules_override.yaml"
        with override_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump({"surge_candidate": merged_rules}, fh, sort_keys=False, allow_unicode=True)
        os.environ["RULES_V1_YAML_PATH"] = str(override_path)
        load_surge_candidate_rules.cache_clear()
        try:
            yield
        finally:
            if previous_path is None:
                os.environ.pop("RULES_V1_YAML_PATH", None)
            else:
                os.environ["RULES_V1_YAML_PATH"] = previous_path
            load_surge_candidate_rules.cache_clear()


def _group_metrics(trades: pd.DataFrame, column: str) -> dict[str, dict[str, float]]:
    if trades.empty or column not in trades:
        return {}
    grouped: dict[str, dict[str, float]] = {}
    for key, sub in trades.groupby(column, dropna=False):
        label = str(key) if pd.notna(key) else "(none)"
        metrics = compute_metrics(sub)
        grouped[label] = {
            "n_trades": float(metrics.n_trades),
            "win_rate": float(metrics.win_rate),
            "avg_return_pct": float(metrics.avg_return),
            "profit_factor": float(metrics.profit_factor),
            "max_drawdown": float(metrics.max_drawdown),
        }
    return grouped


def _expand_dotted(params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in params.items():
        cursor = out
        parts = key.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return out


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)
