# Codex Task — CAN SLIM Phase C4: Institutional rule functions (I-1..I-4) + avg_volume_20

> **Phase C, sub-task 4 of 6.** A, B, C1, C2, C3 are done and green. **Do ONLY C4.** No scoring/aggregation, no other pillars. Stop when C4 tests are green.

## Background

Same pure-function pattern. Thresholds only from `params["institutional"]["rules"]["I-x"]`. Relevant `CanslimFeatures` fields: `foreign_net_5: list[float]|None`, `trust_net_5: list[float]|None`, `dealer_net_5: list[float]|None` (each = last 5 daily net values, chronological, already T+1 lagged in Phase B).

### Read first
- `rules_growth/technical/supply.py` — mirror structure (`INSTITUTIONAL_RULES` list, horizon tags from YAML, reason strings, missing→confidence_delta).
- `types.RuleResult` (now has `hard_block`), `params["institutional"]["rules"]`.

## Step 1 — ADDITIVE feature `avg_volume_20`

Add `avg_volume_20: float | None` to `CanslimFeatures` and populate in `_ohlcv_features` (`volume.tail(20).mean()` when ≥20 bars, else None + `missing_fields`). Additive; existing fields/tests untouched. Add 1 small test for it in the Phase B test file.

## Step 2 — rules (`backend/app/services/strategy/canslim/rules_institutional.py`)

- **I-1 `foreign_consecutive_buy`** (swing): needs `foreign_net_5`. Primary condition = last `consecutive_days_min` (3) values all `> 0`. Cumulative sub-condition: `sum(last 3 foreign_net) >= avg_volume_20 * cumulative_avg_volume_20_min_ratio` (0.02) — apply ONLY when `avg_volume_20` is not None; if `avg_volume_20` is None, skip the cumulative gate and add a `data_warning` ("cumulative-vs-volume check skipped; avg_volume_20 missing"). Trigger (both conditions, or primary-only when volume missing) → signal +15, confidence +10. Missing `foreign_net_5` → not triggered, confidence `missing_data_confidence_delta` (-10).
  - NOTE: net-buy vs volume is a unit-matching **v1 hypothesis** (FinMind net units may differ from share volume) — that's fine, it's flagged for backtest tuning; do not try to "fix" units here.
- **I-2 `investment_trust_confirms`** (swing, long): needs `trust_net_5`. Trigger when count of values `> 0` in last `lookback_days` (5) is `>= net_buy_days_min` (3) → signal +10, confidence +8. Missing → not triggered, confidence 0.
- **I-3 `foreign_and_trust_aligned`** (swing): trigger only when BOTH I-1 and I-2 trigger. Implement by calling `evaluate_i1` and `evaluate_i2` internally and checking their `.triggered`. Trigger → signal +8, confidence +5 (bonus for alignment). Else not triggered, deltas 0.
- **I-4 `proprietary_discount`** (swing, anti-signal): dealer/proprietary flow is untrusted without a hedge breakdown (`hedge_breakdown_available: false`). Always return `triggered=False`, all deltas 0, `data_warning` ("dealer/proprietary flow treated as untrusted — no hedge breakdown available; assumed_hedging_ratio 0.50"). This rule never adds signal from proprietary alone.

Expose `INSTITUTIONAL_RULES = [evaluate_i1, …]`. No buy/sell/hold verbs.

## Tests — `backend/tests/strategy/canslim/test_phase_c4_institutional.py` (≥9)
- I-1: 3-consecutive-buy + sufficient cumulative → triggered; only 2 buy days → not; missing foreign_net_5 → not triggered + confidence −10; `avg_volume_20=None` path → triggered on primary-only + data_warning.
- I-2: ≥3 buy days → triggered; <3 → not; missing → not.
- I-3: both I-1 & I-2 trigger → triggered; only one → not.
- I-4: always `triggered False`, deltas 0, data_warning present.
Build `CanslimFeatures` with kwargs; read expected deltas from `load_params()`.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_c4_institutional.py -q
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
When green, report `avg_volume_20` addition, the 4 rule functions, and test results. Do NOT start C5 (market rules).
