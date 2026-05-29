# William O'Neil CAN SLIM Strategy Research for Taiwan Stock AI Platform

> **Document status**: v1 hypothesis spec. All thresholds, weights, and conditions herein are **research starting points**, not validated truths. Every rule must pass walk-forward backtesting on TW data before deployment. This document is intended to be implementable by a coding agent without further design discussion.
>
> **Scope boundary**: Decision-support only. No absolute buy/sell/hold output. All recommendations are conditional and observation-oriented.

## 1. Strategy Overview

**CAN SLIM** is William J. O'Neil's growth-stock methodology (codified 1962, popularized by *How to Make Money in Stocks* and IBD). It combines **fundamental growth screens** (C/A/N) with **technical leadership** (L), **supply-demand dynamics** (S), **institutional flow** (I), and **market regime** (M). Original target: US large-cap growth equities with 6-18 month holding periods.

**Adaptation thesis for TW AI platform**: CAN SLIM's seven pillars map well to TW data, but four translation gaps require explicit handling:

1. **Reporting cadence differs**: TW publishes monthly revenue (faster than US quarterly), so the "C" pillar can have a higher-frequency leading indicator.
2. **Daily price limits ±10%**: TW limits compress breakout dynamics; institutional accumulation more visible via dark-pool-equivalent (盤後鉅額) but less granular than US.
3. **Institutional structure**: Three named groups (外資 / 投信 / 自營商) publicly reported per stock per day — far more transparent than US 13F.
4. **Liquidity stratification**: TW small/mid-cap can have <100M TWD daily turnover; CAN SLIM's "leader" definition must include explicit liquidity floors.

This document specifies a **rule-based v1 framework** for surfacing CAN SLIM-style observations on TW AI stocks across three independent time horizons.

---

## 2. Original CAN SLIM Logic

### 2.1 C — Current Quarterly Earnings

- **Original concept**: Most recent quarterly EPS growth ≥ 25% YoY (preferably ≥ 40%); ideally accelerating vs. prior quarters.
- **Problem it solves**: Filter out stagnant companies; capture inflection.
- **Quantifiable indicators**: `quarterly_eps_yoy`, `quarterly_eps_qoq`, `eps_acceleration` (current YoY > previous YoY).
- **Common methods**: Compare last 4 quarters' YoY series; flag when latest ≥ 25% AND ≥ previous quarter's YoY.
- **TW limitations**: Quarterly filing deadline lag (1 quarter behind), small companies' reporting noise, IFRS vs. US GAAP differences.
- **TW alternatives**: `TaiwanStockMonthRevenue` provides monthly leading signal; can compute trailing-3-month revenue YoY as proxy.
- **Suitable horizon**: `swing_term` (3-12 weeks) and `long_term` (3-12 months).
- **Failure modes**: One-time gains (處分利得), prior-quarter low base, accounting policy changes.
- **Hypotheses requiring backtesting**:
  - H-C1: 季 EPS YoY ≥ 25% improves T+60 to T+250 return vs. market.
  - H-C2: Adding `eps_acceleration` doubles excess return contribution.

### 2.2 A — Annual Earnings Growth

- **Original concept**: Annual EPS growth ≥ 25% per year for last 3 years; ROE ≥ 17%.
- **Problem it solves**: Distinguish durable growth from one-quarter spikes.
- **Quantifiable indicators**: `annual_eps_cagr_3y`, `roe_ttm`, `gross_margin_trend`, `operating_margin_trend`.
- **Common methods**: 3y EPS CAGR ≥ 25%; ROE ≥ 17%; margin trend non-decreasing.
- **TW limitations**: Cyclical industries (半導體/封測/PCB) have boom-bust years; CAGR misleading.
- **TW alternatives**: For cyclical sectors, use peak-to-peak or 5y rolling instead of 3y.
- **Suitable horizon**: `long_term` only (3-12 months). Annual data too slow for swing.
- **Failure modes**: Cyclical peak, M&A inflated growth, sector rotation away from growth.
- **Hypotheses requiring backtesting**:
  - H-A1: 3y EPS CAGR ≥ 25% AND ROE ≥ 15% outperforms TAIEX over 12 months.
  - H-A2: Combining annual + quarterly improves Sharpe vs. either alone.

### 2.3 N — New Products, Management, Highs, Catalysts

- **Original concept**: A catalyst — new product, new management, industry expansion, new 52-week high — signals attention.
- **Problem it solves**: Most institutional accumulation begins around catalysts.
- **Quantifiable indicators**: `pct_from_52w_high`, `is_at_new_52w_high`, `consecutive_days_at_new_high`, structured news-event flags.
- **Common methods**: Buy in proximity to (or shortly after) new 52w high on volume.
- **TW limitations**: 漲跌停 distorts true price discovery; small caps gap easily; news data quality varies.
- **TW alternatives**: 52w high from `TaiwanStockPrice`; structured catalyst flags from earnings calendar (`tw_calendar.py`), MSCI rebalances, 法說會 dates.
- **Suitable horizon**: `short_term` (event window 1-10 days) and `swing_term`.
- **Failure modes**: News-driven spike then mean revert; ex-rights/dividend optical "new high"; thinly-traded false high.
- **Hypotheses requiring backtesting**:
  - H-N1: Breakout above 52w high on volume ≥ 1.5× 50d avg outperforms in T+20.
  - H-N2: Earnings-catalyst breakouts vs. non-catalyst breakouts have different WR / PF profiles.

### 2.4 S — Supply and Demand

- **Original concept**: Smaller float = larger upside swings; demand surges (volume spikes) signal accumulation.
- **Problem it solves**: Identify when institutional buying is meaningfully absorbing supply.
- **Quantifiable indicators**: `float_shares`, `avg_volume_20`, `volume_spike_ratio`, `turnover_rate`, `day_trade_ratio`, `chip_concentration`.
- **Common methods**: Volume on up-days ≥ 1.5× avg AND down-day volume contracting; rising chip concentration (top-N holder %).
- **TW limitations**: Day-trading culture inflates volume; need to subtract day-trade portion to see true accumulation.
- **TW alternatives**: TWSE/TPEX publishes daily `當沖比`; FinMind `TaiwanStockMarginPurchaseShortSale` gives leverage stress.
- **Suitable horizon**: `swing_term` primary; `short_term` for breakout-day volume.
- **Failure modes**: 隔日沖 inflates volume without true accumulation; 強制 trading suspension.
- **Hypotheses requiring backtesting**:
  - H-S1: Net non-daytrade volume ratio (volume × (1 - day_trade_ratio)) is better S-pillar signal than raw volume.
  - H-S2: 當沖比 > 50% reduces breakout follow-through probability.

### 2.5 L — Leader or Laggard

- **Original concept**: Buy market leaders (top RS ranking), not laggards.
- **Problem it solves**: Within a bull market, concentrate capital in stocks outperforming the index.
- **Quantifiable indicators**: `rs_ranking_252d` (vs. universe), `rs_vs_taiex`, `industry_rs`, sector-relative rank.
- **Common methods**: RS rating ≥ 80 (IBD scale) means top 20% of universe over last year.
- **TW limitations**: Sector rotation in TW is fast (semi → financial → biotech cycles); single-year RS may miss regime turns.
- **TW alternatives**: Compute `rs_60d` AND `rs_252d`; require both top quartile. Use AI tech 53-stock whitelist as bounded universe for sector-relative.
- **Suitable horizon**: All three; weights differ.
- **Failure modes**: Already-extended leaders mean-revert; small-cap RS spikes are illiquidity artifacts.
- **Hypotheses requiring backtesting**:
  - H-L1: Top-quartile RS-60d outperforms bottom-quartile by ≥ 8% over next 60 days.
  - H-L2: Sector-relative RS adds incremental edge over absolute RS.

### 2.6 I — Institutional Sponsorship

- **Original concept**: Increasing institutional ownership (smart money) confirms accumulation.
- **Problem it solves**: Retail-only crowded trades fade fast; institutional accumulation has staying power.
- **Quantifiable indicators**: Quarter-over-quarter institutional holder count change, top-N holder %, consecutive days of net institutional buying.
- **Common methods**: Number of funds holding up QoQ; smart-money buying surges.
- **TW limitations**: TW publishes daily institutional flow (外資/投信/自營商) — much more transparent than US, but 自營商 includes hedging which can mislead.
- **TW alternatives**: `TaiwanStockInstitutionalInvestorsBuySell` daily; track `foreign_consecutive_buy_days`, `investment_trust_consecutive_buy_days`, exclude proprietary hedging where possible.
- **Suitable horizon**: `swing_term` and `long_term`. Short-term institutional flow is too noisy.
- **Failure modes**: Foreign hedging (TWSE 期現對沖) inflates spot buy; passive index inclusion rebalance pumps then exits.
- **Hypotheses requiring backtesting**:
  - H-I1: Foreign + investment trust both net buying for ≥ 3 consecutive days has higher T+20 return.
  - H-I2: Excluding 自營商 from "institutional" composite improves signal quality.

### 2.7 M — Market Direction

- **Original concept**: Bull market = enter long; bear / correction = stand aside. ~75% of stocks follow market.
- **Problem it solves**: Avoid fighting overall regime. Single most important pillar in O'Neil's words.
- **Quantifiable indicators**: TAIEX above/below 30-week MA, distribution day count, `taiex_breadth`, advance-decline.
- **Common methods**: Long only when index in confirmed uptrend; cash when ≥ 5 distribution days in 25 sessions.
- **TW limitations**: TAIEX heavily skewed by TSMC (~30% weight); breadth may diverge from index.
- **TW alternatives**: Use TAIEX 30-week MA + 櫃買 30-week MA + breadth (% of universe above 60-day MA). For AI sector, monitor 費半 (PHLX SOX) given supply-chain coupling.
- **Suitable horizon**: All horizons — used as **regime gate**.
- **Failure modes**: TAIEX up but breadth narrow (FAANG-equivalent TSMC dominates); regime change mid-trade.
- **Hypotheses requiring backtesting**:
  - H-M1: Filtering trades to TAIEX > 30-week MA reduces max drawdown by ≥ 30%.
  - H-M2: Adding breadth filter (advancers > decliners 10-day average) improves CAGR.

---

## 3. Taiwan Market Adaptation — 33 Data Field Mapping

| # | TW Data Field | CAN SLIM Pillar | Horizon Best Fit | Source (this repo) | Notes |
|---|---|---|---|---|---|
| 1 | 季 EPS YoY | C | swing, long | `TaiwanStockFinancialStatements` | Quarterly cadence, ~45 day lag |
| 2 | 季 EPS QoQ | C | swing | same | Seasonality-aware; cyclical caveats |
| 3 | 月營收 YoY | C (leading proxy) | short, swing | `TaiwanStockMonthRevenue` | 10-day publish lag; faster than EPS |
| 4 | 月營收 MoM | C (leading proxy) | short | same | Seasonal noise; smooth with 3M avg |
| 5 | 近 3 年 EPS 成長 | A | long | `TaiwanStockFinancialStatements` | Cyclical sectors need 5y view |
| 6 | 近 3 年營收 CAGR | A | long | `TaiwanStockMonthRevenue` aggregated | Smoother than EPS CAGR |
| 7 | ROE | A | long | `TaiwanStockFinancialStatements` | Quarterly TTM rolling |
| 8 | 毛利率 | A (durability proxy) | long | same | Trend ≥ flat preferred |
| 9 | 營業利益率 | A | long | same | Distinguishes operational quality |
| 10 | 股價相對強度 RS (60d / 252d) | L | all | computed from `TaiwanStockPrice` | Need bounded universe |
| 11 | 產業相對強度 | L | all | derived from sector index | Use 53-stock AI tech whitelist sub-sectors |
| 12 | 52 週新高 | N | short, swing | `TaiwanStockPrice` | 漲跌停 day artifact requires filter |
| 13 | 20/60/120 日均線結構 | L, M (per-stock & market) | swing, long | `TaiwanStockPrice` | Stage 2 = price > 20 > 60 > 120 |
| 14 | 成交量突破 | S, N | short, swing | `TaiwanStockPrice` | Compare to 50d avg |
| 15 | 20 日均量 | S | all | same | Liquidity floor reference |
| 16 | 週轉率 | S | swing | TWSE/TPEX (currently not pulled — `# TODO(future)`) | If unavailable, downgrade confidence on S pillar |
| 17 | 當沖比 | S (anti-signal) | short | TWSE 公開資訊 (currently not in repo — `# TODO(future)`) | High day-trade ratio is risk flag |
| 18 | 外資買賣超 | I | swing | `TaiwanStockInstitutionalInvestorsBuySell` | Largest institutional category |
| 19 | 投信買賣超 | I | swing, long | same | Domestic active funds |
| 20 | 自營商買賣超 | I (lower weight) | short | same | Includes hedging — discount weight |
| 21 | 三大法人合計買賣超 | I (composite) | swing | same | Composite; lower-quality than individual |
| 22 | 法人連續買超 / 賣超天數 | I | swing | derived | Min 3 consecutive days |
| 23 | 籌碼集中度 | S (top-holder %) | swing, long | `TaiwanStockHolderShareholding` (currently not pulled — `# TODO(future)`) | Weekly cadence |
| 24 | 加權指數趨勢 | M | all (regime gate) | yfinance fallback / TWSE | 30-week MA primary |
| 25 | 櫃買指數趨勢 | M | all | same | Confirms breadth for small/mid caps |
| 26 | 費半 / Nasdaq / ADR 影響 | M (external coupling) | swing | yfinance | Especially for cat_2/cat_3 (foundry, packaging) |
| 27 | 產業族群資金流 | L, S | swing | derived (volume × close) per sector | Confirms sector strength |
| 28 | 除權息 | risk filter | event window | `tw_calendar.py` | T-1 to T+5 avoid new entry |
| 29 | 法說會 | N (catalyst) / risk filter | event window | `tw_calendar.py` | Pre-event no new entry |
| 30 | 財報公告前後 | C / risk filter | event window | derived from `TaiwanStockFinancialStatements` publish dates | T-3 to T+1 avoid |
| 31 | MSCI 調整 | I (passive flow) | event window | external (currently not in repo — `# TODO(future)`) | Quarterly; can add later |
| 32 | 季底投信作帳 | I (calendar effect) | event window | derived | Q4 / Q3 known windows |
| 33 | 低流動性風險 | S (hard filter) | all | `TaiwanStockPrice` (turnover) | Daily turnover < 30M = exclude |

**Missing-data policy**: Fields marked `# TODO(future)` are NOT available in the current data layer. When a rule depends on a missing field, that rule's `confidence_effect` MUST decrease, and the rule itself should produce `null` rather than a guess. **The coding agent must not fabricate or estimate missing values.**

---

## 4. Quantifiable Rule Table

> All thresholds below are **v1 hypotheses**, not validated.

### 4.1 Growth Quality Rules

#### Rule G-1: Monthly Revenue YoY Acceleration
- **rule_name**: `revenue_yoy_acceleration`
- **CAN SLIM mapping**: C (leading)
- **horizon**: `swing_term`
- **input_data**: `month_revenue_yoy[-1]`, `month_revenue_yoy[-2]`, `month_revenue_yoy[-3]`
- **condition**: `month_revenue_yoy[-1] ≥ 0.20 AND month_revenue_yoy[-1] > month_revenue_yoy[-2]`
- **score_effect**: `signal += 15` (medium positive)
- **risk_effect**: 0
- **confidence_effect**: `+10` if ≥ 3 months data, else `-10`
- **reason_template**: `"月營收 YoY {pct}% 且加速 (上月 {prev}%)"`
- **invalidation_signal**: `month_revenue_yoy[-1] < 0.10`
- **missing_data_behavior**: Skip rule, downgrade swing-term confidence by 5
- **backtesting_notes**: Test whether acceleration adds edge over level; account for 10-day publish lag (use T+10 for entry)

#### Rule G-2: Quarterly EPS YoY ≥ 25%
- **rule_name**: `quarterly_eps_yoy_strong`
- **CAN SLIM mapping**: C
- **horizon**: `swing_term`, `long_term`
- **input_data**: `quarterly_eps_yoy[-1]`
- **condition**: `quarterly_eps_yoy[-1] ≥ 0.25`
- **score_effect**: `signal += 20`
- **confidence_effect**: `+15` (high-quality fundamental signal)
- **invalidation_signal**: `quarterly_eps_yoy[-1] < 0.10 OR < quarterly_eps_yoy[-2] × 0.5`
- **missing_data_behavior**: rule produces `null`; downgrade swing/long confidence by 15
- **backtesting_notes**: Avoid look-ahead — only use after filing date + 1 trading day

#### Rule G-3: 3-Year EPS CAGR
- **rule_name**: `eps_cagr_3y`
- **CAN SLIM mapping**: A
- **horizon**: `long_term` only
- **input_data**: `annual_eps[-3:]`
- **condition**: `cagr(annual_eps[-3:]) ≥ 0.25 AND all(annual_eps positive)`
- **score_effect**: `signal += 25`
- **confidence_effect**: `+20`
- **invalidation_signal**: `latest_annual_eps < prior_annual_eps × 0.8`
- **missing_data_behavior**: rule null; long-term confidence -20
- **backtesting_notes**: Cyclical sectors (cat_2 foundry, cat_3 packaging) may need 5y rolling

#### Rule G-4: ROE ≥ 15%
- **rule_name**: `roe_strong`
- **CAN SLIM mapping**: A
- **horizon**: `long_term`
- **input_data**: `roe_ttm`
- **condition**: `roe_ttm ≥ 0.15`
- **score_effect**: `signal += 10`
- **confidence_effect**: `+5`
- **invalidation_signal**: `roe_ttm < 0.05`
- **missing_data_behavior**: null; long-term confidence -5

#### Rule G-5: Operating Margin Non-Declining
- **rule_name**: `op_margin_stable_or_rising`
- **CAN SLIM mapping**: A (quality durability)
- **horizon**: `long_term`
- **input_data**: `op_margin[-4:]` (last 4 quarters)
- **condition**: `op_margin[-1] ≥ mean(op_margin[-4:-1]) × 0.95`
- **score_effect**: `signal += 8`
- **risk_effect**: `+10` if op_margin trending down ≥ 200bps over 4 quarters
- **confidence_effect**: `+5`
- **invalidation_signal**: 4 quarters of monotonic decline
- **missing_data_behavior**: null; confidence -5

### 4.2 Technical Leadership Rules

#### Rule T-1: Relative Strength 60d Top Quartile
- **rule_name**: `rs_60d_top_quartile`
- **CAN SLIM mapping**: L
- **horizon**: `swing_term`
- **input_data**: `price_return_60d`, universe-wide return distribution
- **condition**: `price_return_60d` rank in top 25% of AI tech 53-stock universe
- **score_effect**: `signal += 15`
- **risk_effect**: 0
- **confidence_effect**: `+10`
- **invalidation_signal**: rank drops below 50th percentile
- **missing_data_behavior**: requires 60d history; if insufficient, null + confidence -10
- **backtesting_notes**: Compare bounded (53-stock) vs. full-market RS rank

#### Rule T-2: 52-Week High Proximity
- **rule_name**: `near_52w_high`
- **CAN SLIM mapping**: N
- **horizon**: `short_term`, `swing_term`
- **input_data**: `close`, `high_252d`
- **condition**: `close / high_252d ≥ 0.97 AND close > high_252d × 0.999` on breakout day
- **score_effect**: `signal += 12`
- **risk_effect**: `+5` if `pct_from_52w_high > 0.05` (already extended)
- **confidence_effect**: `+10`
- **invalidation_signal**: closes back below 52w high × 0.95
- **missing_data_behavior**: null if < 252 trading days available

#### Rule T-3: MA Stage 2 Alignment
- **rule_name**: `ma_stage2_alignment`
- **CAN SLIM mapping**: L
- **horizon**: `swing_term`, `long_term`
- **input_data**: `close`, `ma20`, `ma60`, `ma120`
- **condition**: `close > ma20 > ma60 > ma120 AND ma120 slope ≥ 0 over last 20 bars`
- **score_effect**: `signal += 15`
- **confidence_effect**: `+10`
- **invalidation_signal**: close drops below ma60
- **missing_data_behavior**: requires 120 bars; null otherwise

#### Rule T-4: Box Breakout
- **rule_name**: `box_breakout`
- **CAN SLIM mapping**: N (new high family)
- **horizon**: `short_term`
- **input_data**: `box_high` (last 20d high), `box_low`, `close`
- **condition**: `close > box_high × 1.005 AND (box_high - box_low) / box_low ≤ 0.15`
- **score_effect**: `signal += 18`
- **risk_effect**: 0
- **confidence_effect**: `+8`
- **invalidation_signal**: close back inside box within 3 days
- **missing_data_behavior**: requires 20 bars

#### Rule T-5: Volume-Confirmed Breakout
- **rule_name**: `volume_breakout`
- **CAN SLIM mapping**: S + N
- **horizon**: `short_term`
- **input_data**: `volume`, `avg_volume_50`
- **condition**: `volume ≥ avg_volume_50 × 1.5`
- **score_effect**: `signal += 20` (combine with T-4 box_breakout for full breakout signal)
- **confidence_effect**: `+10`
- **invalidation_signal**: 3 consecutive sub-average volume days post-breakout
- **missing_data_behavior**: requires 50d history

### 4.3 Supply / Demand Rules

#### Rule SD-1: Liquidity Floor (hard filter)
- **rule_name**: `liquidity_floor`
- **CAN SLIM mapping**: S
- **horizon**: all
- **input_data**: `avg_turnover_20`
- **condition**: `avg_turnover_20 ≥ 30_000_000` (TWD)
- **score_effect**: 0 (gate, not bonus)
- **risk_effect**: `risk = HARD_BLOCK` if condition fails
- **confidence_effect**: 0
- **invalidation_signal**: turnover drops below floor for 5 consecutive days
- **missing_data_behavior**: HARD_BLOCK by default (conservative)

#### Rule SD-2: Volume Expansion on Up Days
- **rule_name**: `up_day_volume_expansion`
- **CAN SLIM mapping**: S
- **horizon**: `swing_term`
- **input_data**: last 10 bars close + volume
- **condition**: Average volume on up-close days > average volume on down-close days × 1.3
- **score_effect**: `signal += 10`
- **confidence_effect**: `+5`
- **invalidation_signal**: ratio drops below 1.0
- **missing_data_behavior**: requires 10 bars

#### Rule SD-3: Day-Trade Ratio Risk
- **rule_name**: `daytrade_ratio_high`
- **CAN SLIM mapping**: S (anti-signal)
- **horizon**: `short_term`
- **input_data**: `day_trade_ratio` (currently not available — `# TODO(future)`)
- **condition**: `day_trade_ratio > 0.50`
- **score_effect**: 0
- **risk_effect**: `+15`
- **confidence_effect**: `-5` if field missing entirely
- **invalidation_signal**: ratio drops below 0.30
- **missing_data_behavior**: rule null; **do not assume low**; emit `data_warning`

#### Rule SD-4: Chip Concentration Rising
- **rule_name**: `chip_concentration_rising`
- **CAN SLIM mapping**: S
- **horizon**: `swing_term`, `long_term`
- **input_data**: `top_holder_pct[-4:]` (currently not available — `# TODO(future)`)
- **condition**: top-holder % rising over 4 weeks
- **score_effect**: `signal += 8`
- **confidence_effect**: `+5` (low confidence v1)
- **missing_data_behavior**: rule null; do not affect score

### 4.4 Institutional Sponsorship Rules

#### Rule I-1: Foreign Net Buy Streak
- **rule_name**: `foreign_consecutive_buy`
- **CAN SLIM mapping**: I
- **horizon**: `swing_term`
- **input_data**: `foreign_net_buy[-5:]` from `TaiwanStockInstitutionalInvestorsBuySell`
- **condition**: ≥ 3 consecutive days of net foreign buying AND cumulative ≥ 2% of avg_volume_20
- **score_effect**: `signal += 15`
- **confidence_effect**: `+10`
- **invalidation_signal**: 2 consecutive days of net foreign selling
- **missing_data_behavior**: null; confidence -10

#### Rule I-2: Investment Trust Confirmation
- **rule_name**: `investment_trust_confirms`
- **CAN SLIM mapping**: I
- **horizon**: `swing_term`, `long_term`
- **input_data**: `investment_trust_net_buy[-5:]`
- **condition**: investment trust net buying ≥ 3 of last 5 days
- **score_effect**: `signal += 10` (additive to I-1)
- **confidence_effect**: `+8`
- **invalidation_signal**: net selling 3 of last 5 days

#### Rule I-3: Foreign + Trust Both Net Buying
- **rule_name**: `foreign_and_trust_aligned`
- **CAN SLIM mapping**: I
- **horizon**: `swing_term`
- **input_data**: both above
- **condition**: I-1 AND I-2 both trigger same day
- **score_effect**: `signal += 8` (bonus for alignment)
- **confidence_effect**: `+5`
- **invalidation_signal**: either flips
- **backtesting_notes**: Test edge of alignment vs. either alone

#### Rule I-4: Self-Hedging Proprietary Filter
- **rule_name**: `proprietary_discount`
- **CAN SLIM mapping**: I (anti-signal in narrow case)
- **horizon**: `swing_term`
- **input_data**: 自營商 buy/sell broken into directional vs. hedge (currently not split — `# TODO(future)`)
- **condition**: Proprietary net buy without hedge breakdown — assume 50% hedging
- **score_effect**: 0 (do not add bonus from proprietary alone)
- **confidence_effect**: 0
- **note**: Treats 自營商 as untrusted on its own.

### 4.5 Market Direction Rules

#### Rule M-1: TAIEX 30-Week MA Regime
- **rule_name**: `taiex_30w_ma_uptrend`
- **CAN SLIM mapping**: M
- **horizon**: all (gate)
- **input_data**: TAIEX close, TAIEX 150-day MA (=30-week)
- **condition**: `taiex_close > taiex_ma_150 AND taiex_ma_150 slope ≥ 0 over 20 bars`
- **score_effect**: 0 (gate)
- **risk_effect**: `risk += 30` AND `mark regime as risk-off` if fails
- **confidence_effect**: 0
- **invalidation_signal**: TAIEX breaks 30-week MA on volume
- **missing_data_behavior**: requires 150d TAIEX history

#### Rule M-2: TPEX (櫃買) 30-Week Confirmation
- **rule_name**: `tpex_30w_confirms`
- **CAN SLIM mapping**: M (small/mid-cap breadth)
- **horizon**: all
- **input_data**: TPEX close, TPEX 150-day MA
- **condition**: same shape as M-1 but for TPEX
- **score_effect**: 0
- **risk_effect**: `+10` if TPEX disagrees with TAIEX
- **confidence_effect**: 0
- **note**: Divergence = caution flag for small/mid-cap names

#### Rule M-3: Breadth Confirmation
- **rule_name**: `breadth_positive`
- **CAN SLIM mapping**: M
- **horizon**: all
- **input_data**: % of 53-stock universe with close > MA60
- **condition**: ≥ 60% of universe above MA60
- **score_effect**: 0
- **risk_effect**: `+10` if below 40%
- **confidence_effect**: `+5` when ≥ 60%

#### Rule M-4: External Coupling — 費半 / Nasdaq
- **rule_name**: `sox_nasdaq_supportive`
- **CAN SLIM mapping**: M (external)
- **horizon**: `swing_term`
- **input_data**: SOX index trend, Nasdaq trend (yfinance)
- **condition**: Both above their 60-day MA (proxies for AI sector global demand)
- **score_effect**: `signal += 5`
- **risk_effect**: `+10` if both below
- **confidence_effect**: `+3`
- **note**: Highly relevant for cat_2 (foundry), cat_3 (packaging), cat_5 (server ODM); less so for cat_6 (cloud).

### 4.6 Risk Filter Rules

#### Rule R-1: Extended from MA20 (overheated)
- **rule_name**: `extended_from_ma20`
- **horizon**: `short_term`, `swing_term`
- **input_data**: `close`, `ma20`
- **condition**: `close > ma20 × 1.15`
- **risk_effect**: `+20`
- **invalidation_signal**: pullback to ma20

#### Rule R-2: Price-Volume Divergence
- **rule_name**: `price_volume_divergence`
- **horizon**: `swing_term`
- **input_data**: 20-bar price trend, 20-bar volume trend
- **condition**: Price making new highs while 20-bar avg volume declining ≥ 20%
- **risk_effect**: `+15`

#### Rule R-3: Institutional Selling
- **rule_name**: `institutional_selling`
- **horizon**: `swing_term`
- **input_data**: `foreign_net_buy[-3:]`, `investment_trust_net_buy[-3:]`
- **condition**: Both net sellers ≥ 2 of last 3 days
- **risk_effect**: `+25`
- **note**: hard turnaround signal

#### Rule R-4: Event Window (earnings / dividend)
- **rule_name**: `event_window_active`
- **horizon**: all
- **input_data**: `tw_calendar.py` outputs
- **condition**: Within (earnings T-3, T+1) OR (ex-rights T-1, T+5)
- **risk_effect**: `+15`
- **note**: Do not produce new-entry observations during these windows; existing positions get caution flag.

#### Rule R-5: Market Risk-Off
- **rule_name**: `market_risk_off`
- **horizon**: all
- **input_data**: M-1, M-2, M-3
- **condition**: M-1 fails OR (M-2 AND M-3 both fail)
- **risk_effect**: `risk = HARD_BLOCK` for new short_term entries; `+30` for swing/long
- **note**: This is the most important risk filter.

#### Rule R-6: Low Liquidity (hard)
- **rule_name**: `low_liquidity_hard`
- **horizon**: all
- **input_data**: `avg_turnover_20`
- **condition**: `avg_turnover_20 < 30_000_000` TWD
- **risk_effect**: `HARD_BLOCK`

#### Rule R-7: High Day-Trade Ratio (data permitting)
- See SD-3 (same data, classified as risk filter when used to block).

#### Rule R-8: High PE but Growth Insufficient
- **rule_name**: `valuation_growth_mismatch`
- **horizon**: `long_term`
- **input_data**: trailing PE, quarterly EPS YoY
- **condition**: `pe_ttm > 40 AND quarterly_eps_yoy < 0.15`
- **risk_effect**: `+20`
- **missing_data_behavior**: null if EPS data missing

---

## 5. Data Requirements

| Required | Status in this repo | If missing |
|---|---|---|
| Daily OHLCV per stock | ✅ `TaiwanStockPrice` | hard block — strategy unusable |
| Monthly revenue history | ✅ `TaiwanStockMonthRevenue` | C-pillar leading proxy disabled, downgrade confidence |
| Quarterly EPS / margin | ✅ `TaiwanStockFinancialStatements` | C/A pillar disabled |
| ROE TTM | ✅ via financial statements | A-pillar partial disable |
| Three-tier institutional flow | ✅ `TaiwanStockInstitutionalInvestorsBuySell` | I-pillar disabled |
| Margin / short balance | ✅ `TaiwanStockMarginPurchaseShortSale` | risk filter partial |
| Industry classification | ✅ `TaiwanStockInfo` + custom whitelist | sector RS disabled |
| TAIEX / TPEX | ✅ via screener_market_loader | M-pillar disabled |
| 費半 / Nasdaq | ✅ yfinance | M-pillar partial (external coupling skipped) |
| Earnings / 法說會 calendar | ✅ `tw_calendar.py` | event-window filter disabled, increase risk |
| Day-trade ratio | ❌ TODO(future) | SD-3 / R-7 emit `data_warning`, do not assume low |
| Chip concentration | ❌ TODO(future) | SD-4 disabled |
| MSCI calendar | ❌ TODO(future) | N pillar slightly weaker for passive flow |
| Stock-specific news / catalysts | partial (`yahoo_news`, `tw_news_sentiment`) | N pillar quality varies |

**Hard rule for the coding agent**: never substitute synthetic / estimated values for missing fields in real backtests. Only valid usage of mocks: dev smoke tests, with explicit `is_mock=True` flag in output.

---

## 6. Signal Score Design

- **Range**: 0 – 100
- **Purpose**: Strength of CAN SLIM bullish thesis after gating.
- **Composition (v1 hypothesis weights — all subject to backtest tuning)**:
  - Growth (C + A rules): 30% of cap (max 30 points)
  - Technical Leadership (L + T-1/T-3): 25% (max 25)
  - Breakout / Catalyst (N + T-2/T-4/T-5): 20% (max 20)
  - Supply-Demand (SD-1 satisfied + SD-2): 10% (max 10)
  - Institutional (I-1/I-2/I-3): 15% (max 15)
- **Aggregation**: For each pillar, sum rule contributions, cap at pillar max.
- **Cannot be cancelled by**: any single negative signal — Signal Score reflects bullish evidence only.
- **Why these weights are v1 only**: O'Neil's qualitative emphasis prioritizes M (market) and C+A (growth); we cannot pre-validate weighting on TW data without backtest. Weights should be tuned via walk-forward.

## 7. Risk Score Design

- **Range**: 0 – 100
- **Purpose**: Independent risk assessment — overheat, structural weakness, regime adverse.
- **Composition (v1)**:
  - Market regime (R-5): up to 30 (hard block for short-term if M fails)
  - Liquidity (R-6 / SD-1 fail): HARD_BLOCK → strategy unusable for that stock
  - Institutional reversal (R-3): up to 25
  - Technical overheat (R-1): up to 20
  - Event window (R-4): up to 15
  - Day-trade / divergence (R-2, SD-3): up to 15
  - Valuation mismatch (R-8): up to 20
- **Hard blocks** (rule produces "do not consider new long" regardless of Signal Score):
  - R-6 low liquidity
  - R-5 market risk-off **for short-term entries**
  - R-4 event window for new entries
- **Soft penalties**: additive risk score; do NOT subtract from signal_score directly. Two scores are reported **independently**.
- **Cannot be cancelled by**: high Signal Score does not zero out Risk Score; both reported, observer chooses.
- **Why v1**: weighting structurally favors regime + liquidity (consistent with O'Neil's M emphasis); concrete numbers require validation.

## 8. Confidence Score Design

- **Range**: 0 – 100
- **Purpose**: Reliability of the analysis — affected by data completeness, sample size, recency.
- **Composition (v1)**:
  - Start at 50 baseline.
  - +10 each: ≥ 12 months revenue history, ≥ 4 quarters EPS, ≥ 150 trading days OHLCV, institutional data current, TAIEX / TPEX both available.
  - −10 each: missing month revenue, missing quarterly EPS, missing institutional flow, missing market index, data > 7 days stale.
  - −20: any HARD_BLOCK condition active (the analysis is inherently lower confidence under risk regime).
- **Floor**: 0. **Ceiling**: 100.
- **Cannot be inflated by**: any signal-side bonus. Confidence ≠ conviction.
- **When < 40**: output MUST mark `low_confidence: true`; downstream UI must visibly degrade or hide recommendation strength.

---

## 9. Conditional Recommendation Design

For each horizon, the system produces an **observation card**. No buy/sell/hold verbs. Structure:

```yaml
short_term:
  status: "{neutral | watching | trigger_proximity | invalidating}"
  direction_hint: "{up | down | sideways | unclear}"
  evidence_based_reason: "{quote of triggered rules, e.g. '突破 20 日箱頂 + 量增 1.8 倍 + 外資連 3 日買超'}"
  suitable_strategy_examples:
    - "若已持有: 觀察 ma20 是否續守"
    - "若未持有: 等待量縮回測 ma5 後再評估"
  key_observation_conditions:
    - "突破後 3 日內價格不跌回箱頂之下"
    - "短線量未萎縮"
  invalidation_signals:
    - "close < box_high × 0.97"
    - "外資連 2 日轉賣超"
  risk_level: "{low | moderate | elevated | high}"
  confidence_level: "{low | moderate | high}"

swing_term:
  status: ...
  direction_hint: ...
  evidence_based_reason: "{trigger of T+I+C rules, e.g. '季 EPS YoY 32%、RS 60d top 18%、外資投信同步買超'}"
  suitable_strategy_examples:
    - "若波段持有: 觀察 ma60 為主軸停損參考"
    - "若觀察新進: 等大盤 M-1 維持 risk-on"
  key_observation_conditions: ...
  invalidation_signals:
    - "ma60 跌破且量增"
    - "季 EPS 不如預期或 forward guidance 下修"
  risk_level: ...
  confidence_level: ...

long_term:
  status: ...
  direction_hint: ...
  evidence_based_reason: "{trigger of A-pillar + multi-quarter + sector L-pillar}"
  suitable_strategy_examples: ...
  key_observation_conditions:
    - "3 年 EPS CAGR ≥ 25% 維持"
    - "產業 RS 仍 top-tier"
  invalidation_signals:
    - "毛利率 4 季持續下滑"
    - "TAIEX 跌破 30 週均線且未收復 1 個月"
  risk_level: ...
  confidence_level: ...
```

**Strict requirements for the coding agent**:
- Do not emit absolute action verbs (買/賣/持有, buy/sell/hold).
- Always include `invalidation_signals` — the user must know when to stop trusting the observation.
- All `evidence_based_reason` lines must reference triggered rule IDs (e.g. `[T-4, T-5, I-1]`) so backtest can attribute outcomes.

---

## 10. Conflict Handling Logic

Below: 10 specific conflict patterns and how the output adjusts. The general principle is **report all observed evidence; do not synthesize a single direction**.

| # | Conflict | Resolution |
|---|---|---|
| 1 | Strong fundamentals + short-term overheat | swing/long: `direction_hint=up`; short: `status=trigger_proximity, risk=elevated`. Confidence unchanged. |
| 2 | Technical breakout, but EPS/revenue do not support | short: include breakout evidence; swing/long: `direction_hint=unclear`, `risk +10`; flag `fundamentals_misaligned`. |
| 3 | High CAN SLIM signal but TAIEX weak (M fails) | All horizons risk +30; short_term HARD_BLOCK new entry; swing/long: status=`watching`, direction=`hold off`. |
| 4 | Foreign net buying but trust net selling | I score = foreign-only contribution × 0.7; flag `institutional_divergence`. |
| 5 | Institutional buying but day-trade ratio high | Discount I score by 50% IF day-trade data available; otherwise emit `data_warning` and reduce confidence. |
| 6 | New 52w high but volume not confirming | T-2 fires but T-5 fails: signal still positive, risk +10 (`distribution_risk`), invalidation tightened. |
| 7 | Revenue at new high but margin declining | A-pillar penalty in long_term (risk +15, signal cap for A-pillar); swing acknowledges revenue strength but flags `quality_deteriorating`. |
| 8 | Long-term growth strong but short-term broke key MA | long_term: direction_hint=up, status=intact; short_term: status=invalidating, direction_hint=down. Both reported separately. |
| 9 | Sector strong, individual stock weak (rank < 50%) | L score = 0 for that stock; swing/long status=watching only, do not output high signal. |
| 10 | Individual strong, sector weak | Add sector_relative_warning; risk +10; swing direction can still be `up` but confidence -5. |

---

## 11. Backtesting Plan

### Goals
- Validate Signal/Risk/Confidence calibration on TW universe.
- Quantify edge per rule and per pillar.
- Determine which weights are statistically supportable.

### Data
- Universe: 53-stock AI tech whitelist (v1). Extend later to TWSE+TPEX growth screen.
- OHLCV: 2018-01-01 to current (minimum 6 years for cyclical sectors).
- Fundamental: matching quarterly statements + monthly revenue.
- Institutional: daily three-tier from 2018-01-01.
- Index: TAIEX, TPEX (and SOX/Nasdaq for external M).

### Period
- In-sample: 2018-2022 (5 years; includes bull and bear).
- Out-of-sample: 2023-onward, walk-forward by quarter.

### Entry conditions (per horizon)
- `short_term`: T-4 + T-5 + R-4 not active + R-5 not active.
- `swing_term`: T-1 ≥ top-quartile + (G-1 or G-2 fires) + I-1 + M-1.
- `long_term`: G-3 + G-4 + T-3 + M-1.

### Exit conditions
- `short_term`: take partial when +2R; close on box re-entry or 5 days no progress.
- `swing_term`: trail by ma60; full exit on ma60 break with volume; partial on +3R.
- `long_term`: re-evaluate quarterly on EPS releases; exit on G-3 invalidation OR M-1 break for > 30 days.

### Stops
- Initial: 7% below entry (O'Neil canonical); or 1×ATR(20), whichever is tighter.
- Hard stop: 10% below entry irrespective of ATR.

### Trailing
- Swing: trail by ma60.
- Long: trail by ma120 OR quarterly EPS confirmation.

### Filters
- Regime: M-1 must be active for new entries (short_term hard, swing/long soft with risk surcharge).
- Liquidity: SD-1 must be active (HARD_BLOCK otherwise).
- Event window: skip new entries within R-4 windows.

### Transaction cost / slippage
- Round-trip cost: 0.685% (commission 0.1425% × 2 + 證交稅 0.3% + slippage 0.1% × 2).
- Apply at gross-return computation.

### Corporate actions
- Adjust historical prices for ex-dividend / ex-rights (forward-adjusted) before computing returns and signals.

### Look-ahead controls
- Quarterly EPS / monthly revenue: usable only AFTER actual publish date + 1 trading day buffer.
- Institutional flow: usable T+1 (TWSE publishes after market close).
- Calendar events: only events with publish date ≤ as-of-date.

### Metrics
- CAGR, max drawdown, Sharpe, Sortino, win rate, profit factor, expectancy in R, turnover, average exposure, total trades, Calmar.
- Per-pillar attribution: how much CAGR comes from C vs. A vs. T vs. I etc.
- WFE (walk-forward efficiency) = OOS CAGR / IS CAGR.

### Walk-forward
- 5 windows, each 4-year train / 6-month test, step 6 months.
- Tier-position sizing also tested as Phase 11/12 framework if integrated.

### Sensitivity
- Vary thresholds ±20% in 5 steps for each rule's primary threshold; record signal/risk score response.
- Sharpe stability under threshold perturbation = robustness measure.

---

## 12. Implementation Notes for Codex / Claude Code

1. **Module placement**: Place CAN SLIM logic in a new sub-package (e.g. `backend/app/services/strategy/canslim/`). Do NOT merge into existing `screener_service.py`.
2. **Reuse existing utilities**:
   - `backend/app/services/finmind_detail.py` for monthly revenue / institutional / margin
   - `backend/app/services/tw_financial_metrics.py` for quarterly EPS / ROE / margin
   - `backend/app/services/tw_calendar.py` for event windows
   - `backend/app/services/backtest/historical_data_store.py` for OHLCV PIT-safe access
3. **Pure rule functions**: each rule is `def evaluate(features, params) -> RuleResult`. No I/O inside rules.
4. **Three independent scores**: each rule contributes to `signal`, `risk`, `confidence` separately; aggregation is a pure function over rule outputs.
5. **Horizon separation**: never compute a `short_term` rule with `swing_term` inputs. Each horizon has its own feature pipeline.
6. **Output schema** (illustrative):
   ```python
   class HorizonObservation:
       horizon: Literal["short_term", "swing_term", "long_term"]
       status: Literal["neutral", "watching", "trigger_proximity", "invalidating"]
       direction_hint: Literal["up", "down", "sideways", "unclear"]
       evidence_based_reasons: list[str]
       triggered_rule_ids: list[str]
       suitable_strategy_examples: list[str]
       key_observation_conditions: list[str]
       invalidation_signals: list[str]
       risk_level: Literal["low", "moderate", "elevated", "high"]
       confidence_level: Literal["low", "moderate", "high"]
       scores: dict  # {"signal": int, "risk": int, "confidence": int}
       data_warnings: list[str]
   ```
7. **YAML-driven thresholds**: all thresholds in `canslim_thresholds_v1.yaml` (or similar), not hardcoded. Coding agent must NOT inline numbers.
8. **Backtest harness**: reuse `backend/app/services/backtest/v1/optimizer.py` infrastructure, adding CAN SLIM rule signal generation as a new candidate type (parallel to existing 起漲前觀察 flow).
9. **Tests**: every rule needs ≥ 2 unit tests (positive case, negative case) + ≥ 1 missing-data behavior test. Aggregator needs ≥ 3 integration tests.
10. **Logging**: every observation card output must log `triggered_rule_ids` + `data_warnings` to make backtest attribution trivial.

---

## 13. Things the Coding Agent Must Not Do

1. Hardcode any threshold numerically inside business logic — all thresholds live in `canslim_thresholds_v1.yaml`.
2. Mix short-term, swing-term, and long-term logic in the same evaluation path.
3. Output absolute buy / sell / hold verbs in any user-facing string.
4. Produce high-confidence conclusions when any required data field is missing or stale.
5. Use future data (e.g. quarterly EPS not yet published, T+1 institutional flow on day T) anywhere in backtesting.
6. Treat any v1 threshold as a proven fact — code MUST allow YAML override and MUST mark `tuning_required: true` in metadata.
7. Add new data sources (especially fabricated MSCI / chip concentration estimates) without explicit design approval.
8. Use subjective language in strategy output ("looks promising", "market sentiment positive", "likely to break out").
9. Hide risk conditions — every risk +N event must appear in the observation card's `data_warnings` or `invalidation_signals`.
10. Allow a high Signal Score to fully cancel or override hard-block risk conditions (R-5 short_term, R-6 liquidity, R-4 event windows).

---

## 14. Open Questions for Future Research

1. Should `自營商` be split into directional vs. hedging buckets? Requires futures + options open-interest cross-reference (not currently in repo).
2. How to encode product-cycle catalysts for AI tech (CoWoS expansion, HBM ramp, sovereign-AI orders) into N-pillar — structured news ontology required.
3. What is the right "leader" universe size for TW small-mid AI? 53-stock whitelist may be too narrow.
4. How to integrate options open interest (if/when data added) as an early demand signal?
5. Should event-window blocking apply equally across horizons, or only to short_term?
6. For cyclical sectors, should A-pillar use rolling 5y CAGR instead of 3y? Backtest required.
7. How to weight 費半 / Nasdaq external coupling per sub-sector (cat_1 .. cat_6)?
8. Should margin balance growth (融資餘額) trigger a "retail froth" risk penalty? Requires backtest.
9. What is the right re-evaluation cadence per horizon (daily vs. weekly snapshots)?
10. How does CAN SLIM integrate with the existing O'Neil Flat Base detection from Phases 9-11 (overlap vs. composition)?

---

**End of document.**

> All numbers herein are **v1 hypotheses requiring backtest validation**. The coding agent implementing this MUST treat thresholds as YAML-overridable and MUST not present output with verbs that imply trading instructions.
