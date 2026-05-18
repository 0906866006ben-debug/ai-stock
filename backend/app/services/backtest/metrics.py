"""Performance metrics — pure math on a list of trade returns.

All functions accept a pandas Series of net_return_pct (one row per trade)
and return a single float. Designed to be testable in isolation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class PerformanceMetrics:
    n_trades: int
    win_rate: float                 # 0~1
    avg_return: float               # mean of net_return_pct
    median_return: float
    std_return: float
    max_return: float
    min_return: float
    profit_factor: float            # gross_profit / gross_loss
    expectancy: float               # (win_rate × avg_win) - (lose_rate × |avg_loss|)
    sharpe: float                   # mean / std × √(252/avg_hold)
    sortino: float                  # mean / downside_std × √(252/avg_hold)
    max_drawdown: float             # in equity terms (cumulative)
    avg_hold_days: float

    def to_dict(self) -> dict:
        return {
            "n_trades": self.n_trades,
            "win_rate": round(self.win_rate, 4),
            "avg_return": round(self.avg_return, 4),
            "median_return": round(self.median_return, 4),
            "std_return": round(self.std_return, 4),
            "max_return": round(self.max_return, 4),
            "min_return": round(self.min_return, 4),
            "profit_factor": round(self.profit_factor, 4) if math.isfinite(self.profit_factor) else None,
            "expectancy": round(self.expectancy, 4),
            "sharpe": round(self.sharpe, 4),
            "sortino": round(self.sortino, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "avg_hold_days": round(self.avg_hold_days, 2),
        }


def compute_metrics(trades_df: pd.DataFrame) -> PerformanceMetrics:
    """Compute performance metrics. Requires net_return_pct + hold_days columns."""
    filled = trades_df[trades_df["entry_status"] == "filled"].copy()
    if filled.empty:
        return PerformanceMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    returns = filled["net_return_pct"].dropna()
    if returns.empty:
        return PerformanceMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    n = len(returns)
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    win_rate = len(wins) / n if n else 0.0

    avg = returns.mean()
    med = returns.median()
    std = returns.std() or 0.0
    mx = returns.max()
    mn = returns.min()

    gross_profit = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    avg_win = wins.mean() if not wins.empty else 0.0
    avg_loss = losses.mean() if not losses.empty else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    avg_hold = filled["hold_days"].mean() if "hold_days" in filled else 10.0
    # Annualization assuming ~252 trading days
    annualization = math.sqrt(252.0 / max(avg_hold, 1.0))
    sharpe = (avg / std * annualization) if std > 0 else 0.0

    downside = returns[returns < 0]
    downside_std = downside.std() if len(downside) > 1 else 0.0
    sortino = (avg / downside_std * annualization) if downside_std > 0 else 0.0

    # Equity curve & max drawdown
    equity = (1 + returns.reset_index(drop=True)).cumprod()
    peak = equity.cummax()
    drawdown = (equity / peak - 1)
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

    return PerformanceMetrics(
        n_trades=n, win_rate=float(win_rate),
        avg_return=float(avg), median_return=float(med), std_return=float(std),
        max_return=float(mx), min_return=float(mn),
        profit_factor=profit_factor, expectancy=float(expectancy),
        sharpe=float(sharpe), sortino=float(sortino),
        max_drawdown=max_dd, avg_hold_days=float(avg_hold),
    )


def compute_equity_curve(trades_df: pd.DataFrame, initial_capital: float = 1_000_000.0) -> pd.DataFrame:
    """Sequential equity curve assuming all trades are taken in order.

    Returns DataFrame with columns: trade_id, exit_date, equity, drawdown_pct
    """
    filled = trades_df[trades_df["entry_status"] == "filled"].copy()
    if filled.empty:
        return pd.DataFrame(columns=["trade_id", "exit_date", "equity", "drawdown_pct"])

    filled = filled.sort_values("exit_date").reset_index(drop=True)
    equity = initial_capital
    rows = []
    peak = initial_capital
    for _, row in filled.iterrows():
        ret = row.get("net_return_pct") or 0.0
        equity *= (1 + ret)
        peak = max(peak, equity)
        rows.append({
            "trade_id": int(row["trade_id"]),
            "exit_date": row["exit_date"],
            "equity": round(equity, 2),
            "drawdown_pct": round((equity / peak - 1), 4),
        })
    return pd.DataFrame(rows)


def group_metrics_by(trades_df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Sub-group performance breakdown (e.g. by sector_category, exit_reason)."""
    filled = trades_df[trades_df["entry_status"] == "filled"]
    if filled.empty or by not in filled.columns:
        return pd.DataFrame()

    rows = []
    for key, sub in filled.groupby(by, dropna=False):
        m = compute_metrics(sub)
        d = m.to_dict()
        d[by] = key if key is not None else "(none)"
        rows.append(d)
    return pd.DataFrame(rows).sort_values("n_trades", ascending=False)
