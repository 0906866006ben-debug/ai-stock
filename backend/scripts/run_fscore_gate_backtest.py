"""Iteration 5 — 長線桶 F-Score 品質閘 dev 驗證。

Protocol: Docs/backtest/experiments_ledger.md Iteration 5（事前註冊 2026-07-04）。
對 opps_v2 的長線桶 S/A dev 事件（2012-2021），以事件日 PIT 可見（filing_date 後
首個交易日生效）的 Piotroski F-Score 分三組，檢驗 T+250 excu 單調性。

F-Score 九項（同季 YoY 比較版，適配季頻報表）：
  1 ROA>0  2 CFO>0*  3 ΔROA>0  4 CFO>NI*  5 Δ(長借/資產)<=0  6 Δ流動比>0
  7 股本未增加  8 Δ毛利率>0  9 Δ資產週轉>0        （* 2017 前無現金流 → 七項版）
分組：九項 高>=7/中5-6/低<=4；七項 高>=6/中4-5/低<=3。
門檻：高−低 T+250 excu 中位差 >= +2%、分年 >=6/10 為正、各組 n >= 150。

Run:  .venv/Scripts/python.exe backend/scripts/run_fscore_gate_backtest.py
Out:  backend/data/backtest/fscore_v1/summary_dev.md
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P_DB = ROOT / "backend" / "pit_fundamentals.db"
H_DB = ROOT / "backend" / "historical_data.db"
EVENTS = ROOT / "backend" / "data" / "backtest" / "opps_v2" / "events.csv"
OUT = ROOT / "backend" / "data" / "backtest" / "fscore_v1"
OUT.mkdir(parents=True, exist_ok=True)

BS_TYPES = {"TotalAssets", "CurrentAssets", "CurrentLiabilities", "LongtermBorrowings", "CapitalStock"}
IS_TYPES = {"IncomeAfterTaxes", "Revenue", "GrossProfit"}


def log(m):  # noqa: D103
    print(m, flush=True)


def load_raw(con, table, sids):
    q = f"SELECT stock_id, period_end, filing_date, raw_json FROM {table} WHERE stock_id IN ({','.join(['?'] * len(sids))})"
    return pd.read_sql(q, con, params=list(sids))


def extract(df, wanted):
    rows = []
    for sid, pe, fd, raw in df.itertuples(index=False):
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            continue
        rec = {"stock_id": sid, "period_end": pe, "filing_date": fd}
        for d in items:
            t = d.get("type")
            if t in wanted:
                rec[t] = d.get("value")
        rows.append(rec)
    return pd.DataFrame(rows)


def main() -> None:
    ev = pd.read_csv(EVENTS, dtype={"stock_id": str})
    ev = ev[(ev.bucket == "long") & (ev.grade.isin(["S", "A"])) & (ev.signal_date <= "2021-12-31")].copy()
    sids = sorted(ev.stock_id.unique())
    log(f"long S/A dev events: {len(ev):,}, stocks: {len(sids)}")

    con = sqlite3.connect(P_DB, timeout=120)
    log("extracting balance sheet items...")
    bs = extract(load_raw(con, "balance_sheet", sids), BS_TYPES)
    log("extracting income statement items...")
    fi = extract(load_raw(con, "financials", sids), IS_TYPES)
    cf = pd.read_sql(
        f"SELECT stock_id, period_end, filing_date, cfo FROM cash_flow WHERE stock_id IN ({','.join(['?'] * len(sids))})",
        con, params=sids)
    con.close()

    f = (fi.merge(bs, on=["stock_id", "period_end"], how="inner", suffixes=("", "_bs"))
           .merge(cf, on=["stock_id", "period_end"], how="left", suffixes=("", "_cf")))
    f["filing"] = f[[c for c in ("filing_date", "filing_date_bs", "filing_date_cf")]].max(axis=1)
    f = f.sort_values(["stock_id", "period_end"]).reset_index(drop=True)
    g = f.groupby("stock_id", sort=False)
    for col in ["IncomeAfterTaxes", "Revenue", "GrossProfit", "TotalAssets", "CurrentAssets",
                "CurrentLiabilities", "LongtermBorrowings", "CapitalStock", "cfo"]:
        if col not in f:
            f[col] = np.nan
        f[f"{col}_p4"] = g[col].shift(4)  # 同季 YoY 比較

    with np.errstate(invalid="ignore", divide="ignore"):
        roa = f.IncomeAfterTaxes / f.TotalAssets
        roa_p = f.IncomeAfterTaxes_p4 / f.TotalAssets_p4
        gm = f.GrossProfit / f.Revenue
        gm_p = f.GrossProfit_p4 / f.Revenue_p4
        turn = f.Revenue / f.TotalAssets
        turn_p = f.Revenue_p4 / f.TotalAssets_p4
        lev = f.LongtermBorrowings.fillna(0) / f.TotalAssets
        lev_p = f.LongtermBorrowings_p4.fillna(0) / f.TotalAssets_p4
        cur = f.CurrentAssets / f.CurrentLiabilities
        cur_p = f.CurrentAssets_p4 / f.CurrentLiabilities_p4
        items = {
            "roa_pos": roa > 0,
            "d_roa": roa > roa_p,
            "d_lev": lev <= lev_p,
            "d_cur": cur > cur_p,
            "no_dilute": f.CapitalStock <= f.CapitalStock_p4,
            "d_gm": gm > gm_p,
            "d_turn": turn > turn_p,
            "cfo_pos": f.cfo > 0,
            "accrual": f.cfo > f.IncomeAfterTaxes,
        }
    has_cfo = f.cfo.notna() & f.period_end.ge("2017-01-01")
    seven = sum(items[k].fillna(False).astype(int) for k in
                ["roa_pos", "d_roa", "d_lev", "d_cur", "no_dilute", "d_gm", "d_turn"])
    nine = seven + items["cfo_pos"].fillna(False).astype(int) + items["accrual"].fillna(False).astype(int)
    f["fscore"] = np.where(has_cfo, nine, seven)
    f["version"] = np.where(has_cfo, 9, 7)
    # 分組（依註冊切點）
    f["fgroup"] = np.where(
        f.version.eq(9),
        np.select([f.fscore >= 7, f.fscore >= 5], ["high", "mid"], "low"),
        np.select([f.fscore >= 6, f.fscore >= 4], ["high", "mid"], "low"),
    )
    # 需要 4 季前資料才有效
    f = f[f.TotalAssets_p4.notna() & f.filing.notna()]
    log(f"fscore rows: {len(f):,}")

    # PIT 生效日：filing 後首個交易日（用 TAIEX 日曆）
    h = sqlite3.connect(H_DB, timeout=120)
    cal = pd.read_sql("SELECT date FROM ohlcv WHERE stock_id='TAIEX' ORDER BY date", h).date.values
    h.close()
    pos = np.searchsorted(cal, f.filing.values, side="right")
    mask = pos < len(cal)
    f = f[mask]
    f["effective"] = cal[pos[mask]]
    f = f.sort_values(["stock_id", "effective"]).drop_duplicates(["stock_id", "effective"], keep="last")

    # merge_asof: 事件日取最近一筆已生效 F-Score（asof 鍵需 datetime）
    ev["sig_dt"] = pd.to_datetime(ev.signal_date)
    f["eff_dt"] = pd.to_datetime(f.effective)
    ev = ev.sort_values("sig_dt")
    f2 = f[["stock_id", "eff_dt", "fscore", "fgroup", "version"]].sort_values("eff_dt")
    ev = pd.merge_asof(ev, f2, left_on="sig_dt", right_on="eff_dt",
                       by="stock_id", direction="backward")
    matched = ev.fgroup.notna()
    log(f"events with F-Score: {matched.sum():,}/{len(ev):,}")
    ev = ev[matched].copy()

    lines = ["# 長線桶 F-Score 品質閘 dev 驗證（Iteration 5）", ""]
    stats = {}
    for grp in ["high", "mid", "low"]:
        s = ev[ev.fgroup == grp].excu_250.dropna()
        stats[grp] = s
        lines.append(f"- {grp}: n={len(s)}, T+250 excu 中位 {s.median():+.4f}, 勝率 {(s > 0).mean():.1%}")
    gap = stats["high"].median() - stats["low"].median()
    lines.append(f"- 高−低 中位差：{gap:+.4f}（門檻 >= +0.02）")
    ev["year"] = ev.signal_date.str[:4]
    yr_pos = yrs = 0
    lines += ["", "## 分年（T+250 excu 中位，高/低/差）", ""]
    for yy, gg in ev.groupby("year"):
        hi = gg[gg.fgroup == "high"].excu_250.dropna()
        lo = gg[gg.fgroup == "low"].excu_250.dropna()
        if len(hi) == 0 or len(lo) == 0:
            lines.append(f"- {yy}: 樣本不足（high n={len(hi)}, low n={len(lo)}）")
            continue
        yrs += 1
        d = hi.median() - lo.median()
        yr_pos += int(d > 0)
        lines.append(f"- {yy}: {hi.median():+.4f} / {lo.median():+.4f} / {d:+.4f}")
    mono = stats["high"].median() >= stats["mid"].median() >= stats["low"].median()
    verdict = (gap >= 0.02) and (yr_pos >= 6) and all(len(stats[g]) >= 150 for g in stats)
    lines += ["", f"- 單調性（高>=中>=低）：{mono}",
              f"- 年度正比例：{yr_pos}/{yrs}（門檻 >= 6/10，樣本不足年不計）",
              f"- **判定：{'PASS' if verdict else 'FAIL'}**（依事前註冊門檻）"]
    (OUT / "summary_dev.md").write_text("\n".join(lines), encoding="utf-8")
    log("\n".join(lines))


if __name__ == "__main__":
    main()
