"""Iteration 4 — 領導股桶（台版 CANSLIM 三件套）dev 回測。

Protocol: Docs/backtest/experiments_ledger.md Iteration 4（事前註冊 2026-07-04）。
Signal (all at close of T, DEV 2012-2021 only — OOS is unsealed, do not generate):
  1. buyable: close>=10, avg20 turnover>=30M, not financial/DR (Iteration 2 table)
  2. position: close >= 0.95 * rolling 252d max close (min 252 sessions of history)
  3. engine: PIT-visible (M+1/10) monthly revenue YoY >= +10% AND > previous month YoY
  4. confirm: volume >= 1.5 * prior-20d avg volume
  5. regime gate: TAIEX close > its 100d SMA
Defenses: next-open entry (skip up to 5 sessions), cost 58.5bp once, 20d dedup,
buyable-pool median (excu) primary benchmark, TAIEX (exc) context.
Registered thresholds: T+60 excu median >= +2%, >=7/10 dev years positive, n >= 300.
Aspirational (report only): T+60 exc median > 0.

Out: backend/data/backtest/leader_v1/{events.csv, summary_dev.md}
Run:  .venv/Scripts/python.exe backend/scripts/run_leader_backtest.py  (from repo root)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
H_DB = ROOT / "backend" / "historical_data.db"
P_DB = ROOT / "backend" / "pit_fundamentals.db"
OUT = ROOT / "backend" / "data" / "backtest" / "leader_v1"
OUT.mkdir(parents=True, exist_ok=True)

START, DEV_END = "2012-01-01", "2021-12-31"
COST = 0.00585
WINDOWS = [5, 20, 60, 120, 250]
PRIMARY_W = 60
DEDUP_LOOKBACK = 20

# Same exclusion snapshot as run_opportunities_backtest.py (Iteration 2 universe).
FINANCIAL_CODES = frozenset({
    "2801", "2807", "2809", "2812", "2816", "2820", "2823", "2827", "2831", "2832", "2833",
    "2834", "2836", "2837", "2838", "2845", "2847", "2849", "2850", "2851", "2852", "2854",
    "2855", "2856", "2867", "2880", "2881", "2882", "2883", "2884", "2885", "2886", "2887",
    "2888", "2889", "2890", "2891", "2892", "2897", "5820", "5854", "5859", "5863", "5864",
    "5876", "5878", "5880", "6004", "6005", "6012", "6015", "6016", "6020", "6021", "6023",
    "6024", "6026", "6027", "6028", "6035", "6878", "9101", "9102", "9103", "9104", "9105",
    "9106", "9110", "9136", "9151", "9157", "9188",
})


def log(msg):  # noqa: D103
    print(msg, flush=True)


def main() -> None:
    log("loading frames...")
    h = sqlite3.connect(H_DB, timeout=120)
    px = pd.read_sql(
        "SELECT stock_id, date, open, close, volume, turnover FROM ohlcv WHERE date>=? AND date<=?",
        h, params=("2010-07-01", "2022-12-31"),
    )
    bench = pd.read_sql(
        "SELECT date, close FROM ohlcv WHERE stock_id='TAIEX' AND date>=? AND date<=? ORDER BY date",
        h, params=("2010-07-01", "2022-12-31"),
    )
    h.close()
    p = sqlite3.connect(P_DB, timeout=120)
    rev = pd.read_sql("SELECT stock_id, date, revenue FROM month_revenue WHERE date>=?",
                      p, params=("2009-01-01",))
    p.close()

    is_common = lambda s: s.str.len().eq(4) & s.str.isdigit()  # noqa: E731
    px = px[is_common(px.stock_id)]
    rev = rev[is_common(rev.stock_id)]

    cal = bench.date.values
    cal_idx = pd.Index(cal)
    log(f"calendar {cal[0]}..{cal[-1]} ({len(cal)} sessions), stocks={px.stock_id.nunique()}")

    log("pivoting prices...")
    open_p = px.pivot_table(index="date", columns="stock_id", values="open").reindex(cal_idx)
    close_p = px.pivot_table(index="date", columns="stock_id", values="close").reindex(cal_idx)
    vol_p = px.pivot_table(index="date", columns="stock_id", values="volume").reindex(cal_idx)
    turn_p = px.pivot_table(index="date", columns="stock_id", values="turnover").reindex(cal_idx)
    close_ff = close_p.ffill()
    avg20_turn = turn_p.fillna(0).rolling(20, min_periods=10).mean()
    stocks = close_p.columns

    log("signal components...")
    # 2. position: at/near 252d high (requires a full year of history — no new listings)
    roll_max = close_ff.rolling(252, min_periods=252).max()
    near_high = (close_p >= 0.95 * roll_max).to_numpy()
    # 4. volume confirm vs PRIOR 20d average
    avg20_vol = vol_p.rolling(20, min_periods=10).mean().shift(1)
    vol_confirm = (vol_p >= 1.5 * avg20_vol).to_numpy()
    # 5. regime gate: TAIEX > 100d SMA
    b_close = bench.set_index("date").close.reindex(cal_idx).ffill()
    regime = (b_close > b_close.rolling(100, min_periods=100).mean()).to_numpy()

    # 3. revenue acceleration, PIT-visible M+1/10 (same construction as opps_v2)
    log("revenue features (PIT M+1/10)...")
    rev = rev.dropna(subset=["revenue"]).copy()
    rev["ym"] = rev.date.str[:4].astype(int) * 12 + rev.date.str[5:7].astype(int)
    rev = rev.sort_values(["stock_id", "ym"]).drop_duplicates(["stock_id", "ym"], keep="last")
    g = rev.groupby("stock_id", sort=False)
    rev["yoy"] = (rev.revenue / g.revenue.shift(12) - 1) * 100
    rev["yoy_prev"] = rev.groupby("stock_id", sort=False).yoy.shift(1)
    rev["accel"] = ((rev.yoy >= 10) & (rev.yoy > rev.yoy_prev)).astype(float)
    y, m = rev.ym // 12, rev.ym % 12
    m2 = m + 1
    y2 = y + (m2 > 12).astype(int)
    m2 = np.where(m2 > 12, 1, m2)
    rev["visible"] = [f"{yy:04d}-{mm:02d}-10" for yy, mm in zip(y2, m2)]
    pos_idx = np.searchsorted(cal, rev.visible.values, side="left")
    keep = pos_idx < len(cal)
    rev = rev[keep]
    rev["vis_date"] = cal[pos_idx[keep]]
    rev = rev.sort_values(["stock_id", "vis_date"]).drop_duplicates(["stock_id", "vis_date"], keep="last")
    accel_m = (rev.pivot_table(index="vis_date", columns="stock_id", values="accel")
               .reindex(cal_idx).reindex(columns=stocks).ffill().to_numpy())

    log("buyable + signal...")
    not_fin = ~np.isin(stocks.values, np.array(sorted(FINANCIAL_CODES)))
    buyable = ((close_p >= 10).to_numpy()
               & (avg20_turn.to_numpy() >= 30_000_000)
               & ~np.isnan(close_p.to_numpy())
               & not_fin[None, :])
    sig = buyable & near_high & (accel_m == 1) & vol_confirm & regime[:, None]

    log("dedup events...")
    sig_df = pd.DataFrame(sig.astype(np.int8), index=cal_idx, columns=stocks)
    prior = sig_df.rolling(DEDUP_LOOKBACK, min_periods=1).max().shift(1).fillna(0).to_numpy()
    ev_mask = sig & (prior == 0)
    ti, si = np.nonzero(ev_mask)
    in_dev = (cal[ti] >= START) & (cal[ti] <= DEV_END)
    ti, si = ti[in_dev], si[in_dev]
    ev = pd.DataFrame({"bucket": "leader", "signal_date": cal[ti],
                       "stock_id": stocks.values[si], "ti": ti, "si": si})
    log(f"  leader events (dev): {len(ev):,}")

    log("universe null baselines...")
    open_np, close_np = open_p.to_numpy(), close_ff.to_numpy()
    bench_close = b_close.to_numpy()
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

    log("forward returns...")
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
        ev[f"exc_{w}"] = r_stock - r_bench
        ev[f"excu_{w}"] = r_stock - r_universe
    ev = ev[valid].drop(columns=["ti", "si"])
    ev.to_csv(OUT / "events.csv", index=False)
    log(f"events saved: {len(ev):,} -> {OUT / 'events.csv'}")

    # ── verdict vs registered thresholds ──
    w = PRIMARY_W
    excu, exc = ev[f"excu_{w}"].dropna(), ev[f"exc_{w}"].dropna()
    lines = [
        "# 領導股桶 dev 回測（Iteration 4）",
        "",
        f"- 事件數 n = {len(ev):,}（門檻 >= 300）",
        f"- T+{w} excu 中位 = {excu.median():+.4f}（門檻 >= +0.02），勝率 {(excu > 0).mean():.1%}",
        f"- T+{w} exc  中位 = {exc.median():+.4f}（企圖性門檻 > 0，vs TAIEX 逐事件）",
        "",
        "## 分年（T+60）",
        "",
        "| 年 | n | excu 中位 | excu 勝率 | exc 中位 |",
        "|---|---|---|---|---|",
    ]
    ev["year"] = ev.signal_date.str[:4]
    yr_pos = yrs = 0
    for yy, gg in ev.groupby("year"):
        e, x = gg[f"excu_{w}"].dropna(), gg[f"exc_{w}"].dropna()
        if len(e) == 0:
            continue
        yrs += 1
        yr_pos += int(e.median() > 0)
        lines.append(f"| {yy} | {len(e)} | {e.median():+.4f} | {(e > 0).mean():.0%} | {x.median():+.4f} |")
    verdict = (excu.median() >= 0.02) and (yr_pos >= 7) and (len(excu) >= 300)
    lines += [
        "",
        f"- 年度正比例：{yr_pos}/{yrs}（門檻 >= 7/10）",
        f"- **判定：{'PASS' if verdict else 'FAIL'}**（依事前註冊門檻）",
        "",
        "其他視窗（excu 中位 / exc 中位 / n）：",
    ]
    for w2 in WINDOWS:
        e, x = ev[f"excu_{w2}"].dropna(), ev[f"exc_{w2}"].dropna()
        lines.append(f"- T+{w2}: {e.median():+.4f} / {x.median():+.4f} / {len(e)}")
    (OUT / "summary_dev.md").write_text("\n".join(lines), encoding="utf-8")
    log("\n".join(lines))


if __name__ == "__main__":
    main()
