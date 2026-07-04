"""Aggregate events.csv into a small static JSON for the frontend backtest dashboard.

Reads:  backend/data/backtest/opps_v2/events.csv
Writes: ai-stock-frontend/public/backtest_dashboard.json  (<300KB, static — no PII, no raw rows)

Benchmark definitions (see backend/scripts/run_opportunities_backtest.py):
  - excu_N = 選股力: stock return minus same-day BUYABLE-UNIVERSE MEDIAN forward return
             over the same window (the honest yardstick for stock-selection skill).
  - exc_N  = 脈絡參考: stock return minus TAIEX (cap-weighted index) over the same window.
  Both are surfaced side-by-side in the UI; they answer different questions and are
  not interchangeable (see Docs/backtest/experiments_ledger.md Iteration 1/1b).

Honesty caveats baked into `meta.caveats` (do not remove without re-reading the ledger):
  - OOS (2022-01-01..) was opened once on 2026-07-02; no further rule changes may claim
    validation against the same OOS window.
  - Selection-skill numbers are likely slightly overstated: delisted-stock coverage is
    partial (~184 tickers, survivorship bias) and prices are not dividend-adjusted
    (this cuts the other way — conservative).

Run:  .venv/Scripts/python.exe backend/scripts/export_backtest_dashboard_data.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "backend" / "data" / "backtest" / "opps_v2" / "events.csv"
OUT = ROOT / "ai-stock-frontend" / "public" / "backtest_dashboard.json"

WINDOWS = [5, 20, 60, 120, 250]
DEV_END = "2021-12-31"
OOS_START = "2022-01-01"
BUCKET_LABEL = {"long": "長線價值桶"}
BUCKET_STATUS = {"long": "production"}
GRADES = ["S", "A", "B", "C"]


def window_stats(sub: pd.DataFrame, w: int) -> dict:
    excu = sub[f"excu_{w}"].dropna()
    exc = sub[f"exc_{w}"].dropna()

    def pack(s: pd.Series) -> dict | None:
        if len(s) == 0:
            return None
        return {
            "median": round(float(s.median()), 4),
            "win_rate": round(float((s > 0).mean()), 4),
            "n": int(len(s)),
        }

    # `n_signals`: all events in this grade/period slice (regardless of whether this
    # window has matured yet); `excu.n` / `exc.n`: matured-and-non-null count actually
    # used for the median/win-rate above. Near the OOS edge these can differ (T+250
    # needs ~1yr of runway past signal_date, so recent oos events aren't matured yet).
    return {"excu": pack(excu), "exc": pack(exc), "n_signals": int(len(sub))}


def build_grade_periods(sub: pd.DataFrame) -> dict:
    """{period -> {window -> stats}} for one bucket/grade slice."""
    out = {}
    for period, lo, hi in [("dev", "2000-01-01", DEV_END), ("oos", OOS_START, "2100-01-01")]:
        psub = sub[(sub.signal_date >= lo) & (sub.signal_date <= hi)]
        if len(psub) == 0:
            continue
        out[period] = {str(w): window_stats(psub, w) for w in WINDOWS}
    return out


def build_yearly(sub: pd.DataFrame, window: int = 60) -> list[dict]:
    """Per-year median/win/n of excu_{window} for grades S+A (the validated cohort)."""
    ab = sub[sub.grade.isin(["S", "A"])].copy()
    if len(ab) == 0:
        return []
    ab["year"] = ab.signal_date.str[:4]
    rows = []
    for year, g in ab.groupby("year"):
        e = g[f"excu_{window}"].dropna()
        if len(e) == 0:
            continue
        rows.append({
            "year": year,
            "n": int(len(e)),
            "median_excu": round(float(e.median()), 4),
            "win_rate": round(float((e > 0).mean()), 4),
        })
    return sorted(rows, key=lambda r: r["year"])


def build_yearly_counts(sub: pd.DataFrame) -> list[dict]:
    """Per-year event count, all grades — for the '每年事件數' chart."""
    s = sub.copy()
    s["year"] = s.signal_date.str[:4]
    rows = []
    for year, g in s.groupby("year"):
        by_grade = {gr: int((g.grade == gr).sum()) for gr in GRADES if (g.grade == gr).any()}
        rows.append({"year": year, "n": int(len(g)), "by_grade": by_grade})
    return sorted(rows, key=lambda r: r["year"])


def build_histogram(sub: pd.DataFrame, window: int = 250, n_bins: int = 24) -> dict | None:
    """Raw (non-excess) forward-return distribution for grades S/A/B, full sample."""
    r = sub[sub.grade.isin(["S", "A", "B"])][f"ret_{window}"].dropna()
    if len(r) == 0:
        return None
    lo, hi = float(np.percentile(r, 1)), float(np.percentile(r, 99))
    lo, hi = min(lo, -0.1), max(hi, 0.1)  # ensure both tails are represented
    edges = np.linspace(lo, hi, n_bins + 1)
    counts, edges = np.histogram(r.clip(lo, hi), bins=edges)
    bins = []
    for i, c in enumerate(counts):
        mid = (edges[i] + edges[i + 1]) / 2
        bins.append({
            "lo": round(float(edges[i]), 4),
            "hi": round(float(edges[i + 1]), 4),
            "count": int(c),
            "is_loss": bool(mid < 0),
        })
    return {
        "window": window,
        "n": int(len(r)),
        "median": round(float(r.median()), 4),
        "mean": round(float(r.mean()), 4),
        "win_rate": round(float((r > 0).mean()), 4),
        "bins": bins,
    }


def main() -> None:
    print(f"loading {EVENTS} ...")
    ev = pd.read_csv(EVENTS, dtype={"stock_id": str})

    buckets_out = {}
    yearly_out = {}
    yearly_counts_out = {}
    histogram_out = {}

    # 中線桶已退役且依使用者要求不再出現於儀表板（歷史數據仍在 events.csv 與總帳）。
    for bucket in ["long"]:
        b = ev[ev.bucket == bucket]
        grades_out = {}
        for grade in GRADES:
            g = b[b.grade == grade]
            if len(g) == 0:
                continue
            periods = build_grade_periods(g)
            if periods:
                grades_out[grade] = periods
        buckets_out[bucket] = {
            "label": BUCKET_LABEL[bucket],
            "status": BUCKET_STATUS[bucket],
            "n_total": int(len(b)),
            "grades": grades_out,
        }
        yearly_out[bucket] = build_yearly(b, window=60)
        yearly_counts_out[bucket] = build_yearly_counts(b)
        histogram_out[bucket] = build_histogram(b, window=250)

    # Headline: long bucket, grade A, T+250 — matches summary_dev.md / summary_oos.md
    long_a = ev[(ev.bucket == "long") & (ev.grade == "A")]
    long_a_dev = long_a[long_a.signal_date <= DEV_END]
    long_a_oos = long_a[long_a.signal_date >= OOS_START]
    headline = {
        "bucket": "long",
        "grade": "A",
        "window": 250,
        "dev": window_stats(long_a_dev, 250)["excu"],
        "oos": window_stats(long_a_oos, 250)["excu"],
    }

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meta": {
            "windows": WINDOWS,
            "dev_range": ["2012-01-01", DEV_END],
            "oos_range": [OOS_START, "2026-06-30"],
            "round_trip_cost_bps": 58.5,
            "benchmarks": {
                "excu": "vs 可買池中位數（選股力）",
                "exc": "vs TAIEX 大盤（脈絡參考，市值加權，僅供脈絡對照）",
            },
            "caveats": [
                "OOS（2022-01-01 起）已於 2026-07-02 開封一次；此後任何規則變更不得再以同一 OOS 期間宣稱驗證。",
                "選股力數字可能輕微高估：下市股票覆蓋僅約 184 檔（生存者偏誤，高估向），"
                "價格未還原除息（保守向，部分抵銷上述高估）。",
                "「vs 可買池中位（選股力）」與「vs TAIEX（脈絡參考）」是兩個不同問題——"
                "個股選股增值 vs 是否贏過大盤——兩者並陳，不可互相替代或混用。",
            ],
        },
        "headline": headline,
        "buckets": buckets_out,
        "yearly": yearly_out,
        "yearly_counts": yearly_counts_out,
        "histogram": histogram_out,
        "disclaimer": "本分析僅供參考，不構成投資建議。",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(text, encoding="utf-8")
    size_kb = len(text.encode("utf-8")) / 1024
    print(f"wrote {OUT} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
