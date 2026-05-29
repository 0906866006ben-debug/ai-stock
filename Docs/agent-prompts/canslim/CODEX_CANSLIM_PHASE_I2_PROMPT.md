# Codex Task — CAN SLIM Phase I2: walk-forward + anti-overfit calibration (FINAL phase)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md` AND the "Soundness & Anti-Overfit Protocol" in the plan. This phase exists specifically to prevent the prior "0 signals / overfit" failure. The whole point is to LIMIT degrees of freedom, not maximize a metric.

> **Phase I, part 2 of 2 — FINAL.** A–H, E2, I1 all green (495 suite). Do ONLY I2. Stop when green + report.

## Core anti-overfit rules (non-negotiable)

1. **Expose only 3–5 tunable params; freeze the rest.** Add `tunable: true` to ONLY these in the YAML, leave all other ~30 thresholds frozen (no flag):
   - `backtest.canslim.min_entry_grade`
   - `backtest.canslim.max_hold_days`
   - `scoring.grades.A_signal_min`
   - `scoring.grades.B_signal_min`
   (Optionally one more, e.g. `backtest.canslim.horizon` — keep total ≤5.)
   The optimizer must REFUSE to vary any param not marked `tunable: true`. Add a guard + a test asserting a non-tunable param is rejected from the search space.

2. **Coarse grids only** — 3–5 steps per tunable param. No fine/continuous search.

3. **Walk-forward**: reuse `backend/app/services/backtest/v1/optimizer.py` harness (read it first). IS = 2018–2022, OOS = 2023+, step by quarter/6mo per `params["backtest"]["walk_forward"]`. Accept a param set only if **WFE = OOS_CAGR / IS_CAGR ≥ 0.5**.

4. **Reward-hack guards (reuse existing from the v1 optimizer):** reject any candidate with `n_trades < min_trades` per window, cap PF, reject degenerate solutions (the n=1/PF=999 class). Add a regression test that a degenerate low-trade solution is rejected.

5. **Sensitivity test:** perturb each tunable threshold ±20%; record Sharpe stability. A set whose Sharpe collapses under small perturbation is overfit → flag/reject.

6. **Per-pillar attribution:** report how much of CAGR comes from each pillar (C/A/T/I/M), to confirm edge isn't one lucky rule.

7. **No tuning on OOS, ever.** PIT controls already in place (EPS filing+1, institutional T+1).

## Build (additive)
- A CANSLIM walk-forward driver that wraps I1's signal generation + trade simulation across windows, using only the tunable params.
- Output an artifacts report (markdown/JSON) per run: per-window IS/OOS CAGR, WFE, Sharpe, max DD, win rate, PF, n_trades, grade distribution, per-pillar attribution. Do NOT send any of this to external APIs; write locally under `artifacts/`.

## Tests — `backend/tests/strategy/canslim/test_phase_i2_walkforward.py` (≥5)
1. Optimizer search space contains ONLY the `tunable: true` params (assert a frozen param is excluded).
2. A degenerate low-trade candidate is rejected by the guards.
3. WFE computed correctly on a synthetic IS/OOS fixture; set with WFE < 0.5 is not accepted.
4. Sensitivity: ±20% perturbation runs and returns a stability metric.
5. End-to-end walk-forward on a small synthetic universe completes and writes a report; existing 起漲前觀察 optimizer path unchanged.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_i2_walkforward.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Report: the tunable param list, WFE/guard behavior, and full-suite status.

## After this phase (USER runs, not Codex)
The real calibration run on the actual 53-stock universe (2018→now) is executed by the user. This phase only builds + unit-tests the harness. Report the command to launch a real walk-forward run.

## STOP
When green, report. **Phase I complete = CAN SLIM quantification DONE** (A→I). Summarize the full pipeline status.
