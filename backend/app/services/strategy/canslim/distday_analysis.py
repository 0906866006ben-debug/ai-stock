"""Measurement-only distribution-day regime diagnostic for CAN SLIM trades."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.params import load_params

DIST_DAY_THRESHOLD = 5


@dataclass(frozen=True)
class DistDayReport:
    source_csv: str
    artifact_json: str
    artifact_md: str
    enriched_csv: str
    verdicts: dict[str, bool]
    window_1_loser_flag_rate: dict[str, Any]
    cohort_comparison: list[dict[str, Any]]
    window_3_false_positive: dict[str, Any]


def run_distday_analysis(
    *,
    enriched_trades_csv: Path | str,
    ohlcv_db_path: Path | str,
    output_dir: Path | str = "artifacts/canslim_attribution",
    output_prefix: str = "distday",
    dist_day_threshold: int = DIST_DAY_THRESHOLD,
) -> DistDayReport:
    _ = load_params()["backtest"]["canslim"]["regime_entry_gate"]
    source_path = Path(enriched_trades_csv)
    trades = pd.read_csv(source_path)
    store = HistoricalDataStore(ohlcv_db_path)
    tagged = tag_trades_with_distday(trades, store, threshold=dist_day_threshold)
    cohort = cohort_comparison(tagged)
    window_1_loser_flag_rate = _window_1_loser_flag_rate(tagged)
    window_3_false_positive = _window_3_false_positive(tagged)
    verdicts = _verdicts(cohort, window_3_false_positive)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{output_prefix}_report.json"
    md_path = out_dir / f"{output_prefix}_report.md"
    csv_path = out_dir / f"{output_prefix}_enriched_trades.csv"
    tagged.to_csv(csv_path, index=False, encoding="utf-8-sig")
    report = DistDayReport(
        source_csv=str(source_path),
        artifact_json=str(json_path),
        artifact_md=str(md_path),
        enriched_csv=str(csv_path),
        verdicts=verdicts,
        window_1_loser_flag_rate=window_1_loser_flag_rate,
        cohort_comparison=cohort,
        window_3_false_positive=window_3_false_positive,
    )
    _write_report(report, json_path, md_path)
    return report


def tag_trades_with_distday(trades: pd.DataFrame, store: HistoricalDataStore, *, threshold: int = DIST_DAY_THRESHOLD) -> pd.DataFrame:
    out = trades.copy()
    cache: dict[str, dict[str, Any]] = {}
    rows = []
    for row in out.to_dict("records"):
        entry_date = str(row.get("entry_date"))
        if entry_date not in cache:
            cache[entry_date] = distday_state_as_of(store, entry_date, threshold=threshold)
        item = dict(row)
        item.update(cache[entry_date])
        rows.append(item)
    return pd.DataFrame(rows)


def distday_state_as_of(store: HistoricalDataStore, entry_date: str, *, threshold: int = DIST_DAY_THRESHOLD) -> dict[str, Any]:
    bars = store.get_ohlcv_as_of("TAIEX", entry_date, 30)
    count = distribution_day_count(bars)
    distribution_today = bool(_distribution_day_flags(bars).iloc[-1]) if len(bars) >= 2 else False
    return {
        "distribution_day": distribution_today,
        "dist_day_count_25": count,
        "dist_risk_off": count >= threshold,
    }


def distribution_day_count(bars: pd.DataFrame) -> int:
    flags = _distribution_day_flags(bars)
    if flags.empty:
        return 0
    return int(flags.tail(25).sum())


def cohort_comparison(trades: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in dict.fromkeys(trades["window"].tolist()):
        frame = trades[trades["window"] == window]
        plain = frame[frame["regime_bucket_at_entry"] == "risk_on"]
        kept = plain[plain["dist_risk_off"] == False]  # noqa: E712
        removed = plain[plain["dist_risk_off"] == True]  # noqa: E712
        rows.append(
            {
                "window": window,
                "plain_risk_on": metrics_dict(plain),
                "risk_on_not_dist_risk_off": metrics_dict(kept),
                "dist_removed_from_risk_on": metrics_dict(removed),
                "removed_count": int(len(removed)),
                "removed_fraction": round(float(len(removed) / len(plain)), 4) if len(plain) else 0.0,
            }
        )
    return rows


def metrics_dict(frame: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(frame["net_return_pct"], errors="coerce").dropna()
    if returns.empty:
        return {"n": 0, "win_rate": 0.0, "profit_factor": 0.0, "avg_return": 0.0, "sum_return": 0.0}
    gross_profit = float(returns[returns > 0].sum())
    gross_loss = abs(float(returns[returns < 0].sum()))
    pf = float("inf") if gross_loss == 0 and gross_profit > 0 else (gross_profit / gross_loss if gross_loss > 0 else 0.0)
    return {
        "n": int(len(returns)),
        "win_rate": round(float((returns > 0).mean()), 4),
        "profit_factor": round(pf, 4) if pf != float("inf") else pf,
        "avg_return": round(float(returns.mean()), 4),
        "sum_return": round(float(returns.sum()), 4),
    }


def _distribution_day_flags(bars: pd.DataFrame) -> pd.Series:
    if bars.empty or len(bars) < 2:
        return pd.Series(dtype=bool)
    close = pd.to_numeric(bars["close"], errors="coerce")
    volume = pd.to_numeric(bars["volume"], errors="coerce")
    return (close.pct_change() <= -0.002) & (volume > volume.shift(1))


def _window_1_loser_flag_rate(trades: pd.DataFrame) -> dict[str, Any]:
    frame = trades[(trades["window"] == "window_1") & (trades["regime_bucket_at_entry"] == "risk_on")]
    losers = frame[pd.to_numeric(frame["net_return_pct"], errors="coerce") < 0]
    flagged = losers[losers["dist_risk_off"] == True]  # noqa: E712
    return {
        "window": "window_1",
        "risk_on_losers": int(len(losers)),
        "flagged_losers": int(len(flagged)),
        "flagged_loser_fraction": round(float(len(flagged) / len(losers)), 4) if len(losers) else 0.0,
    }


def _window_3_false_positive(trades: pd.DataFrame) -> dict[str, Any]:
    frame = trades[(trades["window"] == "window_3") & (trades["regime_bucket_at_entry"] == "risk_on")]
    kept = frame[frame["dist_risk_off"] == False]  # noqa: E712
    removed = frame[frame["dist_risk_off"] == True]  # noqa: E712
    return {
        "window": "window_3",
        "risk_on_total": int(len(frame)),
        "removed_count": int(len(removed)),
        "removed_fraction": round(float(len(removed) / len(frame)), 4) if len(frame) else 0.0,
        "kept": metrics_dict(kept),
        "removed": metrics_dict(removed),
    }


def _verdicts(cohort: list[dict[str, Any]], window_3_false_positive: dict[str, Any]) -> dict[str, bool]:
    by_window = {row["window"]: row for row in cohort}
    window_1 = by_window.get("window_1", {})
    plain_1 = window_1.get("plain_risk_on", {})
    kept_1 = window_1.get("risk_on_not_dist_risk_off", {})
    plain_pf = float(plain_1.get("profit_factor", 0.0))
    kept_pf = float(kept_1.get("profit_factor", 0.0))
    distday_rescues_window1 = kept_pf > plain_pf * 1.5 and kept_pf > 0.75
    kept_3_pf = float(window_3_false_positive.get("kept", {}).get("profit_factor", 0.0))
    removed_fraction = float(window_3_false_positive.get("removed_fraction", 0.0))
    distday_preserves_window3 = kept_3_pf >= 2.0 and removed_fraction <= 0.25
    return {
        "distday_rescues_window1": bool(distday_rescues_window1),
        "distday_preserves_window3": bool(distday_preserves_window3),
        "distday_wiring_justified": bool(distday_rescues_window1 and distday_preserves_window3),
    }


def _write_report(report: DistDayReport, json_path: Path, md_path: Path) -> None:
    payload = {
        "source_csv": report.source_csv,
        "enriched_csv": report.enriched_csv,
        "verdicts": report.verdicts,
        "window_1_loser_flag_rate": report.window_1_loser_flag_rate,
        "cohort_comparison": report.cohort_comparison,
        "window_3_false_positive": report.window_3_false_positive,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# CAN SLIM Distribution-Day Diagnostic Report",
        "",
        f"Source CSV: `{report.source_csv}`",
        f"Enriched CSV: `{report.enriched_csv}`",
        "",
        f"Verdicts: `{report.verdicts}`",
        "",
        f"Window 1 loser flag rate: `{report.window_1_loser_flag_rate}`",
        "",
        "## Cohort Comparison",
        _cohort_table(report.cohort_comparison),
        "",
        f"Window 3 false positive: `{report.window_3_false_positive}`",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cohort_table(rows: list[dict[str, Any]]) -> str:
    headers = ["window", "plain_n", "plain_pf", "kept_n", "kept_pf", "removed_n", "removed_pf", "removed_fraction"]
    body = []
    for row in rows:
        body.append(
            {
                "window": row["window"],
                "plain_n": row["plain_risk_on"]["n"],
                "plain_pf": row["plain_risk_on"]["profit_factor"],
                "kept_n": row["risk_on_not_dist_risk_off"]["n"],
                "kept_pf": row["risk_on_not_dist_risk_off"]["profit_factor"],
                "removed_n": row["dist_removed_from_risk_on"]["n"],
                "removed_pf": row["dist_removed_from_risk_on"]["profit_factor"],
                "removed_fraction": row["removed_fraction"],
            }
        )
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    lines = ["| " + " | ".join(str(row[h]) for h in headers) + " |" for row in body]
    return "\n".join([header, sep, *lines])
