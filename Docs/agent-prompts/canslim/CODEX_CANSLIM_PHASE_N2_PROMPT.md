# Codex Task — CAN SLIM Phase N2: portfolio CONSTRUCTION sensitivity (strength prioritization) before judging overlays

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. MEASUREMENT only — no signal/rule/score/gate change, no production wiring. Anti-overfit: use M3's already-validated finding (strength/high-extension wins) as the prioritization basis (not a fitted post-hoc choice); test only a few sensible concurrency/weight values; judge by robustness, not max return.

> **Phase N2.** Phase N built `portfolio_sim.py` and revealed an ALARMING baseline: CAGR 0.40%, maxDD −72%, Calmar 0.006 — but only 3,584 of 28,768 signals were taken (12%), with NO trade prioritization when the concurrency cap (10) was full. That likely averages in M3's losing low-extension cohort (PF 0.89) instead of harvesting the winning high-extension cohort (PF 1.98). **Do ONLY N2:** determine whether a sensible portfolio construction makes the baseline investable, BEFORE re-judging overlays. Stop when tests green + report.

## Why

PF 1.16 (trade-level) collapsed to 0.4% CAGR / −72% DD at portfolio level. Before concluding the strategy is uninvestable OR designing overlays, we must test the dominant untested lever: **when capacity-constrained, WHICH signals get taken.** M3 proved strength wins — so a strength-prioritized portfolio could behave very differently. Overlays evaluated on an un-prioritized baseline are meaningless.

## Build — extend `portfolio_sim.py` + a sensitivity script

Reuse `artifacts/canslim_multicycle/multicycle_tagged_trades.csv` + TAIEX store. NO backtest rerun.

1. **Trade prioritization when slots are full** (configurable `--priority`):
   - `none` (current behavior — baseline reproduction),
   - `extension` (prefer higher close_to_ma20 / nearer 52w-high),
   - `grade` (S>A>B>C),
   - `composite` (strength + grade).
   When concurrency is full, admit the highest-priority eligible signals; document the queue/replace rule (e.g. rank entrants per as_of week, take top-K to fill free slots).
2. **Concurrency sweep:** `max_concurrent ∈ {10, 20, 30, 50}`.
3. **Weighting:** `equal` vs `strength_weighted`.
4. **Liquidity floor sweep (user-requested — filter out illiquid "junk"):** recompute each trade's entry-date `avg_turnover_20` PIT from the OHLCV store (same pattern as extension metrics), then test floors `∈ {30M (current), 100M, 300M, 500M}` TWD. Also report a standalone **liquidity-bucket attribution**: PF / WR / avg-return by entry-turnover bucket (does higher liquidity → better trades?). NOTE in the report: this is a fast filter on the EXISTING M3 trades; a higher floor genuinely changes the universe, so if it looks promising it warrants a proper M3 re-run at that floor (flag this, don't claim it's final).
5. For each (priority × concurrency × weight × liquidity-floor) combo: CAGR, maxDD, Calmar, Sharpe, annual + per-named-cycle returns, acceptance rate (n taken / n signals), avg PF of taken vs skipped trades. (Keep the grid SENSIBLE/small — a few values per axis, not a full cross-product explosion; anti-overfit.)

Write `artifacts/canslim_portfolio_overlay/construction_sensitivity_report.{json,md}`.

## PRIMARY objective — PRECISION on a SMALL elite cohort (the user's actual style)
The user trades **big swings (大波段), low-frequency, highly selective** — they want FEW HIGH-PRECISION signals, not many opportunities. So aggregate PF/CAGR over all ~28k trades is the WRONG lens. The core study:
- Rank ALL signals by a composite quality score (strength/extension + nearness-to-52w-high + grade + liquidity), take only the **top-K per week** (test K ∈ {3, 5, 10}) and/or **top X%** (test {1%, 2%, 5%}).
- For that elite cohort, report **precision metrics:** win_rate, expectancy (avg return per trade), avg_win vs avg_loss, and **big-swing capture** — % of trades returning >20% and >50%. Plus per-year + per-named-cycle reliability of the elite cohort.
- Question: is there a selectivity level where a SMALL number of signals is reliably accurate and catches big moves (esp. in risk_on/bull), across multiple cycles?

## Secondary questions
- Does **strength-prioritized** selection raise taken-trades' PF vs skipped (harvest the winning cohort)? Report avg PF of TAKEN vs SKIPPED under `extension`/`composite` priority.
- How sensitive are CAGR/maxDD to concurrency (is −72%/0.4% a 10-slot artifact)?

## IMPORTANT caveat to flag (hold period)
The M3 trades used a short `max_hold_days` (≈30) — this **under-captures big swings** (winners cut early). N2 measures the existing trades; if the elite cohort looks precise, the proper big-swing test needs an M3 RE-RUN with a **let-winners-run exit** (trailing stop / measured-move target, long/no time cap — the original Phase 9.8 design). Flag this clearly in the report; do NOT present 30-day-capped returns as the final big-swing result.

## Tests — `backend/tests/strategy/canslim/test_portfolio_construction.py` (≥5) — NO network
1. Priority ranking: with full slots, higher-strength synthetic signals are admitted over lower-strength ones (and taken-set PF > skipped-set PF on a constructed example).
2. Concurrency sweep produces distinct equity curves; metrics computed correctly.
3. strength_weighted vs equal weighting changes sizing as expected.
4. Liquidity floor: trades below the floor (recomputed entry avg_turnover_20) are excluded; liquidity-bucket PF computed correctly on a synthetic set.
5. Precision metrics on an elite top-K cohort: win_rate / expectancy / big-swing-capture (>20%, >50%) computed correctly on a synthetic set; top-K selection picks the highest-composite-score signals.
6. No mutation of YAML/params/strategy; reuses existing sim metrics.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_portfolio_construction.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER the command to run the construction sensitivity report (fast — reads the M3 CSV).

## STOP
When green, report the construction sensitivity table + the taken-vs-skipped PF comparison + the recommended sensible construction. Do NOT re-run overlays or wire anything yet — we pick the construction together, then re-judge overlays (N3).
