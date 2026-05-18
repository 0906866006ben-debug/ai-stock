# 📊 Backtest Report — `run_20260517_012155`

Generated: 2026-05-17 01:24:29

## ⚙️ Configuration

| Parameter | Value |
|-----------|-------|
| run_id | run_20260517_012155 |
| date_range | 2023-01-01 → 2026-05-15 |
| universe_size | 30 |
| candidate_types | 起漲前觀察, 初動候選, 動能確認, 偏熱觀察 |
| hold_days | 20 |
| stop_loss_pct | 7.0% |
| target_pct | 15.0% |
| commission | 0.1425% |
| tax | 0.30% |
| slippage | 0.10% |

## 🎯 Performance Metrics

| Metric | Value |
|--------|-------|
| 交易筆數 (n_trades) | **8432** |
| 勝率 (win_rate) | **48.90%** |
| 平均報酬 (avg_return) | **2.18%** |
| 報酬中位數 | -0.57% |
| 報酬標準差 | 9.91% |
| 最大單筆獲利 | 14.30% |
| 最大單筆虧損 | -11.83% |
| 期望值 (expectancy) | **2.18%** |
| Profit Factor | **1.62** |
| Sharpe Ratio | **1.12** |
| Sortino Ratio | 5.66 |
| Max Drawdown | **-100.00%** |
| 平均持有天數 | 9.7 天 |

## 🚦 Go/No-Go Gates

- ✅ **Win Rate ≥ 45%**: threshold = ≥ 45%, actual = 48.90%
- ✅ **Profit Factor ≥ 1.3**: threshold = ≥ 1.3, actual = 1.62
- ❌ **Max Drawdown ≤ 25%**: threshold = ≤ 25%, actual = 100.00%
- ✅ **Expectancy > 0**: threshold = > 0, actual = 2.18%

## 📤 Exit Reason Breakdown

| exit_reason | n_trades | win_rate | avg_return |
| --- | --- | --- | --- |
| stop_loss_triggered | 3617 | 0.00 | -7.68% |
| target_reached | 2951 | 1.00 | 14.30% |
| hold_days_expired | 1733 | 65.72% | 2.45% |
| no_exit_data | 131 | 25.19% | -2.46% |

## 🤖 Sector Breakdown (6-Layer AI Framework)

| sector_category | n_trades | win_rate | avg_return | max_drawdown |
| --- | --- | --- | --- | --- |
| cat_4_components | 2259 | 50.11% | 2.97% | -1.00 |
| cat_3_packaging | 2216 | 51.08% | 2.51% | -99.99% |
| cat_5_system_integration | 1634 | 47.98% | 2.00% | -1.00 |
| cat_1_silicon_ip | 1473 | 45.15% | 1.32% | -1.00 |
| cat_2_foundry | 541 | 48.80% | 1.28% | -97.52% |
| cat_6_cloud_software | 309 | 47.25% | 0.55% | -96.20% |

## 🏆 Top 5 Winners

| stock_id | signal_date | entry_date | exit_date | hold_days | net_return_pct | exit_reason |
| --- | --- | --- | --- | --- | --- | --- |
| 3034 | 2023-01-03 | 2023-01-04 | 2023-02-08 | 17 | 14.30% | target_reached |
| 3037 | 2023-01-03 | 2023-01-04 | 2023-02-01 | 12 | 14.30% | target_reached |
| 8358 | 2023-01-09 | 2023-01-10 | 2023-02-01 | 8 | 14.30% | target_reached |
| 2454 | 2024-08-02 | 2024-08-05 | 2024-08-07 | 2 | 14.30% | target_reached |
| 3711 | 2024-08-02 | 2024-08-05 | 2024-08-14 | 7 | 14.30% | target_reached |

## 💧 Top 5 Losers

| stock_id | signal_date | entry_date | exit_date | hold_days | net_return_pct | exit_reason |
| --- | --- | --- | --- | --- | --- | --- |
| 6669 | 2026-05-14 | 2026-05-15 | 2026-05-15 | 0 | -9.02% | no_exit_data |
| 3017 | 2026-05-14 | 2026-05-15 | 2026-05-15 | 0 | -9.50% | no_exit_data |
| 3037 | 2026-05-14 | 2026-05-15 | 2026-05-15 | 0 | -9.65% | no_exit_data |
| 2368 | 2026-05-14 | 2026-05-15 | 2026-05-15 | 0 | -11.80% | no_exit_data |
| 6510 | 2026-05-14 | 2026-05-15 | 2026-05-15 | 0 | -11.83% | no_exit_data |

## 📈 Equity Curve (final state)

- 起始資金: $1,000,000
- 最終資金: $54,358,409,616,138,449,875,847,157,807,180,271,226,432,126,097,572,112,459,962,226,049,024
- 總報酬率: **5435840961613844604086686145089101385996312505004546888279523328.00%**
- 最低資金 (回撤底部): $949,103

## 📋 Signal Stats

- Total signals: 8480
- Unique stocks: 30
- Date range: 2023-01-03 → 2026-05-15
