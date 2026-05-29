# Codex Task — CAN SLIM Phase C5: Market/Regime rule functions (M-1..M-4) + MarketFeatures type

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md` (repo root) and obey it. Key point for this phase: the M-pillar is regime *risk* assessment — **M-rules must NOT hard-block or zero out a stock's signal.** Only R-5 (short-term) may hard-block on regime, and that's Phase C6. M-rules only add risk/confidence deltas (and a small M-4 signal). Do not turn the market filter into an all-or-nothing gate.

> **Phase C, sub-task 5 of 6.** A, B, C1–C4 are done and green. **Do ONLY C5.** No scoring/aggregation, no regime data assembly (that's Phase F), no other pillars. Stop when C5 tests are green.

## Background

M-rules judge market direction from **market-level** inputs (TAIEX / TPEX / breadth / SOX / Nasdaq), not per-stock data. So they take a NEW lightweight `MarketFeatures` object, not `CanslimFeatures`. Phase F (`regime.py`) will compute/populate `MarketFeatures` from real index data; C5 only implements the pure judgment functions + the type. Thresholds only from `params["market"]["rules"]["M-x"]`.

### Read first
- `rules_growth/technical/supply/institutional.py` — mirror the pure-function structure.
- `types.RuleResult`, `params["market"]["rules"]`.

## Step 1 — `MarketFeatures` type (in `types.py`, additive)

Pydantic v2 frozen model, all fields `| None`:
`taiex_close`, `taiex_ma150`, `taiex_ma150_slope` (slope over `slope_lookback_bars`), `tpex_close`, `tpex_ma150`, `tpex_ma150_slope`, `breadth_above_ma60_pct` (0–1 fraction of universe above MA60), `sox_above_ma60: bool|None`, `nasdaq_above_ma60: bool|None`, plus `missing_fields: list[str]` and `data_warnings: list[str]`. Do NOT compute these here — that's Phase F.

## Step 2 — rules (`backend/app/services/strategy/canslim/rules_market.py`)

Signature `def evaluate_m1(mf: MarketFeatures, params) -> RuleResult` … m4.

- **M-1 `taiex_30w_ma_uptrend`** (all horizons; a regime check): "uptrend" = `taiex_close > taiex_ma150` AND `taiex_ma150_slope >= slope_min` (0.0). On uptrend → `triggered=True`, no deltas (signal_delta 0). On FAIL → `triggered=False, risk_delta=risk_delta_on_fail` (30); put `regime_on_fail: "risk_off"` info in `reason`. **Never set hard_block here.** Missing inputs → not triggered, `data_warning`, risk_delta 0 (can't assess).
- **M-2 `tpex_30w_confirms`** (all horizons): compute TPEX uptrend the same way. If TPEX disagrees with TAIEX (one up, the other not) → `risk_delta=risk_delta_if_disagrees_with_taiex` (10), `triggered=False`. If both agree up → `triggered=True`, no deltas. Implement by calling `evaluate_m1(mf, params)` for the TAIEX side. Missing → data_warning, no delta.
- **M-3 `breadth_positive`** (all horizons): if `breadth_above_ma60_pct >= universe_above_ma60_pct_min` (0.60) → `triggered=True, confidence_delta=confidence_delta_if_met` (+5). If `< risk_pct_below` (0.40) → `triggered=False, risk_delta=risk_delta_if_below` (10). In between → triggered=False, no deltas. Missing → data_warning, no delta.
- **M-4 `sox_nasdaq_supportive`** (swing, external): if `sox_above_ma60` AND `nasdaq_above_ma60` both True → `triggered=True, signal_delta=5, confidence_delta=3`. If both False → `risk_delta=risk_delta_if_both_below` (10), triggered=False. Mixed → triggered=False, no deltas. Missing → data_warning, no delta.

Expose `MARKET_RULES = [evaluate_m1, …]` with horizon tags from YAML. No buy/sell/hold verbs. **No `hard_block=True` anywhere in this file.**

## Tests — `backend/tests/strategy/canslim/test_phase_c5_market.py` (≥9)
- M-1: uptrend → triggered, no risk; fail → not triggered, risk +30; missing → data_warning, risk 0.
- M-2: both up → triggered; disagree → risk +10.
- M-3: ≥0.60 → confidence +5; <0.40 → risk +10; middle → no delta.
- M-4: both above → signal +5/conf +3; both below → risk +10; mixed → no delta.
- One test asserting **no M-rule ever returns `hard_block=True`** (guardrail regression).
Build `MarketFeatures` with kwargs; read expected deltas from `load_params()`.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_c5_market.py -q
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
When green, report the `MarketFeatures` type, the 4 rule functions, and test results. Do NOT start C6 (risk rules).
