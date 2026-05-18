# 📊 Backtest Report — `run_20260517_013306`

Generated: 2026-05-17 01:35:30

## ⚙️ Configuration

| Parameter | Value |
|-----------|-------|
| run_id | run_20260517_013306 |
| date_range | 2023-01-01 → 2026-05-15 |
| universe_size | 30 |
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
| 交易筆數 (n_trades) | **72** |
| 勝率 (win_rate) | **41.67%** |
| 平均報酬 (avg_return) | **0.41%** |
| 報酬中位數 | -1.92% |
| 報酬標準差 | 8.56% |
| 最大單筆獲利 | 14.30% |
| 最大單筆虧損 | -7.68% |
| 期望值 (expectancy) | **0.41%** |
| Profit Factor | **1.11** |
| Sharpe Ratio | **0.20** |
| Sortino Ratio | 0.68 |
| Max Drawdown | **-65.39%** |
| 平均持有天數 | 14.3 天 |

## 🚦 Go/No-Go Gates

- ❌ **Win Rate ≥ 45%**: threshold = ≥ 45%, actual = 41.67%
- ❌ **Profit Factor ≥ 1.3**: threshold = ≥ 1.3, actual = 1.11
- ❌ **Max Drawdown ≤ 25%**: threshold = ≤ 25%, actual = 65.39%
- ✅ **Expectancy > 0**: threshold = > 0, actual = 0.41%

## 📤 Exit Reason Breakdown

| exit_reason | n_trades | win_rate | avg_return |
| --- | --- | --- | --- |
| hold_days_expired | 33 | 54.55% | 1.98% |
| stop_loss_triggered | 27 | 0.00 | -7.68% |
| target_reached | 12 | 1.00 | 14.30% |

## 🤖 Sector Breakdown (6-Layer AI Framework)

| sector_category | n_trades | win_rate | avg_return | max_drawdown |
| --- | --- | --- | --- | --- |
| cat_1_silicon_ip | 24 | 45.83% | 1.51% | -33.74% |
| cat_5_system_integration | 19 | 31.58% | -0.40% | -55.97% |
| cat_4_components | 13 | 30.77% | -0.36% | -32.93% |
| cat_3_packaging | 11 | 72.73% | 2.61% | -14.77% |
| cat_2_foundry | 5 | 20.00% | -4.60% | -19.41% |

## 🏆 Top 5 Winners

| stock_id | signal_date | entry_date | exit_date | hold_days | net_return_pct | exit_reason |
| --- | --- | --- | --- | --- | --- | --- |
| 3324 | 2023-03-09 | 2023-03-10 | 2023-03-22 | 8 | 14.30% | target_reached |
| 3324 | 2023-03-10 | 2023-03-13 | 2023-03-22 | 7 | 14.30% | target_reached |
| 3231 | 2024-01-16 | 2024-01-17 | 2024-01-22 | 3 | 14.30% | target_reached |
| 3231 | 2024-01-15 | 2024-01-16 | 2024-01-22 | 4 | 14.30% | target_reached |
| 6669 | 2024-05-10 | 2024-05-13 | 2024-05-24 | 9 | 14.30% | target_reached |

## 💧 Top 5 Losers

| stock_id | signal_date | entry_date | exit_date | hold_days | net_return_pct | exit_reason |
| --- | --- | --- | --- | --- | --- | --- |
| 3231 | 2025-12-30 | 2025-12-31 | 2026-01-20 | 13 | -7.68% | stop_loss_triggered |
| 3231 | 2025-12-31 | 2026-01-02 | 2026-01-19 | 11 | -7.68% | stop_loss_triggered |
| 3035 | 2026-01-07 | 2026-01-08 | 2026-01-09 | 1 | -7.68% | stop_loss_triggered |
| 3035 | 2026-01-12 | 2026-01-13 | 2026-02-02 | 14 | -7.68% | stop_loss_triggered |
| 2379 | 2026-01-28 | 2026-01-29 | 2026-03-04 | 16 | -7.68% | stop_loss_triggered |

## 📈 Equity Curve (final state)

- 起始資金: $1,000,000
- 最終資金: $1,043,549
- 總報酬率: **4.35%**
- 最低資金 (回撤底部): $848,061

## 📋 Signal Stats

- Total signals: 72
- Unique stocks: 20
- Date range: 2023-02-10 → 2026-01-28
