"""Iteration 6 — 領導股桶出場疊加（波段交易系統化）dev 回測。

Protocol: Docs/backtest/experiments_ledger.md Iteration 6（事前註冊 2026-07-05）。
事件集 = Iteration 4 領導股訊號（backend/data/backtest/leader_v1/events.csv）。
出場（先觸發者次日開盤出場；皆未觸發 → 第 120 交易日收盤）：
  (a) 收盤 <= 進場價 * 0.92（硬停損 8%）
  (b) 收盤 < SMA20（趨勢失效）
基線 = 同事件固定 T+60（ret_60，Iteration 4 已含成本）。
門檻：平均淨報酬 >= 基線、PF >= 1.3、最差年平均 >= 基線最差年平均。

Run:  .venv/Scripts/python.exe backend/scripts/run_leader_exit_backtest.py
Out:  backend/data/backtest/leader_v1/summary_exit_dev.md
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
H_DB = ROOT / "backend" / "historical_data.db"
EVENTS = ROOT / "backend" / "data" / "backtest" / "leader_v1" / "events.csv"
OUT = ROOT / "backend" / "data" / "backtest" / "leader_v1" / "summary_exit_dev.md"

COST = 0.00585
STOP_MULT = 0.92
MAX_HOLD = 120


def main() -> None:
    ev = pd.read_csv(EVENTS, dtype={"stock_id": str})
    print(f"events: {len(ev):,}")

    con = sqlite3.connect(H_DB, timeout=120)
    px = pd.read_sql(
        "SELECT stock_id, date, open, close FROM ohlcv WHERE date>=? AND date<=?",
        con, params=("2011-06-01", "2022-12-31"),
    )
    bench = pd.read_sql(
        "SELECT date FROM ohlcv WHERE stock_id='TAIEX' AND date>=? AND date<=? ORDER BY date",
        con, params=("2011-06-01", "2022-12-31"),
    )
    con.close()
    cal = bench.date.values
    cal_idx = pd.Index(cal)

    open_p = px.pivot_table(index="date", columns="stock_id", values="open").reindex(cal_idx)
    close_p = px.pivot_table(index="date", columns="stock_id", values="close").reindex(cal_idx)
    close_ff = close_p.ffill()
    sma20 = close_ff.rolling(20, min_periods=20).mean()

    open_np, close_np, sma_np = open_p.to_numpy(), close_ff.to_numpy(), sma20.to_numpy()
    sid_to_col = {s: i for i, s in enumerate(close_p.columns)}
    date_to_row = {d: i for i, d in enumerate(cal)}
    n = len(cal)

    rows = []
    for r in ev.itertuples(index=False):
        col = sid_to_col.get(r.stock_id)
        t0 = date_to_row.get(r.entry_date)
        if col is None or t0 is None:
            continue
        entry = open_np[t0, col]
        if not np.isfinite(entry) or entry <= 0:
            continue
        stop_level = entry * STOP_MULT
        exit_px, exit_reason, exit_t = None, None, None
        last_t = min(t0 + MAX_HOLD, n - 1)
        for t in range(t0, last_t):
            c = close_np[t, col]
            if not np.isfinite(c):
                continue
            trig = (c <= stop_level) or (np.isfinite(sma_np[t, col]) and c < sma_np[t, col])
            if trig:
                # 次日開盤出場（無開盤價則順延，最多 5 日，再無則用當日收盤保守替代）
                for off in range(1, 6):
                    if t + off <= last_t and np.isfinite(open_np[t + off, col]) and open_np[t + off, col] > 0:
                        exit_px, exit_t = open_np[t + off, col], t + off
                        break
                if exit_px is None:
                    exit_px, exit_t = c, t
                exit_reason = "stop8" if c <= stop_level else "sma20"
                break
        if exit_px is None:  # 滿 120 日收盤出場
            exit_t = last_t
            exit_px = close_np[exit_t, col]
            exit_reason = "time120"
            if not np.isfinite(exit_px):
                continue
        net = exit_px / entry - 1 - COST
        rows.append({
            "signal_date": r.signal_date, "stock_id": r.stock_id,
            "hold_days": exit_t - t0, "exit_reason": exit_reason,
            "net": net, "baseline_60": r.ret_60,
        })

    tr = pd.DataFrame(rows)
    tr["year"] = tr.signal_date.str[:4]
    print(f"trades simulated: {len(tr):,}")

    gains = tr.net[tr.net > 0].sum()
    losses = -tr.net[tr.net < 0].sum()
    pf = gains / losses if losses > 0 else float("inf")
    avg, base_avg = tr.net.mean(), tr.baseline_60.mean()
    yearly = tr.groupby("year").agg(n=("net", "size"), avg=("net", "mean"),
                                    base_avg=("baseline_60", "mean"),
                                    win=("net", lambda s: (s > 0).mean()))
    worst, base_worst = yearly.avg.min(), yearly.base_avg.min()

    lines = [
        "# 領導股桶出場疊加 dev 回測（Iteration 6）", "",
        f"- 交易數 n = {len(tr):,}；平均持有 {tr.hold_days.mean():.0f} 日",
        f"- 出場分佈：{tr.exit_reason.value_counts().to_dict()}",
        f"- 平均每筆淨報酬 = {avg:+.4f}（基線 T+60 = {base_avg:+.4f}）→ {'過' if avg >= base_avg else '未過'}",
        f"- 勝率 = {(tr.net > 0).mean():.1%}；獲利因子 PF = {pf:.2f}（門檻 >= 1.3）→ {'過' if pf >= 1.3 else '未過'}",
        f"- 最差年度平均 = {worst:+.4f}（基線最差年 = {base_worst:+.4f}）→ {'過' if worst >= base_worst else '未過'}",
        "", "## 分年（出場疊加 vs 基線 T+60，平均淨報酬）", "",
        "| 年 | n | 疊加 | 基線 | 勝率 |", "|---|---|---|---|---|",
    ]
    for y, g in yearly.iterrows():
        lines.append(f"| {y} | {g.n:.0f} | {g.avg:+.4f} | {g.base_avg:+.4f} | {g.win:.0%} |")
    verdict = (avg >= base_avg) and (pf >= 1.3) and (worst >= base_worst)
    lines += ["", f"- **判定：{'PASS' if verdict else 'FAIL'}**（依事前註冊門檻，三項全過才 PASS）"]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
