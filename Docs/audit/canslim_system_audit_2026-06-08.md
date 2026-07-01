# CANSLIM 量化系統審查報告

**審查日期:** 2026-06-08
**審查視角:** 台股量化策略審查委員 / 華爾街量化 + 資深交易員
**審查標的:** 本專案實際實作的 **CANSLIM 耐久度篩選系統**(非通用模板策略)
**前提:** 所有結論基於實際程式碼(標檔名)+ 專案自身回測記錄(標明來源)。所有未驗證項目一律視為 hypothesis。

> 註:審查框架模板中的 Strategy A/B/C(投信首買 / 投信作帳 / 法人買超+融資)**並非本系統實作的內容**。本系統是 CANSLIM 七柱篩選 + 耐久度評分 + 單次/批次掃描 + 資金配置輔助。以下以相同嚴格度審查「實際存在的系統」。

---

## 1. Executive Verdict

**Overall Status:** Research-validated **SCREENER** ✅ / NOT-yet-investable **PORTFOLIO SYSTEM** ⚠️ → **Modify + Downgrade(部署層級)**

**一句話:** 訊號層(篩選器)有 15 年驗證的動能 edge 且工程嚴謹,但「訊號 → 可投資組合」這段是斷的,而且最近的 durability-led 權重轉向尚未通過驗證——所以可以當決策支援用,**不能當自動交易系統用**。

---

## 2. 模組逐一審查（取代模板 Strategy A/B/C）

| 模組 | Verdict | 主要問題 | 必要修改 | 現在 Level | 目標 |
|------|---------|---------|---------|-----------|------|
| CANSLIM 七柱篩選(signal/grade) | **Keep** | grade 自承「OOS 不穩定」卻在 UI 當主角 | UI 改以 extension+regime 為主訊號 | L2-3 | L3 |
| Durability Score(Path B) | **Research Only** | 宣稱「抗跌」但 Phase B 崩盤驗證**未跑** | 跑 Phase B 才能信 | **L1** | L2 |
| Durability-led 權重(I1.8/A1.6/N0.7) | **Downgrade** | 與 15yr 驗證的動能 edge 相反,且未重驗 | 標 hypothesis;只動 overall_score 不動 grade | **L1** | L2 |
| 單次/批次掃描一致性 | **Keep** | 剛修好,已驗證 25/25 + 3481 | 加開機自檢斷言同 DB/as_of | L3 | L3 |
| Grade Summary(Gemini/模板) | **Keep** | 純呈現,反幻覺到位 | 無 | L3 | L3 |
| 資金配置 / 進場條件層 | **Keep(輔助)** | 是算術工具,非驗證過的部位模型 | 明確標示「非建議」 | L2 | L3 |
| **投資組合層(Phase N)** | **Reject(現狀)** | **CAGR 0.40% / maxDD −72%**(專案自身回測) | 重做選股建構(N2 精選) | **L1** | L2 |

**分級定義:** L0 概念 / L1 資料研究 / L2 歷史回測 / L3 paper trading / L4 小資金實測 / L5 正式自動化。

---

## 3. Factor Audit（七柱 + 耐久度元件）

| Factor | 判定 | 問題 | 修改 | 優先 |
|--------|------|------|------|------|
| **N 近高/突破(extension)** | **Keep — 真正 edge** | 被 durability 權重降到 0.7,與驗證矛盾 | 還原 N 在「訊號」的權重;15yr 最穩因子 | 🔴 高 |
| **L 領先 RS** | **Keep** | 用原始未還權價;RS 受除權息扭曲 | 接 `AISTOCK_ADJUSTED_RS` 還權後重驗 | 🟡 中 |
| **T 技術/MA** | Keep | — | — | 低 |
| **C 當季成長** | Keep | EPS YoY 受低基期扭曲(已有 accel guard) | 加業外排除(已部分) | 🟡 中 |
| **A 年度品質** | Keep | 3yr CAGR 端點偏誤(已有 stability guard) | — | 低 |
| **I 法人** | Modify | 是 flow 非 ownership;單日易雜訊 | 已用連續性;**籌碼資料現落後 11 天**(修正中) | 🔴 高(資料) |
| **S 供需/量** | Modify | float≈CapitalStock/par10 近似 | 標示近似,不可當硬門檻 | 低 |
| **M 大盤 regime** | Keep(gate) | 滯後 30 週 MA,曾把 2022 頂部標 risk_on | 不要再加 gate(專案已下此結論) | 🟡 中 |
| durability:業外排除/ROE趨勢/F-score | Research | 邏輯合理但**零前向驗證** | Phase B 之前只能觀察 | 🔴 高 |
| durability:CFO/NI | Research | 部分資料,F-score 僅 7/9 | 補現金流再算 | 中 |

---

## 4. Critical Problems（依嚴重度）

### P1 — 訊號 edge 無法轉成可投資組合（最致命）
- **Why:** 專案自身 Phase N 回測 = 組合 CAGR 0.40%、maxDD **−72%**、Calmar 0.006。trade-level PF 1.16 **完全沒有**變成可投資的權益曲線。
- **How to fix:** 這是「組合建構」問題,非訊號問題——按使用者風格(大波段、低頻、精選)重做成 **top-K/週 + 強勢優先 + 流動性地板**,衡量精準度而非聚合 PF。
- **Must fix before 真錢?** **YES**

### P2 — Durability-led 權重轉向未驗證就上線
- **Why:** `canslim_thresholds_v1.yaml` 的 `factor_weights` 已是 durability 優先(I 1.8 / A 1.6 / N 0.7),但 15 年 M3 驗證的結論是**動能/extension 才是 edge,低 extension 最差**。方向相反,且 Phase B/C1 重驗**沒跑**。
- **How to fix:** 標回 hypothesis;確認它只影響 `overall_score`(顯示),不影響 `grade`/`pass_status`(交易訊號)——目前 `canslim_output.py` 確實如此,但雙軌易誤導(見 P3)。
- **Must fix?** **YES(至少標示)**

### P3 — overall_score 與 grade 可能互相矛盾
- **Why:** `overall_score`(durability 加權)與 `grade`(signal 加權)是兩個不同邏輯。一檔可能 overall_score 高但 grade 低,反之亦然。使用者會混淆「哪個是訊號」。
- **How to fix:** UI 明確分區:grade=動能訊號、durability=品質觀察、overall_score 拿掉或更名為「綜合觀察分」。
- **Must fix before coding?** No,但上線前要。

### P4 — grade 自承 OOS 不穩定,卻是 UI 主角
- **Why:** `canslim_output.py` 註解明說 grade letter is NOT an OOS-stable ranking,真正穩定的是 extension+regime。但前端卡片以大大的 A/B/C 為主視覺。
- **How to fix:** 卡片主數字改成 extension(距高)+ regime;grade 降為標籤。

### P5 — 資料新鮮度（修正中）
- **Why:** 籌碼落後 11 天、OHLCV 多數卡 2026-05-22。stale 訊號 = 錯訊號。
- **狀態:** 正在背景修(OHLCV loop + PIT `--since-latest`)。

---

## 5. Required Strategy Modifications（具體）

1. **N(extension)權重:** 在 signal/grade 層**還原 N 的貢獻**(驗證最穩因子);durability 降權**只准作用在 overall_score 顯示層**。
2. **Durability:** 標記 `status: hypothesis`,Phase B 崩盤驗證通過前,**不得**進入 pass_status / 部位決策。
3. **新增「投資組合建構」前置:** top-K 精選、強勢優先、單檔上限、流動性地板(成交金額)、最大同時持股——目前在 allocation 計算機但**沒接到驗證過的選股流程**。
4. **刪除/凍結:** 不要再加 regime entry gate(專案已驗證「加 gate 反而更糟,改 portfolio 層」)。
5. **門檻 config 化檢查:** 確認 durability 權重、grade bands、extension 門檻全在 YAML 且標 `tunable_required`(大致已是)。
6. **RS 還權:** L/N 的價格用 `AISTOCK_ADJUSTED_RS` 還權後重驗,否則除權息季系統性扭曲強弱。

---

## 6. Revised Screener Spec（更嚴謹版,僅規格）

- **Universe:** `stock_master` 上市櫃,排除全額交割/處置/停牌;**成交金額地板**(如 20 日均額 ≥ NT$1 億)升為**硬過濾**(目前為加分)。
- **Data / timing:** 全部用**收盤後**資料 → 訊號隔日生效;EPS filing+1、法人 T+1(已做)。
- **Signal(主訊號=動能):** 近 52 週高 proximity + 多週期 RS + MA stage-2 + 帶量突破。
- **Quality overlay(觀察,不進訊號):** durability + C/A 成長品質(C&A 雙 Fail 仍封頂——已做)。
- **No-trade:** regime severe / risk_off;漲停鎖死;流動性 < 地板;近除權息事件窗。
- **Risk score:** 延伸過熱(R-1)、量價背離、法人反手、估值錯配(已做)。
- **Confidence:** 資料完整度 + regime + extension(已做);mock/stale → 上限 50。
- **Invalidation:** 跌破 MA20/MA60/box_low、量縮背離(swing_exit 已做)。
- **Portfolio(缺):** top-K/週、強勢優先、單檔 ≤X%、產業 ≤Y%、最大持股數、bear-year 降曝險——**這層要補且要驗證**。

---

## 7. 正式依賴前必跑的回測

| 測試 | 狀態 |
|------|------|
| Baseline vs TAIEX | ✅ 有(cohort) |
| 交易成本 0.685% | ✅ 有(YAML/backtest) |
| 滑價 / 漲跌停無法成交 | 🟡 部分 |
| 流動性敏感度 | ✅ 有(M3 liquidity bucket) |
| 參數 ±20% 敏感度 | ✅ 有(walk_forward) |
| 多/空/盤整 regime | ✅ 有(15yr 多週期) |
| Out-of-sample / walk-forward WFE≥0.5 | ✅ 有 |
| **Phase B 崩盤韌性(durability)** | ❌ **未跑** |
| **Phase C1 durability-led 重驗** | ❌ **未跑** |
| **可投資組合權益曲線(N2 精選版)** | ❌ **未跑** |

---

## 8. Final Recommendation

1. **現在能不能直接當自動交易系統?** ❌ 不行。訊號→組合斷裂(Phase N maxDD −72%);durability 權重未驗證。
2. **哪些可以先用?** CANSLIM 篩選器當**決策支援/watchlist**(L3 paper)、進場條件層、資金配置算術工具——皆輔助,非自動下單。
3. **哪些只能先研究?** Durability score、durability-led 權重、抗跌假說 → 全部 L1,等 Phase B。
4. **哪些該刪/凍結?** 再加 regime gate 的念頭;把 overall_score 當訊號用。
5. **下一個最小可行任務(MVT):**
   - **(a) 釐清雙軌(可立即做,零回測):** 程式碼 + UI 明確分離「動能訊號(grade/pass)」vs「品質觀察(durability/overall_score)」,避免把未驗證的 durability 當訊號。
   - **(b) 跑 Phase B 崩盤驗證:** 用補齊後的 canonical store,決定 durability 能否進訊號。
   - **(c) Phase N2 精選組合:** 把 15yr 動能 edge 做成 top-K 精選權益曲線,看能否投資。

---

## 一句總結（交易員視角）

你手上是一台**校準良好的選股雷達**(動能 edge 真實、工程嚴謹、PIT 安全),但它**還不是一台會賺錢的交易機器**——缺的是組合建構與部位風控那一層,而且最近想往「品質/抗跌」轉的方向**還沒被資料證實**。先別讓 durability 影響任何進出場決策,先把「雷達訊號 → 可投資組合」這段補起來並驗證。

---

### 附:審查紀律聲明
本報告為審查意見,非投資建議;不含買賣/目標價/停損指令。所有判定皆可被回測驗證;所有「未驗證」項目一律標為 hypothesis,不得在驗證前進入交易決策。
