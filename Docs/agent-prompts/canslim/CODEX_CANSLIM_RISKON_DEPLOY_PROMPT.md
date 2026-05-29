# Codex Task — CAN SLIM: risk_on-only deployability measurement (MEASUREMENT ONLY)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. PURE MEASUREMENT — do NOT change any rule, score, grade, threshold, gate, or YAML behavior. Goal: confirm whether a regime-conditional product — **"trade CAN SLIM momentum only in risk_on; stand aside in severe"** — is a clean, consistent edge, before we change anything.

## Why

Attribution proved the momentum edge FLIPS by regime: risk_on rewards strength/near-high; severe inverts (low-extension/far-from-high survives, near-high crushed). A single static score can't serve both. The candidate product is regime-conditional. We must measure the deployable cohort first.

## Build — extend the analysis tooling (additive, reuse existing enriched CSV)

Reuse `artifacts/canslim_attribution/extension_enriched_trades.csv` (has `window`, `regime_bucket_at_entry`, extension metrics, `net_return_pct`). NO walk-forward rerun. Add `backend/app/services/strategy/canslim/regime_deploy_analysis.py` + `backend/scripts/run_canslim_riskon_analysis.py` → `artifacts/canslim_attribution/riskon_deploy_report.{json,md}` with:

1. **By regime_bucket** (pooled + per window): n, WR, PF, avg_return, sum_return. (risk_on / risk_off / severe / unknown.)
2. **risk_on-only "strategy" view:** treat ONLY `regime_bucket_at_entry == risk_on` trades as the deployed strategy.
   - Per window: n, WR, PF, avg_return. (Note: window_2 has ~0% risk_on → expect ~no trades = correctly stands aside.)
   - Verdict `riskon_positive_all_windows` = PF > 1.0 in every window that HAS ≥ N risk_on trades (e.g. N≥20).
   - Also a risk_off-included variant (risk_on + risk_off) for comparison, so we can see if risk_off is worth trading too.
3. **severe sleeve check:** within `severe`, the low-extension subset (e.g. `pct_from_52w_high <= -10%`) → n, WR, PF, avg. Verdict `severe_lowext_worth_trading` = PF > 1.0 with adequate n. (Decides: go flat in severe, or add a defensive low-extension sleeve.)
4. A short written summary of the recommended regime→action mapping implied by the numbers (e.g. risk_on: trade momentum; risk_off: trade/reduce; severe: flat OR low-ext sleeve).

## What to report (deliverable = numbers + the implied mapping)
- regime-bucket table (pooled + per window).
- risk_on-only per-window PF/WR/avg + the two verdicts.
- risk_off-included comparison.
- severe low-extension sleeve numbers + verdict.

## Tests — `backend/tests/strategy/canslim/test_regime_deploy_analysis.py` (≥3) — NO network
1. Regime-cohort aggregation (PF/WR/avg) correct on a synthetic enriched-trade set with known answers.
2. risk_on-only filtering + per-window verdict logic correct.
3. No mutation of YAML/params/strategy.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_regime_deploy_analysis.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER the command to generate the real report from the existing enriched CSV (fast).

## STOP
When green, report the tables + verdicts + implied regime→action mapping. Do NOT implement the deployment change yet — we decide the YAML/walk-forward change together after seeing these numbers.
