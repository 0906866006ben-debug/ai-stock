# Codex Task — CAN SLIM Phase C1: Growth rule functions (G-1..G-5)

> **Phase C, sub-task 1 of 6.** Phases A (scaffold+YAML) and B (`features.py` → `CanslimFeatures`) are done and green. Phase C is split into 6 small handoffs (one rule file each) to keep each change small and verifiable. **Do ONLY C1: `rules_growth.py` (G-1..G-5).** No scoring/aggregation (Phase E), no other pillars. Stop when C1 tests are green.

## Background

Each CAN SLIM rule is a **pure function** `evaluate(features, params) -> RuleResult`. It reads feature values from `CanslimFeatures` (Phase B) and thresholds from the loaded YAML params (Phase A). It applies the rule's effects (signal/risk/confidence deltas) and returns a `RuleResult`. No I/O.

### Things already built (read them first)
- `backend/app/services/strategy/canslim/types.py` → `RuleResult(rule_id, triggered, signal_delta=0, risk_delta=0, confidence_delta=0, reason=None, data_warning=None)` (frozen dataclass).
- `backend/app/services/strategy/canslim/params.py` → `load_params()` returns an immutable nested mapping. Growth thresholds at `params["growth"]["rules"]["G-1"]["thresholds"][...]` and effects at `[...]["effects"][...]`.
- `backend/app/services/strategy/canslim/features.py` → `CanslimFeatures`. **All ratio fields are stored as decimals** (e.g. 0.25 = 25%) — compare directly against YAML thresholds (also decimals).
- Relevant feature fields: `month_revenue_yoy: list[float]|None` (chronological, most-recent last), `quarterly_eps_yoy: float|None`, `eps_cagr_3y: float|None`, `roe_ttm: float|None`, `op_margin_last4: list[float]|None`.

## Hard constraints
1. **Pure**, no I/O, no network. Inputs are `CanslimFeatures` + params only.
2. **No hardcoded thresholds** — every number comes from `params["growth"]["rules"]["G-x"]`. The only literals allowed are list indices and the rule_id strings.
3. **Missing data** → return `RuleResult(rule_id, triggered=False, confidence_delta=<missing_data_confidence_delta from YAML>, data_warning="...")`. Never fabricate; do not apply signal_delta when the input is None.
4. Effects applied **only when the rule triggers** (signal/risk deltas); confidence_delta applies per YAML (complete vs missing variants).

## Rules to implement (`backend/app/services/strategy/canslim/rules_growth.py`)

Each as `def evaluate_g1(f: CanslimFeatures, params) -> RuleResult:` … through `g5`. Also expose `GROWTH_RULES = [evaluate_g1, …]` and a `HORIZONS` tag per rule (read from YAML `horizons`).

- **G-1 `revenue_yoy_acceleration`** (swing): needs `month_revenue_yoy` with ≥ `min_months_required` (3). Trigger when `month_revenue_yoy[-1] >= latest_month_revenue_yoy_min` (0.20) AND `[-1] > [-2]`. On trigger: `signal_delta=15`, `confidence_delta=confidence_delta_complete` (+10). Missing/insufficient months → `confidence_delta=missing_data_confidence_delta` (-5), not triggered.
- **G-2 `quarterly_eps_yoy_strong`** (swing, long): trigger `quarterly_eps_yoy >= quarterly_eps_yoy_min` (0.25). Trigger → signal +20, confidence +15. None → confidence `missing_data_confidence_delta` (-15).
- **G-3 `eps_cagr_3y`** (long): trigger `eps_cagr_3y >= annual_eps_cagr_3y_min` (0.25). Trigger → signal +25, confidence +20. None → -20.
- **G-4 `roe_strong`** (long): trigger `roe_ttm >= roe_ttm_min` (0.15). Trigger → signal +10, confidence +5. None → -5.
- **G-5 `op_margin_stable_or_rising`** (long): needs `op_margin_last4` with `quarters_required` (4) values. Trigger when `latest >= mean(prior 3) * latest_vs_prior_mean_min_multiplier` (0.95) → signal +8, confidence +5. Additionally if the 4-quarter trend declines (latest < first by ≥ `downtrend_bps_over_4q`/10000 in ratio terms) set `risk_delta=risk_delta_if_downtrend` (10). Missing → confidence -5.

Put a short `reason` string on each triggered result citing the rule_id and the key value (no buy/sell/hold verbs).

## Tests — `backend/tests/strategy/canslim/test_phase_c1_growth.py` (≥11: positive+negative each + ≥1 missing path)
For each rule: a `CanslimFeatures` that triggers, one that doesn't, and (at least once per rule) a None-input case asserting `triggered is False` and the correct `confidence_delta` from YAML. Build `CanslimFeatures` directly with keyword args (don't go through `build_features`). Assert deltas equal the YAML values via `load_params()` (don't hardcode expected numbers — read them from params so the test stays in sync).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_c1_growth.py -q
.venv\Scripts\python -m pytest backend\tests\ -q   # full suite stays green
```

## STOP
When green, report the 5 functions + test results. Do NOT start C2 (technical rules) or any other pillar.
