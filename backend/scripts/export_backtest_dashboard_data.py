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
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "backend" / "data" / "backtest" / "opps_v2" / "events.csv"
OHLCV_DB = ROOT / "backend" / "historical_data.db"
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


def build_plain(ev: pd.DataFrame) -> dict:
    """白話版：每年等權跟隨長線桶 S/A 名單，100 萬本金的逐年複利軌跡。

    三條對照線：
      strategy = ret_250 年均（已扣來回成本 58.5bp，未含股息；事件視窗拼接）
      pool     = ret_250 - excu_250 → 可買池「中位數個股」——單押一檔典型股的樣貌，
                 不是分散隨機組合的期望值（那會靠近平均數、高於中位數）
      taiex    = TAIEX 指數同期「實際買進抱著」（首尾收盤直算，非事件視窗拼接——
                 拼接法經驗算低估指數約兩成，故改用真值）
    年度 cohort 視窗跨年重疊，strategy/pool 為簡化示意，非精確逐日資金曲線。
    """
    sa = ev[(ev.bucket == "long") & (ev.grade.isin(["S", "A"]))].copy()
    sa["year"] = sa.signal_date.str[:4]
    start = 1_000_000

    # TAIEX 真實買進抱著：首個 2012 收盤為基準，各年末（或最新）收盤直算。
    con = sqlite3.connect(str(OHLCV_DB))
    try:
        taiex = pd.read_sql_query(
            "SELECT date, close FROM ohlcv WHERE stock_id='TAIEX' AND date>='2012-01-01' ORDER BY date",
            con,
        )
    finally:
        con.close()
    taiex_base = float(taiex.close.iloc[0])
    taiex["year"] = taiex.date.str[:4]
    taiex_year_end = taiex.groupby("year").close.last()  # 各年最後收盤（末年=最新）

    caps = {"strategy": start, "pool": start}
    rows = []
    for year, g in sa.groupby("year"):
        r = g.ret_250.dropna()
        if len(r) == 0:
            continue
        rets = {
            "strategy": float(r.mean()),
            "pool": float((g.ret_250 - g.excu_250).dropna().mean()),
        }
        for k in caps:
            caps[k] *= 1 + rets[k]
        taiex_cap = start * float(taiex_year_end.get(year, taiex.close.iloc[-1])) / taiex_base
        rows.append({
            "year": year,
            "n": int(len(r)),
            "strategy_ret": round(rets["strategy"], 4),
            "strategy_capital": round(caps["strategy"]),
            "pool_capital": round(caps["pool"]),
            "taiex_capital": round(taiex_cap),
        })
    caps["taiex"] = start * float(taiex.close.iloc[-1]) / taiex_base
    years = len(rows)
    losing = [{"year": r["year"], "ret": r["strategy_ret"]} for r in rows if r["strategy_ret"] < 0]
    return {
        "start_capital": start,
        "years": years,
        "final": {k: round(v) for k, v in caps.items()},
        "cagr": round((caps["strategy"] / start) ** (1 / years) - 1, 4) if years else None,
        "losing_years": losing,
        "worst_year": min(losing, key=lambda r: r["ret"]) if losing else None,
        "rows": rows,
        "assumptions": [
            "每年年初起以等額資金跟隨長線桶 S/A 級名單、每筆持有一年（T+250），逐年複利。",
            "已扣來回交易成本 0.585%；三條線皆未含股息——但名單殖利率（中位約 6~8%）約為大盤（約 3~4%）兩倍，"
            "省略股息對名單一方較不利，實際差距比圖上小。",
            "「同池中位數個股」＝單押一檔最典型股票的樣貌；分散持有的隨機組合期望值靠近平均數，會高於此線。",
            "「大盤」＝TAIEX 指數同期實際買進抱著（收盤價直算）；名單與中位個股線的年度視窗有跨年重疊，屬簡化示意。",
        ],
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
        "plain": build_plain(ev),
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
