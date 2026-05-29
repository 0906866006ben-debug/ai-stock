# AI Stock Assistant

台股與美股 AI 交易分析決策支援平台。後端以 FastAPI 整合多來源市場資料、基本面、技術面、籌碼面與消息面，前端以 Next.js 提供左側工具列式儀表板。系統的核心目標不是直接喊買賣，而是把「資料、證據、風險、失效條件」整理成可檢查的決策卡。

本文件整理日期：2026-05-13。

> 免責聲明：本系統僅作分析支援與研究用途，不構成投資建議。

---

## 專案定位

本專案是一個以台股為主、美股為輔的 AI 股票分析平台。它目前包含：

- 台股個股分析：基本面、技術面、籌碼面、消息面
- 台股 AI 分析：三軸分數、三時序判讀、情境劇本、證據鏈、Wyckoff / 道氏結構、扣抵值、深度報告
- 美股分析：價格、新聞、財務摘要、基本面、同業比較
- 投資組合：持倉、成本、損益、報酬率
- 股票目錄：台股代碼、名稱、市場別、產業篩選
- 市場新聞：大盤、利率、匯率、產業、國際、原物料、地緣、政策
- 行事曆：除息與財報申報時間
- 自選清單與最近搜尋
- Telegram watchlist 同步接口

所有外部 API 都設計為可選。沒有金鑰時，後端會使用 mock / fallback 資料，讓前後端可以完整跑起來。

---

## 系統架構

```text
ai-stock/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                  # FastAPI 路由入口
│  │  ├─ models/schemas.py        # Pydantic response/request schema
│  │  ├─ graphs/                  # LangGraph 分析流程
│  │  │  ├─ stock_analysis_graph.py
│  │  │  ├─ tw_stock_graph.py
│  │  │  └─ comprehensive_analysis_graph.py
│  │  ├─ agents/                  # Gemini/PydanticAI 四大面向代理
│  │  │  ├─ fundamental_agent.py
│  │  │  ├─ technical_agent.py
│  │  │  ├─ chip_agent.py
│  │  │  ├─ news_agent.py
│  │  │  ├─ synthesis_agent.py
│  │  │  └─ equity_research_agent.py
│  │  └─ services/                # 市場資料、技術指標、新聞、Telegram
│  └─ tests/                      # pytest 測試
├─ ai-stock-frontend/
│  ├─ app/
│  │  ├─ page.tsx                 # 主要 dashboard，左側工具列
│  │  ├─ ai-analysis/[symbol]/    # AI 分析直接路由
│  │  └─ components/
│  │     ├─ ai-analysis/          # 新版 7 層 AI 決策介面
│  │     └─ *.tsx                 # 股票分析、目錄、新聞、持倉等元件
│  ├─ hooks/useAIAnalysis.ts
│  ├─ lib/
│  │  ├─ api.ts                   # 前端 API client
│  │  ├─ types.ts                 # 一般前端資料型別
│  │  └─ ai-analysis/             # AI 分析 transformer / constants / mock
│  └─ types/aiAnalysis.ts         # Topics A-E 前端資料合約
├─ Docs/                          # 專案文件、規劃、prompt、知識庫
│  ├─ README.md                   # 文件索引
│  ├─ backtesting/Backtest.md     # 回測完整使用指南
│  ├─ planning/                   # 演進規格與升級計畫
│  └─ agent-prompts/              # Codex / Claude 交接 prompt
└─ README.md
```

---

## 技術棧

| 層級 | 使用技術 |
|---|---|
| Backend | Python、FastAPI、Pydantic v2、httpx、yfinance、LangGraph、PydanticAI |
| Frontend | Next.js 16、React 19、TypeScript、Tailwind CSS v4 |
| Charts | lightweight-charts v5、Plotly、Recharts |
| AI | Google Gemini 2.5 系列，無 key 時 fallback |
| 台股資料 | FinMind、Yahoo Finance、mock fallback |
| 美股資料 | yfinance、FMP、Finnhub、SerpApi fallback、mock fallback |
| 儲存 | 前端 localStorage；Telegram watchlist 使用本機 SQLite 概念接口 |

---

## 快速啟動

### 1. Backend

從專案根目錄執行：

```powershell
cd "C:\Users\09068\OneDrive\文件\GitHub\ai-stock"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn python-dotenv httpx pydantic pydantic-ai langgraph yfinance pandas numpy pytest pytest-asyncio pytest-httpx
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

Backend URL：

```text
http://localhost:8000
```

Health check：

```powershell
Invoke-RestMethod http://localhost:8000/health
```

預期：

```text
status = ok
version = 3.0.0
```

### 2. Frontend

```powershell
cd "C:\Users\09068\OneDrive\文件\GitHub\ai-stock\ai-stock-frontend"
npm.cmd install
npm.cmd run dev
```

Frontend URL：

```text
http://localhost:3000
```

如果 `node` 或 `npm` 找不到，請先安裝 Node.js LTS：

```powershell
winget install OpenJS.NodeJS.LTS
```

如果 PowerShell 擋住 `npm.ps1`，請使用：

```powershell
npm.cmd run dev
```

---

## 環境變數

### Backend `.env`

所有金鑰都是可選。空白時會走 mock / fallback。

| 變數 | 用途 | 狀態 |
|---|---|---|
| `GEMINI_ENABLED` | 是否啟用 Gemini，設為 `false` 可強制 fallback | 已使用 |
| `GEMINI_MODEL` | Gemini 主模型，預設概念為 `gemini-2.5-flash` | 已使用 |
| `GEMINI_FALLBACK_MODELS` | Gemini 備援模型清單，逗號分隔 | 已使用 |
| `GEMINI_API_KEY` | AI 分析、四大面向、研究報告 | 已使用 |
| `FMP_API_KEY` | 美股基本面、同業比較、市場概覽 | 已使用 |
| `FINNHUB_API_KEY` | 美股新聞 | 已使用 |
| `FINMIND_API_KEY` | 台股價格、公司資料、財務、籌碼、股利、ETF | 已使用 |
| `SERPAPI_KEY` | 台股/美股新聞搜尋 fallback | 程式有讀取，建議補進 `.env.example` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot 發送訊息 | 已使用 |
| `TELEGRAM_WEB_CHAT_ID` | Web UI 同步 Telegram watchlist 的 chat id | 已使用 |
| `POLYGON_API_KEY` | 美股資料來源保留欄位 | 目前 README/舊設定保留，程式內未見主要讀取 |

建議 `.env.example` 最終整理成：

```env
GEMINI_ENABLED=true
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=
GEMINI_API_KEY=

FMP_API_KEY=
FINNHUB_API_KEY=
POLYGON_API_KEY=
SERPAPI_KEY=

FINMIND_API_KEY=

TELEGRAM_BOT_TOKEN=
TELEGRAM_WEB_CHAT_ID=
```

### Frontend `.env.local`

| 變數 | 用途 | 預設 |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | 前端呼叫後端 API 的 base URL | `http://localhost:8000` |

---

## 前端 localStorage 變數

前端目前以瀏覽器 localStorage 保存使用者狀態。

| Key | 用途 |
|---|---|
| `stockAssistant.positions` | 投資組合持倉 |
| `stockAssistant.favorites` | 自選清單 |
| `stockAssistant.recents` | 最近搜尋 |

---

## 左側工具列與頁面排版

主畫面是 dashboard 型排版：左側工具列、上方標題列、右側內容區。

| 頁面 | 內容 |
|---|---|
| `AI 分析` | AI 判讀、三軸、三時序、情境、證據鏈、結構、深度報告 |
| `股票分析` | 基本面、技術面、籌碼面、消息面 |
| `投資組合` | 持倉、市值、損益、報酬率、刪除、點選分析 |
| `股票目錄` | 台股代碼/名稱、市場別、產業、搜尋、自選 |
| `市場新聞` | 8 大市場環境新聞分類 |
| `行事曆` | 股利除息與財報申報時程 |
| `自選清單` | Favorites 與最近搜尋 |
| `新增持倉` | 新增股票代碼、公司名稱、張/股、成本、日期 |

### 股票分析頁排版

`股票分析` 是資料面，負責呈現股票本身的四大面向。

| 區塊 | 內容 |
|---|---|
| 基本面 | 股票編號、名稱、分類、開盤、收盤、最高、最低、成交量、營收、估值、ETF 持股 |
| 技術面 | K 線圖、日/週/月/年、MA、RSI、MACD、成交量 |
| 籌碼面 | 外資、投信、自營商、融資、融券、借券、籌碼風險 |
| 消息面 | 個股新聞摘要、recent news、消息催化與風險 |

### AI 分析頁排版

`AI 分析` 是判讀面，負責回答「現在值不值得研究、能不能進場、錯了要看什麼條件」。

目前新版 AI 分析是 7 層決策介面：

| 層級 | 元件 | 目的 |
|---|---|---|
| 1 | `VerdictBar` | 10 秒內看懂方向、跨時序狀態、三軸分數、一句話結論 |
| 2 | `ThreeHorizonView` | 短線、波段、長線各自獨立判讀 |
| 3 | `ScenarioPlaybook` | 多方條件與空方失效條件 |
| 4 | `EvidenceLedger` | 技術、籌碼、基本面、消息面的證據鏈與權重 |
| 5 | `WyckoffStructurePanel` | Wyckoff 四大相位、道氏結構、Swing pivots、MA 扣抵值、MA 壓縮 |
| 6 | `DeepResearchReport` | 市場敘事、基本面、技術籌碼、情境、評級摘要 |
| 7 | `ProvenanceFooter` | 資料來源、模型、資料品質、規則版本、分析時間 |

### AI 分析視覺規則

三軸分數全頁固定顏色：

| 軸 | 顏色 | 意義 |
|---|---|---|
| 技術訊號 `signal` | `#3B6D11` | 技術型態攻擊性 |
| 分析信心 `confidence` | `#185FA5` | 資料可靠性與跨週期一致性 |
| 追價風險 `risk` | `#BA7517` | 當前位置的回撤與過熱風險 |

卡片密度規則：

- 頁面主要 gap：`24px`
- 主要 card padding：`20px 22px`
- section header 到內容間距：`12px`
- Mobile 下三時序卡片垂直堆疊，但不可省略狀態、方向、共識、三軸

---

## 已實作功能

### 台股分析

- `/analyze/tw?symbol=2330`
- 台股代碼 4 到 6 碼辨識
- 公司名稱、市場別、ETF 判斷
- 即時/模擬價格資料
- K 線 OHLCV
- 四大面向資料：
  - `fundamental`
  - `technical`
  - `chip`
  - `news`
- 綜合分析：
  - `comprehensive_analysis`
  - `equity_research`
- 風險與催化劑
- 新聞 `recent_news`
- 下次股利 `next_dividend`
- ETF holdings

### 美股分析

- `/analyze?symbol=AAPL`
- yfinance 價格與 K 線
- FMP 基本面與同業比較
- Finnhub / SerpApi / mock 新聞 fallback
- 財務摘要
- 同業 peers

### 圖表

- lightweight-charts v5
- K 線
- volume
- RSI
- MACD
- MA5 / MA20 / MA60 / MA120 / MA240
- 日線 / 週線 / 月線 / 年線
- 後端會先聚合 K 線，再計算指標

### 投資組合

- 新增持倉
- 公司名稱可依股票代碼自動帶入
- 支援張/股單位切換
- 系統內部以 `lots` 保存，1 張 = 1000 股
- 成本價、現價、市值、損益、報酬率
- localStorage 保存

### 股票目錄

- 搜尋股票代碼或名稱
- 顯示上方公司名稱、下方股票代號
- 市場別：上市、上櫃、ETF、興櫃
- 已移除創新板
- 依 `stock_code` 去重，避免 React duplicate key

### 市場新聞

- `/tw/external-news`
- Yahoo Finance / SerpApi / mock fallback
- 8 類新聞：
  - 大盤
  - 利率
  - 匯率
  - 產業
  - 國際
  - 原物料
  - 地緣
  - 政策
- 每個分類不足時會用 mock 補到至少 3 則

### 行事曆

- 除息日
- 現金股利
- 股票股利
- 發放日
- 財報申報期限
- 過去 EPS

### Telegram

- `/tw/telegram/watchlist/sync`
- `/tw/telegram/webhook`
- 支援加入、移除、列表、報告等 bot 指令概念

---

## API 路由

### Core

| Method | Path | 說明 |
|---|---|---|
| GET | `/health` | 服務狀態 |
| GET | `/search?query=` | 美股 symbol autocomplete |
| GET | `/market` | 美股總經概覽與 top stocks |
| GET | `/compare?symbol=` | 美股同業比較 |
| GET | `/analyze?symbol=` | 美股分析 |
| GET | `/analyze/tw?symbol=` | 台股完整分析 |

### Price / chart

| Method | Path | 說明 |
|---|---|---|
| GET | `/price-history?symbol=&range=&include_indicators=` | 美股歷史價格 |
| GET | `/tw/price-history?stock_code=&range=&include_indicators=` | 台股歷史價格與指標 |

### Taiwan

| Method | Path | 說明 |
|---|---|---|
| GET | `/tw/stocks?q=&stock_type=&industry=&limit=` | 台股目錄 |
| GET | `/tw/external-news?category=` | 市場環境新聞 |
| GET | `/tw/calendar/dividends?symbol=&start=&end=` | 股利行事曆 |
| GET | `/tw/calendar/earnings?symbol=` | 財報行事曆 |
| GET | `/tw/etf/holdings?symbol=` | ETF 持股 |
| POST | `/tw/telegram/watchlist/sync` | Web UI 自選同步 Telegram |
| POST | `/tw/telegram/webhook` | Telegram webhook |

---

## 主要資料合約

### `TaiwanStockAnalysisResponse`

| 欄位 | 說明 |
|---|---|
| `symbol` | 股票代碼 |
| `company_name` | 公司名稱 |
| `market_type` | 市場別 |
| `currency` | 幣別 |
| `current_price` | 現價 |
| `price_change_percent` | 漲跌幅 |
| `volume` | 成交量 |
| `trend` | 趨勢文字 |
| `confidence` | AI 信心 |
| `summary` | AI 摘要 |
| `risks` | 風險 |
| `catalysts` | 催化劑 |
| `recommendation` | 建議 |
| `recent_news` | 消息面新聞 |
| `chart_data` | K 線資料 |
| `data_source` | live / mock |
| `analysis_source` | ai / mock |
| `fundamental` | 基本面分析 |
| `technical` | 技術面分析 |
| `chip` | 籌碼面分析 |
| `news` | 消息面分析 |
| `comprehensive_analysis` | 四大面向綜合 |
| `equity_research` | 深度研究報告 |

### `AIAnalysisResult`

新版 AI 分析前端合約，位於 `ai-stock-frontend/types/aiAnalysis.ts`。

| 欄位 | 說明 |
|---|---|
| `overall_direction` | 整體方向 |
| `cross_horizon_state` | 跨時序狀態 |
| `overall_scores` | 三軸分數 |
| `one_line_summary` | 一句話結論 |
| `horizons.short_term` | 短線判讀 |
| `horizons.swing` | 波段判讀 |
| `horizons.long_term` | 長線判讀 |
| `bullish_scenario` | 多方劇本 |
| `bearish_scenario` | 空方/失效劇本 |
| `evidence_ledger` | 證據鏈 |
| `structure_panel` | Wyckoff / 道氏 / 扣抵值 |
| `report_sections` | 深度報告 |
| `data_quality_score` | 資料品質分數 |
| `disposition_status` | 注意股/處置股狀態 |
| `rule_set_version` | 規則版本 |
| `is_v1_hypothesis` | 是否為 v1 未回測假設 |

### AI enum 變數

| 類型 | 值 |
|---|---|
| `Direction` | `bullish`, `neutral_bullish`, `neutral`, `neutral_bearish`, `bearish` |
| `Horizon` | `short_term`, `swing`, `long_term` |
| `CrossHorizonState` | `aligned_bullish`, `aligned_bearish`, `bull_pullback_in_uptrend`, `dead_cat_bounce`, `reversal_forming`, `distribution_warning`, `triple_resonance_confluence`, `mixed_uncertain` |
| `TechnicalState` | `parabolic_overheat`, `strong_uptrend`, `steady_uptrend`, `high_level_distribution`, `early_weakening`, `tight_consolidation`, `early_strengthening`, `weak_rebound`, `downtrend_continuation`, `selling_climax`, `mixed_signals`, `data_insufficient`, `disposition_suspended` |
| `DowTrendStructure` | `bullish_intact`, `bullish_at_risk`, `bos_down`, `bearish_intact`, `bearish_at_risk`, `bos_up`, `undefined` |
| `WyckoffPhase` | `accumulation_a` 到 `accumulation_e`, `markup`, `distribution_a` 到 `distribution_e`, `markdown`, `unclear` |
| `FactorCategory` | `PRICE_VS_MA`, `MA_GEOMETRY`, `VOLUME_QUALITY`, `STRUCTURE`, `MOMENTUM`, `VOLATILITY`, `CHIP_FLOW`, `BREAKOUT_QUALITY`, `NEWS_CATALYST` |
| `EvidenceSource` | `technical`, `chip`, `fundamental`, `news` |
| `DataQuality` | `live`, `delayed`, `estimated`, `mock`, `fallback` |
| `DispositionStatus` | `normal`, `attention`, `stage_1`, `stage_2` |

---

## Mock fixtures

AI 分析直接路由支援 mock fixtures，可在 backend 未啟動時獨立渲染。

| URL | 用途 |
|---|---|
| `/ai-analysis/2330` | 台積電示範，健康回檔 |
| `/ai-analysis/overheat` | 極端噴發、追價風險高 |
| `/ai-analysis/vcp` | VCP 窄幅整理、MA 壓縮 |
| `/ai-analysis/spring` | Wyckoff Spring 訊號 |

---

## 知識庫與未來計畫

來源：[Docs/knowledge-base/tw_ai_trading_knowledge_base.txt](Docs/knowledge-base/tw_ai_trading_knowledge_base.txt)。以下整理為產品與工程路線圖。

### A. 多因子共振

未來 AI 不應只看單一指標，例如 MA 黃金交叉或 RSI 超買超賣。有效觀點必須同時檢查：

- 價格狀態
- 均線斜率
- 市場結構
- 量價品質
- 支撐壓力
- 動能指標
- 籌碼與消息

目標：每個非中性結論都要有至少 3 個以上類別支持，並給出量化權重。

### B. 多週期框架

三層時間框架：

| 層級 | 時間框架 | 核心問題 |
|---|---|---|
| 短線 | 15 分鐘 / 60 分鐘 / 日線 | 現在是否具備入場點 |
| 波段 | 日線 / 週線 | 趨勢是否健康延續 |
| 長線 | 週線 / 月線 | 是否處於合理位階 |

未來要補完整週期衝突處理：

- 長線保護短線
- 短線觸發長線
- 高階週期為空時，低階多頭訊號降權
- 完全衝突時輸出中性觀望

### C. 10 種價格狀態

已在前端合約定義，未來後端需實作真實分類。

| 狀態 | 意義 |
|---|---|
| 極端噴發態 | 乖離過大、RSI 高檔鈍化、追價風險極高 |
| 強勢多頭態 | MA20/60 多頭排列，HH/HL 結構完整 |
| 穩健增長態 | 沿 MA20 緩升，法人籌碼支撐 |
| 高位派發態 | 高檔價平量增、價跌量增、頂背離 |
| 早期轉強態 | 首次帶量站回 MA20 |
| 窄幅整理態 | ATR 下降、均線糾結、VCP 壓縮 |
| 初步轉弱態 | 跌破 MA20 或 MA5/10 死叉 |
| 弱勢反彈態 | 反彈受阻於下彎均線 |
| 空頭延續態 | MA 空頭排列、LH/LL |
| 恐慌衰竭態 | 急殺爆量、RSI < 20、可能接近跌勢尾端 |

### D. 道氏結構與 Wyckoff 相位

已在前端顯示結構面板，未來後端需自動辨識：

- Swing high / swing low
- HH / HL / LH / LL
- BOS 結構斷裂
- Wyckoff 四大相位：累積期、主升段、派發期、主跌段
- Spring
- UTAD
- SOS / LPS / SOW

### E. 均線扣抵值與斜率預測

已在前端有 `KouDiTimeline` 視覺化。未來後端需提供：

- MA20 / MA60 / MA120 扣抵值
- 未來 3 到 5 日斜率變化
- 助漲區段
- 沉重區段
- 關鍵扣抵點
- MA 壓縮度

### F. 量價四象限

未來要同時計算成交張數與成交金額，避免高價股與低價股量能失真。

| 類型 | 條件 | 解讀 |
|---|---|---|
| 健康擴張 | 價漲量增 | 趨勢被資金確認 |
| 惜售或追價疲弱 | 價漲量縮 | 多頭末端或高度鎖碼 |
| 主動式殺盤 | 價跌量增 | 賣壓擴大 |
| 良性回檔 | 價跌量縮 | 多頭中的健康修正 |

也要加入當沖比率，當沖比過高時降低量能可信度。

### G. 支撐壓力

未來新增支撐壓力面板，來源包含：

- 前波高低點
- 區間邊界
- 缺口
- MA20 / MA60 動態支撐
- 心理整數關卡
- 分價量表與籌碼密集區

### H. 突破、跌破與假訊號

未來突破品質需納入：

- 幅度超過阻力 3%
- 成交量達 VMA20 的 1.5 倍
- K 棒實體大於 70%
- 上影線不宜過長
- 法人籌碼協同

假突破偵測：

- 1 到 3 日內跌回突破點
- OBV 或動能背離
- 長上影線陷阱

### I. RSI / MACD / KD 場景化

未來動能面板不只顯示數值，而是解釋場景：

- RSI 50 中軸
- RSI 高位鈍化
- MACD 零軸上/下意義
- MACD histogram 二階動能
- KD 短線節奏與鈍化

### J. 過熱、乖離與背離

未來要加入：

- 頂背離
- 底背離
- BIAS z-score
- MA20 乖離 15% 到 20% 的過熱警報
- 過熱時 signal 可高，但 risk 也必須同步高

### K. K 棒與缺口

未來要量化：

- 實體比例
- 上下影線比例
- Doji / Hammer
- 高檔長上影線連發
- 突破缺口
- 衰竭缺口

### L. 型態學

未來要把型態變成規則，不靠肉眼：

- VCP
- 杯柄
- 雙底
- 頭肩底
- 回撤幅度收縮
- 量縮 dry-up
- 第二底 RSI 高於第一底

### M. 台股特殊規則

未來要補強台股微結構：

- 10% 漲跌停
- 漲停磁吸效應
- 注意股
- 處置股第一階段
- 處置股第二階段
- 分盤撮合造成技術指標失真
- 信用交易限制

前端已保留 `DispositionWarning` 與 `DispositionStatus`。

### N. 籌碼技術交互

未來要建立籌碼與技術共振：

| 訊號 | 條件 | 行動 |
|---|---|---|
| 黃金共振 | 帶量長紅突破 + 外資/投信雙買 | 高信心訊號 |
| 虛漲背離 | 創高 + 融資增加 + 法人賣超 | 出貨風險 |
| 底部吸籌 | 橫盤 + 籌碼集中度上升 | 追蹤等待突破 |
| 法人護盤 | 回測 MA20 + 法人續買 | 技術降分但信心保留 |

### O. 條件式交易訊號分類

未來 AI 輸出不應只有 Buy / Sell，而要分成：

- 直接觸發訊號
- 觀察性訊號
- 過濾性訊號
- 失效/止損訊號

每個訊號都要有觸發條件、監控欄位與失效條件。

### P. 三軸決策框架

已在前端完成視覺化。

| 軸 | 範圍 | 意義 |
|---|---|---|
| Signal | 0-100 | 技術攻擊性 |
| Confidence | 0-100 | 資料與邏輯可信度 |
| Risk | 0-100 | 追價與回撤風險 |

原則：

- 不能只顯示信心度
- 強訊號不等於低風險
- risk 高時 UI 要讓使用者看到警示

### Q. 資料品質與信心上限

未來要硬編碼 confidence cap：

| 情境 | 信心上限 |
|---|---|
| 使用估計/預測資料 | 60 |
| 單一技術因子觸發 | 40 |
| 成交金額低於流動性門檻 | 30 |
| mock data | 顯示 mock 警示 |
| 資料異常 | Data Unreliable，暫停決策 |

### R. 可回測假設

所有規則先視為 `v1 hypothesis`，未來要用歷史資料回測。

待回測假設：

- VCP 突破後 20 日勝率
- 高乖離 + 頂背離後回測 MA20 機率
- 處置股出關後放量突破續漲機率
- 外資/投信連買對突破成功率的影響

### S. 必要資料欄位

後端未來的 `TechnicalFeatureBuilder` 應提供：

| 類別 | 欄位 |
|---|---|
| 量價 | `turnover_value`, `vwap`, `body_ratio`, `shadow_ratio` |
| 均線 | `ma_slopes`, `kou_di_indices`, `ma_compression_ratio` |
| 結構 | `swing_hh_hl`, `wyckoff_phase_id`, `volume_profile_peak` |
| 波動 | `atr_ratio`, `bias_20_zscore`, `historical_vol_regime` |
| 微結構 | `day_trading_ratio`, `institutional_consecutive_days`, `disposition_status` |

### T. 最終輸出格式

未來 AI 最終輸出應是技術診斷卡：

- 狀態診斷
- 三軸雷達或分數列
- 核心證據
- 多方劇本
- 空方失效條件
- 自然語言行動建議
- 資料來源與規則版本

---

## 開發驗證

### Backend tests

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/ -q
```

近期驗證紀錄：

```text
92 passed, 1 warning
```

### Frontend TypeScript

```powershell
cd ai-stock-frontend
npx.cmd tsc --noEmit
```

### Frontend build

```powershell
cd ai-stock-frontend
npm.cmd run build
```

近期驗證：

```text
Compiled successfully
TypeScript passed
Route /
Route /ai-analysis/[symbol]
```

---

## 開發原則

- mock fallback 是正式設計，不是臨時 workaround
- schema 採 additive extension，避免舊前端壞掉
- AI 輸出要 structured JSON，不依賴自由文字 parsing
- AI 判斷必須有失效條件
- 每條證據要有來源、方向、權重
- 台股處置股、注意股、當沖比、法人籌碼會影響信心
- 前端要清楚區分「股票資料」與「AI 判讀」

---

## 已知待整理事項

- `backend/.env.example` 建議補上 `SERPAPI_KEY`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_WEB_CHAT_ID`
- `POLYGON_API_KEY` 目前看起來是保留欄位，若未使用可之後移除或補接 Polygon
- AI 分析 Topics A-E 目前以前端合約與 mock/transformer 承接，後端真實 feature builder 尚待完整實作
- Topics F-T 已整理為 roadmap，尚未全部落地
- 技術分析知識庫中的引用來源很長，README 只保留產品化摘要，完整研究內容請看 txt 原檔

---

## License

Personal project. No license assigned.
