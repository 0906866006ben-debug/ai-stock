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


# Major TW crashes (user-chosen). T0 = onset; trough searched to trough_end; recovery deadline.
CRASH_EVENTS: tuple[CrashEvent, ...] = (
    CrashEvent("2011_euro",   "2011-08-01", "2012-01-31", "2012-12-31"),
    CrashEvent("2015_china",  "2015-08-01", "2016-01-31", "2016-12-31"),
    CrashEvent("2018_q4",     "2018-10-01", "2019-01-31", "2019-12-31"),
    CrashEvent("2020_covid",  "2020-02-01", "2020-04-30", "2020-12-31"),
    CrashEvent("2022_rates",  "2022-01-01", "2022-11-30", "2023-12-31"),
)


def run_crash_resilience(
    *,
    run_id: str = "crash_resilience",
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    candidate_symbols: list[str] | None = None,
    events: tuple[CrashEvent, ...] = CRASH_EVENTS,
    impair_threshold: float = 0.5,     # close stays < T0*this through recovery_end -> impaired
    staleness_days: int = 20,          # last bar this far before recovery_end -> delisted
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
        per_event[ev.name] = _summarize(df)
        df["event"] = ev.name
        pooled_rows.append(df)
        logger.info("event %s: %d names scored, trough=%s", ev.name, len(df), per_event[ev.name]["trough_date"])

    pooled = pd.concat(pooled_rows, ignore_index=True) if pooled_rows else pd.DataFrame()
    report = {
        "run_id": run_id, "elapsed_seconds": round(time.time() - started, 1),
        "events": per_event,
        "pooled": _summarize(pooled) if not pooled.empty else {},
    }
    if not pooled.empty:
        pooled.to_csv(out_dir / "crash_rows.csv", index=False, encoding="utf-8-sig")
    (out_dir / "crash_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "crash_summary.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _event_rows(data_store, pit_store, params, candidates, ev: CrashEvent, impair_thr, staleness_days) -> list[dict[str, Any]]:
    trough_date = _trough_date(data_store, ev.t0, ev.trough_end)
    rows: list[dict[str, Any]] = []
    for sym in candidates:
        dur = _durability_at(pit_store, str(sym), ev.t0, params)
        if dur is None:
            continue
        metrics = symbol_crash_metrics(data_store, str(sym), ev, trough_date, impair_thr, staleness_days)
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


def symbol_crash_metrics(store, sym: str, ev: CrashEvent, trough_date: str, impair_thr: float, staleness_days: int) -> dict[str, Any] | None:
    """T0->trough drawdown, days-to-recovery (first close >= T0 close after trough), and
    delisting/permanent-impairment. None when there's no usable T0 price."""
    series = _close_series(store, sym, ev.t0, ev.recovery_end, lookback=1000)
    if series is None or series.empty:
        return None
    entry = float(series.iloc[0])
    if entry <= 0:
        return None
    # Drawdown from entry to the worst close up to the trough window.
    pre = series[series.index <= trough_date]
    trough_px = float(pre.min()) if not pre.empty else entry
    drawdown = trough_px / entry - 1.0
    # Recovery: first close >= entry strictly after the trough date.
    post = series[series.index > trough_date]
    recovered = False
    recovery_days = None
    if not post.empty:
        hit = post[post.values >= entry]
        if not hit.empty:
            recovered = True
            rec_date = str(hit.index[0])
            recovery_days = int((pd.Timestamp(rec_date) - pd.Timestamp(trough_date)).days)
    last_date = str(series.index[-1])
    delisted = (pd.Timestamp(ev.recovery_end) - pd.Timestamp(last_date)).days > staleness_days
    impaired = (not recovered) and (float(series.iloc[-1]) < entry * impair_thr)
    return {
        "drawdown": round(drawdown, 4),
        "recovered": recovered,
        "recovery_days": recovery_days,
        "delisted": bool(delisted),
        "impaired": bool(impaired or delisted),
    }


def _trough_date(store, t0: str, trough_end: str) -> str:
    s = _close_series(store, "TAIEX", t0, trough_end, lookback=400)
    if s is None or s.empty:
        return trough_end
    return str(s.idxmin())


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
        by_q[q] = {
            "n": int(len(g)),
            "median_durability": round(float(g["durability"].median()), 1),
            "median_drawdown": round(float(g["drawdown"].median()), 4),
            "pct_recovered": round(float(g["recovered"].mean()), 3),
            "median_recovery_days": (int(rec["recovery_days"].median()) if not rec.empty else None),
            "delisting_rate": round(float(g["delisted"].mean()), 4),
            "impairment_rate": round(float(g["impaired"].mean()), 4),
        }
    out["by_quintile"] = by_q
    if "Q1" in by_q and "Q5" in by_q:
        out["Q1_vs_Q5"] = {
            "drawdown_gap": round(by_q["Q1"]["median_drawdown"] - by_q["Q5"]["median_drawdown"], 4),
            "recovered_gap": round(by_q["Q1"]["pct_recovered"] - by_q["Q5"]["pct_recovered"], 3),
            "impairment_gap": round(by_q["Q1"]["impairment_rate"] - by_q["Q5"]["impairment_rate"], 4),
        }
    return out


def _markdown(report: dict[str, Any]) -> str:
    lines = [f"# Crash-resilience cohort: {report['run_id']}", f"\n{report['elapsed_seconds']}s\n",
             "Hypothesis: Q1 (durable) shows smaller drawdown, faster recovery, ~0 delisting vs Q5 (junk).\n"]

    def _table(title: str, summ: dict[str, Any]) -> list[str]:
        ls = [f"## {title}" + (f" (trough {summ.get('trough_date','-')})" if summ.get("trough_date") else ""),
              "| Q | n | medDurab | medDD | %recov | medRecovD | delist% | impair% |",
              "|---|---|---|---|---|---|---|---|"]
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            m = summ.get("by_quintile", {}).get(q)
            if not m:
                continue
            ls.append(f"| {q} | {m['n']} | {m['median_durability']} | {m['median_drawdown']:+.1%} | "
                      f"{m['pct_recovered']:.0%} | {m['median_recovery_days']} | {m['delisting_rate']:.1%} | {m['impairment_rate']:.1%} |")
        vs = summ.get("Q1_vs_Q5")
        if vs:
            ls.append(f"\n**Q1−Q5**: drawdown gap {vs['drawdown_gap']:+.1%} (Q1 should be less negative), "
                      f"recovered gap {vs['recovered_gap']:+.0%}, impairment gap {vs['impairment_gap']:+.1%}.\n")
        return ls

    if report.get("pooled"):
        lines += _table("POOLED (all events)", report["pooled"])
    for name, summ in report.get("events", {}).items():
        lines += _table(name, summ)
    return "\n".join(lines) + "\n"
