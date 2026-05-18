# 📊 Backtest 完整使用指南

> 起漲前觀察 screener 的歷史回測系統 — 從零到產出完整績效報告

---

## 📑 目錄

1. [系統架構](#1-系統架構)
2. [前置準備](#2-前置準備)
3. [Step 1: 快速試跑（10 分鐘）](#3-step-1-快速試跑10-分鐘)
4. [Step 2: 完整回測（建議流程）](#4-step-2-完整回測建議流程)
5. [Step 3: 解讀報告](#5-step-3-解讀報告)
6. [Step 4: 進階調參](#6-step-4-進階調參)
7. [指令完整參考](#7-指令完整參考)
8. [Go/No-Go Gates 說明](#8-gono-go-gates-說明)
9. [常見問題](#9-常見問題)
10. [檔案位置一覽](#10-檔案位置一覽)

---

## 1. 系統架構

```
┌─────────────────────────────────────────────────────────────┐
│  FinMind / yfinance API                                      │
│         ↓                                                    │
│  download_history.py  ──→  historical_data.db (SQLite)      │
│                                  │                           │
│                                  ↓                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  run_backtest.py 主流程                              │   │
│  │  ─────────────────────────────────────────           │   │
│  │  1. signal_replay  (point-in-time, no lookahead)    │   │
│  │       ↓ writes signals to backtest_signals          │   │
│  │  2. trade_simulator (entry T+1 open, 3 exit rules)  │   │
│  │       ↓ writes trades to backtest_trades            │   │
│  │  3. metrics + report_generator                      │   │
│  │       ↓ outputs Markdown + CSV                      │   │
│  └──────────────────────────────────────────────────────┘   │
│         ↓                ↓                                  │
│   report.md          trades.csv                              │
└─────────────────────────────────────────────────────────────┘
```

### 核心保證

- ✅ **No Lookahead Bias** — `get_ohlcv_as_of` 嚴格只取 ≤ cutoff date 的資料；通過 `test_no_lookahead_bias_in_signal_replay` 驗證
- ✅ **真實成本模型** — 0.1425% 手續費 ×2 + 0.3% 證交稅 + 0.1% 雙邊 slippage
- ✅ **三種出場規則** — Stop Loss / Target Reached / Max Hold Days（whichever fires first）
- ✅ **漲停買不到模擬** — 隔日開盤即漲停 9.5%+ 標記為 SKIPPED_LIMIT_UP
- ✅ **AI 科技股 sector tag** — 6-Layer Framework 自動分群

---

## 2. 前置準備

### 2.1 確認環境

所有指令從 **repo root** 執行：

```powershell
cd "c:\Users\09068\OneDrive\文件\GitHub\ai-stock"
```

確認 venv 可用：

```powershell
.venv\Scripts\python.exe --version
# 應該顯示 Python 3.12.x
```

確認測試通過（敏感度檢查）：

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_backtest.py -q
# 應該 14 passed
```

### 2.2 （可選）FinMind API Key

免費版額度約 600 次/日。如果有 API Key，建立 `backend/.env`：

```env
FINMIND_API_KEY=your_token_here
```

沒 API Key 也可以跑 — 系統會自動 fallback 到 yfinance。

---

## 3. Step 1: 快速試跑（10 分鐘）

**目標**：用 3 檔股票 × 500 天驗證整個 pipeline 沒問題。

### 3.1 下載小資料集

```powershell
.venv\Scripts\python.exe -m backend.scripts.download_history `
  --stocks 2330 6669 3661 `
  --days 500 `
  --verbose
```

**預期輸出**：
```
[INFO] Downloading 3 stocks, ~500 days each, to .../historical_data.db
[INFO] (1/3) downloading 2330...
[INFO]   → wrote 500 rows
[INFO] (2/3) downloading 6669...
[INFO]   → wrote 500 rows
[INFO] (3/3) downloading 3661...
[INFO]   → wrote 500 rows
[INFO] Done. Wrote 1500 total rows in ~7 seconds.
```

### 3.2 確認資料進 DB

```powershell
.venv\Scripts\python.exe -c "from backend.app.services.backtest.historical_data_store import HistoricalDataStore; s = HistoricalDataStore(); print(f'總列數: {s.row_count()}, 股票: {s.list_stocks()}')"
```

### 3.3 跑試跑 backtest

⚠️ **重要：日期區間要對齊你下載的資料範圍**

如果 `--days 500` 是從今天往回抓，yfinance 通常回傳的是**最近一年多**的資料（從 2025-01 左右開始）。所以 `--start` 不能寫 2024，要寫 2025-08 之後（前 7 個月當暖機期）。

確認你的資料區間：
```powershell
.venv\Scripts\python.exe -c "from backend.app.services.backtest.historical_data_store import HistoricalDataStore; s = HistoricalDataStore(); dates = s.get_all_trading_dates('2020-01-01', '2030-12-31'); print(f'資料區間: {dates[0]} → {dates[-1]} (共 {len(dates)} 天)')"
```

然後選暖機期之後的日期當 `--start`（建議 +150 trading days 給 EMA/range_90d 暖機）：

```powershell
.venv\Scripts\python.exe -m backend.scripts.run_backtest `
  --start 2025-08-01 `
  --end 2026-05-15 `
  --stocks 2330 6669 3661 `
  --hold-days 20 `
  --stop-loss 0.07 `
  --target 0.15 `
  --output quick_test_report.md `
  --csv-output quick_test_trades.csv `
  --verbose
```

**預期輸出**：
```
[INFO] Backtest universe size: 3 stocks
[INFO] Step 1: replaying signals...
[INFO] Replay done: 12 signals over 240 days
[INFO] Step 2: simulating trades...
[INFO] Simulation done: 11 filled, 1 skipped, win_rate=45.45%, avg_return=2.31%
[INFO] Report saved to quick_test_report.md
```

### 3.4 開啟報告

```powershell
notepad quick_test_report.md
# 或用 VSCode 預覽
code quick_test_report.md
```

✅ 看到 Markdown 報告 → pipeline 正常，可進 Step 2。

---

## 4. Step 2: 完整回測（建議流程）

### 4.1 下載 33 檔 AI 科技股 4 年資料

```powershell
.venv\Scripts\python.exe -m backend.scripts.download_history `
  --days 1500 `
  --rate-limit 0.8 `
  --verbose
```

**時間**：約 30-60 分鐘（依 FinMind 速度）。**可放著去做別的事**。

**中斷重跑無妨** — script 是 idempotent，已下載的不會重抓。

### 4.2 跑完整回測

⚠️ **先確認你的資料區間**（yfinance 通常從 ~2022-04 開始）：

```powershell
.venv\Scripts\python.exe -c "from backend.app.services.backtest.historical_data_store import HistoricalDataStore; s = HistoricalDataStore(); dates = s.get_all_trading_dates('2020-01-01', '2030-12-31'); print(f'資料區間: {dates[0]} → {dates[-1]}')"
```

然後**留 150 天暖機**，從資料起始日的 9 個月後開始回測：

```powershell
.venv\Scripts\python.exe -m backend.scripts.run_backtest `
  --start 2023-01-01 `
  --end 2026-05-15 `
  --hold-days 20 `
  --stop-loss 0.07 `
  --target 0.15 `
  --output backtest_full.md `
  --csv-output trades_full.csv `
  --verbose
```

**時間**：約 5-15 分鐘（33 檔 × 850 交易日 × 起漲前評估）。

### 4.3 開報告

```powershell
code backtest_2022_2024.md
```

---

## 5. Step 3: 解讀報告

報告會有以下章節：

### 5.1 Configuration

回測參數摘要 — 確認你跑的版本。

### 5.2 Performance Metrics（核心）

| 指標 | 含義 | 目標 |
|------|------|------|
| n_trades | 總交易筆數 | 至少 30+ 才有統計顯著性 |
| **win_rate** | 勝率 | ≥ 45% |
| **avg_return** | 平均報酬（含成本） | > 1.5% |
| std_return | 報酬標準差 | 越小越好 |
| **Profit Factor** | 總獲利 ÷ 總虧損 | ≥ 1.3 |
| **Expectancy** | (勝率×平均贏)-(敗率×平均輸) | > 0 |
| **Sharpe Ratio** | 風險調整報酬（年化） | > 1.0 |
| Sortino Ratio | 只看下行風險的 Sharpe | > 1.5 |
| **Max Drawdown** | 最大資金回撤 | ≤ 25% |

### 5.3 Go/No-Go Gates

報告自動列出 4 道 Gate 的通過狀態：

```
✅ Win Rate ≥ 45%: threshold = ≥ 45%, actual = 48.20%
✅ Profit Factor ≥ 1.3: threshold = ≥ 1.3, actual = 1.65
✅ Max Drawdown ≤ 25%: threshold = ≤ 25%, actual = 18.40%
✅ Expectancy > 0: threshold = > 0, actual = 1.85%
```

**判讀**：
- **4 道全過** → 策略有 edge，但還要 walk-forward 驗證才能真錢
- **過 3 道** → 邊緣，需要調參數
- **過 ≤ 2 道** → 策略本身有問題，重新檢視 rules

### 5.4 Exit Reason Breakdown

各種出場原因的分布：

```
| exit_reason          | n_trades | win_rate | avg_return |
| -------------------- | -------- | -------- | ---------- |
| target_reached       | 25       | 100.00%  | 14.20%     |
| stop_loss_triggered  | 18       | 0.00%    | -7.50%     |
| hold_days_expired    | 12       | 41.67%   | 0.80%      |
```

**判讀**：
- target 比例高 → 賺得快，獲利目標可能設太低
- stop 比例高 → 太多假突破，setup 規則要更嚴
- hold_days 比例高 → 持有期可能太長

### 5.5 Sector Breakdown（依 6-Layer Framework）

```
| sector_category           | n_trades | win_rate | avg_return |
| ------------------------- | -------- | -------- | ---------- |
| cat_3_packaging           | 18       | 61.11%   | 4.20%      |
| cat_5_system_integration  | 14       | 50.00%   | 1.80%      |
| cat_1_silicon_ip          | 10       | 40.00%   | -0.50%     |
```

**判讀**：哪一層 AI 鏈最適合這個策略？通常 Cat 3 先進封裝（瓶頸層）表現最強。

### 5.6 Top 5 Winners / Losers

人工檢視 → 找贏家共通模式（強化規則）/ 找輸家共通模式（加 filter）。

### 5.7 Equity Curve

```
- 起始資金: $1,000,000
- 最終資金: $1,342,500
- 總報酬率: 34.25%
- 最低資金 (回撤底部): $895,000
```

---

## 6. Step 4: 進階調參

### 6.1 持有期掃描

```powershell
# 5/10/20/30 日持有期比較
foreach ($h in 5, 10, 20, 30) {
    .venv\Scripts\python.exe -m backend.scripts.run_backtest `
      --start 2022-01-01 --end 2024-12-31 `
      --hold-days $h `
      --output "report_hold${h}.md" `
      --run-id "hold_$h"
}
```

### 6.2 停損 / 目標 grid search

```powershell
foreach ($sl in 0.05, 0.07, 0.10) {
    foreach ($tg in 0.12, 0.15, 0.20, 0.25) {
        .venv\Scripts\python.exe -m backend.scripts.run_backtest `
          --start 2022-01-01 --end 2024-12-31 `
          --stop-loss $sl --target $tg `
          --output "report_sl${sl}_tg${tg}.md" `
          --run-id "sl${sl}_tg${tg}"
    }
}
```

### 6.3 單一 sector 隔離測試

```powershell
# 只測 Cat 3 先進封裝（瓶頸層）
.venv\Scripts\python.exe -m backend.scripts.run_backtest `
  --start 2022-01-01 --end 2024-12-31 `
  --stocks 3711 2449 3583 3680 6223 6510 6147 `
  --output report_cat3_packaging.md `
  --run-id cat3_isolated
```

```powershell
# 只測 Cat 5 ODM
.venv\Scripts\python.exe -m backend.scripts.run_backtest `
  --start 2022-01-01 --end 2024-12-31 `
  --stocks 2382 3231 6669 2317 2356 2308 `
  --output report_cat5_odm.md `
  --run-id cat5_isolated
```

### 6.4 跨年度切割（Walk-Forward 雛形）

```powershell
# 2022 in-sample
.venv\Scripts\python.exe -m backend.scripts.run_backtest --start 2022-01-01 --end 2022-12-31 --output report_2022.md --run-id is_2022

# 2023 in-sample
.venv\Scripts\python.exe -m backend.scripts.run_backtest --start 2023-01-01 --end 2023-12-31 --output report_2023.md --run-id is_2023

# 2024 out-of-sample
.venv\Scripts\python.exe -m backend.scripts.run_backtest --start 2024-01-01 --end 2024-12-31 --output report_2024.md --run-id oos_2024
```

**比對**：2022/2023 績效 vs 2024 績效，**衰減 < 30%** 才算 robust。

---

## 7. 指令完整參考

### 7.1 `download_history.py`

| 參數 | 說明 | 預設 |
|------|------|------|
| `--stocks` | 指定股票（空白分隔） | 讀 AI 白名單 |
| `--universe-file` | 白名單 JSON 路徑 | `backend/data/sectors/ai_tech_tw.json` |
| `--days` | 從今天往回抓幾天 | 1500 (~4 年) |
| `--db` | SQLite 路徑 | `backend/historical_data.db` |
| `--rate-limit` | 每次請求間隔秒數 | 0.5 |
| `--verbose / -v` | 詳細 log | False |

### 7.2 `run_backtest.py`

| 參數 | 說明 | 預設 |
|------|------|------|
| `--start` | 回測起日 YYYY-MM-DD | **必填** |
| `--end` | 回測終日 YYYY-MM-DD | **必填** |
| `--stocks` | 指定股票（蓋掉 universe） | 用 AI 白名單 |
| `--universe-file` | 白名單 JSON | `backend/data/sectors/ai_tech_tw.json` |
| `--candidate-types` | 要追蹤的分類 | `起漲前觀察` |
| `--hold-days` | 最長持有天數 | 20 |
| `--stop-loss` | 停損百分比 | 0.07 |
| `--target` | 獲利目標百分比 | 0.15 |
| `--commission` | 單邊手續費 | 0.001425 |
| `--tax` | 賣方證交稅 | 0.003 |
| `--slippage` | 單邊滑點 | 0.001 |
| `--db` | SQLite 路徑 | `backend/historical_data.db` |
| `--output` | Markdown 報告路徑 | `backtest_report.md` |
| `--csv-output` | CSV trades 輸出 | 不輸出 |
| `--run-id` | 自訂 run ID | auto-generate |
| `--verbose / -v` | 詳細 log | False |

### 7.3 指定多種 candidate_type

```powershell
.venv\Scripts\python.exe -m backend.scripts.run_backtest `
  --start 2024-01-01 --end 2024-12-31 `
  --candidate-types 起漲前觀察 初動候選 動能確認 `
  --output report_all_signals.md
```

---

## 8. Go/No-Go Gates 說明

報告中自動評估的 4 道閘門 — **每道都過了**才能往下一階段：

### Gate 1: Win Rate ≥ 45%
**意義**：勝率太低（< 45%）代表 setup 訊號雜訊太多，賺一筆要靠運氣。

**不過的話**：把起漲前觀察規則改更嚴（提高 score min, 加 sector resonance）。

### Gate 2: Profit Factor ≥ 1.3
**意義**：賺的錢/賠的錢 ≥ 1.3 倍。低於 1.3 代表「贏的時候賺不多 / 輸的時候賠太兇」。

**不過的話**：調 target/stop 比例。例如 target 0.15 / stop 0.07 = 2.14:1。

### Gate 3: Max Drawdown ≤ 25%
**意義**：最差時資金縮水 ≤ 25%。超過代表單一連續虧損就讓策略爆。

**不過的話**：加 concurrent positions limit、加大盤過濾 (TAIEX < 200ma 不執行)。

### Gate 4: Expectancy > 0
**意義**：每筆交易的數學期望值為正。為負代表平均下來必虧。

**不過的話**：根本問題，setup 沒 edge，重新檢視策略。

---

## 9. 常見問題

### Q1: FinMind rate limit 被 ban
```
[WARNING] Fetch failed for XXX: 402 Client Error
```
**解法**：
- 加大 `--rate-limit 1.5`（每 1.5 秒抓一檔）
- 申請免費 FinMind API Key 放 `.env`
- 等 24 小時讓額度回復後重跑

### Q2: 報告顯示 0 signals
**可能原因**：
- 區間太短（< 60 天）
- 規則太嚴沒股票通過
- 該段市場處於大空頭

**解法**：
- 拉長區間
- 試跑 `--candidate-types 起漲前觀察 初動候選 動能確認 偏熱觀察` 看哪一類有訊號
- 檢查 rules_v1.yaml 參數

### Q3: 某些 trade 顯示 SKIPPED
**原因**：
- `SKIPPED_NO_NEXT_DAY` — 訊號在最後一個交易日，沒下一天可進
- `SKIPPED_OPEN_LIMIT_UP` — 隔日開盤即漲停買不到

**這是正常的**，反映真實市場無法成交的場景。

### Q4: 結果太完美，懷疑有 lookahead bias
**確認方式**：跑 `test_no_lookahead_bias_in_signal_replay`：

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_backtest.py::test_no_lookahead_bias_in_signal_replay -v
```

通過 → 系統沒偷看未來。

### Q5: 中文亂碼
**Windows PowerShell**：
```powershell
chcp 65001
$OutputEncoding = [System.Text.Encoding]::UTF8
```

### Q6: 想清空 DB 重跑
```powershell
Remove-Item backend\historical_data.db -Force
# 然後重新 download_history
```

### Q7: 想看某一個 run 的詳細 trades
```powershell
.venv\Scripts\python.exe -c "from backend.app.services.backtest.trade_simulator import load_trades; df = load_trades('backend/historical_data.db', 'YOUR_RUN_ID'); print(df.head(20))"
```

---

## 10. 檔案位置一覽

```
ai-stock/
├── backend/
│   ├── historical_data.db                      ← SQLite 歷史資料（gitignore）
│   │
│   ├── app/services/backtest/
│   │   ├── historical_data_store.py            ← OHLCV cache
│   │   ├── signal_replay.py                    ← point-in-time signal replay
│   │   ├── trade_simulator.py                  ← entry/exit + cost model
│   │   ├── metrics.py                          ← Sharpe / DD / PF 等
│   │   └── report_generator.py                 ← Markdown / CSV
│   │
│   ├── scripts/
│   │   ├── download_history.py                 ← 下載歷史資料 CLI
│   │   └── run_backtest.py                     ← 主回測 CLI
│   │
│   ├── data/sectors/
│   │   └── ai_tech_tw.json                     ← 6-Layer AI 白名單
│   │
│   ├── technical_analyzer/v1/registry/
│   │   └── rules_v1.yaml                       ← 起漲前觀察規則
│   │
│   └── tests/
│       └── test_backtest.py                    ← 14 個回測測試
│
├── (產出檔案 — 放 repo root 或 gitignore)
│   ├── quick_test_report.md
│   ├── backtest_2022_2024.md
│   └── trades_2022_2024.csv
│
└── Backtest.md                                 ← 本文件
```

---

## 🎯 推薦學習路徑

### 第一週：熟悉系統
1. Step 1 快速試跑（10 分鐘）
2. 看 `quick_test_report.md` 每個欄位
3. 跑 6.1 持有期掃描，感受參數影響

### 第二週：完整回測
1. Step 2 下載 4 年資料（30-60 分鐘）
2. 跑 2022-2024 完整 backtest
3. **檢視 4 道 Gate** — 過了幾道？
4. 跑 6.3 sector 隔離測試 — 哪一層 AI 鏈最強？

### 第三週：Walk-Forward 雛形
1. 跑 6.4 跨年度切割
2. 比對 2022/2023 in-sample vs 2024 out-of-sample
3. 衰減 < 30% → 策略 robust；衰減 > 50% → overfitting

### 第四週：放真錢前
1. **Phase 2 walk-forward 嚴格框架**（之後再做）
2. **MCPT 蒙地卡羅排列檢定**（之後再做）
3. **Paper trading 3 個月**
4. 都過了才用 **總資金 < 5%** 的 size 試水溫

---

## 📞 想做下一步？

| 目前狀態 | 建議下一步 |
|---------|----------|
| 還沒下載資料 | Step 1 快速試跑 |
| 跑完 quick test | Step 2 完整下載 + 4 年 backtest |
| 跑完完整 backtest，過 3-4 道 Gate | 6.4 跨年度切割看 walk-forward 衰減 |
| 過 ≤ 2 道 Gate | 調參數 → 6.1 / 6.2 grid search |
| Walk-forward 也過 | 加 walk_forward.py 嚴格框架（Phase 2） |
| 嚴格 WF 也過 | Paper trading 3 個月 |

---

*本文件由起漲前觀察 backtest 框架自動產出。任何 bug、改善建議歡迎反饋。*
