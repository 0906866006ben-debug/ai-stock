"""CAN SLIM walk-forward calibration harness.

This module is intentionally conservative. It exposes only YAML-marked
parameters, uses coarse grids, rejects low-sample reward hacks, and writes
local artifacts for human review. It does not call external APIs.
"""
from __future__ import annotations

import itertools
import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd
import yaml

from backend.app.services.backtest.historical_data_store import CachedHistoricalDataStore, HistoricalDataStore
from backend.app.services.backtest.metrics import PerformanceMetrics, compute_metrics
from backend.app.services.backtest.pit_fundamentals_store import (
    CachedPitFundamentalsStore,
    DEFAULT_PIT_DB_PATH,
    PitFundamentalsStore,
)
from backend.app.services.backtest.signal_replay import CANSLIM_CANDIDATE_TYPE, ReplayConfig, load_signals, replay_signals
from backend.app.services.backtest.trade_simulator import canslim_trade_rules_from_params, load_trades, simulate_trades
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pit_inputs import build_pit_inputs
from backend.app.services.strategy.canslim.observer import observe
from backend.app.services.strategy.canslim.regime import build_market_features
from backend.app.services.strategy.canslim.rules_market import regime_severity
from backend.app.services.strategy.canslim.types import MarketFeatures

ALLOWED_TUNABLE_KEYS = {
    "backtest.canslim.min_entry_grade",
    "backtest.canslim.max_hold_days",
    "scoring.grades.A_signal_min",
    "scoring.grades.B_signal_min",
}
GRADE_VALUES = ("C", "B", "A", "S")
PILLAR_RULE_PREFIX = {
    "C": ("G-",),
    "A": ("G-",),
    "T": ("T-", "SD-"),
    "I": ("I-",),
    "M": ("M-",),
}


@dataclass(frozen=True)
class GuardResult:
    accepted: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WindowResult:
    name: str
    is_metrics: dict[str, Any]
    oos_metrics: dict[str, Any]
    wfe: float
    accepted: bool
    guard_reasons: list[str]
    grade_distribution: dict[str, int]
    pillar_attribution: dict[str, float]
    regime_gate_removed: int = 0
    regime_gate_diagnostics: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)


@dataclass(frozen=True)
class WalkForwardReport:
    run_id: str
    params: dict[str, Any]
    tunable_params: list[str]
    windows: list[WindowResult]
    accepted: bool
    artifact_json: str
    artifact_md: str


def discover_tunable_params(params: dict[str, Any] | None = None) -> list[str]:
    """Return dotted params whose sibling `<name>_tunable` flag is true."""
    raw = params or _thaw(load_params())
    found: list[str] = []

    def visit(node: Any, prefix: str = "") -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key.endswith("_tunable") and value is True:
                base_key = key.removesuffix("_tunable")
                found.append(f"{prefix}.{base_key}" if prefix else base_key)
        for key, value in node.items():
            if isinstance(value, dict):
                visit(value, f"{prefix}.{key}" if prefix else key)

    visit(raw)
    return sorted(found)


def build_coarse_search_space(params: dict[str, Any] | None = None) -> dict[str, list[Any]]:
    tunables = set(discover_tunable_params(params))
    space: dict[str, list[Any]] = {
        "backtest.canslim.min_entry_grade": ["C", "B", "A"],
        "backtest.canslim.max_hold_days": [20, 30, 40],
        "scoring.grades.A_signal_min": [50, 55, 60],
        "scoring.grades.B_signal_min": [30, 35, 40],
    }
    filtered = {key: values for key, values in space.items() if key in tunables}
    validate_search_space(filtered, tunables=tunables)
    return filtered


def validate_search_space(search_space: dict[str, list[Any]], *, tunables: set[str] | None = None) -> None:
    allowed = tunables or set(discover_tunable_params())
    for key, values in search_space.items():
        if key not in allowed:
            raise ValueError(f"Parameter is not tunable: {key}")
        if key not in ALLOWED_TUNABLE_KEYS:
            raise ValueError(f"Parameter is not in CANSLIM I2 allowlist: {key}")
        if not 3 <= len(values) <= 5:
            raise ValueError(f"Coarse grid requires 3-5 values for {key}")


def grid_candidates(search_space: dict[str, list[Any]]) -> list[dict[str, Any]]:
    validate_search_space(search_space)
    keys = list(search_space)
    return [dict(zip(keys, values)) for values in itertools.product(*(search_space[key] for key in keys))]


def guard_candidate(metrics: PerformanceMetrics, *, min_trades: int = 3, pf_cap: float = 10.0) -> GuardResult:
    reasons: list[str] = []
    if metrics.n_trades < min_trades:
        reasons.append(f"n_trades<{min_trades}")
    if (math.isinf(metrics.profit_factor) or metrics.profit_factor >= 999.0) and metrics.n_trades < 10:
        reasons.append("degenerate_unbounded_pf")
    if math.isfinite(metrics.profit_factor) and metrics.profit_factor > pf_cap and metrics.n_trades < 10:
        reasons.append("thin_high_pf")
    return GuardResult(accepted=not reasons, reasons=reasons)


def compute_wfe(is_cagr: float, oos_cagr: float) -> float:
    if is_cagr <= 0:
        return 0.0
    return oos_cagr / is_cagr


def accepted_by_wfe(is_cagr: float, oos_cagr: float, *, minimum: float = 0.5) -> bool:
    return compute_wfe(is_cagr, oos_cagr) >= minimum


def cagr_from_metrics(metrics: PerformanceMetrics) -> float:
    if metrics.n_trades == 0:
        return 0.0
    avg_hold = max(metrics.avg_hold_days, 1.0)
    periods = 252.0 / avg_hold
    return (1 + metrics.avg_return) ** periods - 1


def sensitivity_stability(base_sharpe: float, perturbed_sharpes: list[float]) -> dict[str, float]:
    if not perturbed_sharpes:
        return {"base_sharpe": base_sharpe, "worst_sharpe": base_sharpe, "stability": 1.0}
    worst = min(perturbed_sharpes)
    denominator = max(abs(base_sharpe), 1.0)
    stability = max(0.0, 1.0 - abs(base_sharpe - worst) / denominator)
    return {"base_sharpe": base_sharpe, "worst_sharpe": worst, "stability": stability}


def perturb_params(params: dict[str, Any], *, pct: float = 0.20) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for key, value in params.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            for multiplier in (1 - pct, 1 + pct):
                variant = dict(params)
                variant[key] = round(value * multiplier)
                variants.append(variant)
        elif key.endswith("min_entry_grade"):
            current_idx = GRADE_VALUES.index(value) if value in GRADE_VALUES else 1
            for idx in {max(0, current_idx - 1), min(len(GRADE_VALUES) - 1, current_idx + 1)}:
                variant = dict(params)
                variant[key] = GRADE_VALUES[idx]
                variants.append(variant)
    return variants


def run_sensitivity(params: dict[str, Any], base_sharpe: float, evaluator) -> dict[str, float]:
    sharpes = [float(evaluator(variant)) for variant in perturb_params(params)]
    return sensitivity_stability(base_sharpe, sharpes)


def run_walk_forward(
    *,
    run_id: str,
    data_store: HistoricalDataStore,
    stock_universe: list[str],
    windows: list[tuple[str, str, str, str]],
    params: dict[str, Any],
    output_dir: Path | str = "artifacts/canslim_walk_forward",
    replay_kwargs: dict[str, Any] | None = None,
    min_trades: int = 3,
) -> WalkForwardReport:
    tunables = discover_tunable_params()
    validate_search_space({key: [value, value, value] for key, value in params.items()}, tunables=set(tunables))
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    window_results: list[WindowResult] = []
    replay_extra = replay_kwargs or {}

    with TemporaryDirectory() as tmp:
        override_path = _write_params_override(params, Path(tmp))
        previous = os.environ.get("CANSLIM_PARAMS_YAML_PATH")
        os.environ["CANSLIM_PARAMS_YAML_PATH"] = str(override_path)
        try:
            for idx, (is_start, is_end, oos_start, oos_end) in enumerate(windows, start=1):
                is_signals, is_trades = _run_segment(
                    f"{run_id}_w{idx}_is",
                    is_start,
                    is_end,
                    stock_universe,
                    data_store,
                    out_dir / f"{run_id}.db",
                    replay_extra,
                )
                oos_signals, oos_trades = _run_segment(
                    f"{run_id}_w{idx}_oos",
                    oos_start,
                    oos_end,
                    stock_universe,
                    data_store,
                    out_dir / f"{run_id}.db",
                    replay_extra,
                )
                is_metrics = compute_metrics(is_trades) if not is_trades.empty else compute_metrics(_empty_trades())
                oos_metrics = compute_metrics(oos_trades) if not oos_trades.empty else compute_metrics(_empty_trades())
                guard = guard_candidate(oos_metrics, min_trades=min_trades)
                is_cagr = cagr_from_metrics(is_metrics)
                oos_cagr = cagr_from_metrics(oos_metrics)
                wfe = compute_wfe(is_cagr, oos_cagr)
                accepted = guard.accepted and wfe >= 0.5
                window_results.append(
                    WindowResult(
                        name=f"window_{idx}",
                        is_metrics=is_metrics.to_dict(),
                        oos_metrics=oos_metrics.to_dict(),
                        wfe=round(wfe, 4),
                        accepted=accepted,
                        guard_reasons=guard.reasons,
                        grade_distribution=_grade_distribution(oos_signals),
                        pillar_attribution=_pillar_attribution(oos_trades),
                        regime_gate_removed=int(oos_signals.attrs.get("regime_gate_removed", 0)),
                        regime_gate_diagnostics=dict(oos_signals.attrs.get("regime_gate_diagnostics", {})),
                    )
                )
        finally:
            if previous is None:
                os.environ.pop("CANSLIM_PARAMS_YAML_PATH", None)
            else:
                os.environ["CANSLIM_PARAMS_YAML_PATH"] = previous

    accepted = bool(window_results) and all(window.accepted for window in window_results)
    json_path = out_dir / f"{run_id}_report.json"
    md_path = out_dir / f"{run_id}_report.md"
    report = WalkForwardReport(
        run_id=run_id,
        params=params,
        tunable_params=tunables,
        windows=window_results,
        accepted=accepted,
        artifact_json=str(json_path),
        artifact_md=str(md_path),
    )
    _write_report(report, json_path, md_path)
    return report


def run_real_data_walk_forward(
    *,
    run_id: str,
    ohlcv_db_path: Path | str,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    stock_universe: list[str],
    windows: list[tuple[str, str, str, str]],
    params: dict[str, Any],
    output_dir: Path | str = "artifacts/canslim_real_walk_forward",
    min_trades: int = 3,
    market: MarketFeatures | dict | None = None,
) -> WalkForwardReport:
    """Run CANSLIM walk-forward using only local OHLCV + PIT fundamentals stores."""
    window_start = min(window[0] for window in windows)
    window_end = max(window[3] for window in windows)
    data_store = CachedHistoricalDataStore(
        ohlcv_db_path,
        universe=[*stock_universe, "TAIEX", "TPEX"],
        start_date=window_start,
        end_date=window_end,
        lookback_buffer_days=500,
        forward_buffer_days=180,
    )
    pit_store = CachedPitFundamentalsStore(pit_db_path, universe=stock_universe)
    tunables = discover_tunable_params()
    validate_search_space({key: [value, value, value] for key, value in params.items()}, tunables=set(tunables))

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / f"{run_id}.db"
    window_results: list[WindowResult] = []

    with TemporaryDirectory() as tmp:
        override_path = _write_params_override(params, Path(tmp))
        previous = os.environ.get("CANSLIM_PARAMS_YAML_PATH")
        os.environ["CANSLIM_PARAMS_YAML_PATH"] = str(override_path)
        observation_cache: dict[tuple[str, str], tuple[str, dict[str, Any]] | None] = {}
        returns_cache: dict[tuple[str, int], dict[str, float]] = {}
        try:
            for idx, (is_start, is_end, oos_start, oos_end) in enumerate(windows, start=1):
                is_signals, is_trades = _run_real_segment(
                    f"{run_id}_w{idx}_is",
                    is_start,
                    is_end,
                    stock_universe,
                    data_store,
                    pit_store,
                    db_path,
                    market=market,
                    observation_cache=observation_cache,
                    returns_cache=returns_cache,
                )
                oos_signals, oos_trades = _run_real_segment(
                    f"{run_id}_w{idx}_oos",
                    oos_start,
                    oos_end,
                    stock_universe,
                    data_store,
                    pit_store,
                    db_path,
                    market=market,
                    observation_cache=observation_cache,
                    returns_cache=returns_cache,
                )
                is_metrics = compute_metrics(is_trades) if not is_trades.empty else compute_metrics(_empty_trades())
                oos_metrics = compute_metrics(oos_trades) if not oos_trades.empty else compute_metrics(_empty_trades())
                guard = guard_candidate(oos_metrics, min_trades=min_trades)
                wfe = compute_wfe(cagr_from_metrics(is_metrics), cagr_from_metrics(oos_metrics))
                window_results.append(
                    WindowResult(
                        name=f"window_{idx}",
                        is_metrics=is_metrics.to_dict(),
                        oos_metrics=oos_metrics.to_dict(),
                        wfe=round(wfe, 4),
                        accepted=guard.accepted and wfe >= 0.5,
                        guard_reasons=guard.reasons,
                        grade_distribution=_grade_distribution(oos_signals),
                        pillar_attribution=_pillar_attribution(oos_trades),
                        regime_gate_removed=int(oos_signals.attrs.get("regime_gate_removed", 0)),
                        regime_gate_diagnostics=dict(oos_signals.attrs.get("regime_gate_diagnostics", {})),
                    )
                )
        finally:
            if previous is None:
                os.environ.pop("CANSLIM_PARAMS_YAML_PATH", None)
            else:
                os.environ["CANSLIM_PARAMS_YAML_PATH"] = previous

    accepted = bool(window_results) and all(window.accepted for window in window_results)
    json_path = out_dir / f"{run_id}_report.json"
    md_path = out_dir / f"{run_id}_report.md"
    report = WalkForwardReport(
        run_id=run_id,
        params=params,
        tunable_params=tunables,
        windows=window_results,
        accepted=accepted,
        artifact_json=str(json_path),
        artifact_md=str(md_path),
    )
    _write_report(report, json_path, md_path)
    return report


def _run_segment(
    run_id: str,
    start_date: str,
    end_date: str,
    universe: list[str],
    data_store: HistoricalDataStore,
    db_path: Path,
    replay_kwargs: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = ReplayConfig(
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
        stock_universe=universe,
        target_candidate_types=[CANSLIM_CANDIDATE_TYPE],
        **replay_kwargs,
    )
    replay_signals(cfg, data_store=data_store, db_path=db_path)
    signals = load_signals(db_path, run_id)
    if signals.empty:
        return signals, _empty_trades()
    simulate_trades(
        signals_df=signals,
        data_store=data_store,
        rules=canslim_trade_rules_from_params(),
        run_id=run_id,
        db_path=db_path,
    )
    return signals, load_trades(db_path, run_id)


def _run_real_segment(
    run_id: str,
    start_date: str,
    end_date: str,
    universe: list[str],
    data_store: HistoricalDataStore,
    pit_store: PitFundamentalsStore,
    db_path: Path,
    *,
    market: MarketFeatures | dict | None,
    observation_cache: dict[tuple[str, str], tuple[str, dict[str, Any]] | None] | None = None,
    returns_cache: dict[tuple[str, int], dict[str, float]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = data_store.get_all_trading_dates(start_date, end_date)
    signal_rows: list[dict[str, Any]] = []
    params = load_params()
    canslim_cfg = params["backtest"]["canslim"]
    horizon = str(canslim_cfg.get("horizon", "swing_term"))
    min_grade = str(canslim_cfg.get("min_entry_grade", "B"))
    regime_entry_gate = bool(canslim_cfg.get("regime_entry_gate", True))
    observation_cache = observation_cache if observation_cache is not None else {}
    returns_cache = returns_cache if returns_cache is not None else {}
    market_cache: dict[str, MarketFeatures] = {}
    gate_removed = 0
    gate_diagnostics: dict[str, dict[str, dict[str, int]]] = {}
    for as_of_date in dates:
        market_features = _market_features_for_entry(
            as_of_date,
            market=market,
            data_store=data_store,
            universe=universe,
            cache=market_cache,
        )
        severity = regime_severity(market_features, params) or "unknown"
        returns_key_60d = (as_of_date, 60)
        if returns_key_60d not in returns_cache:
            returns_cache[returns_key_60d] = _universe_returns_as_of(data_store, universe, as_of_date, 60)
        returns_60d = returns_cache[returns_key_60d]
        returns_key_252d = (as_of_date, 252)
        if returns_key_252d not in returns_cache:
            returns_cache[returns_key_252d] = _universe_returns_as_of(data_store, universe, as_of_date, 252)
        returns_252d = returns_cache[returns_key_252d]
        for stock_id in universe:
            cache_key = (stock_id, as_of_date)
            cached = observation_cache.get(cache_key)
            if cached is not None:
                cached_horizon, cached_row = cached
                if cached_horizon == horizon:
                    grade = str(cached_row.get("canslim_grade", "C"))
                    gate_blocks = _regime_entry_gate_blocks(
                        horizon,
                        grade,
                        market_features,
                        params,
                        enabled=regime_entry_gate,
                    )
                    _record_regime_gate_diagnostic(gate_diagnostics, severity, grade, blocked=gate_blocks)
                    if gate_blocks:
                        gate_removed += 1
                        continue
                    row = dict(cached_row)
                    row["run_id"] = run_id
                    signal_rows.append(row)
                continue
            if cache_key in observation_cache:
                continue
            bars = data_store.get_ohlcv_as_of(stock_id, as_of_date, 280)
            if len(bars) < 65:
                observation_cache[cache_key] = None
                continue
            detail, fin_metrics, eps_filing_date = build_pit_inputs(stock_id, as_of_date, pit_store)
            cards = observe(
                stock_id,
                as_of_date,
                store=data_store,
                market=market_features,
                fin_metrics=fin_metrics,
                detail=detail,
                universe_returns_60d=returns_60d,
                universe_returns_252d=returns_252d,
                event_window_active=False,
                eps_filing_date=eps_filing_date,
            )
            card = cards[horizon]
            grade = str(card.scores.get("grade", "C"))
            if bool(card.scores.get("hard_blocked", False)) or not _grade_at_least(grade, min_grade):
                observation_cache[cache_key] = None
                continue
            row = _signal_row_from_card(run_id, stock_id, as_of_date, bars, horizon, card)
            cached_row = dict(row)
            cached_row.pop("run_id", None)
            observation_cache[cache_key] = (horizon, cached_row)
            gate_blocks = _regime_entry_gate_blocks(
                horizon,
                grade,
                market_features,
                params,
                enabled=regime_entry_gate,
            )
            _record_regime_gate_diagnostic(gate_diagnostics, severity, grade, blocked=gate_blocks)
            if gate_blocks:
                gate_removed += 1
                continue
            signal_rows.append(row)
    signals = pd.DataFrame(signal_rows)
    signals.attrs["regime_gate_removed"] = gate_removed
    signals.attrs["regime_gate_diagnostics"] = gate_diagnostics
    if signals.empty:
        return signals, _empty_trades()
    simulate_trades(
        signals_df=signals,
        data_store=data_store,
        rules=canslim_trade_rules_from_params(),
        run_id=run_id,
        db_path=db_path,
    )
    return signals, load_trades(db_path, run_id)


def _market_features_for_entry(
    as_of_date: str,
    *,
    market: MarketFeatures | dict | None,
    data_store,
    universe: list[str],
    cache: dict[str, MarketFeatures],
) -> MarketFeatures:
    if isinstance(market, MarketFeatures):
        return market
    if as_of_date not in cache:
        if isinstance(market, dict):
            cache[as_of_date] = build_market_features(as_of_date, index_bundle=market, store=data_store, universe=universe)
        else:
            cache[as_of_date] = build_market_features(as_of_date, store=data_store, universe=universe)
    return cache[as_of_date]


def _regime_entry_gate_blocks(
    horizon: str,
    grade: str,
    market: MarketFeatures,
    params: dict[str, Any],
    *,
    enabled: bool,
) -> bool:
    if not enabled or horizon not in {"swing_term", "long_term"}:
        return False
    normalized_grade = str(grade).upper()
    if normalized_grade == "S":
        return False
    severity = regime_severity(market, params)
    if severity is None or severity == "risk_on":
        return False
    if severity == "risk_off":
        return normalized_grade in {"B", "C"}
    if severity == "severe":
        return normalized_grade in {"A", "B", "C"}
    return False


def _record_regime_gate_diagnostic(
    diagnostics: dict[str, dict[str, dict[str, int]]],
    severity: str,
    grade: str,
    *,
    blocked: bool,
) -> None:
    bucket = diagnostics.setdefault(severity, {})
    grade_bucket = bucket.setdefault(str(grade).upper(), {"entered": 0, "removed": 0})
    grade_bucket["entered"] += 1
    if blocked:
        grade_bucket["removed"] += 1


def _signal_row_from_card(run_id: str, stock_id: str, as_of_date: str, bars: pd.DataFrame, horizon: str, card) -> dict[str, Any]:
    latest = bars.iloc[-1]
    close = float(latest["close"])
    base_high = float(pd.to_numeric(bars["high"].tail(20), errors="coerce").max())
    base_low = float(pd.to_numeric(bars["low"].tail(20), errors="coerce").min())
    return {
        "run_id": run_id,
        "signal_date": as_of_date,
        "stock_id": stock_id,
        "candidate_type": CANSLIM_CANDIDATE_TYPE,
        "surge_candidate_score": int(card.scores.get("signal", 0) or 0),
        "pre_breakout_score": int(card.scores.get("signal", 0) or 0),
        "confidence_score": int(card.scores.get("confidence", 0) or 0),
        "risk_score": int(card.scores.get("risk", 0) or 0),
        "close_price": close,
        "sector_category": None,
        "base_high": base_high,
        "base_low": base_low,
        "atr20": _atr20(bars),
        "entry_tier": 0,
        "canslim_horizon": horizon,
        "canslim_grade": str(card.scores.get("grade", "C")),
        "canslim_signal_raw": int(card.scores.get("signal_raw", 0) or 0),
        "canslim_signal_achievable_max": int(card.scores.get("signal_achievable_max", 0) or 0),
        "triggered_rule_ids": ",".join(card.triggered_rule_ids),
    }


def _universe_returns_as_of(data_store: HistoricalDataStore, universe: list[str], as_of_date: str, lookback: int) -> dict[str, float]:
    returns: dict[str, float] = {}
    for stock_id in universe:
        bars = data_store.get_ohlcv_as_of(stock_id, as_of_date, lookback + 1)
        if len(bars) <= lookback:
            continue
        start = float(bars["close"].iloc[0])
        end = float(bars["close"].iloc[-1])
        if start:
            returns[stock_id] = (end - start) / start
    return returns


def _grade_at_least(grade: str, minimum: str) -> bool:
    rank = {"C": 0, "B": 1, "A": 2, "S": 3}
    return rank.get(grade, -1) >= rank.get(minimum, 1)


def _atr20(frame: pd.DataFrame) -> float:
    if len(frame) < 21:
        return 0.0
    bars = frame.tail(21).reset_index(drop=True)
    ranges = []
    for idx in range(1, len(bars)):
        high = float(bars.loc[idx, "high"])
        low = float(bars.loc[idx, "low"])
        prev_close = float(bars.loc[idx - 1, "close"])
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return float(sum(ranges[-20:]) / 20) if ranges else 0.0


def _write_params_override(overrides: dict[str, Any], temp_dir: Path) -> Path:
    payload = _thaw(load_params())
    for key, value in overrides.items():
        cursor = payload
        parts = key.split(".")
        for part in parts[:-1]:
            cursor = cursor[part]
        cursor[parts[-1]] = value
    path = temp_dir / "canslim_params_override.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _grade_distribution(signals: pd.DataFrame) -> dict[str, int]:
    if signals.empty or "canslim_grade" not in signals:
        return {}
    return {str(key): int(value) for key, value in signals["canslim_grade"].value_counts().sort_index().items()}


def _pillar_attribution(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty or "entry_status" not in trades:
        return {pillar: 0.0 for pillar in PILLAR_RULE_PREFIX}
    filled = trades[trades["entry_status"] == "filled"]
    if filled.empty:
        return {pillar: 0.0 for pillar in PILLAR_RULE_PREFIX}
    total = float(filled["net_return_pct"].sum()) or 1.0
    attribution = {pillar: 0.0 for pillar in PILLAR_RULE_PREFIX}
    for _, row in filled.iterrows():
        rules = str(row.get("triggered_rule_ids", ""))
        matched = [pillar for pillar, prefixes in PILLAR_RULE_PREFIX.items() if any(prefix in rules for prefix in prefixes)]
        if not matched:
            matched = ["T"]
        contribution = float(row.get("net_return_pct", 0.0)) / len(matched)
        for pillar in matched:
            attribution[pillar] += contribution
    return {key: round(value / total, 4) for key, value in attribution.items()}


def _write_report(report: WalkForwardReport, json_path: Path, md_path: Path) -> None:
    payload = {
        "run_id": report.run_id,
        "params": report.params,
        "tunable_params": report.tunable_params,
        "accepted": report.accepted,
        "windows": [asdict(window) for window in report.windows],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        f"# CAN SLIM Walk-Forward Report: {report.run_id}",
        "",
        f"Accepted: {report.accepted}",
        "",
        "## Tunable Params",
        *[f"- `{key}`" for key in report.tunable_params],
        "",
        "## Windows",
    ]
    for window in report.windows:
        lines.extend(
            [
                f"- {window.name}: WFE={window.wfe}, accepted={window.accepted}, "
                f"OOS trades={window.oos_metrics.get('n_trades', 0)}, "
                f"regime_gate_removed={window.regime_gate_removed}, "
                f"regime_gate_diagnostics={window.regime_gate_diagnostics}, guards={window.guard_reasons}",
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=["entry_status", "net_return_pct", "hold_days"])


def _thaw(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _thaw(item) for key, item in value.items()}
    if hasattr(value, "items"):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
