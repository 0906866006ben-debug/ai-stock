"""Iterations 7+8 — 隔夜報酬延續 & 融資退場訊號 dev 回測（共用矩陣，假設各自獨立判定）。

Protocol: Docs/backtest/experiments_ledger.md Iteration 7/8（事前註冊 2026-07-06）。
每月首個交易日對可買池分三組:
  I7: 過去 20 日累積隔夜報酬 Π(open_t/close_{t-1})−1 → 高/中/低
  I8: 融資餘額 20 日變化率 → 大減/中/大增（多頭側=大減）
前瞻: 次日開盤進場、收盤出場（T+20 / T+60）、扣 0.585%、excu=vs 可買池中位。

Run:  .venv/Scripts/python.exe backend/scripts/run_overnight_margin_backtest.py
Out:  backend/data/backtest/overnight_margin_v1/summary_dev.md
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
H_DB = ROOT / "backend" / "historical_data.db"
P_DB = ROOT / "backend" / "pit_fundamentals.db"
OUT = ROOT / "backend" / "data" / "backtest" / "overnight_margin_v1"
OUT.mkdir(parents=True, exist_ok=True)

START, DEV_END = "2012-01-01", "2021-12-31"
COST = 0.00585
WINDOWS = [20, 60]

FINANCIAL_CODES = frozenset({
    "2801", "2807", "2809", "2812", "2816", "2820", "2823", "2827", "2831", "2832", "2833",
    "2834", "2836", "2837", "2838", "2845", "2847", "2849", "2850", "2851", "2852", "2854",
    "2855", "2856", "2867", "2880", "2881", "2882", "2883", "2884", "2885", "2886", "2887",
    "2888", "2889", "2890", "2891", "2892", "2897", "5820", "5854", "5859", "5863", "5864",
    "5876", "5878", "5880", "6004", "6005", "6012", "6015", "6016", "6020", "6021", "6023",
    "6024", "6026", "6027", "6028", "6035", "6878", "9101", "9102", "9103", "9104", "9105",
    "9106", "9110", "9136", "9151", "9157", "9188",
})


def log(m):  # noqa: D103
    print(m, flush=True)


def main() -> None:
    log("loading...")
    h = sqlite3.connect(H_DB, timeout=120)
    px = pd.read_sql("SELECT stock_id, date, open, close, turnover FROM ohlcv WHERE date>=? AND date<=?",
                     h, params=("2011-06-01", "2022-12-31"))
    bench = pd.read_sql("SELECT date, close FROM ohlcv WHERE stock_id='TAIEX' AND date>=? AND date<=? ORDER BY date",
                        h, params=("2011-06-01", "2022-12-31"))
    h.close()
    p = sqlite3.connect(P_DB, timeout=120)
    mar = pd.read_sql("SELECT stock_id, date, margin_balance FROM margin WHERE date>=? AND date<=?",
                      p, params=("2011-06-01", "2022-06-30"))
    p.close()

    is_common = lambda s: s.str.len().eq(4) & s.str.isdigit()  # noqa: E731
    px = px[is_common(px.stock_id)]
    mar = mar[is_common(mar.stock_id)]

    cal = bench.date.values
    cal_idx = pd.Index(cal)
    log(f"calendar {cal[0]}..{cal[-1]} ({len(cal)})")

    open_p = px.pivot_table(index="date", columns="stock_id", values="open").reindex(cal_idx)
    close_p = px.pivot_table(index="date", columns="stock_id", values="close").reindex(cal_idx)
    turn_p = px.pivot_table(index="date", columns="stock_id", values="turnover").reindex(cal_idx)
    close_ff = close_p.ffill()
    avg20_turn = turn_p.fillna(0).rolling(20, min_periods=10).mean()
    stocks = close_p.columns
    n = len(cal)

    not_fin = ~np.isin(stocks.values, np.array(sorted(FINANCIAL_CODES)))
    buyable = ((close_p >= 10).to_numpy()
               & (avg20_turn.to_numpy() >= 30_000_000)
               & ~np.isnan(close_p.to_numpy())
               & not_fin[None, :])

    log("factors...")
    # I7: 20 日累積隔夜報酬
    on = open_p / close_ff.shift(1) - 1
    cum_on = ((1 + on).rolling(20, min_periods=18).apply(np.prod, raw=True) - 1)
    f7 = cum_on.to_numpy()
    # I8: 融資餘額 20 日變化率
    bal = (mar.pivot_table(index="date", columns="stock_id", values="margin_balance")
           .reindex(cal_idx).reindex(columns=stocks).ffill())
    bal20 = bal.shift(20)
    f8 = np.where(bal20.to_numpy() > 0, bal.to_numpy() / bal20.to_numpy() - 1, np.nan)

    log("baselines...")
    open_np, close_np = open_p.to_numpy(), close_ff.to_numpy()
    bench_close = bench.set_index("date").close.reindex(cal_idx).ffill().to_numpy()
    baseline = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        entry_open = np.vstack([open_np[1:], np.full((1, open_np.shape[1]), np.nan)])
        for w in WINDOWS:
            exit_close = np.full_like(close_np, np.nan)
            if 1 + w < n:
                exit_close[: n - 1 - w] = close_np[1 + w:]
            r = exit_close / entry_open - 1 - COST
            r[~buyable] = np.nan
            baseline[w] = (r, np.nanmedian(r, axis=1))

    # 每月首個交易日（dev 期間）
    months = pd.Series(cal_idx).groupby(pd.Series(cal_idx).str[:7]).first()
    month_rows = [cal_idx.get_loc(d) for d in months if START <= d <= DEV_END]
    log(f"monthly rebalance dates: {len(month_rows)}")

    def run_hypothesis(name, factor, w_primary, long_is_low):
        """factor 矩陣逐月三分位 → 各組 excu 統計。long_is_low=True 表示多頭側為低分位組。"""
        recs = []
        for t in month_rows:
            f = factor[t].copy()
            ok = buyable[t] & np.isfinite(f)
            if ok.sum() < 90:
                continue
            vals = f[ok]
            q1, q2 = np.nanquantile(vals, [1 / 3, 2 / 3])
            for w in WINDOWS:
                r_all, med = baseline[w]
                r_t = r_all[t]
                for grp, mask in [("lo", ok & (f <= q1)), ("mid", ok & (f > q1) & (f < q2)), ("hi", ok & (f >= q2))]:
                    rr = r_t[mask]
                    rr = rr[np.isfinite(rr)]
                    if len(rr) == 0:
                        continue
                    recs.append({"date": cal[t], "year": cal[t][:4], "w": w, "grp": grp,
                                 "med_ret": np.median(rr), "med_excu": np.median(rr - med[t]), "n": len(rr)})
        df = pd.DataFrame(recs)
        long_grp, short_grp = ("lo", "hi") if long_is_low else ("hi", "lo")

        lines = [f"# {name}", ""]
        w = w_primary
        sub = df[df.w == w]
        stat = {}
        for g in ["hi", "mid", "lo"]:
            gg = sub[sub.grp == g]
            med = gg.med_excu.median()  # 逐月中位的中位（等權月份）
            stat[g] = med
            lines.append(f"- {g}: 逐月 T+{w} excu 中位 = {med:+.4f}（月數 {len(gg)}，平均組內 n={gg.n.mean():.0f}）")
        gap = stat[long_grp] - stat[short_grp]
        yr = sub[sub.grp == long_grp].groupby("year").med_excu.median()
        yr_pos = int((yr > 0).sum())
        mono = (stat[long_grp] >= stat["mid"] >= stat[short_grp])
        lines += [
            f"- 多頭側（{long_grp}）− 空頭側（{short_grp}）= {gap:+.4f}（門檻 ≥ +0.015）",
            f"- 多頭側分年為正: {yr_pos}/{len(yr)}（門檻 ≥ 7/10）",
            f"- 單調性: {mono}",
            "", "分年（多頭側 T+%d excu 中位）:" % w,
        ]
        for y, v in yr.items():
            lines.append(f"  - {y}: {v:+.4f}")
        verdict = (stat[long_grp] >= 0.01) and (gap >= 0.015) and mono and (yr_pos >= 7)
        lines += ["", f"**判定: {'PASS' if verdict else 'FAIL'}**（多頭側中位 ≥ +1% 且 gap ≥ +1.5% 且單調 且 ≥7/10 年）", ""]
        # 附上另一視窗參考
        for w2 in WINDOWS:
            if w2 == w:
                continue
            s2 = df[df.w == w2]
            lines.append(f"參考 T+{w2}: " + " / ".join(
                f"{g}={s2[s2.grp == g].med_excu.median():+.4f}" for g in ["hi", "mid", "lo"]))
        return "\n".join(lines)

    log("hypothesis I7: overnight persistence...")
    r7 = run_hypothesis("Iteration 7 — 隔夜報酬延續（高=過去20日隔夜報酬最強）", f7, 20, long_is_low=False)
    log(r7)
    log("hypothesis I8: margin retreat...")
    r8 = run_hypothesis("Iteration 8 — 融資退場訊號（lo=融資20日大減）", f8, 60, long_is_low=True)
    log(r8)
    (OUT / "summary_dev.md").write_text(r7 + "\n\n---\n\n" + r8, encoding="utf-8")
    log(f"saved -> {OUT / 'summary_dev.md'}")


if __name__ == "__main__":
    main()
