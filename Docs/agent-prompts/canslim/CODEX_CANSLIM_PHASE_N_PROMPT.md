# Codex Task — CAN SLIM Phase N: portfolio simulator + portfolio-level risk overlay research (MEASUREMENT)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Specifics:
> - MEASUREMENT/research only. Do NOT change any signal/rule/score/grade/gate, and do NOT wire overlays into production yet.
> - The signal is validated (M3): it's a momentum/trend-continuation strategy. We are NOT touching it. This phase studies PORTFOLIO-LEVEL risk control to cut bear-year drawdown (2022 esp.).
> - **Anti-overfit the OVERLAY ITSELF:** test only 2–3 threshold values per overlay; judge by CONSISTENT improvement across ALL bad years (2011/2012/2016/2018/2022) with minimal damage to good years — NEVER pick the setting that just minimizes 2022. Report the tradeoff explicitly.

> **Phase N.** M3 done: `artifacts/canslim_multicycle/multicycle_tagged_trades.csv` (2011-2025, 28,768 trades, per-trade entry_date/grade/regime_bucket/net_return_pct/holding_days/extension). TAIEX is in the OHLCV `HistoricalDataStore`. **Do ONLY Phase N.** Stop when tests green + run command + a first comparison read are reported.

## Why

Trade-level PF (1.16) doesn't reveal portfolio drawdown or investability. We need a portfolio equity curve to evaluate risk overlays. M3 showed the edge is real but with concentrated bear-year drawdown — best managed at the portfolio level, not per-signal.

## Build

### 1. Portfolio simulator — `backend/app/services/strategy/canslim/portfolio_sim.py`
From the tagged trades, build a time-ordered portfolio equity curve under a configurable sizing model:
- `max_concurrent` positions (e.g. 10), equal-weight, fixed fraction per position; entry on `entry_date`, exit on `entry_date + holding_days`, realize `net_return_pct`.
- Capital accounting with concurrency cap (skip/queue entries when full — document which).
- Output metrics: CAGR, max_drawdown, Sharpe, Sortino, Calmar, annual returns, per-named-cycle returns, exposure %, trade count.
- This is the BASELINE (no overlay).

### 2. Overlays (each toggleable; evaluate individually + O1+O2 combined)
- **O1 market trend filter:** skip NEW entries when TAIEX `close < MA_long` OR `MA_long slope < 0`. Test `MA_long ∈ {150, 200}` days.
- **O2 drawdown circuit-breaker:** halt NEW entries when portfolio equity drawdown from peak `> D`; resume when DD recovers (e.g. above `D/2`). Test `D ∈ {10%, 15%, 20%}`. (Sequential — depends on the simulated equity path.)
- **O3 regime-scaled sizing:** position size × `{risk_on:1.0, risk_off:0.5, severe:0.0}` using the existing `regime_bucket_at_entry` tag. (One config; it's not a fitted threshold.)

### 3. Comparison report — `artifacts/canslim_portfolio_overlay/overlay_report.{json,md}`
Baseline vs O1(each MA) vs O2(each D) vs O3 vs O1+O2 → table of CAGR, maxDD, Calmar, Sharpe, AND a per-year + per-named-cycle breakdown (highlight 2011/2012/2016/2018/2022 vs the good years). For each overlay, report explicitly: **how much bear-year drawdown/loss it removes AND how much good-year CAGR it gives up.** Verdict = the overlay (if any) that improves Calmar/maxDD consistently across bad years with the least CAGR sacrifice. If no overlay helps without gutting returns, SAY SO.

## Tests — `backend/tests/strategy/canslim/test_portfolio_sim.py` (≥5) — NO network
1. Portfolio equity curve + CAGR/maxDD/Calmar correct on a synthetic trade set with known answers.
2. Concurrency cap respected (entries skipped/queued when full per the documented rule).
3. O1 trend filter removes entries on dates where synthetic TAIEX is below MA / negative slope.
4. O2 drawdown breaker halts entries after a synthetic DD breach and resumes on recovery (sequential correctness).
5. O3 sizing scales by regime bucket; no mutation of YAML/params/strategy.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_portfolio_sim.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER the command to generate the real overlay report from the M3 tagged CSV + TAIEX store (fast — no backtest rerun).

## STOP
When green, report the baseline portfolio metrics + the overlay comparison table + the honest verdict. Do NOT wire any overlay into production — we decide together after seeing the drawdown/CAGR tradeoffs.
