# CAN SLIM Guardrails — PREPEND THIS TO EVERY REMAINING PHASE PROMPT

> **Read this before writing any aggregation, classification, entry, or backtest logic.**

## What went wrong before (do not repeat)

A prior version of this strategy produced **ZERO tradeable signals across 4 years of data**. That is the exact opposite of the user's intent. Two linked root causes:

1. **Over-strict AND-gating** — too many conditions chained with `AND`, so almost nothing ever passed all of them at once.
2. **Overfit / degenerate optimization** — the optimizer pushed thresholds to extremes to maximize a metric, yielding solutions with ~0 trades that *looked* good (e.g. PF=999 on n=1) but were useless.

The user's words: "可交易訊號4年來都是0 這跟我的初衷完全不同."

## Hard rules to prevent recurrence

1. **This is a SCORING system, not a hard AND-gate.** Rules contribute *graded* deltas to Signal/Risk/Confidence. **Never require all rules to be true** to produce an observation. A stock with a partial match must still surface a graded card.

2. **Only the explicitly-listed hard blocks may suppress output**: `R-6` (liquidity), `R-5` short-term (regime risk-off), `R-4` (event window). These are the ONLY rules allowed to block new-entry observations. No other rule, and no combination of soft rules, may silently zero everything out.

3. **Signal-frequency sanity check is MANDATORY for any gate/classifier/entry threshold.** Before shipping any threshold that decides "candidate vs not" or "entry vs not", count how many events fire per year on the 53-stock universe. **If the count is ~0 (or absurdly low), the gate is too strict — STOP and report it, do not ship it silently.** A healthy strategy fires a reasonable, non-zero stream of candidates.

4. **A backtest with too few trades is BROKEN, not excellent.** Reject degenerate solutions: enforce a minimum trade count per walk-forward window (≥3, prefer higher). Never treat a high PF/Sharpe built on a handful of trades as a win.

5. **Prefer graded composition over strict chains.** Use weighted sums, count-of-conditions-met (e.g. "≥4 of 6 pillars positive"), or thresholded scores — NOT long `A AND B AND C AND D AND …` chains. If a strict conjunction is genuinely required, justify it and verify (rule 3) that it still fires.

6. **Anti-overfit:** freeze most thresholds at canonical values; expose only 3–5 as tunable; coarse grids only; walk-forward with OOS confirmation (WFE ≥ 0.5); ±20% sensitivity stability. Do not tune toward extremes.

7. **Emit diagnostics so a 0-signal collapse is immediately visible.** Any pipeline stage that filters candidates must log/return how many entered vs. how many survived. A silent collapse to zero is a defect.

## When in doubt

If implementing your phase would plausibly produce zero or near-zero signals on real data, that is a red flag — surface it in your report rather than shipping it. The goal is a *usable stream of graded observations*, not a perfect-but-empty filter.
