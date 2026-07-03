"""Simplified forward-return backtest for the daily-opportunities buckets.

Protocol: Docs/planning/backtest_plan_daily_opportunities_2026-07-02.md
Rules under test: research report v2 §5 (as implemented in
backend/app/services/tw_daily_opportunities.py), replayed 2012-2026 from the
local PIT stores.

Honesty rails baked in:
  - Revenue for month M becomes visible on the 10th of month M+1 (statutory).
  - Entry at NEXT trading day's OPEN after the signal date; skip if no open
    within 5 sessions.
  - Round-trip cost 58.5 bps deducted once.
  - Excess return vs TAIEX over the same window.
  - Event de-dup: a stock only creates an event when its grade-rank exceeds
    its own max over the prior 20 sessions (upgrade events).
  - DEV window (<2022) is printed; OOS (>=2022) is computed and saved but the
    summary is withheld until DEV gates pass (multiple-testing discipline).
Known simplifications (reported, not hidden): prices not dividend-adjusted
(conservative), partial delisted coverage (~184 dead tickers -> some
survivorship inflation), industry/MAX/IVOL filters not applied.

Run:  .venv/Scripts/python.exe backend/scripts/run_opportunities_backtest.py
Out:  backend/data/backtest/opps_v2/{events.csv, summary_dev.md, summary_oos.md}
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
H_DB = ROOT / "backend" / "historical_data.db"
P_DB = ROOT / "backend" / "pit_fundamentals.db"
OUT = ROOT / "backend" / "data" / "backtest" / "opps_v2"
OUT.mkdir(parents=True, exist_ok=True)

START, DEV_END, END = "2012-01-01", "2021-12-31", "2026-06-30"
COST = 0.00585
WINDOWS = [5, 20, 60, 120, 250]
DEDUP_LOOKBACK = 20

# mid-bucket grade thresholds (identical to tw_daily_opportunities._grade_mid)
def grade_rank(yoy, streak_mo, fstreak, tstreak):
    inst = np.maximum(fstreak, tstreak)
    r = np.zeros(yoy.shape, dtype=np.int8)
    with np.errstate(invalid="ignore"):
        c = (~np.isnan(yoy)) & ((yoy > 0) | (fstreak >= 3))
        b = (~np.isnan(yoy)) & (yoy > 0) & (inst >= 3)
        a = (~np.isnan(yoy)) & (yoy >= 10) & (streak_mo >= 2) & (inst >= 3)
        s = (~np.isnan(yoy)) & (yoy >= 30) & (streak_mo >= 3) & (fstreak >= 5)
    r[c] = 1; r[b] = 2; r[a] = 3; r[s] = 4
    return r

GRADE_NAME = {4: "S", 3: "A", 2: "B", 1: "C"}


def log(msg):  # noqa: D103
    print(msg, flush=True)


def load_frames():
    h = sqlite3.connect(H_DB)
    px = pd.read_sql(
        "SELECT stock_id, date, open, close, turnover FROM ohlcv WHERE date>=?",
        h, params=("2011-01-01",),
    )
    bench = pd.read_sql(
        "SELECT date, close FROM ohlcv WHERE stock_id='TAIEX' AND date>=? ORDER BY date",
        h, params=("2011-01-01",),
    )
    h.close()

    p = sqlite3.connect(P_DB)
    inst = pd.read_sql(
        "SELECT stock_id, date, foreign_net, trust_net FROM institutional WHERE date>=?",
        p, params=("2011-01-01",),
    )
    rev = pd.read_sql(
        "SELECT stock_id, date, revenue FROM month_revenue WHERE date>=?",
        p, params=("2010-01-01",),
    )
    val = pd.read_sql(
        "SELECT stock_id, date, per, pbr, dividend_yield FROM per WHERE date>=?",
        p, params=("2011-12-01",),
    )
    p.close()
    return px, bench, inst, rev, val


def build():
    log("loading frames...")
    px, bench, inst, rev, val = load_frames()

    # universe: 4-digit numeric common stocks
    def is_common(s):
        return s.str.len().eq(4) & s.str.isdigit()

    px = px[is_common(px.stock_id)]
    inst = inst[is_common(inst.stock_id)]
    rev = rev[is_common(rev.stock_id)]
    val = val[is_common(val.stock_id)]

    cal = bench.date.values  # market calendar
    cal_idx = pd.Index(cal)
    log(f"calendar {cal[0]}..{cal[-1]} ({len(cal)} sessions), stocks px={px.stock_id.nunique()}")

    log("pivoting prices...")
    open_p = px.pivot_table(index="date", columns="stock_id", values="open").reindex(cal_idx)
    close_p = px.pivot_table(index="date", columns="stock_id", values="close").reindex(cal_idx)
    turn_p = px.pivot_table(index="date", columns="stock_id", values="turnover").reindex(cal_idx)
    close_ff = close_p.ffill()
    avg20_turn = turn_p.fillna(0).rolling(20, min_periods=10).mean()
    stocks = close_p.columns

    log("institutional streaks...")
    f_pos = (inst.pivot_table(index="date", columns="stock_id", values="foreign_net")
             .reindex(cal_idx).reindex(columns=stocks).fillna(0) > 0).to_numpy()
    t_pos = (inst.pivot_table(index="date", columns="stock_id", values="trust_net")
             .reindex(cal_idx).reindex(columns=stocks).fillna(0) > 0).to_numpy()

    def streaks(b):
        out = np.zeros(b.shape, dtype=np.int16)
        for i in range(1, b.shape[0]):
            out[i] = (out[i - 1] + 1) * b[i]
        out[0] = b[0]
        return out

    f_str, t_str = streaks(f_pos), streaks(t_pos)

    log("revenue features (PIT: visible M+1/10)...")
    rev = rev.dropna(subset=["revenue"]).copy()
    rev["ym"] = rev.date.str[:4].astype(int) * 12 + rev.date.str[5:7].astype(int)
    rev = rev.sort_values(["stock_id", "ym"]).drop_duplicates(["stock_id", "ym"], keep="last")
    g = rev.groupby("stock_id", sort=False)
    rev["yoy"] = (rev.revenue / g.revenue.shift(12) - 1) * 100
    pos = (rev.yoy > 0).astype(int)
    grp_break = pos.eq(0).groupby(rev.stock_id, sort=False).cumsum()
    rev["yoy_streak"] = pos.groupby([rev.stock_id, grp_break], sort=False).cumsum() * pos
    rev["new_high"] = (rev.revenue >= g.revenue.rolling(14, min_periods=14).max()
                       .reset_index(level=0, drop=True)).astype(float)
    # visibility date: 10th of following month
    y, m = rev.ym // 12, rev.ym % 12
    m2 = m + 1
    y2 = y + (m2 > 12).astype(int)
    m2 = np.where(m2 > 12, 1, m2)
    rev["visible"] = [f"{yy:04d}-{mm:02d}-10" for yy, mm in zip(y2, m2)]
    # map to first session >= visible
    pos_idx = np.searchsorted(cal, rev.visible.values, side="left")
    keep = pos_idx < len(cal)
    rev = rev[keep]
    rev["vis_date"] = cal[pos_idx[keep]]
    rev = rev.sort_values(["stock_id", "vis_date"]).drop_duplicates(["stock_id", "vis_date"], keep="last")

    def rev_state(col):
        w = rev.pivot_table(index="vis_date", columns="stock_id", values=col)
        return w.reindex(cal_idx).reindex(columns=stocks).ffill().to_numpy()

    yoy_m, streak_m, nh_m = rev_state("yoy"), rev_state("yoy_streak"), rev_state("new_high")

    log("buyable + grades...")
    buyable = ((close_p >= 10).to_numpy()
               & (avg20_turn.to_numpy() >= 30_000_000)
               & ~np.isnan(close_p.to_numpy()))
    ranks = grade_rank(yoy_m, np.nan_to_num(streak_m), f_str, t_str)
    ranks = np.where(buyable, ranks, 0)

    log("mid-bucket upgrade events...")
    rank_df = pd.DataFrame(ranks, index=cal_idx, columns=stocks)
    prior_max = rank_df.rolling(DEDUP_LOOKBACK, min_periods=1).max().shift(1).fillna(0).to_numpy()
    ev_mask = (ranks > prior_max) & (ranks >= 1)
    ti, si = np.nonzero(ev_mask)
    in_window = (cal[ti] >= START) & (cal[ti] <= END)
    ti, si = ti[in_window], si[in_window]
    mid_ev = pd.DataFrame({
        "bucket": "mid", "signal_date": cal[ti], "stock_id": stocks.values[si],
        "grade": [GRADE_NAME[r] for r in ranks[ti, si]], "ti": ti, "si": si,
    })
    log(f"  mid events: {len(mid_ev):,}")

    log("long bucket (monthly)...")
    val = val.sort_values("date")
    month_first = pd.Series(cal_idx).groupby(pd.Series(cal_idx).str[:7]).first()
    month_first = [d for d in month_first if START <= d <= END]
    vmap = {d: g for d, g in val.groupby("date") if d in set(month_first)}
    sid_to_col = {s: i for i, s in enumerate(stocks)}
    long_rows = []
    prev_grade: dict[str, str] = {}
    for d in month_first:
        ti0 = cal_idx.get_loc(d)
        vg = vmap.get(d)
        if vg is None:
            continue
        vg = vg[(vg.per > 0) & (vg.pbr > 0) & (vg.dividend_yield > 0)]
        vg = vg[vg.stock_id.isin(sid_to_col)]
        cols = vg.stock_id.map(sid_to_col).to_numpy()
        ok = buyable[ti0, cols]
        vg, cols = vg[ok], cols[ok]
        if len(vg) < 50:
            continue
        score = ((1 / vg.per).rank(pct=True) + vg.dividend_yield.rank(pct=True)
                 + (1 / vg.pbr).rank(pct=True)) / 3
        vg = vg.assign(score=score.values, col=cols)
        vg = vg.sort_values("score", ascending=False).head(60)
        yoy_now = yoy_m[ti0, vg.col.to_numpy()]
        vg = vg[(~np.isnan(yoy_now)) & (yoy_now > 0)]
        cur = {}
        for _, r in vg.iterrows():
            g_ = "S" if (r.score >= 0.85 and yoy_m[ti0, int(r.col)] >= 10) else ("A" if r.score >= 0.75 else "B")
            cur[r.stock_id] = g_
            if prev_grade.get(r.stock_id) != g_:  # entry/upgrade only
                long_rows.append(("long", d, r.stock_id, g_, ti0, int(r.col)))
        prev_grade = cur
    long_ev = pd.DataFrame(long_rows, columns=["bucket", "signal_date", "stock_id", "grade", "ti", "si"])
    log(f"  long events: {len(long_ev):,}")

    ev = pd.concat([mid_ev, long_ev], ignore_index=True)

    log("forward returns...")
    open_np, close_np = open_p.to_numpy(), close_ff.to_numpy()
    bench_close = bench.set_index("date").close.reindex(cal_idx).ffill().to_numpy()

    # ── Null control: median forward return of the BUYABLE universe, same
    # entry convention (next open -> close at T+w), per signal day. This is
    # the honest yardstick for stock-SELECTION skill; cap-weighted TAIEX
    # is structurally unbeatable by the median stock in mega-cap-led years.
    log("universe null baselines...")
    n = len(cal)
    baseline = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        entry_open = np.vstack([open_np[1:], np.full((1, open_np.shape[1]), np.nan)])
        for w in WINDOWS:
            exit_close = np.full_like(close_np, np.nan)
            if 1 + w < n:
                exit_close[: n - 1 - w] = close_np[1 + w:]
            r = exit_close / entry_open - 1 - COST
            r[~buyable] = np.nan
            baseline[w] = np.nanmedian(r, axis=1)
    n = len(cal)
    ent_idx = np.full(len(ev), -1)
    ent_px = np.full(len(ev), np.nan)
    for k, (t, s) in enumerate(zip(ev.ti.to_numpy(), ev.si.to_numpy())):
        for off in range(1, 6):
            if t + off < n and not np.isnan(open_np[t + off, s]) and open_np[t + off, s] > 0:
                ent_idx[k], ent_px[k] = t + off, open_np[t + off, s]
                break
    ev["entry_date"] = [cal[i] if i >= 0 else None for i in ent_idx]
    valid = ent_idx >= 0
    ev_ti = ev.ti.to_numpy()
    for w in WINDOWS:
        xi = np.minimum(ent_idx + w, n - 1)
        matured = valid & (ent_idx + w <= n - 1)
        r_stock = np.where(matured, close_np[xi, ev.si.to_numpy()] / ent_px - 1 - COST, np.nan)
        r_bench = np.where(matured, bench_close[xi] / bench_close[np.maximum(ent_idx, 0)] - 1, np.nan)
        r_universe = baseline[w][np.clip(ev_ti, 0, n - 1)]
        ev[f"ret_{w}"] = r_stock
        ev[f"exc_{w}"] = r_stock - r_bench          # vs cap-weighted TAIEX (context)
        ev[f"excu_{w}"] = r_stock - r_universe      # vs buyable-universe median (selection skill)
    ev = ev[valid].drop(columns=["ti", "si"])
    ev.to_csv(OUT / "events.csv", index=False)
    log(f"events saved: {len(ev):,} -> {OUT/'events.csv'}")
    return ev


def summarize(ev: pd.DataFrame, lo: str, hi: str, name: str):
    sub = ev[(ev.signal_date >= lo) & (ev.signal_date <= hi)].copy()
    sub["year"] = sub.signal_date.str[:4]
    lines = [f"# Opportunities backtest summary — {name} ({lo}..{hi})", ""]
    for bucket in ["mid", "long"]:
        b = sub[sub.bucket == bucket]
        for label, col in [("vs 可買池中位（選股力）", "excu"), ("vs TAIEX（脈絡參考）", "exc")]:
            lines += [f"## {bucket} bucket — {label}", "",
                      "| grade | n | " + " | ".join(f"T+{w} med / win%" for w in WINDOWS) + " |",
                      "|---|---|" + "---|" * len(WINDOWS)]
            for g_ in ["S", "A", "B", "C"]:
                gg = b[b.grade == g_]
                if not len(gg):
                    continue
                cells = []
                for w in WINDOWS:
                    e = gg[f"{col}_{w}"].dropna()
                    cells.append(f"{e.median()*100:+.2f}% / {(e>0).mean()*100:.0f}%" if len(e) else "—")
                lines.append(f"| {g_} | {len(gg)} | " + " | ".join(cells) + " |")
            lines.append("")
        # yearly stability at T+60 for A-and-above, universe-relative
        ab = b[b.grade.isin(["S", "A"])]
        if len(ab):
            lines += [f"**A 級以上 T+60 逐年中位（vs 可買池，{bucket}）**", ""]
            yr = ab.groupby("year")["excu_60"].agg(["count", "median"])
            for y, row in yr.iterrows():
                lines.append(f"- {y}: n={int(row['count'])} median={row['median']*100:+.2f}%")
            pos_years = (yr["median"] > 0).mean()
            lines.append(f"- **正年度比例: {pos_years*100:.0f}%**")
        lines.append("")
    text = "\n".join(lines)
    (OUT / f"summary_{name}.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    ev = build()
    dev = summarize(ev, START, DEV_END, "dev")
    summarize(ev, "2022-01-01", END, "oos")  # saved, NOT printed (discipline)
    print("\n" + "=" * 70 + "\n" + dev)
    print("\n[OOS summary computed and saved but withheld until DEV gates pass]")
