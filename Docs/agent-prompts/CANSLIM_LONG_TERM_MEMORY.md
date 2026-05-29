# CANSLIM Long-Term Memory

This file is a persistent handoff note for Codex / Claude Code collaboration.

## Why This Exists

The project previously produced zero or near-zero tradeable signals across years of data because the strategy logic became too strict and the optimizer rewarded degenerate low-trade results. Do not repeat that failure mode.

## Non-Negotiable Guardrails

1. CANSLIM is a graded scoring system, not an all-conditions hard gate.
2. Never require all pillars or all rules to be true before producing an observation.
3. Only explicit hard blockers may suppress new-entry observations:
   - `R-6` liquidity hard block
   - `R-5_short_term` market risk-off hard block
   - `R-4` event-window hard block
4. Treat `SD-1` liquidity carefully: if it is used as a hard block, document whether it is acting as the `R-6` alias. Do not accidentally introduce an extra blocker outside the approved list.
5. Any future candidate classifier, entry threshold, or gate must report signal-frequency diagnostics on the 53-stock universe. If event count is near zero, stop and report it.
6. A high PF / Sharpe from a tiny number of trades is broken, not excellent. Reject low-trade solutions per walk-forward window.
7. Optimizer search must be conservative:
   - Freeze most YAML thresholds.
   - Tune only 3-5 coarse parameters at once.
   - Avoid extreme threshold drift.
   - Require OOS / walk-forward confirmation.
   - Include sensitivity stability checks when possible.
8. Every pipeline stage that filters candidates should return or log entered/survived counts. Silent collapse to zero is a defect.

## Current C1-C4 Review Notes

- C1-C4 are mostly safe because they are pure rule functions emitting `RuleResult` deltas.
- Real overfit risk starts when aggregation, classification, entry, and backtest optimization use those rule results.
- Do not turn bonus rules like `I-3`, `T-2`, `T-3`, `T-4`, or multi-pillar alignment into required entry conditions.
- Prefer weighted sums, count-of-positive-pillars, and score thresholds over long `A AND B AND C` chains.

## Quick Reminder For Future Phase Prompts

Prepend or read `Docs/agent-prompts/canslim/CODEX_CANSLIM_GUARDRAILS.md` before any remaining CANSLIM phase that touches aggregation, scoring, classifier, entry, optimizer, or backtest behavior.
