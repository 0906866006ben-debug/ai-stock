# Codex Task — CAN SLIM: extension attribution (MEASUREMENT ONLY) — is "lateness" the real edge-killer?

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. PURE MEASUREMENT — do NOT change any rule, score, grade, threshold, or gate. Goal: test the hypothesis that ENTRY EXTENSION (how far the stock has already run at entry) inversely predicts forward return, more so than `grade`.

## Why

Attribution showed grade is INVERSELY related to OOS return (pooled PF: S 0.78 < A 0.99 < B 1.19; B×severe in window_2 = PF 1.71 / +2.02%). Hypothesis: `signal_score` rewards "everything is already hot" = extended/late entries, while the real edge is the pre-breakout / low-extension setup. We must confirm whether **low extension → positive edge across regimes**, independent of grade.

## Build — extend the attribution tooling (additive, no strategy change)

Reuse the existing tagged OOS trades (`artifacts/canslim_attribution/...tagged_oos_trades.csv`) — join, do NOT re-run the 30-min walk-forward. For each trade, compute **point-in-time extension metrics at `entry_date`** from the OHLCV `HistoricalDataStore` (reuse existing feature helpers in `features.py`; use bars ≤ entry_date only):
- `close_to_ma20` = close / ma20
- `pct_from_52w_high` = close / high_252d − 1
- `return_20d`, `return_60d` (already-realized run-up at entry)
- (optional, only if cheap) `days_since_breakout` = bars since last close crossed the prior 20-bar box high

Add `backend/app/services/strategy/canslim/extension_attribution.py` + a script `backend/scripts/run_canslim_extension_attribution.py` that produces `artifacts/canslim_attribution/extension_report.{json,md}` with:
- **By extension bucket** (use BOTH fixed bands and tertiles): for `close_to_ma20` bands `<1.05 / 1.05–1.15 / >1.15`, and `pct_from_52w_high` bands `≤−10% / −10%..−3% / >−3%` → n, WR, PF, avg_return.
- **Extension × regime_bucket** (risk_on/risk_off/severe): same metrics.
- **Extension × grade**: same metrics (to see if extension dominates grade).
- A verdict flag: `low_extension_positive_edge` = (PF of the lowest-extension bucket > 1.0 in ALL regimes) and `extension_monotonic` = (PF decreases as extension increases).

## What to report (the deliverable = numbers)
- The extension-bucket PF/WR/avg tables (fixed + tertile), pooled and per window.
- Extension × regime and extension × grade tables.
- Verdicts: does low extension carry positive edge across regimes? Does extension explain returns better than grade?

## Tests — `backend/tests/strategy/canslim/test_extension_attribution.py` (≥3) — NO network
1. Extension metrics computed correctly from a synthetic OHLCV store at a given entry_date (known values).
2. Bucketing + PF/WR/avg aggregation correct on a synthetic tagged-trade set with known answers.
3. The analysis does not mutate YAML/params/strategy.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_extension_attribution.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER the command to generate the real extension report from the existing tagged CSV (fast — no walk-forward rerun), and where it lands.

## STOP
When green, report the extension tables + verdicts. Do NOT propose or implement any scoring/rule redesign — we decide that together after reading these numbers.
