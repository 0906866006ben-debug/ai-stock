# Codex Task — CAN SLIM Phase C2: Technical rule functions (T-1..T-5) + small feature additions

> **Phase C, sub-task 2 of 6.** A, B, C1 (`rules_growth`) are done and green. **Do ONLY C2.** No scoring/aggregation, no other pillars. Stop when C2 tests are green.

## Background

Same pattern as C1: each rule is a pure `def evaluate_tX(f: CanslimFeatures, params) -> RuleResult`. Thresholds come only from `params["technical"]["rules"]["T-x"]`. Ratio/price fields in `CanslimFeatures` are already decimals.

### Read first
- `rules_growth.py` (C1) — mirror its structure exactly (per-rule function, `TECHNICAL_RULES` list, reason strings, missing→confidence_delta).
- `features.py` / `CanslimFeatures` and `types.RuleResult`.
- `params["technical"]["rules"]` keys T-1..T-5.

## Step 1 — small ADDITIVE feature extension (do not change existing fields/semantics)

The breakout rules need data Phase B didn't expose. Add to `CanslimFeatures` and populate in `build_features` / `_ohlcv_features`:
- `latest_volume: float | None` — volume of the most recent bar (last row).
- `box_high_prior_20: float | None` — max **high** over the 20 bars **excluding the most recent bar** (i.e. `high.iloc[-21:-1]`); needs ≥21 bars else None + `missing_fields`.
- `box_low_prior_20: float | None` — min **low** over the same prior-20 window.

Keep existing `box_high_20`/`box_low_20` exactly as they are (inclusive of today) — additive only. Add ≤2 small tests to `test_phase_b_features.py` (or a new `test_phase_b_features_ext.py`) covering the new fields incl. the <21-bars None path. Phase B's existing tests must stay green.

## Step 2 — rules (`backend/app/services/strategy/canslim/rules_technical.py`)

- **T-1 `rs_60d_top_quartile`** (swing): trigger `rs_60d_pct >= rank_percentile_min` (0.75). Trigger → signal +15, confidence +10. None → confidence `missing_data_confidence_delta` (-10), not triggered.
- **T-2 `near_52w_high`** (short, swing): needs `close` and `high_252d`. Trigger when `close/high_252d >= close_to_high_252d_min` (0.97) AND `close > high_252d * breakout_high_252d_multiplier` (0.999). Trigger → signal +12, confidence +10. Additionally if `pct_from_52w_high > risk_pct_from_52w_high_above` (0.05) set `risk_delta=risk_delta_if_extended` (5). Missing high_252d → not triggered (no confidence delta specified for T-2 → use 0).
- **T-3 `ma_stage2_alignment`** (swing, long): needs close/ma20/ma60/ma120/ma120_slope. Trigger when `close>ma20>ma60>ma120` AND `ma120_slope >= ma120_slope_min` (0.0). Trigger → signal +15, confidence +10. Any None → not triggered, confidence 0.
- **T-4 `box_breakout`** (short): needs `close` and `box_high_prior_20`/`box_low_prior_20`. Trigger when `close > box_high_prior_20 * breakout_multiplier` (1.005) AND box tightness `(box_high_prior_20 - box_low_prior_20)/box_low_prior_20 <= box_range_pct_max` (0.15). Trigger → signal +18, confidence +8. Missing → not triggered.
- **T-5 `volume_breakout`** (short): needs `latest_volume` and `avg_volume_50`. Trigger when `latest_volume >= avg_volume_50 * volume_multiple_min` (1.5). Trigger → signal +20, confidence +10. Missing → not triggered.

Expose `TECHNICAL_RULES = [evaluate_t1, …]` and per-rule horizon tags read from YAML. `reason` strings cite rule_id + key value; no buy/sell/hold verbs.

## Tests — `backend/tests/strategy/canslim/test_phase_c2_technical.py` (≥11)
Positive + negative for each of T-1..T-5, plus ≥1 missing-data path. Build `CanslimFeatures` directly with kwargs. Read expected deltas from `load_params()` — don't hardcode numbers. For T-2 include an "extended" case asserting the +5 risk_delta.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_c2_technical.py -q
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q   # C1 + B + C2 all green
.venv\Scripts\python -m pytest backend\tests\ -q                    # full suite stays green
```

## STOP
When green, report the feature additions, the 5 rule functions, and test results. Do NOT start C3 (supply rules).
