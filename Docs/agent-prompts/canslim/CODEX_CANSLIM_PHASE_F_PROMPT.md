# Codex Task — CAN SLIM Phase F: Regime engine (build MarketFeatures from real index data)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Regime is a RISK/CONFIDENCE input — it must NOT hard-block on its own (only R-5 short_term, in C6, may block on regime). Missing index data → emit `data_warning` and leave fields None; do NOT block on unknown regime.

> **Phase F.** A–E done (126 canslim tests, full suite 470). **Do ONLY Phase F.** No observer (G). Stop when F tests green.

## Goal

Implement `backend/app/services/strategy/canslim/regime.py` that **computes/populates** the `MarketFeatures` object (defined in C5 `types.py`) from real index data, point-in-time safe. C5 already has the pure M-rules that consume `MarketFeatures`; F only builds it.

### Reuse (do not invent data sources)
- TAIEX / TPEX / SOX / Nasdaq history via the existing market loader (`screener_market_loader.py` / yfinance fallback). Read it first and reuse its functions; do not add new providers.
- 53-stock universe breadth via `HistoricalDataStore.get_ohlcv_as_of` over `backend/data/sectors/ai_tech_tw.json`.
- Thresholds from `params["market"]["rules"]` (ma_days 150, slope_lookback_bars 20) — no hardcoding.

## Build

```python
def build_market_features(as_of_date: str, *, index_bundle=None, store=None, universe=None) -> MarketFeatures: ...
```
Injectable deps for offline tests. Compute:
- `taiex_close`, `taiex_ma150`, `taiex_ma150_slope` (slope over 20 bars); same for `tpex_*`.
- `breadth_above_ma60_pct` = fraction of universe with close > its MA60 as of date.
- `sox_above_ma60`, `nasdaq_above_ma60` (bool: index close > its 60d MA).
- Missing any input → field None + `missing_fields`/`data_warnings`; never fabricate.

### Additive informational fields on `MarketFeatures` (from Gemini research)
Add (additive, default None): `distribution_day_count: int | None` (count of distribution days — close down ≥0.2% on higher volume — in last 25 sessions of TAIEX), `follow_through_day: bool | None` (a rally day +1.x% on rising volume after a low). These are informational for now (not yet wired into rules); expose them + a short docstring noting they can later augment R-5. Keep detection deterministic and simple.

### TSMC-excluded proxy
Provide `taiex_ex_tsmc_*` if 2330 weight is available; if not, set None + `data_warning` ("ex-TSMC proxy unavailable; using full TAIEX") — do NOT estimate weights.

## Tests — `backend/tests/strategy/canslim/test_phase_f_regime.py` (≥5)
Inject synthetic index/universe bundles: uptrend TAIEX → ma150 + positive slope; downtrend; ≥5 distribution days → count ≥5; FTD detection on a synthetic rally; missing-index path → fields None + data_warning. Then feed the built `MarketFeatures` into C5 `evaluate_m1` to confirm it flows end-to-end (one assert).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_f_regime.py -q
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
Report build_market_features behavior, the new informational fields, and test results. Do NOT start Phase G.
