# Codex Task — CAN SLIM Phase I1: backtest signal generation + entry/exit/stop (produce trades)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Backtest-specific: a run with too few trades is BROKEN, not excellent. After wiring, REPORT how many CANSLIM trades the fixture produced. If ~0, the entry gate is too strict — flag it.

> **Phase I, part 1 of 2.** A–H + E2 fix all green. **Do ONLY I1** (signal generation + trade entry/exit/stop, produce trades on a fixture). Walk-forward + anti-overfit calibration is I2 — do NOT do it here. Stop when I1 tests green.

## Read first (do not break existing 起漲前觀察 backtest)
- `backend/app/services/backtest/signal_replay.py` — `ReplayConfig` (has `target_candidate_types`, default `["起漲前觀察"]`), `replay_signals()` (day-by-day, persists to `backtest_signals`). Understand how it builds + filters signals by candidate_type.
- `backend/app/services/backtest/trade_simulator.py` — `TradeRules` (tier_position_multipliers, measured_move_*, max_hold_days, stop_loss_pct) and how trades simulate from persisted signals.
- `params["backtest"]` in the YAML: pyramiding (50/30/20 at +0/+2-3/+4-5%), stops (initial 0.07, hard 0.10, atr 1.0), costs (round_trip 0.00685), walk_forward.

## Build (additive — existing 起漲前觀察 path untouched)

1. **CANSLIM signal source.** Add a CANSLIM signal generator that, for each (stock, as_of_date), runs the Phase G `observe()` (reuse the Phase H opt-in path) and emits a `backtest_signals` row with `candidate_type="CANSLIM觀察"` **when**: the chosen horizon's `grade >= min_grade` (new YAML `backtest.canslim.min_entry_grade`, default "B", `tunable: true`) AND `hard_blocked is False`. Store grade + signal/risk/confidence on the row (reuse existing columns / add nullable ones). Pick the horizon via a YAML `backtest.canslim.horizon` (default "swing_term", tunable).
   - Register `"CANSLIM觀察"` as an allowed `target_candidate_types` value; do NOT change the default.

2. **Entry / exit / stop** (from `params["backtest"]`, no hardcoding):
   - Entry on the signal date (PIT: signal computed only from data ≤ as_of).
   - Stops: initial `stop_loss_pct` (0.07) or `1×ATR(20)` whichever tighter; hard stop `hard_stop_pct` (0.10).
   - Trail: ma60 for swing.
   - **Hold horizon is a YAML param** `backtest.canslim.max_hold_days` (TW-shortened vs O'Neil's 8-week US rule — default e.g. 30, `tunable: true`). 0 = no time limit (measured-move target).
   - Pyramiding (50/30/20) optional behind a flag; if complex, implement single-entry first and leave pyramiding as a documented TODO for I2.

3. **PIT / look-ahead controls:** EPS only after filing_date+1, institutional T+1, calendar publish ≤ as_of. Reuse the gating already in `observe()`/`build_features`.

4. **Costs:** apply `round_trip_cost_pct` (0.00685) at gross→net return.

## Tests — `backend/tests/strategy/canslim/test_phase_i1_backtest.py` (≥4)
1. `replay_signals` with `target_candidate_types=["CANSLIM觀察"]` on a small synthetic multi-stock store produces a NON-zero number of CANSLIM signals (anti-zero-signal guard).
2. Trade simulation on those signals yields ≥1 trade with net return = gross − round_trip_cost.
3. PIT guard: a stock whose EPS filing_date is after as_of does not leak future EPS into the signal.
4. Existing 起漲前觀察 replay unchanged (default config still works).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_i1_backtest.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Report: # CANSLIM signals + # trades on the fixture, and full-suite status.

## STOP
When green, report. Do NOT start I2 (walk-forward + anti-overfit calibration).
