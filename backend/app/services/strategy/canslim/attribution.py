"""Measurement-only CAN SLIM grade x regime attribution."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd
import yaml

from backend.app.services.backtest.historical_data_store import CachedHistoricalDataStore
from backend.app.services.backtest.metrics import compute_metrics
from backend.app.services.backtest.pit_fundamentals_store import CachedPitFundamentalsStore, DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.regime import build_market_features
from backend.app.services.strategy.canslim.rules_market import regime_severity
from backend.app.services.strategy.canslim.walk_forward import _run_real_segment, _thaw, discover_tunable_params

GRADE_ORDER = ("S", "A", "B", "C")
REGIME_ORDER = ("risk_on", "risk_off", "severe", "unknown")


@dataclass(frozen=True)
class AttributionReport:
    run_id: str
    params: dict[str, Any]
    windows: list[dict[str, Any]]
    pooled: dict[str, Any]
    artifact_json: str
    artifact_md: str
    trades_csv: str


def run_real_data_attribution(
    *,
    run_id: str,
    ohlcv_db_path: Path | str,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    stock_universe: list[str],
    windows: list[tuple[str, str, str, str]],
    params: dict[str, Any],
    output_dir: Path | str = "artifacts/canslim_attribution",
) -> AttributionReport:
    """Run full-population OOS attribution with regime entry gate disabled."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / f"{run_id}.db"
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
    oos_rows: list[pd.DataFrame] = []
    window_reports: list[dict[str, Any]] = []

    overrides = dict(params)
    overrides["backtest.canslim.regime_entry_gate"] = False
    with TemporaryDirectory() as tmp:
        override_path = _write_params_override(overrides, Path(tmp))
        previous = os.environ.get("CANSLIM_PARAMS_YAML_PATH")
        os.environ["CANSLIM_PARAMS_YAML_PATH"] = str(override_path)
        try:
            for idx, (_is_start, _is_end, oos_start, oos_end) in enumerate(windows, start=1):
                signals, trades = _run_real_segment(
                    f"{run_id}_w{idx}_oos",
                    oos_start,
                    oos_end,
                    stock_universe,
                    data_store,
                    pit_store,
                    db_path,
                    market=None,
                )
                tagged = tag_oos_trades(
                    window=f"window_{idx}",
                    horizon=str(load_params()["backtest"]["canslim"].get("horizon", "swing_term")),
                    signals=signals,
                    trades=trades,
                    data_store=data_store,
                    stock_universe=stock_universe,
                )
                oos_rows.append(tagged)
                window_reports.append(
                    _window_report(
                        f"window_{idx}",
                        tagged,
                        _regime_composition(oos_start, oos_end, data_store, stock_universe),
                    )
                )
        finally:
            if previous is None:
                os.environ.pop("CANSLIM_PARAMS_YAML_PATH", None)
            else:
                os.environ["CANSLIM_PARAMS_YAML_PATH"] = previous

    all_trades = pd.concat(oos_rows, ignore_index=True) if oos_rows else _empty_tagged_trades()
    pooled = _pooled_report(all_trades)
    json_path = out_dir / f"{run_id}_attribution_report.json"
    md_path = out_dir / f"{run_id}_attribution_report.md"
    csv_path = out_dir / f"{run_id}_tagged_oos_trades.csv"
    all_trades.to_csv(csv_path, index=False, encoding="utf-8-sig")
    report = AttributionReport(
        run_id=run_id,
        params=params,
        windows=window_reports,
        pooled=pooled,
        artifact_json=str(json_path),
        artifact_md=str(md_path),
        trades_csv=str(csv_path),
    )
    _write_report(report, json_path, md_path)
    return report


def tag_oos_trades(
    *,
    window: str,
    horizon: str,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    data_store,
    stock_universe: list[str],
) -> pd.DataFrame:
    if trades.empty:
        return _empty_tagged_trades()
    filled = trades[trades["entry_status"] == "filled"].copy()
    if filled.empty:
        return _empty_tagged_trades()
    signal_cols = ["stock_id", "signal_date", "canslim_grade", "canslim_horizon"]
    merged = filled.merge(signals[signal_cols], on=["stock_id", "signal_date"], how="left")
    params = load_params()
    regime_cache: dict[str, str] = {}
    rows = []
    for row in merged.to_dict("records"):
        entry_date = str(row.get("entry_date") or "")
        if entry_date not in regime_cache:
            regime_cache[entry_date] = regime_bucket_at_entry(entry_date, data_store, stock_universe, params)
        rows.append(
            {
                "window": window,
                "horizon": row.get("canslim_horizon") or horizon,
                "stock_id": row.get("stock_id"),
                "signal_date": row.get("signal_date"),
                "entry_date": entry_date,
                "grade": str(row.get("canslim_grade") or "unknown"),
                "regime_bucket_at_entry": regime_cache[entry_date],
                "net_return_pct": float(row.get("net_return_pct") or 0.0),
                "holding_days": int(row.get("hold_days") or 0),
            }
        )
    return pd.DataFrame(rows)


def regime_bucket_at_entry(entry_date: str, data_store, stock_universe: list[str], params: dict[str, Any] | None = None) -> str:
    active_params = params or load_params()
    market = build_market_features(entry_date, store=data_store, universe=stock_universe)
    return regime_severity(market, active_params) or "unknown"


def aggregate_by(trades: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    rows: list[dict[str, Any]] = []
    grouped = trades.groupby(columns, dropna=False, sort=False)
    for keys, frame in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {column: key for column, key in zip(columns, keys)}
        row.update(_metrics_dict(frame))
        rows.append(row)
    return rows


def grade_monotonic_by_pf(by_grade: list[dict[str, Any]]) -> bool:
    pf_by_grade = {str(row["grade"]): float(row["profit_factor"]) for row in by_grade}
    if not all(grade in pf_by_grade for grade in ("S", "A", "B")):
        return False
    return pf_by_grade["S"] >= pf_by_grade["A"] >= pf_by_grade["B"]


def _window_report(name: str, trades: pd.DataFrame, regime_composition: dict[str, float]) -> dict[str, Any]:
    by_grade = _ordered_rows(aggregate_by(trades, ["grade"]), ["grade"], GRADE_ORDER)
    by_grade_regime = _ordered_rows(aggregate_by(trades, ["grade", "regime_bucket_at_entry"]), ["grade", "regime_bucket_at_entry"], GRADE_ORDER, REGIME_ORDER)
    return {
        "window": name,
        "n_trades": int(len(trades)),
        "by_grade": by_grade,
        "by_grade_regime": by_grade_regime,
        "grade_monotonic": grade_monotonic_by_pf(by_grade),
        "regime_composition": regime_composition,
    }


def _pooled_report(trades: pd.DataFrame) -> dict[str, Any]:
    by_grade = _ordered_rows(aggregate_by(trades, ["grade"]), ["grade"], GRADE_ORDER)
    by_grade_regime = _ordered_rows(aggregate_by(trades, ["grade", "regime_bucket_at_entry"]), ["grade", "regime_bucket_at_entry"], GRADE_ORDER, REGIME_ORDER)
    return {
        "n_trades": int(len(trades)),
        "by_grade": by_grade,
        "by_grade_regime": by_grade_regime,
        "grade_monotonic": grade_monotonic_by_pf(by_grade),
    }


def _metrics_dict(frame: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(frame["net_return_pct"], errors="coerce").dropna()
    if returns.empty:
        return {"n": 0, "win_rate": 0.0, "profit_factor": 0.0, "avg_return": 0.0, "median_return": 0.0}
    gross_profit = float(returns[returns > 0].sum())
    gross_loss = abs(float(returns[returns < 0].sum()))
    if gross_loss == 0:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss
    return {
        "n": int(len(returns)),
        "win_rate": round(float((returns > 0).mean()), 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else profit_factor,
        "avg_return": round(float(returns.mean()), 4),
        "median_return": round(float(returns.median()), 4),
    }


def _regime_composition(start_date: str, end_date: str, data_store, stock_universe: list[str]) -> dict[str, float]:
    params = load_params()
    dates = data_store.get_all_trading_dates(start_date, end_date)
    counts = {bucket: 0 for bucket in REGIME_ORDER}
    for date in dates:
        counts[regime_bucket_at_entry(date, data_store, stock_universe, params)] += 1
    total = sum(counts.values())
    if total == 0:
        return {bucket: 0.0 for bucket in REGIME_ORDER}
    return {bucket: round(count / total, 4) for bucket, count in counts.items()}


def _ordered_rows(rows: list[dict[str, Any]], columns: list[str], *orders: tuple[str, ...]) -> list[dict[str, Any]]:
    order_maps = [{value: idx for idx, value in enumerate(order)} for order in orders]

    def key(row: dict[str, Any]) -> tuple:
        out = []
        for idx, column in enumerate(columns):
            value = str(row.get(column))
            out.append(order_maps[idx].get(value, len(order_maps[idx])) if idx < len(order_maps) else value)
        return tuple(out)

    return sorted(rows, key=key)


def _write_params_override(overrides: dict[str, Any], temp_dir: Path) -> Path:
    payload = _thaw(load_params())
    for key, value in overrides.items():
        cursor = payload
        parts = key.split(".")
        for part in parts[:-1]:
            cursor = cursor[part]
        cursor[parts[-1]] = value
    path = temp_dir / "canslim_attribution_params.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _write_report(report: AttributionReport, json_path: Path, md_path: Path) -> None:
    payload = {
        "run_id": report.run_id,
        "params": report.params,
        "tunable_params": discover_tunable_params(),
        "windows": report.windows,
        "pooled": report.pooled,
        "trades_csv": report.trades_csv,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        f"# CAN SLIM Attribution Report: {report.run_id}",
        "",
        f"Tagged OOS trades CSV: `{report.trades_csv}`",
        "",
        "## Pooled By Grade",
        _markdown_table(report.pooled["by_grade"], ["grade", "n", "win_rate", "profit_factor", "avg_return", "median_return"]),
        "",
        f"Pooled grade_monotonic: {report.pooled['grade_monotonic']}",
    ]
    for window in report.windows:
        lines.extend(
            [
                "",
                f"## {window['window']}",
                f"n_trades: {window['n_trades']}",
                f"grade_monotonic: {window['grade_monotonic']}",
                f"regime_composition: `{window['regime_composition']}`",
                "",
                "### By Grade",
                _markdown_table(window["by_grade"], ["grade", "n", "win_rate", "profit_factor", "avg_return", "median_return"]),
                "",
                "### By Grade x Regime",
                _markdown_table(window["by_grade_regime"], ["grade", "regime_bucket_at_entry", "n", "win_rate", "profit_factor", "avg_return", "median_return"]),
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows_"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(str(row.get(column, "")) for column in columns) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def _empty_tagged_trades() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "window",
            "horizon",
            "stock_id",
            "signal_date",
            "entry_date",
            "grade",
            "regime_bucket_at_entry",
            "net_return_pct",
            "holding_days",
        ]
    )
