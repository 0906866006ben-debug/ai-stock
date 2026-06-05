"""Crash-resilience cohort (Path B validation — MEASUREMENT ONLY).

Tests the core durability thesis the user holds ("buy companies that durably make money;
crashes are cyclical and don't negate a good company; add at lows"): across major TW crashes,
do PRE-CRASH durable-quality stocks (Q1 by Composite Durability Score) actually show SMALLER
drawdown, FASTER recovery, and NEAR-ZERO delisting vs junk (Q5)?

Per crash event: at T0 (onset) sort the survivorship universe (incl. delisted — required for
the delisting-rate metric) into durability quintiles Q1..Q5, then measure each name's
T0->trough drawdown, days-to-recovery (first close >= T0 close), and delisting/permanent-
impairment. PIT-safe: durability uses only data <= T0; forward prices only measure outcomes.
No buy/sell output — this validates the screen, it does not trade.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.backtest.historical_data_store import CachedHistoricalDataStore, DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import CachedPitFundamentalsStore, DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.durability import compute_durability
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pit_inputs import build_pit_inputs
from backend.app.services.strategy.canslim.quarterly_backtest import _close_series

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrashEvent:
    name: str
    t0: str            # crash onset (durability measured as-of here)
    trough_end: str    # search window end for the trough (min TAIEX close in [t0, trough_end])
    recovery_end: str  # deadline to recover back to the T0 price


@dataclass(frozen=True)
class Quintile:
    name: str
    symbols: list[str]


# Major TW crashes (user-chosen). T0 = onset; trough searched to trough_end; recovery deadline.
CRASH_EVENTS: tuple[CrashEvent, ...] = (
    CrashEvent("2011_h2",     "2011-06-01", "2011-09-30", "2012-03-31"),
    CrashEvent("2015_h2",     "2015-08-01", "2015-09-30", "2015-12-31"),
    CrashEvent("2018_q4",     "2018-10-01", "2018-12-31", "2019-04-30"),
    CrashEvent("2020_covid",  "2020-03-01", "2020-03-31", "2020-06-30"),
    CrashEvent("2022_rates",  "2022-01-01", "2022-11-30", "2023-03-31"),
)


def quintile_sort_at_date(
    universe: list[str],
    durability_scores: dict[str, float | int | None],
    *,
    quintiles: int = 5,
) -> list[Quintile]:
    """Sort symbols into durability quintiles, with Q1 = highest score."""
    rows = [
        {"stock_id": str(symbol), "durability": float(score)}
        for symbol in universe
        if (score := durability_scores.get(str(symbol))) is not None
    ]
    if not rows:
        return []
    df = pd.DataFrame(rows)
    labels = [f"Q{i}" for i in range(1, quintiles + 1)]
    try:
        df["quintile"] = pd.qcut(
            df["durability"].rank(method="first", ascending=False),
            quintiles,
            labels=labels,
        ).astype(str)
    except ValueError:
        df["quintile"] = labels[0]
    out: list[Quintile] = []
    for label in labels:
        symbols = df[df["quintile"] == label]["stock_id"].astype(str).tolist()
        out.append(Quintile(label, symbols))
    return out


def measure_mdd(close_series_t0_to_trough: pd.Series) -> float | None:
    """Maximum drawdown from the first close to the minimum close in the series."""
    series = pd.to_numeric(close_series_t0_to_trough, errors="coerce").dropna()
    if series.empty:
        return None
    entry = float(series.iloc[0])
    if entry <= 0:
        return None
    return float(series.min()) / entry - 1.0


def measure_recovery_days(
    close_series_trough_onward: pd.Series,
    *,
    target_close: float,
    trough_date: str,
) -> int | None:
    """Trading sessions after trough until first close >= target_close, or None."""
    if close_series_trough_onward is None or close_series_trough_onward.empty or target_close <= 0:
        return None
    series = pd.to_numeric(close_series_trough_onward, errors="coerce").dropna()
    if series.empty:
        return None

    trough_ts = pd.Timestamp(trough_date)
    trading_day = 0
    for idx, close in series.items():
        try:
            if pd.Timestamp(str(idx)) <= trough_ts:
                continue
        except Exception:
            pass
        trading_day += 1
        if float(close) >= float(target_close):
            return trading_day
    return None


def measure_delisting_rate(
    quintile_symbols: list[str],
    store,
    as_of_t0: str,
    window_end: str,
    *,
    staleness_days: int = 20,
) -> float:
    """Fraction of symbols whose last available bar is stale before window_end."""
    if not quintile_symbols:
        return 0.0
    delisted = 0
    for symbol in quintile_symbols:
        series = _close_series(store, str(symbol), as_of_t0, window_end, lookback=1000)
        if series is None or series.empty:
            delisted += 1
            continue
        last_date = str(series.index[-1])
        if (pd.Timestamp(window_end) - pd.Timestamp(last_date)).days > staleness_days:
            delisted += 1
    return delisted / len(quintile_symbols)


def run_crash_resilience(
    *,
    run_id: str = "crash_resilience",
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    candidate_symbols: list[str] | None = None,
    events: tuple[CrashEvent, ...] = CRASH_EVENTS,
    impair_threshold: float = 0.5,     # close stays < T0*this through recovery_end -> impaired
    staleness_days: int = 20,          # last bar this far before recovery_end -> stopped trading
    output_dir: Path | str = "artifacts/canslim_crash_resilience",
) -> dict[str, Any]:
    started = time.time()
    out_dir = Path(output_dir); out_dir.mkdir(parents=True, exist_ok=True)
    from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
    candidates = candidate_symbols or fundamentals_covered_symbols(pit_db_path)
    params = load_params()
    span_start = min(e.t0 for e in events)
    span_end = max(e.recovery_end for e in events)
    logger.info("crash-resilience %s: %d candidates, span %s..%s", run_id, len(candidates), span_start, span_end)

    data_store = CachedHistoricalDataStore(
        ohlcv_db_path, universe=[*candidates, "TAIEX"],
        start_date=span_start, end_date=span_end, lookback_buffer_days=400, forward_buffer_days=40,
    )
    pit_store = CachedPitFundamentalsStore(pit_db_path, universe=candidates)

    per_event: dict[str, Any] = {}
    pooled_rows: list[dict[str, Any]] = []
    for ev in events:
        rows = _event_rows(data_store, pit_store, params, candidates, ev, impair_threshold, staleness_days)
        if not rows:
            logger.warning("event %s: no rows", ev.name)
            continue
        df = pd.DataFrame(rows)
        df["quintile"] = _quintiles(df["durability"])
        event_summary = _summarize(df)
        per_event[ev.name] = event_summary
        df["event"] = ev.name
        pooled_rows.append(df)
        df.to_csv(out_dir / f"rows_{ev.name}.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(_summary_rows(event_summary)).to_csv(
            out_dir / f"event_{ev.name}.csv",
            index=False,
            encoding="utf-8-sig",
        )
        (out_dir / f"quintile_stocks_{ev.name}.json").write_text(
            json.dumps(_quintile_symbols(df), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("event %s: %d names scored, trough=%s", ev.name, len(df), per_event[ev.name]["trough_date"])

    pooled = pd.concat(pooled_rows, ignore_index=True) if pooled_rows else pd.DataFrame()
    pooled_summary = _summarize(pooled) if not pooled.empty else {}
    verdict = _decision_gate(per_event, pooled_summary, expected_event_count=len(events))
    report = {
        "run_id": run_id, "elapsed_seconds": round(time.time() - started, 1),
        "events": per_event,
        "pooled": pooled_summary,
        "decision_gate": verdict,
    }
    if not pooled.empty:
        pooled.to_csv(out_dir / "crash_rows.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(_summary_rows(pooled_summary)).to_csv(out_dir / "pooled_summary.csv", index=False, encoding="utf-8-sig")
    (out_dir / "crash_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "crash_summary.md").write_text(_markdown(report), encoding="utf-8")
    (out_dir / "pooled_summary.md").write_text(_pooled_markdown(report), encoding="utf-8")
    return report


def _event_rows(data_store, pit_store, params, candidates, ev: CrashEvent, impair_thr, staleness_days) -> list[dict[str, Any]]:
    trough_date = _trough_date(data_store, ev.t0, ev.trough_end)
    recovery_window_days = _event_recovery_window_trading_days(data_store, ev, trough_date)
    rows: list[dict[str, Any]] = []
    for sym in candidates:
        dur = _durability_at(pit_store, str(sym), ev.t0, params)
        if dur is None:
            continue
        metrics = symbol_crash_metrics(
            data_store,
            str(sym),
            ev,
            trough_date,
            impair_thr,
            staleness_days,
            event_recovery_window_trading_days=recovery_window_days,
        )
        if metrics is None:
            continue
        rows.append({"stock_id": str(sym), "durability": dur, "trough_date": trough_date, **metrics})
    return rows


def _durability_at(pit_store, sym: str, t0: str, params) -> int | None:
    try:
        fin = pit_store.get_financials_as_of(sym, t0, limit=20)
        bs = pit_store.get_balance_sheet_as_of(sym, t0, limit=8)
        cf = pit_store.get_cash_flow_as_of(sym, t0, limit=12) if hasattr(pit_store, "get_cash_flow_as_of") else None
        detail, fin_metrics, _ = build_pit_inputs(sym, t0, pit_store)
    except Exception:
        return None
    res = compute_durability(fin_metrics=fin_metrics, detail=detail, financials=fin,
                             balance_sheet=bs, params=params, cash_flow=cf)
    # Require a meaningfully-scored name (enough components), else skip (no fabrication).
    if not res.components or len(res.missing) >= 5:
        return None
    return res.score


def symbol_crash_metrics(
    store,
    sym: str,
    ev: CrashEvent,
    trough_date: str,
    impair_thr: float,
    staleness_days: int,
    *,
    event_recovery_window_trading_days: int | None = None,
) -> dict[str, Any] | None:
    """T0->trough drawdown, days-to-recovery (first close >= T0 close after trough), and
    delisting/permanent-impairment. None when there's no usable T0 price."""
    series = _close_series(store, sym, ev.t0, ev.recovery_end, lookback=1000)
    if series is None or series.empty:
        return None
    entry = float(series.iloc[0])
    if entry <= 0:
        return None
    pre = series[series.index <= trough_date]
    drawdown = measure_mdd(pre)
    if drawdown is None:
        drawdown = 0.0
    post = series[series.index > trough_date]
    recovery_days = measure_recovery_days(post, target_close=entry, trough_date=trough_date)
    recovered = recovery_days is not None
    last_date = str(series.index[-1])
    delisted = (pd.Timestamp(ev.recovery_end) - pd.Timestamp(last_date)).days > staleness_days
    impaired = (not recovered) and (float(series.iloc[-1]) < entry * impair_thr)
    recovery_window_trading_days = (
        int(event_recovery_window_trading_days)
        if event_recovery_window_trading_days is not None
        else int(len(post))
    )
    return {
        "drawdown": round(drawdown, 4),
        "recovered": recovered,
        "recovery_days": recovery_days,
        "recovery_window_trading_days": recovery_window_trading_days,
        "delisted": bool(delisted),
        "impaired": bool(impaired or delisted),
    }


def _trough_date(store, t0: str, trough_end: str) -> str:
    s = _close_series(store, "TAIEX", t0, trough_end, lookback=400)
    if s is None or s.empty:
        return trough_end
    return str(s.idxmin())


def _event_recovery_window_trading_days(store, ev: CrashEvent, trough_date: str) -> int:
    series = _close_series(store, "TAIEX", trough_date, ev.recovery_end, lookback=1000)
    if series is None or series.empty:
        return 0
    return int(len(series[series.index > trough_date]))


def _quintiles(scores: pd.Series) -> pd.Series:
    """Q1 = highest durability ... Q5 = lowest. Falls back to rank-based cut on ties."""
    try:
        q = pd.qcut(scores.rank(method="first", ascending=False), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
        return q.astype(str)
    except ValueError:
        return pd.Series(["Q1"] * len(scores), index=scores.index)


def _summarize(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "trough_date" in df.columns and not df.empty:
        out["trough_date"] = str(df["trough_date"].iloc[0])
    by_q: dict[str, Any] = {}
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        g = df[df["quintile"] == q]
        if g.empty:
            continue
        rec = g[g["recovered"]]
        recovery_values = pd.to_numeric(rec["recovery_days"], errors="coerce").dropna() if not rec.empty else pd.Series(dtype=float)
        effective_recovery_values = _effective_recovery_days(g)
        by_q[q] = {
            "n": int(len(g)),
            "median_durability": round(float(g["durability"].median()), 1),
            "mean_drawdown": round(float(g["drawdown"].mean()), 4),
            "median_drawdown": round(float(g["drawdown"].median()), 4),
            "std_drawdown": round(float(g["drawdown"].std(ddof=0)), 4) if len(g) > 1 else 0.0,
            "pct_recovered": round(float(g["recovered"].mean()), 3),
            "mean_recovery_days": (round(float(recovery_values.mean()), 1) if not recovery_values.empty else None),
            "median_recovery_days": (int(recovery_values.median()) if not recovery_values.empty else None),
            "mean_effective_recovery_days": (
                round(float(effective_recovery_values.mean()), 1) if not effective_recovery_values.empty else None
            ),
            "median_effective_recovery_days": (
                int(effective_recovery_values.median()) if not effective_recovery_values.empty else None
            ),
            "delisting_rate": round(float(g["delisted"].mean()), 4),
            "impairment_rate": round(float(g["impaired"].mean()), 4),
        }
    out["by_quintile"] = by_q
    if "Q1" in by_q and "Q5" in by_q:
        q1_mean_rec = by_q["Q1"]["mean_effective_recovery_days"]
        q5_mean_rec = by_q["Q5"]["mean_effective_recovery_days"]
        recovery_reduction = None
        if q1_mean_rec is not None and q5_mean_rec not in (None, 0):
            recovery_reduction = round((float(q5_mean_rec) - float(q1_mean_rec)) / float(q5_mean_rec), 3)
        out["Q1_vs_Q5"] = {
            "drawdown_gap": round(by_q["Q1"]["median_drawdown"] - by_q["Q5"]["median_drawdown"], 4),
            "mean_drawdown_gap": round(by_q["Q1"]["mean_drawdown"] - by_q["Q5"]["mean_drawdown"], 4),
            "recovered_gap": round(by_q["Q1"]["pct_recovered"] - by_q["Q5"]["pct_recovered"], 3),
            "impairment_gap": round(by_q["Q1"]["impairment_rate"] - by_q["Q5"]["impairment_rate"], 4),
            "recovery_days_reduction": recovery_reduction,
        }
    return out


def _effective_recovery_days(group: pd.DataFrame) -> pd.Series:
    """Recovery duration with unrecovered names carried to the window deadline."""
    if group.empty:
        return pd.Series(dtype=float)
    if "recovery_days" not in group.columns:
        return pd.Series(dtype=float)
    recovered_days = pd.to_numeric(group["recovery_days"], errors="coerce")
    if "recovery_window_trading_days" not in group.columns:
        return recovered_days.dropna()
    window_days = pd.to_numeric(group["recovery_window_trading_days"], errors="coerce")
    effective = recovered_days.where(recovered_days.notna(), window_days)
    return effective.dropna()


def _summary_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        m = summary.get("by_quintile", {}).get(q)
        if not m:
            continue
        rows.append({"quintile": q, **m})
    return rows


def _quintile_symbols(df: pd.DataFrame) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        out[q] = df[df["quintile"] == q]["stock_id"].astype(str).tolist()
    return out


def _decision_gate(
    events: dict[str, Any],
    pooled: dict[str, Any],
    *,
    expected_event_count: int | None = None,
) -> dict[str, Any]:
    event_gaps = [
        float(summ.get("Q1_vs_Q5", {}).get("mean_drawdown_gap"))
        for summ in events.values()
        if summ.get("Q1_vs_Q5", {}).get("mean_drawdown_gap") is not None
    ]
    avg_drawdown_gap = round(float(pd.Series(event_gaps).mean()), 4) if event_gaps else None

    q1 = pooled.get("by_quintile", {}).get("Q1", {})
    q5 = pooled.get("by_quintile", {}).get("Q5", {})
    q1_recovery = q1.get("mean_effective_recovery_days")
    q5_recovery = q5.get("mean_effective_recovery_days")
    recovery_reduction = None
    if q1_recovery is not None and q5_recovery not in (None, 0):
        recovery_reduction = round((float(q5_recovery) - float(q1_recovery)) / float(q5_recovery), 3)

    q1_delist = q1.get("delisting_rate")
    q5_delist = q5.get("delisting_rate")
    event_checks = _event_directional_checks(events)
    checks = {
        "event_coverage": bool(expected_event_count is None or len(events) == expected_event_count),
        "event_directional": bool(event_checks and all(item["pass"] for item in event_checks.values())),
        "mdd_spread": bool(avg_drawdown_gap is not None and avg_drawdown_gap >= 0.10),
        "recovery_faster": bool(recovery_reduction is not None and recovery_reduction >= 0.30),
        "delisting_rate": bool(q1_delist is not None and q5_delist is not None and float(q1_delist) < 0.05 and float(q5_delist) > 0.10),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "thresholds": {
            "avg_q1_q5_mean_mdd_gap_min": 0.10,
            "q1_recovery_days_reduction_min": 0.30,
            "q1_delisting_rate_max": 0.05,
            "q5_delisting_rate_min": 0.10,
        },
        "event_checks": event_checks,
        "metrics": {
            "avg_q1_q5_mean_mdd_gap": avg_drawdown_gap,
            "q1_effective_recovery_days": q1_recovery,
            "q5_effective_recovery_days": q5_recovery,
            "q1_recovery_days_reduction": recovery_reduction,
            "q1_delisting_rate": q1_delist,
            "q5_delisting_rate": q5_delist,
        },
    }


def _event_directional_checks(events: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, summ in events.items():
        q1 = summ.get("by_quintile", {}).get("Q1", {})
        q5 = summ.get("by_quintile", {}).get("Q5", {})
        q1_vs_q5 = summ.get("Q1_vs_Q5", {})
        drawdown_gap = q1_vs_q5.get("mean_drawdown_gap")
        recovery_reduction = q1_vs_q5.get("recovery_days_reduction")
        q1_delist = q1.get("delisting_rate")
        q5_delist = q5.get("delisting_rate")
        checks = {
            "drawdown_direction": bool(drawdown_gap is not None and float(drawdown_gap) >= 0.0),
            "recovery_direction": bool(recovery_reduction is not None and float(recovery_reduction) >= 0.0),
            "delisting_direction": bool(
                q1_delist is not None and q5_delist is not None and float(q1_delist) <= float(q5_delist)
            ),
        }
        out[name] = {"pass": all(checks.values()), "checks": checks}
    return out


def _markdown(report: dict[str, Any]) -> str:
    lines = [f"# Crash-resilience cohort: {report['run_id']}", f"\n{report['elapsed_seconds']}s\n",
             "Hypothesis: Q1 (durable) shows smaller drawdown, faster recovery, ~0 delisting vs Q5 (junk).\n"]

    def _table(title: str, summ: dict[str, Any]) -> list[str]:
        ls = [f"## {title}" + (f" (trough {summ.get('trough_date','-')})" if summ.get("trough_date") else ""),
              "| Q | n | medDurab | medDD | %recov | medEffRecovD | delist% | impair% |",
              "|---|---|---|---|---|---|---|---|"]
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            m = summ.get("by_quintile", {}).get(q)
            if not m:
                continue
            median_effective = "-" if m["median_effective_recovery_days"] is None else m["median_effective_recovery_days"]
            ls.append(f"| {q} | {m['n']} | {m['median_durability']} | {m['median_drawdown']:+.1%} | "
                      f"{m['pct_recovered']:.0%} | {median_effective} | {m['delisting_rate']:.1%} | {m['impairment_rate']:.1%} |")
        vs = summ.get("Q1_vs_Q5")
        if vs:
            ls.append(f"\n**Q1−Q5**: drawdown gap {vs['drawdown_gap']:+.1%} (Q1 should be less negative), "
                      f"recovered gap {vs['recovered_gap']:+.0%}, impairment gap {vs['impairment_gap']:+.1%}.\n")
        return ls

    gate = report.get("decision_gate") or {}
    if gate:
        lines.append(f"## Decision gate\n\n**Verdict: {gate.get('status', 'UNKNOWN')}**\n")
        metrics = gate.get("metrics", {})
        lines.append(
            f"- Avg Q1−Q5 mean MDD gap: {metrics.get('avg_q1_q5_mean_mdd_gap')}\n"
            f"- Recovery reduction: {metrics.get('q1_recovery_days_reduction')}\n"
            f"- Delisting rates: Q1={metrics.get('q1_delisting_rate')}, Q5={metrics.get('q5_delisting_rate')}\n"
        )
    if report.get("pooled"):
        lines += _table("POOLED (all events)", report["pooled"])
    for name, summ in report.get("events", {}).items():
        lines += _table(name, summ)
    return "\n".join(lines) + "\n"


def _pooled_markdown(report: dict[str, Any]) -> str:
    pooled = report.get("pooled") or {}
    gate = report.get("decision_gate") or {}
    lines = [
        "# Crash-Resilience Results (Pooled Across 5 Events)",
        "",
        f"Verdict: **{gate.get('status', 'UNKNOWN')}**",
        "",
        "| Quintile | n | Mean_MDD | Median_MDD | Std_MDD | Mean_EffectiveRecoveryDays | % Recovered | Delisting_Rate | Impairment_Rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        m = pooled.get("by_quintile", {}).get(q)
        if not m:
            continue
        mean_rec = "-" if m["mean_effective_recovery_days"] is None else m["mean_effective_recovery_days"]
        lines.append(
            f"| {q} | {m['n']} | {m['mean_drawdown']:+.1%} | {m['median_drawdown']:+.1%} | "
            f"{m['std_drawdown']:.1%} | {mean_rec} | {m['pct_recovered']:.0%} | "
            f"{m['delisting_rate']:.1%} | {m['impairment_rate']:.1%} |"
        )
    if gate:
        checks = gate.get("checks", {})
        metrics = gate.get("metrics", {})
        lines.extend([
            "",
            "## Decision Gate",
            "",
            f"- MDD spread: {'PASS' if checks.get('mdd_spread') else 'FAIL'} "
            f"(avg Q1−Q5 mean gap {metrics.get('avg_q1_q5_mean_mdd_gap')})",
            f"- Recovery speed: {'PASS' if checks.get('recovery_faster') else 'FAIL'} "
            f"(Q1 reduction {metrics.get('q1_recovery_days_reduction')})",
            f"- Delisting rate: {'PASS' if checks.get('delisting_rate') else 'FAIL'} "
            f"(Q1 {metrics.get('q1_delisting_rate')}, Q5 {metrics.get('q5_delisting_rate')})",
        ])
    return "\n".join(lines) + "\n"
