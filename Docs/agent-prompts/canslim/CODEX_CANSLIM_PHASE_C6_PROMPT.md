# Codex Task — CAN SLIM Phase C6: Risk rule functions (R-1..R-8) + feature additions

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md` (repo root) and obey it. THIS PHASE OWNS ALL HARD BLOCKS — it is the exact area that previously caused **0 tradeable signals in 4 years**. Be conservative about blocking: **only R-4, R-5(short_term only), and R-6 may set `hard_block=True`.** Every other risk rule only adds a `risk_delta`. When a blocking input is unknown/missing, prefer NOT to block (emit a `data_warning` instead) — over-blocking is the failure we are preventing.

> **Phase C, sub-task 6 of 6 (final rule pillar).** A, B, C1–C5 done and green. **Do ONLY C6.** No scoring/aggregation (Phase E). Stop when C6 tests are green.

## Background

Risk rules have heterogeneous inputs (some per-stock, some market-level, R-5 is horizon-dependent). Use a **uniform signature** so the aggregator can iterate:

```python
def evaluate_r1(f: CanslimFeatures, mf: MarketFeatures, params, horizon: str) -> RuleResult: ...
```
Each rule ignores inputs it doesn't need. Thresholds only from `params["risk"]["rules"]["R-x"]`.

### Read first
- `rules_growth/.../market.py` — mirror structure; `RISK_RULES` list + horizon tags from YAML.
- `types.RuleResult` (has `hard_block`), `MarketFeatures`, `CanslimFeatures`, `params["risk"]["rules"]`.

## Step 1 — ADDITIVE features (do not change existing fields)

Add to `CanslimFeatures` + populate in `build_features`:
- `pe_ttm: float | None` — from injected `fin_metrics` (`pe_ttm`/`pe_ratio`); None + missing_fields if absent.
- `volume_ratio_recent_vs_prior_20: float | None` — `mean(volume[-10:]) / mean(volume[-20:-10])` (needs ≥20 bars; else None).
- `is_20d_high: bool | None` — `close >= box_high_20 * 0.999` (needs box_high_20; else None).
- `event_window_active: bool | None` — NEW **injected** param on `build_features(..., event_window_active: bool | None = None)`. Default None (unknown). Population from `tw_calendar` happens later at Phase H wiring — not here.

Add ≤3 small tests in the Phase B test file for the new fields (incl. None paths).

## Step 2 — rules (`backend/app/services/strategy/canslim/rules_risk.py`)

- **R-1 `extended_from_ma20`** (short, swing): needs close, ma20. `close > ma20 * close_to_ma20_multiplier_above` (1.15) → `risk_delta=20`, triggered=True. Else/missing → not triggered, no delta.
- **R-2 `price_volume_divergence`** (swing): needs `is_20d_high` and `volume_ratio_recent_vs_prior_20`. Trigger when `is_20d_high` True AND `volume_ratio_recent_vs_prior_20 <= (1 - volume_decline_pct_min)` (i.e. ≥20% decline → ratio ≤ 0.80) → `risk_delta=15`. Missing → not triggered.
- **R-3 `institutional_selling`** (swing): needs foreign_net_5, trust_net_5. Count net-seller days (value < 0) in last `lookback_days` (3) for each; trigger when BOTH have `>= net_seller_days_min` (2) seller days → `risk_delta=25`. Missing → not triggered.
- **R-4 `event_window_active`** (all): if `event_window_active is True` → `risk_delta=15`, `hard_block=True`, triggered=True (blocks NEW-entry observations). If False → not triggered. **If None (unknown) → not triggered, NO hard_block, `data_warning`** ("event calendar unknown — not blocking"). (Conservative-against-over-blocking per guardrails.)
- **R-5 `market_risk_off`** (all, HORIZON-DEPENDENT): compute regime via `evaluate_m1/m2/m3(mf, params)`. Risk-off when `M-1 fails` OR (`M-2 fails` AND `M-3 fails`). On risk-off:
  - if `horizon == "short_term"` → `hard_block=True`, `risk_delta=0`, triggered=True;
  - else (swing/long) → `risk_delta=swing_long_risk_delta` (30), `hard_block=False`, triggered=True.
  On not-risk-off → not triggered. If market inputs missing → not triggered, `data_warning`, **no hard_block** (don't block on unknown regime).
- **R-6 `low_liquidity_hard`** (all): needs avg_turnover_20. `avg_turnover_20 < avg_turnover_20_below_twd` (30,000,000) → `hard_block=True`, triggered=True. **Missing avg_turnover_20 → `hard_block=True`** (this matches SD-1's conservative liquidity stance — illiquid-by-default is the one place we DO block, because trading an unknown-liquidity name is the real danger). Add a `data_warning` when blocking due to missing data.
- **R-7 `high_daytrade_ratio`** (short): `day_trade_ratio` always None (`data_available: false`) → never triggers; return triggered=False, `data_warning`. No risk_delta, no block.
- **R-8 `valuation_growth_mismatch`** (long): needs `pe_ttm` and `quarterly_eps_yoy`. Trigger when `pe_ttm > pe_ttm_above` (40) AND `quarterly_eps_yoy < quarterly_eps_yoy_below` (0.15) → `risk_delta=20`. Missing either → not triggered.

Expose `RISK_RULES = [evaluate_r1, …]`. No buy/sell/hold verbs.

## Tests — `backend/tests/strategy/canslim/test_phase_c6_risk.py` (≥14)
- R-1/R-2/R-3/R-8: trigger + non-trigger each.
- R-4: active→hard_block True; inactive→not triggered; **None→not triggered + NO hard_block + data_warning**.
- R-5: short_term risk-off → hard_block True; swing risk-off → risk +30, hard_block False; not-risk-off → not triggered; **missing market inputs → not triggered, no hard_block**.
- R-6: below floor → hard_block; missing turnover → hard_block + data_warning.
- R-7: always not triggered + data_warning.
- **Guardrail regression test:** assert that across R-1..R-8, the ONLY rules that ever return `hard_block=True` are R-4, R-5(short_term), R-6 — and that R-4 None / R-5 missing-inputs do NOT block.
Build `CanslimFeatures`/`MarketFeatures` with kwargs; read deltas from `load_params()`.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_c6_risk.py -q
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
When green, report feature additions, the 8 rule functions, the hard-block guardrail test result, and full-suite status. Phase C is then COMPLETE — do NOT start Phase E (aggregator).
