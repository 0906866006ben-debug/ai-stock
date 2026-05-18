"""Markdown / CSV report generator for backtest runs."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.app.services.backtest.metrics import (
    compute_equity_curve,
    compute_metrics,
    group_metrics_by,
)


def generate_markdown_report(
    *,
    run_id: str,
    config_summary: dict,
    trades_df: pd.DataFrame,
    signals_df: Optional[pd.DataFrame] = None,
) -> str:
    """Generate a Markdown performance report. Returns the report string."""
    metrics = compute_metrics(trades_df)
    metric_dict = metrics.to_dict()

    lines: list[str] = []
    lines.append(f"# 📊 Backtest Report — `{run_id}`")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # Configuration
    lines.append("## ⚙️ Configuration")
    lines.append("")
    lines.append("| Parameter | Value |")
    lines.append("|-----------|-------|")
    for k, v in config_summary.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # Core metrics
    lines.append("## 🎯 Performance Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| 交易筆數 (n_trades) | **{metric_dict['n_trades']}** |")
    lines.append(f"| 勝率 (win_rate) | **{metric_dict['win_rate']*100:.2f}%** |")
    lines.append(f"| 平均報酬 (avg_return) | **{metric_dict['avg_return']*100:.2f}%** |")
    lines.append(f"| 報酬中位數 | {metric_dict['median_return']*100:.2f}% |")
    lines.append(f"| 報酬標準差 | {metric_dict['std_return']*100:.2f}% |")
    lines.append(f"| 最大單筆獲利 | {metric_dict['max_return']*100:.2f}% |")
    lines.append(f"| 最大單筆虧損 | {metric_dict['min_return']*100:.2f}% |")
    lines.append(f"| 期望值 (expectancy) | **{metric_dict['expectancy']*100:.2f}%** |")
    pf = metric_dict.get("profit_factor")
    lines.append(f"| Profit Factor | **{pf:.2f}** |" if pf is not None else "| Profit Factor | ∞ (no losses) |")
    lines.append(f"| Sharpe Ratio | **{metric_dict['sharpe']:.2f}** |")
    lines.append(f"| Sortino Ratio | {metric_dict['sortino']:.2f} |")
    lines.append(f"| Max Drawdown | **{metric_dict['max_drawdown']*100:.2f}%** |")
    lines.append(f"| 平均持有天數 | {metric_dict['avg_hold_days']:.1f} 天 |")
    lines.append("")

    # Go/no-go gates
    lines.append("## 🚦 Go/No-Go Gates")
    lines.append("")
    gate_results = _evaluate_gates(metric_dict)
    for gate, passed, threshold, actual in gate_results:
        emoji = "✅" if passed else "❌"
        lines.append(f"- {emoji} **{gate}**: threshold = {threshold}, actual = {actual}")
    lines.append("")

    # Exit reason breakdown
    if not trades_df.empty and "exit_reason" in trades_df.columns:
        lines.append("## 📤 Exit Reason Breakdown")
        lines.append("")
        exit_breakdown = group_metrics_by(trades_df, "exit_reason")
        if not exit_breakdown.empty:
            lines.append(_df_to_markdown(exit_breakdown[["exit_reason", "n_trades", "win_rate", "avg_return"]]))
        lines.append("")

    # Sector breakdown
    if not trades_df.empty and "sector_category" in trades_df.columns:
        lines.append("## 🤖 Sector Breakdown (6-Layer AI Framework)")
        lines.append("")
        sector_breakdown = group_metrics_by(trades_df, "sector_category")
        if not sector_breakdown.empty:
            lines.append(_df_to_markdown(sector_breakdown[["sector_category", "n_trades", "win_rate", "avg_return", "max_drawdown"]]))
        lines.append("")

    # Top winners / losers
    filled = trades_df[trades_df.get("entry_status") == "filled"].copy() if not trades_df.empty else pd.DataFrame()
    if not filled.empty:
        filled_sorted = filled.sort_values("net_return_pct", ascending=False)
        lines.append("## 🏆 Top 5 Winners")
        lines.append("")
        top5 = filled_sorted.head(5)[["stock_id", "signal_date", "entry_date", "exit_date", "hold_days", "net_return_pct", "exit_reason"]]
        lines.append(_df_to_markdown(top5))
        lines.append("")
        lines.append("## 💧 Top 5 Losers")
        lines.append("")
        bottom5 = filled_sorted.tail(5)[["stock_id", "signal_date", "entry_date", "exit_date", "hold_days", "net_return_pct", "exit_reason"]]
        lines.append(_df_to_markdown(bottom5))
        lines.append("")

    # Equity curve (text)
    eq = compute_equity_curve(trades_df)
    if not eq.empty:
        lines.append("## 📈 Equity Curve (final state)")
        lines.append("")
        start_eq = 1_000_000.0
        end_eq = float(eq["equity"].iloc[-1])
        total_return = (end_eq / start_eq) - 1
        lines.append(f"- 起始資金: $1,000,000")
        lines.append(f"- 最終資金: ${end_eq:,.0f}")
        lines.append(f"- 總報酬率: **{total_return*100:.2f}%**")
        lines.append(f"- 最低資金 (回撤底部): ${eq['equity'].min():,.0f}")
        lines.append("")

    # Signal summary
    if signals_df is not None and not signals_df.empty:
        lines.append("## 📋 Signal Stats")
        lines.append("")
        lines.append(f"- Total signals: {len(signals_df)}")
        lines.append(f"- Unique stocks: {signals_df['stock_id'].nunique()}")
        lines.append(f"- Date range: {signals_df['signal_date'].min()} → {signals_df['signal_date'].max()}")
        lines.append("")

    return "\n".join(lines)


def _evaluate_gates(metric_dict: dict) -> list[tuple[str, bool, str, str]]:
    """Apply the go/no-go thresholds from the Wall Street trader checkpoint list."""
    gates = []
    win_rate = metric_dict["win_rate"]
    pf = metric_dict.get("profit_factor")
    max_dd = abs(metric_dict["max_drawdown"])
    expectancy = metric_dict["expectancy"]

    gates.append(("Win Rate ≥ 45%", win_rate >= 0.45, "≥ 45%", f"{win_rate*100:.2f}%"))
    gates.append(("Profit Factor ≥ 1.3", (pf or 0) >= 1.3, "≥ 1.3", f"{pf:.2f}" if pf else "N/A"))
    gates.append(("Max Drawdown ≤ 25%", max_dd <= 0.25, "≤ 25%", f"{max_dd*100:.2f}%"))
    gates.append(("Expectancy > 0", expectancy > 0, "> 0", f"{expectancy*100:.2f}%"))
    return gates


def _df_to_markdown(df: pd.DataFrame) -> str:
    """Simple DataFrame → Markdown table converter."""
    if df.empty:
        return "*(empty)*"
    cols = list(df.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = []
    for _, r in df.iterrows():
        parts = []
        for c in cols:
            v = r[c]
            if isinstance(v, float):
                if abs(v) < 1 and abs(v) > 0:
                    parts.append(f"{v*100:.2f}%")
                else:
                    parts.append(f"{v:.2f}")
            else:
                parts.append(str(v) if v is not None else "—")
        rows.append("| " + " | ".join(parts) + " |")
    return "\n".join([header, sep, *rows])


def export_trades_csv(trades_df: pd.DataFrame, output_path: Path | str) -> None:
    """Export all trades to a CSV for Excel inspection."""
    trades_df.to_csv(output_path, index=False, encoding="utf-8-sig")


def save_report(report_md: str, output_path: Path | str) -> None:
    Path(output_path).write_text(report_md, encoding="utf-8")
