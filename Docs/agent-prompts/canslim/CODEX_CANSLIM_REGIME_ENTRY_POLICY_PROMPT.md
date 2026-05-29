# Codex Task — CAN SLIM: replace binary regime gate with a graded entry-grade ladder

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. The previous binary gate drove window_2 to 0 trades — a zero-signal RED FLAG we must not ship. This change makes the regime response GRADED, never zero:
> - Risk-off RAISES the minimum entry grade instead of blocking everything. S-grade is ALWAYS allowed (the ladder never zeros the stream).
> - Backtest-entry layer only. Observation cards UNCHANGED. Fail-open on unknown regime.
> - Frozen design (NOT optimizer-tunable) for now.

## Why

The binary `regime_entry_gate` (risk-off → block all swing/long entries) made window_2 (2022 H2) emit 0 trades. Too hard. Replace it with a regime-conditional minimum entry grade so adverse regimes increase selectivity rather than halting.

## Build

### 1. YAML — replace the binary flag with a graded policy (frozen, NOT tunable)
In `backtest.canslim`, remove/deprecate `regime_entry_gate` and add:
```yaml
backtest:
  canslim:
    regime_entry_policy:
      enabled: true
      risk_on_min_grade: "B"      # normal regime
      risk_off_min_grade: "A"     # R-5 risk-off → only A/S enter
      severe_min_grade: "S"       # severe risk-off → only S enters (never blocks all)
      severe_breadth_below: 0.40  # severe = M-1 fail AND breadth < this
```
(`risk_on_min_grade` should default to the existing `min_entry_grade` so risk-on behavior is unchanged.)

### 2. Regime severity helper
Reuse `is_regime_risk_off(market, params)`. Add `regime_severity(market, params) -> Literal["risk_on","risk_off","severe"] | None`:
- `severe` when M-1 fails AND `breadth_above_ma60_pct < severe_breadth_below`.
- `risk_off` when `is_regime_risk_off` True (but not severe).
- `risk_on` otherwise. `None` when market inputs missing (unknown).

### 3. Entry policy in the backtest entry path
Replace the binary block in `walk_forward._run_real_segment` / the CANSLIM signal source. For each NEW swing/long entry:
- Determine `required_min_grade` from `regime_severity` via the YAML ladder (risk_on→B, risk_off→A, severe→S).
- Enter only if the signal's `grade >= required_min_grade` (grade order S>A>B>C).
- `None` (unknown regime) → use `risk_on_min_grade` (fail-open, normal selectivity).
- short_term still hard-blocks via R-5 (unchanged). Observation cards unchanged.
- Report per-window counts: entries allowed by regime bucket + by grade (diagnostic). **If any window still hits 0 entries while S/A signals existed pre-policy, that's a red flag — surface it.**

## Tests — update `backend/tests/strategy/canslim/test_regime_entry_gate.py` (≥6)
1. `regime_severity`: M-1 fail + low breadth → "severe"; R-5 risk-off + ok breadth → "risk_off"; ok → "risk_on"; missing → None.
2. risk_on → B-grade signal enters.
3. risk_off → A/S enter, B rejected.
4. severe → only S enters; A/B rejected; **but a stream WITH S signals is non-zero** (assert not all blocked).
5. unknown regime → uses risk_on_min_grade (fail-open).
6. Observation cards unchanged across all regimes (still graded, regime in risk_score). R-5 regression still green.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_regime_entry_gate.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Report: the ladder, per-bucket/per-grade entry diagnostic on a synthetic fixture, and full-suite status.

## STOP
When green, report. Then USER re-runs the 3-window real walk-forward; expect window_2 to be NON-zero again (A/S still enter) and windows 1/2 OOS quality improved vs the no-gate baseline, without zeroing the stream.
