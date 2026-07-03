# CLAUDE.md

本檔是每個 session 的開機記憶。以下是**上市等級的工程紀律**，不是建議。

## 專案定位

台股個人投資研究平台（**已上線營運**）：AI 四面向個股分析 + 每日三桶選股（研究實證驅動）+ 美股輔助。
- 前端 https://ai-stock-rosy-eight.vercel.app （Vercel，push 自動部署）
- 後端 https://ai-stock-backend-akxd.onrender.com （Render 免費層，push 自動部署；閒置休眠、冷啟動 30-50 秒）
- Repo **私有**。金鑰經擁有者同意存於 render.yaml；**轉公開前必須先撤光金鑰**（歷史教訓：公開 repo 的 Gemini 金鑰數分鐘內被 Google 偵測撤銷）。

## Repo 佈局

- `backend/` — Python FastAPI；venv 在 repo 根 `.venv/`（**Windows**：`.venv/Scripts/python.exe`）
- `ai-stock-frontend/` — Next.js 16 App Router（TypeScript + Tailwind v4）
- `Docs/research/` 策略研究報告、`Docs/planning/` 計畫、`Docs/backtest/experiments_ledger.md` **實驗總帳**、`Docs/orchestration/agents-archive/` 歷代代理定義
- `backend/historical_data.db`（OHLCV 2003-，962MB）+ `backend/pit_fundamentals.db`（月營收/法人/PER/財報含 filing_date，9.2GB）＝**正典資料庫**（gitignored、只在本機；根目錄 `refresh_data.py` 更新）

## 指令（Windows；一律從 repo 根執行使 `backend.app...` 可解析）

```bash
# 後端測試（全套 ~26 分；平時跑受影響子集）
.venv/Scripts/python.exe -m pytest backend/tests/ -q
.venv/Scripts/python.exe -m pytest backend/tests/test_tw_indicators.py::test_rsi_warmup_is_none -q
# 前端型別檢查（無測試套件；這是前端最低關卡）
cd ai-stock-frontend && npx tsc --noEmit
# 本機 dev
.venv/Scripts/uvicorn backend.app.main:app --reload --port 8000
cd ai-stock-frontend && npm run dev
# 回測引擎（本機，讀正典資料庫；直接跑模組需 PYTHONPATH=.）
.venv/Scripts/python.exe backend/scripts/run_opportunities_backtest.py
```

`backend/pytest.ini` 設 `asyncio_mode = auto`（async 測試免 marker）。

## 架構

### 後端管線
`/analyze`（美股）與 `/analyze/tw`（台股）走 LangGraph 圖（`backend/app/graphs/`）+ 服務層（`backend/app/services/`，命名 `{provider}_{domain}.py`：`fmp_*` 美股、`finmind_*` 台股、`tw_*` 台股聚合運算）。

**AI 呼叫鐵則：每次分析只有 2 次呼叫**——主摘要（tw_stock_graph）+ `tw_unified_analysis.py` 的**單次整合呼叫**（四面向敘述+綜合，結構化欄位由程式從原始資料確定性計算）。不得回退成多 agent 逐面向呼叫（374 秒慘案根源）。equity_research 節點預設關（`TW_EQUITY_RESEARCH`）。

### AI 供應商（三家可切換，解析器在 `services/gemini_diagnostics.py`）
- `TW_AI_MODEL` 主摘要（現役 `anthropic:claude-sonnet-4-6`）、`TW_AI_MODEL_UNIFIED` 整合呼叫（現役 haiku，快 2-3 倍）
- 格式 `anthropic:…`/`openai:…`/`google-gla:…`；金鑰閘門 `ai_key_available()` 依前綴查對應 env（Gemini 亦接受 `GOOGLE_API_KEY`）
- 成本 ~NT$1/檔·日；`file_cache` 以（symbol, UTC日）快取，**只快取 AI 成功回應**（mock 永不釘死）
- 現況：Claude 主力、Gemini 備援（免費 ~10 RPM）、OpenAI 空槽

### 資料層（誠實資料契約）
- 外部服務失敗一律優雅降級：回 mock/空 + `is_mock`/`data_source`/`status` 旗標，**永不 crash、mock 永不混充真資料**；缺資料回 `status:"no_data"` 與空陣列，不捏數字。
- 台股基本面走 FinMind 真實 dataset（MonthRevenue/PER/FinancialStatements/BalanceSheet/CashFlows）。dataset `TaiwanStockFinancials` **不存在**，勿用。
- 全市場批量走 TWSE 官方免費接口（STOCK_DAY_ALL / BWIBBU_ALL / RWD T86）——FinMind 免費層不支援省略 data_id 的按日批量。
- 雲端**沒有**正典資料庫：依賴它的功能須有雲端 fallback（如 heatmap 的 TWSE fallback）或誠實顯示無資料（screener）。

### 前端
單一 client page（`app/page.tsx`）+ 側欄視圖切換；portfolio/watchlist 僅存 localStorage。圖表用 lightweight-charts v5（`addSeries(SeriesType, options)` API）；`PriceHistoryChart` 多 pane 共享時間軸——**不要呼叫 `fitContent()`**（會蓋掉 bar spacing）。Next.js 16 與訓練資料有落差：動 routing/layout/config 前先讀 `node_modules/next/dist/docs/`。

### 台股特定
- 指標是純數學（`services/tw_indicators.py`），輸出與輸入等長、暖機期用 None；K 線粒度 `tw_candles.py`（range=D/W/M/Y，指標算在聚合後序列上）。
- ETF 持股（0050/0056/00878/00919）是策展 mock；未知 ETF 回 `status:"unsupported"`。
- Telegram bot 用 SQLite（`backend/telegram_watchlist.db`，勿 commit）。

## 量化紀律（違反即結論作廢）

1. **PIT 時點**：月營收＝所屬月+1 月 10 日後可見；財報用 `filing_date`；法人買賣超 T 日盤後可見。
2. **回測防線**：訊號日**次日開盤**進場；扣來回成本 0.585%；分年度看穩定性；事件去重。
3. **基準**：選股力用「可買池中位數」對照組；市值加權 TAIEX 僅脈絡參考（拿個股中位比 TAIEX 是量尺錯配）。
4. **樣本外**：dev 2012-2021 / OOS 2022-2026-06。**OOS 已於 2026-07-02 開封一次**——之後任何規則變更不得再以同一 OOS 宣稱驗證。
5. 門檻**事前註冊**；每次實驗（含失敗）記入 `Docs/backtest/experiments_ledger.md`；同一假設最多調參一次。
6. **驗證現況**（動「每日交易機會」前必讀）：長線桶 dev+OOS 雙過（OOS A 級 T+250 中位超額 +5.36%）；中線桶 OOS 陣亡（T+60≈0）；已知偏誤：未還原除息（保守向）、下市覆蓋僅 ~184 檔（略高估）。
7. 未經稽核的結果必標「尚未稽核，不可採信」。

## 使用者面鐵則

- **verb-free**：使用者面字串不得出現買/賣/持有/目標價/停損等指令詞——只描述條件與數據。
- 免責聲明「本分析僅供參考，不構成投資建議。」必須保留。
- AI 輸出一律 PydanticAI 結構化 JSON（宣告 `output_type`）。
- UI 慣例：台股**紅漲綠跌**、數字 `tabular-nums`、繁體中文、暗色模式兩套都顧、RWD 必查（使用者主要用手機）。

## Schema 規則（Pydantic v2）

`backend/app/models/schemas.py` 是唯一真源。既有回應模型加欄位必須 **optional + nullable**（向下相容）；本檔內 forward reference 自動解析。

## 測試鐵則（省錢保命）

- AI 閘門測試必須清光**所有**供應商 env：`GEMINI_API_KEY, ANTHROPIC_API_KEY, TW_AI_MODEL, TW_AI_MODEL_UNIFIED`——只清 Gemini 會真的打 Claude API（燒錢 + 25 分鐘）。
- 改「每日交易機會」邏輯 → 本機用**新股票代號**測（當日快取會掩蓋改動）。

## 部署與發布

1. 改動 → 受影響測試 + `tsc` 過 → commit（訊息講 why）→ push `001-mvp-stock-analysis`。
2. push 即自動部署（Render 3-8 分、Vercel 1-2 分）。**雲端相依改 `backend/requirements-deploy.txt`**——`requirements.txt` 是 Windows freeze（含 pywin32），雲端裝不起，勿用於部署。
3. **上線驗證迴圈（宣稱完成前必跑）**：`/health` 200 → 未快取代號打 `/analyze/tw` 確認 `analysis_source:"ai"` 且 <90 秒（Render 代理 ~100 秒上限）→ 前端實際載入。
4. 回滾＝`git revert` + push。
5. 機密：`backend/.env` **永不 commit**（含 GitHub PAT 等高危金鑰）。

## 已知陷阱（都是真實踩過的）

- `load_dotenv` **不覆蓋**既有 OS 環境變數——.env 改了沒生效先查這個（曾被已撤銷的殭屍金鑰騙過）。
- 外部 API 401/403 先 `curl` 直測金鑰本身（供應商會主動撤銷）；金鑰格式不做預判（`AQ.` 開頭也是合法 Gemini 金鑰）。
- `NEXT_PUBLIC_*` build 時固化——改後端網址要重 build 前端（`ai-stock-frontend/.env.production` 已入版控）。
- PowerShell 5.1：無 `&&`；原生 exe 的 stderr 會顯示成假錯誤（git push 成功也一片紅，看實際輸出判斷）。
- Windows App Control 擋未簽章 exe（nlm.exe 案例：改用 pip 套件以 python 跑入口函式）。

## 委派原則（主 session 減負）

超過 ~10 次搜尋/讀檔的任務派子代理：researcher（查證，Gemini 引擎）/ auditor（稽核，Opus）/ designer（介面，Sonnet）/ debugger（除錯，codex 引擎）。重要結論用全域 `gpt "<問題>"` 取 GPT 二意見。金融格式產出（論文/估值/財報）優先用官方金融插件。主 session 保留：決策、整合、部署、記憶。
