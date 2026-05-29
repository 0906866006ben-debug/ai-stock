# Codex Task — Formalize per-pillar CANSLIM SCREENING criteria (C/A/N/S/L/I/M → Pass/Weak/Fail/Insufficient)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This makes each CANSLIM pillar a clear, deliberate SCREENING verdict — NOT a trade signal. Hard rules:
> - Output is condition-match per pillar. **NO buy/sell/hold/target-price/prediction anywhere** (assert).
> - **All band thresholds in YAML** (`screening:` section, `tunable_required: true`), never hardcoded.
> - **Do NOT change the validated signal/rule/score math** (rules_*, aggregator, regime). This ADDS a screening-verdict layer on top of the existing rule outputs.
> - Missing/unavailable data → `Insufficient_Data` + a data_warning + lowered confidence; never fabricate. Day-trade ratio and chip concentration are NOT available — S pillar must say so.
> - Additive + backward-compatible; existing 566 tests stay green.

## Context
R1 built `ScreeningResult` + `build_screening_result()` (in `screening.py`) with a basic observe()→pillar mapping. This task FORMALIZES each pillar's verdict into explicit, documented, YAML-driven criteria. Reuse the existing rule outputs (`RuleResult` from rules_growth/technical/supply/institutional/market) and `regime.py`; do not recompute signals.

## Build — `backend/app/services/strategy/canslim/pillar_screening.py`

A pure function per pillar: `screen_C(features, rule_results, params) -> PillarVerdict`, … `screen_M(market, params)`. `PillarVerdict = {status: PillarStatus, reason: str (verb-free, cites the driving values/rule-ids), drivers: list[str], data_warnings: list[str]}`. Then `assemble_pillars(...)` returns `dict[str, PillarVerdict]` for C/A/N/S/L/I/M, consumed by `build_screening_result()`.

### Per-pillar criteria (thresholds from YAML `screening.<pillar>`)
- **C (Current quarterly):** PASS `quarterly_eps_yoy ≥ c_pass` (0.25); WEAK `[c_weak,c_pass)` (0.10–0.25); FAIL `< c_weak` or negative. Revenue-accel (G-1) can upgrade WEAK→PASS-adjacent (document). Missing → Insufficient.
- **A (Annual):** PASS `eps_cagr_3y ≥ a_cagr_pass` (0.25) AND `roe_ttm ≥ a_roe_pass` (0.15); WEAK one of them met (or CAGR in `[a_cagr_weak, a_cagr_pass)`); FAIL `cagr < a_cagr_weak` (0.15) or `roe < a_roe_fail` (0.10). Missing → Insufficient. (Note cyclical caveat in reason for semis.)
- **N (New high / catalyst — HYBRID):** quant = 52w-high proximity (T-2). Qualitative = R3 AI news evidence (with source). PASS at/near new high AND ≥1 sourced catalyst; WEAK near-high-no-catalyst OR catalyst-not-near-high; `AI_Review_Required` when news is live-only/unanalyzed; FAIL far from high AND no catalyst. Never invent catalysts.
- **S (Supply/demand):** PASS liquidity floor (SD-1) met AND up-day volume expansion (SD-2); WEAK liquid but no volume expansion; FAIL below liquidity floor. **ALWAYS append a data_warning that day-trade-ratio and chip-concentration are unavailable → S is a partial assessment** (status may be Insufficient_Data if you judge the available signals too thin — document the rule).
- **L (Leader/laggard):** PASS `rs_60d_pct ≥ l_rs_pass` (0.75) AND MA stage-2 (T-3); WEAK one of them; FAIL `rs_60d_pct < l_rs_fail` (0.50). Missing history → Insufficient.
- **I (Institutional):** PASS foreign AND trust both net-buying (I-3 / I-1+I-2); WEAK one institution net-buying; FAIL institutions net-selling (R-3 active); missing → Insufficient.
- **M (Market — regime gate, market-level not per-stock):** from `regime_severity`/`is_regime_risk_off`: PASS=risk_on, WEAK=risk_off, FAIL=severe, Insufficient=unknown. M caps the overall `action_type` and reduces confidence when WEAK/FAIL (already partly in R1 — consolidate here).

### Wire into `build_screening_result`
Replace R1's ad-hoc mapping with `assemble_pillars(...)`. `canslim_match` = count of PASS pillars / 7. `candidate_grade` stays from the validated aggregator (do not redefine it); just ensure pillar verdicts + match count + interpretation (verb-free, summarizing which pillars Pass/Weak/Fail and what needs manual review) are populated.

## YAML
Add a `screening:` block with all band thresholds above, `meta.tunable_required: true`. No screening threshold hardcoded in .py.

## Tests — `backend/tests/strategy/canslim/test_pillar_screening.py` (≥9) — NO network
- One PASS + one FAIL + one Insufficient case per pillar (build features/rule_results/market directly), reading expected bands from `load_params()`.
- N: AI_Review_Required when no catalyst evidence; never fabricates.
- S: data_warning for day-trade/chip always present.
- M: risk_on→PASS, severe→FAIL, unknown→Insufficient.
- Verb-free assertion across all pillar reasons + interpretation.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_pillar_screening.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
When green, report the per-pillar criteria as implemented + the YAML `screening` block + test results. Do NOT wire into /analyze/tw yet (separate step).
