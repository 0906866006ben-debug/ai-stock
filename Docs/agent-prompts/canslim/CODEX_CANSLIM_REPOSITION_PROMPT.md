# Codex Task — Reposition system: Trading-signal generator → CANSLIM Stock Screener / decision-support (STAGED)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This is a REPOSITIONING toward "screener-first, decision-support, user makes the final call." Hard rules:
> - **NO buy/sell/hold/target-price/"will rise"/"guaranteed" anywhere in user-facing output.** Output is condition-match + interpretation only.
> - **Do NOT change the validated CANSLIM signal/rule/score logic** (rules_*, aggregator, regime, observer math). This is repositioning the PRODUCT SURFACE + naming + module boundaries, not re-tuning the strategy.
> - **Additive / backward-compatible.** Do not break `/analyze`, `/analyze/tw`, or existing tests. New fields optional+nullable per CLAUDE.md.
> - The CANSLIM `observe()` layer already outputs verb-free graded cards — REUSE it; do not reinvent.

> **Do the phases IN ORDER, one at a time, tests green before next.** Stop and report after each.

## Context
The system is currently a MIXED system leaning "trading signal generator": `schemas.py` has `recommendation`/"investment action narrative", `screener_schemas.py` has `entry_tier`, and trade_simulator/optimizer/position-size frame it as an auto-strategy. New direction: **Screener first → analysis second → recommendation last/optional → user decides.** The validated momentum signal + the `canslim` observation layer stay as-is; we re-surface them as a SCREENER.

## Phase R1 — `ScreeningResult` schema + screener assembly (additive)
- Add `ScreeningResult` (Pydantic v2, in `screener_schemas.py` or a new `screening_schemas.py`): `stock_id, as_of_date, candidate_grade: Literal["S","A","B","C","D"], canslim_match: str ("5/7"), pillars: dict[str, Literal["Pass","Weak","Fail","AI_Review_Required","Neutral","Insufficient_Data"]], market_regime: Literal["risk_on","risk_off","severe","unknown"], interpretation: str (verb-free), evidence: list[Evidence], data_warnings: list[str], needs_manual_review: list[str], action_type: Literal["Watchlist Candidate","Manual Review Required","Track Only"]`. `Evidence = {pillar, source_url, published_date, summary}`.
- Add a `build_screening_result(symbol, as_of_date, ...)` that maps the existing CANSLIM `observe()` output (grades, per-pillar triggers, regime, data_warnings) into `ScreeningResult`. Reuse `observe()`; map each pillar's rule outcomes → Pass/Weak/Fail/Neutral; N → `AI_Review_Required` until R3 fills it.
- Market regime (`regime.py`) is computed FIRST and attached; when `severe`/`risk_off`, `action_type` cannot exceed "Manual Review Required" and grade confidence is reduced (regime gate as a screener-level modifier, not a trade block).
- Tests (≥4, no network): mapping observe()→ScreeningResult; verb-free assertion on `interpretation`/all strings; regime gate downgrades action_type in severe; missing-data pillars → Insufficient_Data + needs_manual_review.

## Phase R2 — rename trading-flavored fields (additive aliases, no breakage)
- `entry_tier` → add `candidate_grade` (keep `entry_tier` as a deprecated alias property for backward-compat; do not delete yet).
- `recommendation` (TW/analysis responses) → add `screening_summary` (verb-free); keep `recommendation` populated for now but document it as deprecated/internal.
- `candidate_type` (起漲前觀察 etc.) → expose as `screening_status` alias.
- Frontend-facing strings: prefer "candidate"/"watchlist" wording (frontend changes only if low-risk; otherwise just expose the new fields).
- Tests: aliases resolve; existing tests using old names still pass.

## Phase R3 — N pillar via AI-with-sources (anti-hallucination)
- Add an AI qualitative analyzer for the N pillar that consumes ONLY structured news/法說/announcements already fetched (`yahoo_news`, `tw_news_sentiment`, calendar). It MUST: cite `source_url` + `published_date` for every claim; output `evidence: found|not_found`; never invent catalysts; never output price targets/predictions; set N pillar `confidence: low` when no sources. Output is structured (PydanticAI output_type), feeding `ScreeningResult.evidence` + `pillars["N"]`.
- Tests: AI output schema requires sources; no-source input → `not_found` + low confidence; a verb-free assertion on N output.

## Phase R4 — demote backtest/optimizer/position-size to internal validation
- Ensure `trade_simulator`, `optimizer`, position multipliers, `entry_tier` numeric multipliers are NOT referenced by the user-facing `/analyze*` or screener output paths. They remain available as an INTERNAL backtest/validation module only. No code deletion — just sever any user-facing surface that presents them as advice. Document the module boundary.
- Tests: `/analyze/tw` and screener output contain no position-size/trade-signal fields; backtest module still imports/runs in isolation.

## Verify (after each phase)
```powershell
.venv\Scripts\python -m pytest backend\tests\ -q   # must stay green throughout
```
After R1: also smoke `build_screening_result` on a fixture; after R3: confirm N evidence carries source_url.

## Acceptance
- No buy/sell/hold/target-price/prediction in any user-facing output (assert in tests).
- `ScreeningResult` is the primary product surface; CANSLIM signal logic unchanged; backtest/position-size internal-only; renames are additive (old names still work).
- Market regime is computed first and gates action_type/confidence.

## STOP
Do Phase R1 only first; report; wait. Do not run R2–R4 until R1 is reviewed.
