# CANSLIM 現況診斷報告

**日期:** 2026-05-26
**性質:** 只讀量測(measure-first),未修改任何程式/設定。
**目的:** 在動 CANSLIM 升級(資料誠實層 + Reviewer + grade 定位)之前,先用既有資料把「現況到底有沒有問題、問題在哪」量出來。

**資料來源:**
- 15 年廣域多週期 backtest:`artifacts/canslim_multicycle/multicycle_tagged_trades.csv`(28,768 筆,2011–2025,595 檔候選,週頻)
- walk-forward OOS attribution:`artifacts/canslim_attribution/canslim_real_v1_attribution_attribution_report.md`(~7,500 筆,3 視窗)
- 資料庫覆蓋率:`backend/historical_data.db`(OHLCV)、`backend/pit_fundamentals.db`(PIT)

---

## 1. 資料覆蓋率 — 已不是瓶頸(舊前提過時)

| 來源 | distinct stock_id |
|------|------|
| OHLCV | 2,410 |
| PIT 月營收 (month_revenue) | 2,428 |
| PIT 法人 (institutional) | 2,442 |
| PIT 財報 (financials) | 2,403 |
| PIT 融資券 (margin) | 1,958 |
| PIT 本益比 (per) | 2,098 |
| 三大核心齊全(營收+財報+法人) | **2,374** |
| OHLCV 但完全無 PIT 的 | 6 / 2,410 |

**結論:** C/A/I 現在幾乎全市場可評。先前計畫文件擔心的「只有 ~390 檔有基本面」已被回填解決。唯一小缺口:margin / per 各少約 300–450 檔(影響 S 融資券與估值因子)。

---

## 2. S < A < B「反轉」是小樣本 + 空頭期假象,不是穩定現象

| 資料集 | S | A | B | 方向 |
|--------|---|---|---|------|
| 15 年廣域多週期(28,768 筆) | PF **1.43** (n=219) | 1.23 (n=5,106) | 1.09 (n=23,443) | **S>A>B 單調正確** |
| real_v1 walk-forward OOS(~7,500 筆,3 視窗) | 0.78 (n=131) | 0.99 | 1.19 | 反轉 |

反轉幾乎全來自 **2022 空頭視窗**:window_1 有 64% 是 severe、window_2 為 100% risk_off/severe;window_3(多頭)三個 grade 皆獲利。且 **S 樣本太少(131–219 筆)**,兩邊都不可信。

**結論:** grade 字母單獨看,排序會隨資料集翻轉,**不可當成已驗證的可交易分層**。但「grade 是反指標」的說法被大樣本推翻 — 它只是**不穩定**,不是反指標。**不應據此重調 grade 門檻(會過擬合)。**

---

## 3. 真正穩定、跨資料集一致的 edge = 離 52 週高點的距離(extension)

| 距高點 | n | 勝率 | 平均報酬 | PF |
|--------|---|------|---------|-----|
| 創高/貼高 (at/above) | 931 | 45.3% | +7.69% | **4.02** |
| 近高 (-5~0%) | 6,868 | 28.8% | +1.41% | 1.50 |
| 中段 (-15~-5%) | 12,350 | 23.3% | -0.13% | 0.96 |
| 遠離 (<-15%) | 8,619 | 22.1% | -0.49% | 0.86 |

每一刀都單調且差距巨大。**動量/強勢(貼近高點)才是真正的 edge,不是 grade 字母。**(與 15 年結論 `canslim-score-inversion` 一致。)

---

## 4. Regime:「unknown」一律最差

A/B 在 `regime=unknown` 的 PF 為 0.77–0.90(全資料集最差)。
**結論:** 未確認的市場狀態應壓低 confidence,而非當中性計分。severe 樣本太小,個別高 PF 屬雜訊。

---

## 5. 進場 grade 分佈(28,768 筆進場)

B 81.5% / A 17.7% / **S 僅 0.8%**。S 本就極稀少(符合「少而精」風格),但也因太稀少而無法驗證。

---

## 對後續升級(②Reviewer / ③grade 定位)的決策

1. **不要重調 grade 門檻** — 無任何資料集給出夠穩健的單調 grade 訊號,調了就是過擬合。
2. **confidence 的真正驅動軸 = extension + regime,不是 grade 字母**:
   - HIGH 僅當「貼近/創 52 週高 **且** regime 已知(risk_on)**且** 真實資料」。
   - `regime=unknown` 或 mock/fallback → 不得 HIGH。
   - 單靠 S-grade → 不得 HIGH(未經 OOS 驗證且樣本稀少)。
3. **資料誠實層(Reviewer)重點轉移**:從「補覆蓋率」(已解決)轉為「mock→不得 HIGH、unknown regime→不得 HIGH、grade 不得被當成已驗證訊號」。
4. **grade 定位**:輸出/UI 標明「grade = 條件匹配度,未通過 OOS 單調性驗證」;真正要凸顯給使用者的是 extension / regime。

## 被討論但否決(留底)

- 「改成多因子排名、把差一條的高 alpha 撈進來」→ 降低精度,與「少而精」風格相反。
- 「Markov regime switching / 直接套 Minervini Trend Template」→ 小樣本下成本高且易過擬合,不划算。
