# 📊 Backtest Report — `run_20260517_014301`

Generated: 2026-05-17 01:43:32

## ⚙️ Configuration

| Parameter | Value |
|-----------|-------|
| run_id | run_20260517_014301 |
| date_range | 2023-01-01 → 2026-05-15 |
| universe_size | 7 |
| candidate_types | 起漲前觀察 |
| hold_days | 20 |
| stop_loss_pct | 7.0% |
| target_pct | 15.0% |
| commission | 0.1425% |
| tax | 0.30% |
| slippage | 0.10% |

## 🎯 Performance Metrics

| Metric | Value |
|--------|-------|
| 交易筆數 (n_trades) | **11** |
| 勝率 (win_rate) | **72.73%** |
| 平均報酬 (avg_return) | **2.61%** |
| 報酬中位數 | 3.60% |
| 報酬標準差 | 7.24% |
| 最大單筆獲利 | 11.13% |
| 最大單筆虧損 | -7.68% |
| 期望值 (expectancy) | **2.61%** |
| Profit Factor | **2.25** |
| Sharpe Ratio | **1.33** |
| Sortino Ratio | 0.00 |
| Max Drawdown | **-14.77%** |
| 平均持有天數 | 18.4 天 |

## 🚦 Go/No-Go Gates

- ✅ **Win Rate ≥ 45%**: threshold = ≥ 45%, actual = 72.73%
- ✅ **Profit Factor ≥ 1.3**: threshold = ≥ 1.3, actual = 2.25
- ✅ **Max Drawdown ≤ 25%**: threshold = ≤ 25%, actual = 14.77%
- ✅ **Expectancy > 0**: threshold = > 0, actual = 2.61%

## 📤 Exit Reason Breakdown

| exit_reason | n_trades | win_rate | avg_return |
| --- | --- | --- | --- |
| hold_days_expired | 8 | 1.00 | 6.47% |
| stop_loss_triggered | 3 | 0.00 | -7.68% |

## 🤖 Sector Breakdown (6-Layer AI Framework)

| sector_category | n_trades | win_rate | avg_return | max_drawdown |
| --- | --- | --- | --- | --- |
| cat_3_packaging | 11 | 72.73% | 2.61% | -14.77% |

## 🏆 Top 5 Winners

| stock_id | signal_date | entry_date | exit_date | hold_days | net_return_pct | exit_reason |
| --- | --- | --- | --- | --- | --- | --- |
| 3711 | 2025-09-04 | 2025-09-05 | 2025-10-07 | 20 | 11.13% | hold_days_expired |
| 3711 | 2023-11-09 | 2023-11-10 | 2023-12-08 | 20 | 9.41% | hold_days_expired |
| 3711 | 2023-11-06 | 2023-11-07 | 2023-12-05 | 20 | 8.94% | hold_days_expired |
| 3711 | 2023-11-03 | 2023-11-06 | 2023-12-04 | 20 | 8.90% | hold_days_expired |
| 6147 | 2023-08-21 | 2023-08-22 | 2023-09-19 | 20 | 5.17% | hold_days_expired |

## 💧 Top 5 Losers

| stock_id | signal_date | entry_date | exit_date | hold_days | net_return_pct | exit_reason |
| --- | --- | --- | --- | --- | --- | --- |
| 6147 | 2023-08-18 | 2023-08-21 | 2023-09-18 | 20 | 2.54% | hold_days_expired |
| 6147 | 2024-03-06 | 2024-03-07 | 2024-04-08 | 20 | 2.04% | hold_days_expired |
| 3711 | 2023-08-29 | 2023-08-30 | 2023-09-22 | 17 | -7.68% | stop_loss_triggered |
| 6510 | 2023-12-19 | 2023-12-20 | 2024-01-04 | 10 | -7.68% | stop_loss_triggered |
| 6510 | 2023-12-20 | 2023-12-21 | 2024-01-15 | 16 | -7.68% | stop_loss_triggered |

## 📈 Equity Curve (final state)

- 起始資金: $1,000,000
- 最終資金: $1,294,046
- 總報酬率: **29.40%**
- 最低資金 (回撤底部): $995,663

## 📋 Signal Stats

- Total signals: 11
- Unique stocks: 3
- Date range: 2023-08-18 → 2025-09-04
