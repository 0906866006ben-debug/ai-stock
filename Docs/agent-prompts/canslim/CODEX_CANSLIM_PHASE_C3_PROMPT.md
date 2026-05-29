# Codex Task — CAN SLIM Phase C3: Supply/Demand rule functions (SD-1..SD-4) + RuleResult.hard_block

> **Phase C, sub-task 3 of 6.** A, B, C1 (`rules_growth`), C2 (`rules_technical` + feature additions) are done and green. **Do ONLY C3.** No scoring/aggregation, no other pillars. Stop when C3 tests are green.

## Background

Same pure-function pattern as C1/C2. Thresholds only from `params["supply"]["rules"]["SD-x"]`. Relevant `CanslimFeatures` fields: `avg_turnover_20: float|None`, `up_down_volume_ratio_10: float|None`, `day_trade_ratio` (always None — not in data layer), `chip_concentration` (always None).

### Read first
- `rules_growth.py` / `rules_technical.py` — mirror structure (per-rule fn, `SUPPLY_RULES` list, horizon tags from YAML, reason strings).
- `types.RuleResult`, `params["supply"]["rules"]`.

## Step 1 — ADDITIVE field on `RuleResult` (types.py)

Add `hard_block: bool = False` to the `RuleResult` frozen dataclass (after the existing fields, default False). This represents gate-type rules that must block new-entry observations regardless of signal. Existing C1/C2 results default to False, so their tests stay green. (The Phase E aggregator will OR `hard_block` across all rule results.)

## Step 2 — rules (`backend/app/services/strategy/canslim/rules_supply.py`)

- **SD-1 `liquidity_floor`** (all horizons; a GATE, not a bonus): pass when `avg_turnover_20 >= avg_turnover_20_min_twd` (30,000,000). On pass → `triggered=True, signal_delta=0`. On fail → `triggered=False, hard_block=True`, reason citing the floor. **Missing `avg_turnover_20` → `hard_block=True`** (conservative default per research doc), `triggered=False`, `data_warning`. `confidence_delta=0` in all cases.
- **SD-2 `up_day_volume_expansion`** (swing): trigger `up_down_volume_ratio_10 >= up_to_down_volume_ratio_min` (1.3) → signal +10, confidence +5. None → not triggered, confidence 0.
- **SD-3 `daytrade_ratio_high`** (short, anti-signal): `day_trade_ratio` is ALWAYS None in this repo (`thresholds.data_available: false`). So this rule never triggers: return `triggered=False`, `confidence_delta=confidence_delta_missing` (-5), and a `data_warning` ("day_trade_ratio unavailable — cannot assess day-trade risk; do not assume low"). Do NOT apply any risk_delta (data unavailable).
- **SD-4 `chip_concentration_rising`** (swing, long): `chip_concentration` ALWAYS None (`data_available: false`). Per research doc missing_data_behavior = "rule null; do not affect score". Return `triggered=False`, all deltas 0, `data_warning` ("chip_concentration unavailable").

Expose `SUPPLY_RULES = [evaluate_sd1, …]`. No buy/sell/hold verbs in reasons.

## Tests — `backend/tests/strategy/canslim/test_phase_c3_supply.py` (≥9)
- SD-1: pass case (`triggered True`, `hard_block False`); fail case (`triggered False`, `hard_block True`); missing-turnover case (`hard_block True`).
- SD-2: trigger + non-trigger + missing.
- SD-3: assert `triggered False`, `confidence_delta == -5` (read from params), `data_warning` present.
- SD-4: assert `triggered False`, all deltas 0, `data_warning` present.
- One test asserting C1/C2 results still default `hard_block False` (regression guard for the new field).
Build `CanslimFeatures` with kwargs; read expected deltas from `load_params()`.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_c3_supply.py -q
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
When green, report the `RuleResult.hard_block` addition, the 4 rule functions, and test results. Do NOT start C4 (institutional rules).
