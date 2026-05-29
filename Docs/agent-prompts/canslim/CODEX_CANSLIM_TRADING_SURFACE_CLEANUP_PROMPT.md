# Codex Task — Clean the TW user-facing trading-signal surface (scoped, verify in browser)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md` and `ai-stock-frontend/AGENTS.md` (Next.js 16 differs from training data — read node_modules/next/dist/docs before changing routing/layout/config). Frontend changes MUST be verified in a browser before claiming done.

## Strict scope (do NOT exceed)
- **Only the TW screener/analysis user-facing surface.** Do NOT touch the US `/analyze` flow, the US multi-factor synthesis logic, or the internal backtest/optimizer engine (entry_tier/tier_classifier/signal_replay/trade_simulator/v1/v2 — these are R4-walled internal validation; leave them).
- `recommendation` field stays in the schema (US shares it). We change what the TW SURFACE shows, not the shared field's existence.
- No buy/sell/hold/target-price/prediction shown to the user on the TW side (assert).

## Goal
On the TW side, present the CANSLIM **ScreeningResult** (decision-support, condition-match) as the primary output and stop surfacing trading-instruction language. The screener already produces verb-free output (`ScreeningResult`, `screening_summary`); wire the TW UI to it.

## Changes
1. **`ai-stock-frontend/app/components/TwAnalysisCard.tsx`**: replace the raw `data.recommendation` block (lines ~88-95) with a screening-oriented block — render `data.screening_result` (the new `ScreeningResult`: candidate_grade, canslim_match, per-pillar Pass/Weak/Fail, interpretation, action_type, needs_manual_review) when present; fall back to a verb-free summary otherwise. Do NOT show action-instruction text. (The single-symbol screener UI in the screenshot already exists — reuse its presentation/components if shared.)
2. **`SynthesisRecommendation` on the TW path**: if this component renders US-style buy/sell/recommendation wording, either hide it on the TW view OR pass it verb-free content. Must NOT change its US usage. Prefer: gate its render to non-TW, or branch on a prop. Confirm US view unaffected.
3. **`lib/types.ts`**: add the `ScreeningResult` type (mirror the backend Pydantic shape) to `TaiwanStockAnalysisResponse` (optional). 
4. **Backend (optional, safe)**: ensure `/analyze/tw` populates `screening_result` (it already does behind `include_screening=true`); have the TW frontend request `include_screening=true`.
5. Run any verb-free lint/assert on TW-rendered strings.

## Tests / verification
- Frontend type-check: `cd ai-stock-frontend && npx tsc --noEmit` (must pass).
- **Browser**: start backend + `npm run dev`, open a TW symbol, confirm: the screener (grade + 7 pillars) shows, no buy/sell/target-price wording on the TW view, and the US `/analyze` view is visually unchanged. Report what you saw.
- Backend: `.venv\Scripts\python -m pytest backend\tests\ -q` stays green (no US/analyze regressions).

## STOP
When tsc passes + browser-verified + suite green, report: what the TW surface now shows, confirmation US view is unchanged, and that no trading-instruction language remains on the TW side. Do NOT remove the shared `recommendation` field or touch the internal engine.
