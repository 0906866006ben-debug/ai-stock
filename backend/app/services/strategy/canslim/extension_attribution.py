"""Measurement-only CAN SLIM entry extension attribution."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.params import load_params

EXTENSION_METRICS = ("close_to_ma20", "pct_from_52w_high", "return_20d", "return_60d")


@dataclass(frozen=True)
class ExtensionAttributionReport:
    source_csv: str
    artifact_json: str
    artifact_md: str
    enriched_csv: str
    pooled: dict[str, Any]
    windows: list[dict[str, Any]]


def run_extension_attribution(
    *,
    tagged_trades_csv: Path | str,
    ohlcv_db_path: Path | str,
    output_dir: Path | str = "artifacts/canslim_attribution",
    output_prefix: str = "extension",
) -> ExtensionAttributionReport:
    """Enrich existing tagged OOS trades with PIT extension metrics and aggregate."""
    _ = load_params()["backtest"]["canslim"]["regime_entry_gate"]
    source_path = Path(tagged_trades_csv)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trades = pd.read_csv(source_path)
    store = HistoricalDataStore(ohlcv_db_path)
    enriched = enrich_trades_with_extension(trades, store)
    enriched = add_extension_buckets(enriched)

    windows = [_window_report(name, frame) for name, frame in enriched.groupby("window", sort=False)]
    pooled = _pooled_report(enriched)
    json_path = out_dir / f"{output_prefix}_report.json"
    md_path = out_dir / f"{output_prefix}_report.md"
    csv_path = out_dir / f"{output_prefix}_enriched_trades.csv"
    enriched.to_csv(csv_path, index=False, encoding="utf-8-sig")
    report = ExtensionAttributionReport(
        source_csv=str(source_path),
        artifact_json=str(json_path),
        artifact_md=str(md_path),
        enriched_csv=str(csv_path),
        pooled=pooled,
        windows=windows,
    )
    _write_report(report, json_path, md_path)
    return report


def enrich_trades_with_extension(trades: pd.DataFrame, store: HistoricalDataStore) -> pd.DataFrame:
    rows = []
    cache: dict[tuple[str, str], dict[str, float | int | None]] = {}
    for row in trades.to_dict("records"):
        key = (str(row.get("stock_id")), str(row.get("entry_date")))
        if key not in cache:
            cache[key] = compute_extension_metrics(store, key[0], key[1])
        item = dict(row)
        item.update(cache[key])
        rows.append(item)
    return pd.DataFrame(rows)


def compute_extension_metrics(store: HistoricalDataStore, stock_id: str, entry_date: str) -> dict[str, float | int | None]:
    bars = store.get_ohlcv_as_of(stock_id, entry_date, 280)
    if bars.empty:
        return _empty_extension_metrics()
    close = pd.to_numeric(bars["close"], errors="coerce")
    high = pd.to_numeric(bars["high"], errors="coerce")
    if close.dropna().empty:
        return _empty_extension_metrics()
    latest_close = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean()) if len(close.dropna()) >= 20 else None
    high_252d = float(high.tail(252).max()) if len(high.dropna()) >= 1 else None
    return {
        "close_to_ma20": round(latest_close / ma20, 6) if ma20 and ma20 > 0 else None,
        "pct_from_52w_high": round(latest_close / high_252d - 1, 6) if high_252d and high_252d > 0 else None,
        "return_20d": _lookback_return(close, 20),
        "return_60d": _lookback_return(close, 60),
        "days_since_breakout": _days_since_breakout(bars),
    }


def add_extension_buckets(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.copy()
    out["close_to_ma20_bucket"] = out["close_to_ma20"].apply(close_to_ma20_bucket)
    out["pct_from_52w_high_bucket"] = out["pct_from_52w_high"].apply(pct_from_52w_high_bucket)
    out["close_to_ma20_tertile"] = _tertile_bucket(out["close_to_ma20"], "close_to_ma20")
    out["pct_from_52w_high_tertile"] = _tertile_bucket(out["pct_from_52w_high"], "pct_from_52w_high")
    return out


def close_to_ma20_bucket(value: Any) -> str:
    value = _to_float(value)
    if value is None:
        return "unknown"
    if value < 1.05:
        return "low_<1.05"
    if value <= 1.15:
        return "mid_1.05_1.15"
    return "high_>1.15"


def pct_from_52w_high_bucket(value: Any) -> str:
    value = _to_float(value)
    if value is None:
        return "unknown"
    if value <= -0.10:
        return "low_<=-10pct"
    if value <= -0.03:
        return "mid_-10pct_-3pct"
    return "high_>-3pct"


def aggregate_by(trades: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    rows: list[dict[str, Any]] = []
    for keys, frame in trades.groupby(columns, sort=False, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {column: key for column, key in zip(columns, keys)}
        row.update(_metrics_dict(frame))
        rows.append(row)
    return rows


def low_extension_positive_edge(rows: list[dict[str, Any]], bucket_column: str, low_bucket: str) -> bool:
    by_regime = [row for row in rows if row.get(bucket_column) == low_bucket]
    regimes = {str(row.get("regime_bucket_at_entry")) for row in by_regime}
    required = {"risk_on", "risk_off", "severe"}
    if not required.issubset(regimes):
        return False
    return all(float(row.get("profit_factor", 0.0)) > 1.0 for row in by_regime if row.get("regime_bucket_at_entry") in required)


def extension_monotonic(rows: list[dict[str, Any]], bucket_column: str, order: tuple[str, str, str]) -> bool:
    pf = {str(row.get(bucket_column)): float(row.get("profit_factor", 0.0)) for row in rows}
    if not all(bucket in pf for bucket in order):
        return False
    return pf[order[0]] >= pf[order[1]] >= pf[order[2]]


def _window_report(name: str, trades: pd.DataFrame) -> dict[str, Any]:
    return _report_block(name, trades)


def _pooled_report(trades: pd.DataFrame) -> dict[str, Any]:
    return _report_block("pooled", trades)


def _report_block(name: str, trades: pd.DataFrame) -> dict[str, Any]:
    close_fixed = _ordered(aggregate_by(trades, ["close_to_ma20_bucket"]), "close_to_ma20_bucket", ("low_<1.05", "mid_1.05_1.15", "high_>1.15", "unknown"))
    high_fixed = _ordered(aggregate_by(trades, ["pct_from_52w_high_bucket"]), "pct_from_52w_high_bucket", ("low_<=-10pct", "mid_-10pct_-3pct", "high_>-3pct", "unknown"))
    close_regime = _ordered(aggregate_by(trades, ["close_to_ma20_bucket", "regime_bucket_at_entry"]), "close_to_ma20_bucket", ("low_<1.05", "mid_1.05_1.15", "high_>1.15", "unknown"))
    high_regime = _ordered(aggregate_by(trades, ["pct_from_52w_high_bucket", "regime_bucket_at_entry"]), "pct_from_52w_high_bucket", ("low_<=-10pct", "mid_-10pct_-3pct", "high_>-3pct", "unknown"))
    close_grade = _ordered(aggregate_by(trades, ["close_to_ma20_bucket", "grade"]), "close_to_ma20_bucket", ("low_<1.05", "mid_1.05_1.15", "high_>1.15", "unknown"))
    high_grade = _ordered(aggregate_by(trades, ["pct_from_52w_high_bucket", "grade"]), "pct_from_52w_high_bucket", ("low_<=-10pct", "mid_-10pct_-3pct", "high_>-3pct", "unknown"))
    close_tertile = _ordered(aggregate_by(trades, ["close_to_ma20_tertile"]), "close_to_ma20_tertile", ("low", "mid", "high", "unknown"))
    high_tertile = _ordered(aggregate_by(trades, ["pct_from_52w_high_tertile"]), "pct_from_52w_high_tertile", ("low", "mid", "high", "unknown"))
    return {
        "name": name,
        "n_trades": int(len(trades)),
        "close_to_ma20_fixed": close_fixed,
        "pct_from_52w_high_fixed": high_fixed,
        "close_to_ma20_tertile": close_tertile,
        "pct_from_52w_high_tertile": high_tertile,
        "close_to_ma20_x_regime": close_regime,
        "pct_from_52w_high_x_regime": high_regime,
        "close_to_ma20_x_grade": close_grade,
        "pct_from_52w_high_x_grade": high_grade,
        "verdicts": {
            "close_to_ma20_low_extension_positive_edge": low_extension_positive_edge(close_regime, "close_to_ma20_bucket", "low_<1.05"),
            "pct_from_52w_high_low_extension_positive_edge": low_extension_positive_edge(high_regime, "pct_from_52w_high_bucket", "low_<=-10pct"),
            "close_to_ma20_extension_monotonic": extension_monotonic(close_fixed, "close_to_ma20_bucket", ("low_<1.05", "mid_1.05_1.15", "high_>1.15")),
            "pct_from_52w_high_extension_monotonic": extension_monotonic(high_fixed, "pct_from_52w_high_bucket", ("low_<=-10pct", "mid_-10pct_-3pct", "high_>-3pct")),
        },
    }


def _metrics_dict(frame: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(frame["net_return_pct"], errors="coerce").dropna()
    if returns.empty:
        return {"n": 0, "win_rate": 0.0, "profit_factor": 0.0, "avg_return": 0.0, "median_return": 0.0}
    gross_profit = float(returns[returns > 0].sum())
    gross_loss = abs(float(returns[returns < 0].sum()))
    profit_factor = float("inf") if gross_loss == 0 and gross_profit > 0 else (gross_profit / gross_loss if gross_loss > 0 else 0.0)
    return {
        "n": int(len(returns)),
        "win_rate": round(float((returns > 0).mean()), 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else profit_factor,
        "avg_return": round(float(returns.mean()), 4),
        "median_return": round(float(returns.median()), 4),
    }


def _lookback_return(close: pd.Series, bars: int) -> float | None:
    clean = pd.to_numeric(close, errors="coerce").dropna()
    if len(clean) <= bars:
        return None
    prior = float(clean.iloc[-bars - 1])
    latest = float(clean.iloc[-1])
    if prior <= 0:
        return None
    return round(latest / prior - 1, 6)


def _days_since_breakout(bars: pd.DataFrame) -> int | None:
    if len(bars) < 22:
        return None
    close = pd.to_numeric(bars["close"], errors="coerce").reset_index(drop=True)
    high = pd.to_numeric(bars["high"], errors="coerce").reset_index(drop=True)
    for idx in range(len(bars) - 1, 20, -1):
        prior_box_high = float(high.iloc[idx - 20 : idx].max())
        if prior_box_high > 0 and float(close.iloc[idx]) > prior_box_high:
            return len(bars) - 1 - idx
    return None


def _tertile_bucket(series: pd.Series, metric_name: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    out = pd.Series(["unknown"] * len(values), index=series.index, dtype=object)
    valid = values.dropna()
    if valid.empty:
        return out
    try:
        labels = pd.qcut(valid.rank(method="first"), q=3, labels=["low", "mid", "high"])
    except ValueError:
        labels = pd.Series(["unknown"] * len(valid), index=valid.index, dtype=object)
    out.loc[valid.index] = labels.astype(str)
    return out


def _ordered(rows: list[dict[str, Any]], column: str, order: tuple[str, ...]) -> list[dict[str, Any]]:
    index = {value: idx for idx, value in enumerate(order)}
    return sorted(rows, key=lambda row: (index.get(str(row.get(column)), len(index)), str(row.get(column))))


def _write_report(report: ExtensionAttributionReport, json_path: Path, md_path: Path) -> None:
    payload = {
        "source_csv": report.source_csv,
        "enriched_csv": report.enriched_csv,
        "pooled": report.pooled,
        "windows": report.windows,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# CAN SLIM Extension Attribution Report",
        "",
        f"Source CSV: `{report.source_csv}`",
        f"Enriched CSV: `{report.enriched_csv}`",
        "",
        "## Pooled Verdicts",
        f"`{report.pooled['verdicts']}`",
        "",
        "## Pooled close_to_ma20 fixed",
        _markdown_table(report.pooled["close_to_ma20_fixed"], ["close_to_ma20_bucket", "n", "win_rate", "profit_factor", "avg_return", "median_return"]),
        "",
        "## Pooled pct_from_52w_high fixed",
        _markdown_table(report.pooled["pct_from_52w_high_fixed"], ["pct_from_52w_high_bucket", "n", "win_rate", "profit_factor", "avg_return", "median_return"]),
    ]
    for window in report.windows:
        lines.extend(
            [
                "",
                f"## {window['name']}",
                f"n_trades: {window['n_trades']}",
                f"verdicts: `{window['verdicts']}`",
                "",
                "### close_to_ma20 fixed",
                _markdown_table(window["close_to_ma20_fixed"], ["close_to_ma20_bucket", "n", "win_rate", "profit_factor", "avg_return", "median_return"]),
                "",
                "### pct_from_52w_high fixed",
                _markdown_table(window["pct_from_52w_high_fixed"], ["pct_from_52w_high_bucket", "n", "win_rate", "profit_factor", "avg_return", "median_return"]),
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


def _empty_extension_metrics() -> dict[str, float | int | None]:
    return {
        "close_to_ma20": None,
        "pct_from_52w_high": None,
        "return_20d": None,
        "return_60d": None,
        "days_since_breakout": None,
    }


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed
