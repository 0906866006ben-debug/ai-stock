# FinMind 免費版整合計畫書

> 目標：在**只用 FinMind 免費版（Free / $0）**的前提下，把官方文件裡可用的資料與工具整合進本系統（股票分析 / AI 分析 / CANSLIM / 大膽的計畫）。
> 來源：FinMind 官方 tutor 文件（Technical / Chip / Fundamental / Derivative / RealTime / IndexCodes / Others / Materials / analysis 各頁 / StressTest / BanIPPolicy），逐頁讀過並實測過免費 token。

---

## 0. 免費版的硬限制（先認清邊界）

| 限制 | 內容 | 對系統的影響 |
|---|---|---|
| 流量 | 免費註冊會員 ~**600 req/hr**（滾動視窗） | 全市場掃描要分批/過夜；單檔即時查沒問題 |
| IP 封鎖 | **403、約 30 分鐘**，由「短時間大量 4xx」觸發（尤其重試壞 token） | 下載要**封鎖感知**：402 等額度、403 停手、4xx 不重試 |
| 即時資料 | **全部即時 snapshot 都是 Sponsor 付費**（個股/期貨/選擇權） | 系統只能用 **EOD 日資料**，盤中需標示「延遲/收盤」 |
| 還原股價 | `TaiwanStockPriceAdj` **付費** | 免費要**自己算還原**（除權息＋分割），否則 RS/報酬會有除權息跳空誤差 |

**付費才有（標記為「未來儲值再開」，現在不做）：** 即時報價、分K `TaiwanStockKBar`、tick、5 秒委託/指數、當沖 `TaiwanStockDayTrading`、股權分散 `TaiwanStockHoldingSharesPer`、市值 `TaiwanStockMarketValue`、景氣信號 `TaiwanBusinessIndicator`、產業鏈 `TaiwanStockIndustryChain`、週/月K、券商分點。

---

## 1. 免費可用資料盤點（已實測 token 可抓）

| Dataset | 內容 | 系統現況 |
|---|---|---|
| `TaiwanStockPrice` | 日 OHLCV（1994~） | ✅ 已用（股價、技術面、RS） |
| `TaiwanStockInfo` | 全市場代號/產業 | ✅ 已用（universe） |
| `TaiwanStockTradingDate` | 交易日曆 | ⬜ 可用來精準 PIT/補洞 |
| `TaiwanStockPER` | PER/PBR/殖利率 | ✅ 已用 |
| `TaiwanStockTotalReturnIndex` | 加權/櫃買**報酬指數** | ⬜ 可當 RS/M 支柱基準（比價格指數更正確） |
| `TaiwanStockMonthRevenue` | 月營收（2002~） | ✅ 已用（C 支柱） |
| `TaiwanStockFinancialStatements` | 綜合損益（含 EPS）（1990~） | ✅ 已用（C/A） |
| `TaiwanStockBalanceSheet` | 資產負債（2011~） | ✅ 已用（ROE） |
| `TaiwanStockCashFlowsStatement` | 現金流（2008~） | 🟡 AI 基本面 agent 有；股票分析 detail 沒有 |
| `TaiwanStockDividend` / `DividendResult` | 股利政策 / 除權息結果 | 🟡 股利日曆用部分；**DividendResult 可拿來自算還原股價** |
| `TaiwanStockInstitutionalInvestorsBuySell` | 三大法人買賣超 | ✅ 已用（I/籌碼） |
| `TaiwanStockMarginPurchaseShortSale` | 融資融券 | ✅ 已用（籌碼） |
| `TaiwanStockShareholding` | **外資持股比例** | ✅ 本輪剛補（籌碼 agent） |
| `TaiwanStockSecuritiesLending` | 借券 | ⬜ 可選 |
| `TaiwanStockDelisting` | 下市公司 | ⬜ **回測去存活者偏差** |
| `TaiwanStockSplitPrice` / `CapitalReduction` / `ParValueChange` | 分割/減資/面額參考價 | ⬜ 自算還原股價需要 |
| `TaiwanFuturesInstitutionalInvestors` | **三大法人期貨未平倉**（2018~） | ⬜ M 支柱/大盤情緒（之前以為付費，**實測免費**） |
| `TaiwanFuturesDaily` / `TaiwanOptionDaily` | 期貨/選擇權日成交 | ⬜ 可選（大盤情緒） |
| `TaiwanStockNews` | **個股新聞**（含 title/link/source/date） | 🟡 **實測免費**，但「一次一天」。比 Google News RSS 更適合 N 支柱來源契約 |
| `GoldPrice` / `CrudeOilPrices` | 黃金/原油 | 🟡 現用 yfinance，可改 FinMind |

---

## 2. 要補進系統的（依價值×成本排序）

### 已完成（前幾輪）
- CANSLIM：未涵蓋股票改**即時 call+decode**（免下載）。
- AI 新聞 agent：mock → 真實 Google News RSS。
- 籌碼：補上**外資持股比例**。

### Phase 1 — 資料補齊（低風險、免費、現有資料源）
1. **現金流進股票分析 detail**：`TaiwanStockCashFlowsStatement` → 營業現金流 / 自由現金流 / 趨勢。(AI 分析已有，補在 `/analyze/tw` detail 顯示層。)
2. **外資期貨未平倉 → M 支柱/大盤情緒**：`TaiwanFuturesInstitutionalInvestors`（免費、2018~）。當 regime 風險的輔助指標（連續淨多/淨空）。註：這是「報告」建議過、原以為付費、**現確認免費**的項目。
3. **（可選）N 支柱新聞改用 `TaiwanStockNews`**：結構化、原生 link+date+source，完全符合 N 的「來源必填」契約；缺點是「一天一抓」（近 5–7 天 = 5–7 次呼叫）。可與 Google News RSS 並用（FinMind 為主、RSS 為備）。

### Phase 2 — 正確性（免費但要計算）
4. **自算還原股價**：免費無 `PriceAdj` → 用 `DividendResult`＋`SplitPrice`/`CapitalReduction` 算還原係數，餵給 RS / 報酬 / 技術指標，消除除權息跳空誤差（報告點名的盲點）。
5. **下市資料去存活者偏差**：`TaiwanStockDelisting` 納入回測 universe 歷史，修正只含現存股票的偏差。

### Phase 3 — 視覺/工具（前端「大膽的計畫」可加）
6. **板塊熱力圖 Treemap**：用**免費日資料**算當日漲跌幅 → plotly treemap（FinMind 範例用 Flask+plotly；我們用前端算即可）。放進「大膽的計畫」。
7. **個股資料面板**（仿 FinMind Customer Dashboard）：月營收 bar + 外資持股 line + （免費版無股權分散 pie，改用三大法人）。
   - K 線：**我們已用 lightweight-charts**，不需 FinMind 的 `plotting.kline`。

### 不採用
- **FinMind Backtesting SDK**：我們有自己的 CANSLIM 多週期回測；且官方 backtester「缺成長/盈餘指標」，不適合 CANSLIM。

---

## 3. 統一的免費版呼叫策略（已部分落地）

- **全部走後端代理**（`finmind_query.query_finmind` / `live_finmind_inputs`）；**token 永遠留後端**。
- **封鎖感知**（依 BanIPPolicy）：`402`=等額度、`403`=停手約 30 分、`400/401/param`=**不重試**（先修設定）。playground 與 live 解碼已遵守；**下載腳本 `download_history` 還沒，列入 Phase 4**。
- **每檔每天快取**（`file_cache`，已用於 N / live inputs / analyze_tw）→ 重查不耗額度。
- **批量**：序列 + `--rate-limit`、`--auto-resume`；**勿多 terminal 共用同一 token**。
- **即時性**：免費無即時 → 任何盤中數字標示「收盤/前一日」。

---

## 4. 分階段落地（每階段獨立可測、不破壞現有）

| 階段 | 內容 | 動到的檔 | 風險 |
|---|---|---|---|
| **P1** | 現金流→detail；期貨OI→regime；(可選)N改 TaiwanStockNews | finmind_detail / schemas / regime / news_pillar | 低 |
| **P2** | 自算還原股價→RS/報酬；Delisting 去存活者偏差 | 新 service + features/historical store | 中（碰回測正確性，要測） |
| **P3** | Treemap 板塊圖 + 個股面板（大膽的計畫） | 前端 + 1~2 後端聚合端點 | 低（需瀏覽器驗證） |
| **P4** | 下載腳本封鎖感知 + 統一 _env | download_history/fundamentals | 低 |

**驗證原則（每階段）**：`pytest backend/tests/ -q` 全綠 + `tsc --noEmit` + 對 2330/2882/2603 等實證；測試強制 token 空保持 hermetic（已建立）。

---

## 5. 一句話結論
免費版**足以**支撐目前系統的全部核心（EOD 資料、基本面、籌碼、新聞、CANSLIM）；要再補的高 CP 值項目是**現金流、外資期貨未平倉、自算還原股價、下市去偏差**，外加前端**板塊熱力圖**。即時報價/分K/股權分散/市值/景氣信號等需付費，明確標為「未來再開」。
