# Codex Task — CAN SLIM: Distribution-Day early risk-off measurement (MEASUREMENT ONLY)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. PURE MEASUREMENT — do NOT change any rule, score, grade, threshold, gate, or YAML. Goal: test whether an O'Neil **Distribution-Day** based early-risk-off signal would have reclassified window_1's losing "risk_on" entries (2022 H1 top) as risk-off, WITHOUT killing the good window_3 (2023 bull) trades.

## Why

risk_on-only analysis showed window_1 risk_on PF 0.39 (loss) vs window_3 risk_on PF 2.36. Hypothesis: the regime label uses the **lagging** TAIEX 30-week MA, which mislabeled the 2022-H1 topping process as risk_on. O'Neil's Distribution-Day count is designed to flag tops BEFORE the MA breaks. `distribution_day_count` already exists (Phase F regime) but is NOT wired into the regime label. Measure its retro-diagnostic power before deciding to wire it in.

## Build — analysis tooling (additive, reuse existing data)

Reuse `artifacts/canslim_attribution/extension_enriched_trades.csv` (entry_date, regime_bucket_at_entry, net_return_pct, window). For each trade's `entry_date`, recompute a PIT Distribution-Day signal from the **TAIEX** series in the OHLCV `HistoricalDataStore` (data_id `TAIEX`, bars ≤ entry_date):
- `distribution_day` = index close down ≥ 0.2% on volume higher than the prior day.
- `dist_day_count_25` = count of distribution days in the trailing 25 sessions.
- `dist_risk_off` = `dist_day_count_25 >= 5` (O'Neil canonical; read the threshold from YAML if present, else 5 as an analysis constant — this is analysis, not a strategy param).
- (optional) `breadth_rolling_over` if breadth history is available.

Add `backend/app/services/strategy/canslim/distday_analysis.py` + `backend/scripts/run_canslim_distday_analysis.py` → `artifacts/canslim_attribution/distday_report.{json,md}`:

1. **Reclassification of window_1 risk_on losers:** of the window_1 `regime_bucket_at_entry == risk_on` trades (the losers), what fraction have `dist_risk_off == True`? (i.e., would the dist-day signal have caught them?)
2. **Effective cohort "risk_on AND NOT dist_risk_off"** per window: n, WR, PF, avg_return. Compare side-by-side to plain risk_on.
3. **False-positive check on window_3:** how many good window_3 risk_on trades does `dist_risk_off` remove, and what's the PF of removed vs kept? (We must not gut the bull window.)
4. Verdict flags: `distday_rescues_window1` = (window_1 risk_on PF improves meaningfully once dist_risk_off entries are excluded) AND `distday_preserves_window3` = (window_3 risk_on PF stays strong, e.g. ≥ ~2.0, after exclusion).

## What to report (deliverable = numbers + verdicts)
- window_1 risk_on losers: % flagged by dist_risk_off.
- "risk_on AND NOT dist_risk_off" per-window PF/WR/avg vs plain risk_on.
- window_3 false-positive impact.
- The two verdicts → does wiring Distribution Days into the regime label look justified?

## Tests — `backend/tests/strategy/canslim/test_distday_analysis.py` (≥3) — NO network
1. Distribution-day count + `dist_risk_off` computed correctly from a synthetic TAIEX series (known answer, incl. the "higher volume" condition).
2. Cohort re-aggregation (risk_on AND NOT dist_risk_off) PF/WR/avg correct on a synthetic set.
3. No mutation of YAML/params/strategy.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_distday_analysis.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER the command to generate the real report from the existing enriched CSV + TAIEX store (fast, no walk-forward rerun).

## STOP
When green, report the numbers + verdicts. Do NOT wire Distribution Days into the live regime yet — we decide that together based on whether it rescues window_1 without gutting window_3.
