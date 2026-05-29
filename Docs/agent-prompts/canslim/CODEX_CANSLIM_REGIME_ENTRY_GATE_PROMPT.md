# Codex Task — CAN SLIM: regime entry gate for swing/long backtest entries (DESIGN CHANGE, not tuning)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This is a deliberate, tested design change — NOT an optimizer tunable. Critical boundaries:
> - **Gate the BACKTEST ENTRY decision only — do NOT change observation cards.** Cards must still surface graded S/A/B/C observations during risk-off (regime adversity already shows up in `risk_score`). We are not hiding observations; we are stopping the backtest from OPENING new swing/long positions into a risk-off market.
> - **Fail OPEN on unknown regime:** if regime data is missing/unavailable for a date, DO NOT gate (allow entry) + log. Over-blocking on unknown is the zero-signal failure we forbid.
> - Do NOT add this flag to the optimizer's tunable search space. It is a frozen design flag (default ON), reversible via YAML.

## Why

Real walk-forward showed window_1 (2022 H1 bear) OOS PF 0.28 / WR 9.6% — the strategy kept opening swing positions into a downtrend. Root cause: in `swing_term`, R-5 (market risk-off) only adds `risk_delta` (+30); it does NOT block entry (entry gates on grade only). This change makes swing/long backtest entries respect regime.

## Build

### 1. Shared helper `is_regime_risk_off(market, params) -> bool | None`
Add to `regime.py` (or `rules_market.py`). Returns the R-5 risk-off condition: `M-1 fails OR (M-2 fails AND M-3 fails)`, computed from `MarketFeatures` (reuse `evaluate_m1/m2/m3`). Returns `None` when the needed market inputs are missing (unknown regime). **Refactor R-5 (`rules_risk.evaluate_r5`) to call this helper** so R-5 behavior is unchanged (regression test must still pass).

### 2. YAML flag (frozen, NOT tunable)
Add `backtest.canslim.regime_entry_gate: true` (no `tunable` marker). Document: gates new swing/long backtest entries when regime risk-off; short_term already hard-blocks via R-5.

### 3. Entry gate in the backtest entry path
In the CANSLIM signal/entry path used by the real walk-forward (`walk_forward._run_real_segment` and/or the CANSLIM signal source in `signal_replay`), before emitting/entering a `"CANSLIM觀察"` NEW entry:
- Compute per-`as_of_date` regime via `build_market_features(as_of_date, store=...)` (PIT-safe Phase F). 
- If `regime_entry_gate` AND `is_regime_risk_off(...) is True` AND horizon ∈ {swing_term, long_term} → **skip the new entry** (do not open). 
- If regime is `None` (unknown) or risk-on → allow as before (fail-open).
- This affects ONLY new-entry decisions; existing-position exit logic unchanged. Observation cards (`observe()`) are NOT modified.
- Count and log how many entries the gate removes per window (diagnostic — if it removes ~all signals, that's a red flag to surface, not ship silently).

## Tests — `backend/tests/strategy/canslim/test_regime_entry_gate.py` (≥5)
1. `is_regime_risk_off`: M-1 fail → True; M-1 ok & M-2/M-3 ok → False; missing inputs → None.
2. R-5 regression: existing R-5 hard-block (short_term) / risk_delta (swing) behavior unchanged after refactor.
3. Entry gate ON + risk-off + swing → new entry skipped; risk-on → entry allowed.
4. Entry gate ON + **unknown regime (None)** → entry ALLOWED (fail-open).
5. Entry gate OFF (flag false) → old behavior (entry allowed in risk-off). Observation card for the same risk-off case is UNCHANGED (still returns a graded card; regime shows in risk_score, not hidden).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_regime_entry_gate.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Report: the helper, the gate location, per-window entries-removed diagnostic on a synthetic fixture, and full-suite status. Note that for the REAL run the user must have TAIEX/TPEX history available to `build_market_features` (else the gate fails open and changes nothing).

## STOP
When green, report. Then the USER re-runs the 3-window real walk-forward; expect window_1/2 OOS to improve (fewer bear-market entries) while signal stream stays non-zero.
