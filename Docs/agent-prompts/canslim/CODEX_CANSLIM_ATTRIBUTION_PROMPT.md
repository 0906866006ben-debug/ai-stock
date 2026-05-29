# Codex Task — CAN SLIM: grade × regime attribution analysis (MEASUREMENT ONLY)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This task is PURE MEASUREMENT — do NOT change any rule, threshold, score, grade, or gate. Do NOT try to "fix" performance. The only goal is to produce data that tells us whether `grade` carries OOS edge, and how that interacts with regime. Run with the regime entry policy DISABLED so the FULL population (including B-grade) is observed.

## Why

Real walk-forward showed window_2 got WORSE after the grade ladder gate (no-gate PF 1.03 → gated PF 0.40), implying B-grade signals were the profitable ones there and A/S underperformed. Before changing anything else, we must measure the empirical relationship: does `grade` (S/A/B/C) actually predict OOS forward return, and is it regime-dependent?

## Build — an attribution run + report (additive, no behavior change to the strategy)

Add `backend/app/services/strategy/canslim/attribution.py` (or extend `walk_forward.py` with an analysis-only entry point) that:

1. Runs the existing real-data walk-forward signal+trade generation **with `regime_entry_policy.enabled = False`** (full population), over the same 3 windows / 53-stock universe / OHLCV + PIT stores. Reuse `run_real_data_walk_forward` plumbing; do NOT alter it — pass an override that disables the policy for this analysis only.
2. For every OOS trade, record a row: `window`, `horizon`, `stock_id`, `entry_date`, `grade`, `regime_bucket_at_entry` (`risk_on`/`risk_off`/`severe`/`unknown` via `regime_severity(build_market_features(entry_date, store), params)`), `net_return_pct`, `holding_days`.
3. Aggregate and write `artifacts/canslim_attribution/attribution_report.json` + a readable markdown table:
   - **By grade** (per window and pooled): n, win_rate, profit_factor, avg_return, median_return.
   - **By grade × regime_bucket**: same metrics.
   - **Regime composition** of each window's OOS span (fraction of entry-eligible dates in each bucket).
   - A computed verdict flag per window: `grade_monotonic` = (PF(S) ≥ PF(A) ≥ PF(B)) — True/False — and pooled.

## What to report back (this is the deliverable — numbers, not a fix)
- The by-grade and by-grade×regime tables for all 3 windows.
- Whether grade is monotonic in PF (per window + pooled).
- Whether B outperformed A/S in window_2 specifically (confirm/deny the hypothesis).
- Regime composition of each window.

## Tests — `backend/tests/strategy/canslim/test_attribution.py` (≥3) — NO network
1. Attribution aggregation computes WR/PF/avg-return correctly on a synthetic set of tagged trades (known answers).
2. `regime_bucket_at_entry` tagging maps a known market state to the right bucket.
3. The analysis run does NOT mutate YAML/params or the strategy (assert `regime_entry_policy` in the live YAML is unchanged after the run; the disable is an in-run override only).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_attribution.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER the command to run the real attribution (≈ one walk-forward pass, ~30 min) and where the report lands.

## STOP
When green, report. Do NOT propose or implement any gate/threshold/rule change — we decide that together AFTER reading the attribution numbers.
