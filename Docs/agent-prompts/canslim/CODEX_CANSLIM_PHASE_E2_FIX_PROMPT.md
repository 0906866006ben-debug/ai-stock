# Codex Task — CAN SLIM Phase E2 (fix): per-horizon signal normalization for grading

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This fix is squarely anti-zero-signal: today every `short_term` card is structurally locked to grade C and `long_term` can't reach A, because grade bands are global but each horizon's achievable signal ceiling differs. Fix = normalize signal per horizon. Do NOT add hard gates.

> **Scope:** revise `backend/app/services/strategy/canslim/aggregator.py` and update affected tests. Do ONLY this. Stop when green.

## Problem (confirmed)

`grade` is computed from absolute `signal_score` against global bands (S≥75/A≥55/B≥35). But applicable rules differ per horizon:
- `short_term`: only breakout_catalyst rules apply → max signal ≈ 20 → forced grade C.
- `long_term`: growth + only T-3 (+base) → max ≈ 65 → can't reach A.
- `swing_term`: all pillars → ~100.
So a perfect short-term breakout scores C. Wrong.

## Fix — normalize by each horizon's achievable max

1. Add `_achievable_signal_max(horizon, params) -> int`: compute the maximum signal_score reachable in this horizon, using the SAME pillar logic as `_signal_breakdown`:
   - For each pillar in `SIGNAL_PILLARS`, sum `effects.signal_delta` of the pillar's rules **whose YAML `horizons` include this horizon**, capped at the pillar's `pillar_caps` value.
   - For `breakout_catalyst`, the achievable max = its full `pillar_caps` value (the base pattern can always fill the pillar to cap via `quality_score=100`), regardless of which T-rules apply.
   - Sum the capped pillar achievables. Read both `horizons` and `signal_delta` from `params` (paths: growth.rules/technical.rules/supply.rules/institutional.rules → `[rule_id]["horizons"]` and `["effects"]["signal_delta"]`, default 0). Guard against 0 (return at least 1 to avoid div-by-zero).

2. In `aggregate(...)`: keep the existing raw computation, then
   - `raw_signal = clamp(sum(pillar_breakdown.values()), 0, signal.range_max)`
   - `achievable = _achievable_signal_max(horizon, params)`
   - `signal_score = clamp(round(raw_signal / achievable * 100), signal.range_min, signal.range_max)`
   - `grade = _grade(signal_score, scoring)` (single global bands — unchanged).

3. Add transparency fields to `AggregateResult` (additive): `signal_raw: int`, `signal_achievable_max: int`. Keep `pillar_breakdown` as the RAW per-pillar values. `signal_score` is now the normalized 0–100 value used for grading.

Result: a full short-term breakout (raw 20 / achievable 20) → 100 → S. A long-term stock at raw 45 / achievable 65 → ~69 → A. swing unchanged in spirit.

## Behavior to preserve (guardrail checks)
- Missing data must still depress the grade for horizons where that data IS applicable (denominator is the FIXED per-horizon achievable, NOT per-stock available data) — confirm a swing stock missing all fundamentals normalizes low + low_confidence.
- `short_term` does not include fundamental/institutional rules in its denominator, so a pure breakout legitimately reaches S (intended).
- Hard block, risk_score, confidence_score logic unchanged.

## Tests
Update `backend/tests/strategy/canslim/test_phase_e_aggregator.py` for the new normalized numbers (read `signal_delta`/`horizons` from `load_params()` to derive expected achievable; don't hardcode). Add:
- `test_short_term_full_breakout_reaches_S` — raw==achievable → signal 100 → grade S.
- `test_long_term_achievable_below_100` — assert `_achievable_signal_max("long_term", params) < 100` and a strong long stock can reach A.
- `test_swing_missing_fundamentals_normalizes_low` — swing achievable is high; missing growth/institutional → low normalized + low_confidence.
Re-run the Phase G observer and Phase H frequency tests; expect a healthier grade spread (more A/B). Update those assertions only if they hardcoded old absolute numbers — keep their intent (non-zero spread, verb-free, etc.).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Report: the achievable max per horizon, the new grade spread from the Phase H frequency fixture, and full-suite status.

## STOP
When green, report. Do NOT start Phase I.
