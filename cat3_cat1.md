# 📊 Backtest Report — `cat3_cat1`

Generated: 2026-05-17 01:55:55

## ⚙️ Configuration

| Parameter | Value |
|-----------|-------|
| run_id | cat3_cat1 |
| date_range | 2023-01-01 → 2026-05-15 |
| universe_size | 13 |
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
| 交易筆數 (n_trades) | **35** |
| 勝率 (win_rate) | **54.29%** |
| 平均報酬 (avg_return) | **1.86%** |
| 報酬中位數 | 2.04% |
| 報酬標準差 | 7.47% |
| 最大單筆獲利 | 14.30% |
| 最大單筆虧損 | -7.68% |
| 期望值 (expectancy) | **1.86%** |
| Profit Factor | **1.79** |
| Sharpe Ratio | **0.95** |
| Sortino Ratio | 2.35 |
| Max Drawdown | **-35.13%** |
| 平均持有天數 | 17.3 天 |

## 🚦 Go/No-Go Gates

- ✅ **Win Rate ≥ 45%**: threshold = ≥ 45%, actual = 54.29%
- ✅ **Profit Factor ≥ 1.3**: threshold = ≥ 1.3, actual = 1.79
- ❌ **Max Drawdown ≤ 25%**: threshold = ≤ 25%, actual = 35.13%
- ✅ **Expectancy > 0**: threshold = > 0, actual = 1.86%

## 📤 Exit Reason Breakdown

| exit_reason | n_trades | win_rate | avg_return |
| --- | --- | --- | --- |
| hold_days_expired | 23 | 69.57% | 3.96% |
| stop_loss_triggered | 9 | 0.00 | -7.68% |
| target_reached | 3 | 1.00 | 14.30% |

## 🤖 Sector Breakdown (6-Layer AI Framework)

| sector_category | n_trades | win_rate | avg_return | max_drawdown |
| --- | --- | --- | --- | --- |
| cat_1_silicon_ip | 24 | 45.83% | 1.51% | -33.74% |
| cat_3_packaging | 11 | 72.73% | 2.61% | -14.77% |

## 🏆 Top 5 Winners

| stock_id | signal_date | entry_date | exit_date | hold_days | net_return_pct | exit_reason |
| --- | --- | --- | --- | --- | --- | --- |
| 3034 | 2023-10-13 | 2023-10-16 | 2023-11-07 | 16 | 14.30% | target_reached |
| 3034 | 2023-10-12 | 2023-10-13 | 2023-11-06 | 16 | 14.30% | target_reached |
| 3034 | 2023-10-06 | 2023-10-11 | 2023-11-06 | 18 | 14.30% | target_reached |
| 3711 | 2025-09-04 | 2025-09-05 | 2025-10-07 | 20 | 11.13% | hold_days_expired |
| 2379 | 2023-11-14 | 2023-11-15 | 2023-12-13 | 20 | 10.21% | hold_days_expired |

## 💧 Top 5 Losers

| stock_id | signal_date | entry_date | exit_date | hold_days | net_return_pct | exit_reason |
| --- | --- | --- | --- | --- | --- | --- |
| 3035 | 2025-03-06 | 2025-03-07 | 2025-03-12 | 3 | -7.68% | stop_loss_triggered |
| 2379 | 2024-08-22 | 2024-08-23 | 2024-09-04 | 8 | -7.68% | stop_loss_triggered |
| 3035 | 2026-01-07 | 2026-01-08 | 2026-01-09 | 1 | -7.68% | stop_loss_triggered |
| 3035 | 2026-01-12 | 2026-01-13 | 2026-02-02 | 14 | -7.68% | stop_loss_triggered |
| 2379 | 2026-01-28 | 2026-01-29 | 2026-03-04 | 16 | -7.68% | stop_loss_triggered |

## 📈 Equity Curve (final state)

- 起始資金: $1,000,000
- 最終資金: $1,736,544
- 總報酬率: **73.65%**
- 最低資金 (回撤底部): $1,074,434

## 📋 Signal Stats

- Total signals: 35
- Unique stocks: 7
- Date range: 2023-05-16 → 2026-01-28
