"""Analyze backtest trades by year / sector / exit reason / score.

Usage:
    python -m backend.scripts.analyze_trades --csv trades_pre_breakout_only.csv
    python -m backend.scripts.analyze_trades --csv trades_cat3.csv --db backend/historical_data.db
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd


SECTOR_LABELS = {
    "cat_1_silicon_ip": "1 IC設計/IP",
    "cat_2_foundry": "2 晶圓代工",
    "cat_3_packaging": "3 先進封裝★瓶頸",
    "cat_4_components": "4 散熱/PCB",
    "cat_5_system_integration": "5 系統組裝ODM",
    "cat_6_cloud_software": "6 雲端/軟體",
}


def stats(sub: pd.DataFrame, label: str) -> None:
    if len(sub) == 0:
        return
    n = len(sub)
    wr = (sub["net_return_pct"] > 0).sum() / n * 100
    avg = sub["net_return_pct"].mean() * 100
    mn = sub["net_return_pct"].min() * 100
    mx = sub["net_return_pct"].max() * 100
    print(f"{label:<30} n={n:<4} 勝率={wr:<5.1f}% 平均={avg:<6.2f}% 最差={mn:<6.2f}% 最佳={mx:<6.2f}%")


def equity_curve(sub: pd.DataFrame) -> tuple[float, float]:
    if len(sub) == 0:
        return 1.0, 0.0
    sub = sub.sort_values("exit_date").reset_index(drop=True)
    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    for _, r in sub.iterrows():
        eq *= 1 + r["net_return_pct"]
        peak = max(peak, eq)
        max_dd = min(max_dd, eq / peak - 1)
    return eq, max_dd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="trades CSV file")
    parser.add_argument("--db", default="backend/historical_data.db", help="SQLite DB for score lookup")
    args = parser.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        return 1

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    filled = df[df["entry_status"] == "filled"].copy()
    if filled.empty:
        print("No filled trades in CSV.")
        return 0

    filled["exit_date"] = pd.to_datetime(filled["exit_date"])
    filled["year"] = filled["exit_date"].dt.year

    print("━" * 100)
    print("📅 按年度看：")
    for y in sorted(filled["year"].unique()):
        stats(filled[filled["year"] == y], f"{y} 年")

    print()
    print("━" * 100)
    print("🤖 按 Sector 看：")
    for cat, label in SECTOR_LABELS.items():
        stats(filled[filled["sector_category"] == cat], label)

    print()
    print("━" * 100)
    print("🚪 按出場原因看：")
    for er in filled["exit_reason"].unique():
        stats(filled[filled["exit_reason"] == er], str(er))

    # Score join
    print()
    print("━" * 100)
    print("💯 按分數看：")
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"  (DB not found: {db_path}, skipping)")
        return 0

    conn = sqlite3.connect(db_path)
    signals = pd.read_sql_query(
        "SELECT run_id, signal_date, stock_id, surge_candidate_score FROM backtest_signals",
        conn,
    )
    conn.close()

    # Cast both stock_id columns to str to avoid merge type mismatch
    signals["stock_id"] = signals["stock_id"].astype(str)
    filled["stock_id"] = filled["stock_id"].astype(str)
    filled["signal_date"] = filled["signal_date"].astype(str)
    signals["signal_date"] = signals["signal_date"].astype(str)

    merged = filled.merge(signals, on=["run_id", "signal_date", "stock_id"], how="left")
    if merged["surge_candidate_score"].isna().all():
        print("  (no score data joined — check run_id matches)")
        return 0

    print(f"  分數範圍: 最低 {merged['surge_candidate_score'].min():.0f} / 中位 {merged['surge_candidate_score'].median():.0f} / 最高 {merged['surge_candidate_score'].max():.0f}")
    print()
    for t in [55, 60, 65, 70, 75]:
        sub = merged[merged["surge_candidate_score"] >= t]
        stats(sub, f"score >= {t}")

    # Bonus: equity curve summary
    print()
    print("━" * 100)
    print("📈 全部 trades 複利曲線 (假設每筆都 ALL-IN，僅作參考)：")
    eq, dd = equity_curve(filled)
    print(f"  最終資金倍數: {eq:.4f}x  ({(eq - 1) * 100:+.2f}%)")
    print(f"  最大回撤: {dd * 100:.2f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
