"""Measurement-only regime deployment analysis for CAN SLIM trades."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.strategy.canslim.params import load_params

REGIME_ORDER = ("risk_on", "risk_off", "severe", "unknown")


@dataclass(frozen=True)
class RegimeDeployReport:
    source_csv: str
    artifact_json: str
    artifact_md: str
    by_regime: dict[str, Any]
    risk_on_only: dict[str, Any]
    risk_on_plus_risk_off: dict[str, Any]
    severe_low_extension_sleeve: dict[str, Any]
    implied_mapping: dict[str, str]


def run_regime_deploy_analysis(
    *,
    enriched_trades_csv: Path | str,
    output_dir: Path | str = "artifacts/canslim_attribution",
    output_prefix: str = "riskon_deploy",
    min_window_trades: int = 20,
    min_sleeve_trades: int = 20,
) -> RegimeDeployReport:
    _ = load_params()["backtest"]["canslim"]["regime_entry_gate"]
    source_path = Path(enriched_trades_csv)
    trades = pd.read_csv(source_path)
    by_regime = {
        "pooled": _ordered(aggregate_by(trades, ["regime_bucket_at_entry"]), "regime_bucket_at_entry", REGIME_ORDER),
        "windows": [
            {"window": window, "rows": _ordered(aggregate_by(frame, ["regime_bucket_at_entry"]), "regime_bucket_at_entry", REGIME_ORDER)}
            for window, frame in trades.groupby("window", sort=False)
        ],
    }
    risk_on_only = _strategy_view(trades, ["risk_on"], min_window_trades=min_window_trades)
    risk_on_plus_risk_off = _strategy_view(trades, ["risk_on", "risk_off"], min_window_trades=min_window_trades)
    severe_low_extension_sleeve = _severe_low_extension_sleeve(trades, min_trades=min_sleeve_trades)
    implied_mapping = _implied_mapping(risk_on_only, risk_on_plus_risk_off, severe_low_extension_sleeve)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{output_prefix}_report.json"
    md_path = out_dir / f"{output_prefix}_report.md"
    report = RegimeDeployReport(
        source_csv=str(source_path),
        artifact_json=str(json_path),
        artifact_md=str(md_path),
        by_regime=by_regime,
        risk_on_only=risk_on_only,
        risk_on_plus_risk_off=risk_on_plus_risk_off,
        severe_low_extension_sleeve=severe_low_extension_sleeve,
        implied_mapping=implied_mapping,
    )
    _write_report(report, json_path, md_path)
    return report


def aggregate_by(trades: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    rows: list[dict[str, Any]] = []
    for keys, frame in trades.groupby(columns, sort=False, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {column: key for column, key in zip(columns, keys)}
        row.update(metrics_dict(frame))
        rows.append(row)
    return rows


def metrics_dict(frame: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(frame["net_return_pct"], errors="coerce").dropna()
    if returns.empty:
        return {"n": 0, "win_rate": 0.0, "profit_factor": 0.0, "avg_return": 0.0, "sum_return": 0.0}
    gross_profit = float(returns[returns > 0].sum())
    gross_loss = abs(float(returns[returns < 0].sum()))
    profit_factor = float("inf") if gross_loss == 0 and gross_profit > 0 else (gross_profit / gross_loss if gross_loss > 0 else 0.0)
    return {
        "n": int(len(returns)),
        "win_rate": round(float((returns > 0).mean()), 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else profit_factor,
        "avg_return": round(float(returns.mean()), 4),
        "sum_return": round(float(returns.sum()), 4),
    }


def riskon_positive_all_windows(window_rows: list[dict[str, Any]], *, min_window_trades: int = 20) -> bool:
    eligible = [row for row in window_rows if int(row.get("n", 0)) >= min_window_trades]
    if not eligible:
        return False
    return all(float(row.get("profit_factor", 0.0)) > 1.0 for row in eligible)


def _strategy_view(trades: pd.DataFrame, regimes: list[str], *, min_window_trades: int) -> dict[str, Any]:
    filtered = trades[trades["regime_bucket_at_entry"].isin(regimes)].copy()
    window_rows = []
    all_windows = list(dict.fromkeys(trades["window"].tolist()))
    for window in all_windows:
        frame = filtered[filtered["window"] == window]
        row = {"window": window, **metrics_dict(frame)}
        row["eligible_for_verdict"] = int(row["n"]) >= min_window_trades
        window_rows.append(row)
    return {
        "regimes": regimes,
        "pooled": metrics_dict(filtered),
        "windows": window_rows,
        "riskon_positive_all_windows": riskon_positive_all_windows(window_rows, min_window_trades=min_window_trades),
        "min_window_trades": min_window_trades,
    }


def _severe_low_extension_sleeve(trades: pd.DataFrame, *, min_trades: int) -> dict[str, Any]:
    severe = trades[trades["regime_bucket_at_entry"] == "severe"].copy()
    sleeve = severe[pd.to_numeric(severe["pct_from_52w_high"], errors="coerce") <= -0.10].copy()
    windows = []
    all_windows = list(dict.fromkeys(trades["window"].tolist()))
    for window in all_windows:
        frame = sleeve[sleeve["window"] == window]
        row = {"window": window, **metrics_dict(frame)}
        row["eligible_for_verdict"] = int(row["n"]) >= min_trades
        windows.append(row)
    pooled = metrics_dict(sleeve)
    verdict = int(pooled["n"]) >= min_trades and float(pooled["profit_factor"]) > 1.0
    return {
        "definition": "regime=severe and pct_from_52w_high<=-0.10",
        "pooled": pooled,
        "windows": windows,
        "severe_lowext_worth_trading": bool(verdict),
        "min_sleeve_trades": min_trades,
    }


def _implied_mapping(
    risk_on_only: dict[str, Any],
    risk_on_plus_risk_off: dict[str, Any],
    severe_low_extension_sleeve: dict[str, Any],
) -> dict[str, str]:
    risk_on_action = "trade_momentum" if risk_on_only["riskon_positive_all_windows"] else "insufficient_or_inconsistent"
    risk_off_pf = float(risk_on_plus_risk_off["pooled"].get("profit_factor", 0.0))
    risk_on_pf = float(risk_on_only["pooled"].get("profit_factor", 0.0))
    risk_off_action = "include_with_risk_on" if risk_off_pf >= risk_on_pf and risk_off_pf > 1.0 else "exclude_or_reduce"
    severe_action = "low_extension_sleeve" if severe_low_extension_sleeve["severe_lowext_worth_trading"] else "flat"
    return {
        "risk_on": risk_on_action,
        "risk_off": risk_off_action,
        "severe": severe_action,
    }


def _ordered(rows: list[dict[str, Any]], column: str, order: tuple[str, ...]) -> list[dict[str, Any]]:
    index = {value: idx for idx, value in enumerate(order)}
    return sorted(rows, key=lambda row: (index.get(str(row.get(column)), len(index)), str(row.get(column))))


def _write_report(report: RegimeDeployReport, json_path: Path, md_path: Path) -> None:
    payload = {
        "source_csv": report.source_csv,
        "by_regime": report.by_regime,
        "risk_on_only": report.risk_on_only,
        "risk_on_plus_risk_off": report.risk_on_plus_risk_off,
        "severe_low_extension_sleeve": report.severe_low_extension_sleeve,
        "implied_mapping": report.implied_mapping,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# CAN SLIM Risk-On Deployability Report",
        "",
        f"Source CSV: `{report.source_csv}`",
        "",
        f"Implied mapping: `{report.implied_mapping}`",
        "",
        "## By Regime Pooled",
        _markdown_table(report.by_regime["pooled"], ["regime_bucket_at_entry", "n", "win_rate", "profit_factor", "avg_return", "sum_return"]),
        "",
        "## Risk-On Only",
        f"verdict: {report.risk_on_only['riskon_positive_all_windows']}",
        _markdown_table(report.risk_on_only["windows"], ["window", "n", "win_rate", "profit_factor", "avg_return", "sum_return", "eligible_for_verdict"]),
        "",
        "## Risk-On + Risk-Off",
        f"verdict: {report.risk_on_plus_risk_off['riskon_positive_all_windows']}",
        _markdown_table(report.risk_on_plus_risk_off["windows"], ["window", "n", "win_rate", "profit_factor", "avg_return", "sum_return", "eligible_for_verdict"]),
        "",
        "## Severe Low-Extension Sleeve",
        f"verdict: {report.severe_low_extension_sleeve['severe_lowext_worth_trading']}",
        _markdown_table(report.severe_low_extension_sleeve["windows"], ["window", "n", "win_rate", "profit_factor", "avg_return", "sum_return", "eligible_for_verdict"]),
    ]
    for window in report.by_regime["windows"]:
        lines.extend(
            [
                "",
                f"## {window['window']} By Regime",
                _markdown_table(window["rows"], ["regime_bucket_at_entry", "n", "win_rate", "profit_factor", "avg_return", "sum_return"]),
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
