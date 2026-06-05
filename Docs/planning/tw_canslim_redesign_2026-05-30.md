# TW-CANSLIM 重設計與落地計畫（2026-05-30）

> 來源：`/canslim-redesign` 機構級審查 + 本 session 已完成的倖存者偏誤實測（`artifacts/canslim_cohort_surv/cohort_summary.md`）。
> 本檔是「審查結論 → 具體、排序、有閘門的下一步」。**不寫交易系統、不出買賣訊號**；所有產出都是無動詞的篩選/觀察層。

---

## 0. 背景與定位

CANSLIM 在本專案**只能**是：股票池篩選器 / watchlist 排名 / 多因子 screening / 決策支援。
**永不**輸出：buy/sell/hold/entry/exit/部位大小/目標價/停損/停利。
允許輸出：`screening_grade`、`watchlist_priority`、`signal_score`、`confidence_score`、`risk_score`、`pillar_breakdown`、`data_quality_flags`、`risk_warning`、`downgrade_reason`、`observe_only_reason`。

**重新定位：** TW-CANSLIM = **每季刷新、以 A 級為頂、N/I 主導、M 為閘門的成長型觀察清單篩選器**。它是 1–3 個月的動能/品質篩選，**不是**買進長抱的排名器（6–12 個月會反轉）。

---

## 0.5 策略轉向 — Path B：durable 品質長抱篩選器（2026-05-30，取代上方波段定位）

**為何轉向：** Phase 4 季度回測（15 年、含下市、扣成本）給出誠實結論：選股有真 edge
（CAGR 11.5% vs TAIEX 8.2%，總報酬 +391% vs +215%），**但當成機械式動能組合風險不及格**
（maxDD −43%、Calmar 0.27 < 大盤 0.41；2018 單年 −43%）。同時使用者明確表述投資哲學：
**(1) 重心是篩「健康、會持續賺錢的公司」**（品質基本面）；(2) 崩盤是週期、不否定好公司，
**抱過去 + 低點加碼**；(3) 長期持有。

**契合度判定：** 使用者哲學與 **CANSLIM 動能/交易半邊（N 追新高、7-8% 停損不攤平、M 擇時
出場、短線）全面衝突**，但與 **品質/基本面半邊（C/A/I）高度契合**。資料支持後者：**A 12M
+11.6% vs +9.3%、I 12M +13.1% vs +9.0%**（品質支柱有 durable 長期 edge；反轉的是 N 延伸）。

**新定位：用 CANSLIM 的 C/A/I 品質引擎當「durable 品質成長篩選器」，丟掉其動能交易規則。**
重心＝找「會持續賺本業真錢、機構持續持有」的公司；讓使用者「抱過週期 + 低點加碼」的紀律
建立在「durable 品質」而非「週期高峰/劣質股」之上（台股硬體景氣循環是主要陷阱）。

**權重/驗證隨之改變（取代 Phase 2 的波段偏 N/I 設定）：**
- **加重**：A（多年「持續」成長，非單季）、**獲利品質**（營益率穩定、ROE、現金流、**排除業外
  一次性**）、I（機構持續持有/連續性）。
- **降重**：N（創新高延伸）與 S（小 float）—— 正是會反轉、又最易把週期高峰誤標成成長、且
  最不該攤平的那種。
- **驗證改長線**：12 個月以上 cohort 切面 + **崩盤回復力分析**（高品質 vs 低品質在 2018/2022
  後的收復速度與下市率），取代 1–3 個月鏡頭。anti-overfit：先量再調權重。

**注意：** Phase 1+2（commit b7210f0）的波段偏 N/I 權重在 Path B 下需重新檢視；不直接刪，改為
在「品質傾向」設定下重測，確認哪個權重在 12M+durability 目標下最穩再定。

---

## 1. 現況（已完成、已驗證 — 不要重做）

- **PIT 正確性**：`pit_fundamentals_store.get_financials_as_of` 以 `WHERE filing_date <= as_of` gating（非 period_end）；法人 T+1；OHLCV as_of。✅
- **倖存者偏誤**：`cohort_surv` 已跑（1147→1333 檔，含下市股 + `max_staleness_days` 在最後一根後剔除）。✅
- **三分制**（signal/confidence/risk）、**無動詞 reviewer**、**mock/fallback/staleness 旗標**：已存在。✅
- **pillar 級前向報酬驗證**（20/60/120/252 日）：已在 cohort 完成。✅
- **門檻集中於 YAML**（`canslim_thresholds_v1.yaml`）。✅

### 1.1 倖存者實測關鍵結論（決定本計畫優先序）
- **S 級（總分≥80）的優勢崩了**：1M 由 +3.04% → **+0.86%**（低於 baseline +0.94%），n=68/15 年、統計不顯著 → **S 是倖存者偏誤+雜訊**。
- **真正抗倖存者的 edge 守住**：**A 級**（n=665，+1.68%/中位+0.37%/勝 51%）、**N**（1M +2.89 vs +0.81，所有期間正）、**I**（12M +13.1 vs +9.0，隨時間放大）、**M**（3M +4.01 vs +0.41，閘門有效）。
- **INSUFFICIENT_DATA 強烈負**（12M −8.9%）→ 垃圾過濾有效。
- **S 支柱 Pass 反而輸**（1M +0.58 vs +1.02）、**L 12M 負貢獻** → 不可當分數主力。

---

## 2. 缺口（本計畫要處理的；其餘已完成）

1. **等級最高層是雜訊**：S 級需降級併入 A；signal 權重需更偏 N+I；C/A 應改為「資格門檻」而非分數主力。
2. **I 法人疑似加總**：需拆外資/投信/自營、量比標準化、投信首買 vs 連買；融資同步暴增要降級。（需先確認 `screen_I` 現況。）
3. **L 過於單薄**：只有大盤 RS；缺產業相對 RS + 多週期(1/3/6/12) + 過熱懲罰。
4. **推導 filing_date 的軟性未來函數**：`derive_filing_date()` 在 filing_date 缺值時估算 → 需標記並降信心。
5. **回測缺成本/滑價/漲跌停無法成交、缺 OOS/walk-forward**：等級在信任任何 CAGR 前必須補這些。
6. **資料天花板**（當沖比/處置股/大戶/投信持股% 免費版取不到）→ 只能列 `future_enhancement`，不進核心。

---

## 3. 階段計畫（排序、有閘門）

> 原則：先資料完整性 → 再等級校準 → 再因子重設計 → 再含成本驗證 → 最後輸出/前端。
> 每階段都：additive、verb-free、門檻入 YAML、**不改已驗證的 signal/score/grade 數學除非走「預設關閉旗標 + 重驗證」**、PIT-safe、measure-first 反過擬合。

### Phase 1 — 資料完整性護欄（小、先做）
- 標記使用「推導 filing_date」的列（新增 `data_quality_flags` 項）。
- 強制規則：`is_mock` 或推導 filing_date ⇒ `confidence ≤ MEDIUM`（在 reviewer / build_full_result）。
- 確認融資、月營收的公布日 gating 與法人 T+1 一致。
- **檔案**：`pit_fundamentals_store.py`、`live_screening.py`、`reviewer.py`、`canslim_output.py`。
- **驗收**：單元測試證明 mock/推導日不得 HIGH 信心；PIT 測試通過；既有測試全綠。

### Phase 2 — 等級重校準（**本計畫 MVP，最高價值/最低風險**）
- **降級 S**：取消 S 作為獨立層，併入 A（或將 S 門檻對齊 A 行為）；A 成為最高可靠層。
- **signal 重新加權**：更偏 **N + I**（倖存者後仍最強）；M 維持/升級為**等級上限閘門**（空頭/高波動降上限）。
- **C/A 改資格門檻**：低於門檻則整檔不可進高級別（確認「成長股」），而非只是扣分。
- **檔案**：`canslim_output.py`、YAML `presentation.factor_weights` + `screening.M`、`pillar_screening.py`。
- **驗收**：**重跑 `cohort_surv`**，確認 1–3M 等級**乾淨單調 A>B>C>D、無 S 異常**；A 級維持 ~+1.7%/1M、正中位；INSUFFICIENT 仍負。

### Phase 3 — I / L 因子重設計（measure-first）
- **I**：拆外資/投信/自營分開計分；淨買以成交量/額標準化；投信首買 vs 連買分開；融資同步暴增 → 降級。
- **L**：加產業相對 RS + 多週期(20/60/120/252) + 過熱懲罰；空頭強勢股標 higher risk 而非高分。
- **先量再 wire**：在 cohort 加新 I/L 變數的 pillar 級前向報酬切面，證明新版勝舊版才採用。
- **檔案**：`pillar_screening.py`(`screen_I`,`screen_L`)、`features.py`、`pit_inputs.py`、YAML。
- **驗收**：pillar cohort 顯示新版 I/L 前向報酬區分力勝現況；無動詞；缺資料→Insufficient。

### Phase 4 — 季度組合驗證（含成本）＝ TW-CANSLIM-Q + 影片對照
- 用現成 `canslim_ranking` + 組合模擬器，做**季度換股回測**（4/1、5/16、8/15、11/15，對齊財報截止隔日）：
  - 每期取 **A 級以上、N/I 加權 top-N**、等權重、M 閘門調整檔數；持有一季→刷新複利。
  - **含交易成本 + 滑價 + 漲跌停無法成交**；在**含下市股**資料上跑。
  - 輸出**年度報酬 / CAGR / maxDD / Calmar / vs 加權指數**（年度鏡頭）。
  - **對照組**：跑「影片版（C/A + 最小流通股 30 檔季調等權）」，在同一份無偏誤資料上比較。
  - 門檻敏感度(±20%)、OOS 切分 + walk-forward。
- **檔案**：新 `backend/app/services/strategy/canslim/quarterly_portfolio_backtest.py`（復用既有元件）+ runner。
- **驗收**：年度績效表產出；TW-CANSLIM-Q 在淨報酬上 ≥ 影片版且 OOS WFE 可接受；誠實標示成本後 edge。

### Phase 5 — 輸出 / 前端
- 將重校準後的等級 + 三分數 + `risk_warning` + `data_quality_flags` 以 optional/nullable 欄位呈現。
- **檔案**：`screener_schemas.py`、`main.py`、前端 `CanslimGradeCard`。
- **驗收**：`/tw/screen/full` 向後相容；`npx tsc --noEmit` + `next build` 乾淨；瀏覽器驗證。

### Phase 6 —（已通過、改排於此）主升段 exit/observation overlay
- 計畫見 `~/.claude/plans/splendid-growing-ladybug.md`（TW 主升段 overlay）。
- **重新排序理由**：要先有「乾淨、單調、抗倖存者的等級」(Phase 2-4)，再疊 MA5/測幅/主升段觀察區的出場觀察層才有意義。
- Phase 0 measure-first（ma5 / pivot×1.4 / 跌破MA5 / 動能爆發 的 cohort 切面）仍照原計畫。

### Phase 7 — 營運化（原 P3）
- 每週/每季優質觀察清單（`canslim_ranking` 排程化）+ 可選 Telegram 推播。

---

## 4. 閘門（gates）

- **G1**（已過）：倖存者實測完成，確認 A/N/I/M edge 抗倖存者。✅
- **G2**：Phase 2 重跑 `cohort_surv` 必須顯示 1–3M 乾淨單調、無 S 異常 → 才進 Phase 3。
- **G3**：Phase 4 含成本後 TW-CANSLIM-Q 仍有正 edge 且 OOS 站得住 → 才進前端/營運化與主升段 overlay。
- 任一階段若 edge 消失或過擬合徵兆，**停手、回報、不硬推**。

---

## 5. 約束 / 護欄（全程）

- **無動詞**：reviewer 必須 APPROVE；測試 assert 無 買/賣/持有/停損/停利/進場/出場。
- **加法、不破壞**：不動已驗證 signal/score/grade 數學，除非走「預設關閉旗標 + 重驗證」；不破壞 `/analyze`(US)、`/analyze/tw`、`/tw/screen`、既有測試。
- **PIT-safe**：只用 as_of 當下可得資料；推導 filing_date 要標記降信心。
- **資料誠實**：缺/mock/estimated/stale → Insufficient 或降信心，永不捏造、永不給 HIGH。
- **反過擬合**：門檻入 YAML 標 `v1_hypothesis`；先測量再 wire；coarse grid；OOS/walk-forward；別在 tech 子集挑好看的。
- **記憶體**：本機 7.7GB；組合回測用有界 universe（tech+下市 ~1400），沿用 `CachedPitFundamentalsStore` 分塊載入修正。

---

## 6. 下一步（立即）

**MVP = Phase 1（資料護欄，小）+ Phase 2（等級重校準）**，完成後**重跑 `cohort_surv`** 驗證 1–3M 乾淨單調、無 S 異常（G2）。
其餘（I/L 重設計、含成本季度組合回測 + 影片對照、前端、主升段 overlay、營運化）依序疊上，各有閘門。
