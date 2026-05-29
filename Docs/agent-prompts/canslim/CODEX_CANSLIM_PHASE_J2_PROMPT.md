# Codex Task — CAN SLIM Phase J2: PIT as-of adapter + wire into walk-forward (FINAL data step)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Specifics:
> - **NO look-ahead.** All inputs come from `PitFundamentalsStore` as-of readers (already date/filing gated). Institutional flow is T+1 lagged — reuse `build_features`'s existing lag logic by passing dated rows, do NOT pre-lag incorrectly.
> - **No rule changes.** The adapter must emit the EXACT `detail` / `fin_metrics` dict shapes that `build_features`/`observe()` already parse, so G/T/SD/I/M/R rules stay untouched.
> - Backtest must NOT call live snapshot functions; only the PIT store.

> **Phase J, part 2 of 2 — FINAL.** A→I + J1 all green (507 suite). **Do ONLY J2.** Stop when green.

## Read first
- `backend/app/services/backtest/pit_fundamentals_store.py` (J1) — readers: `get_month_revenue_as_of`, `get_institutional_as_of`, `get_margin_as_of`, `get_per_as_of`, `get_financials_as_of`. Columns per table are known (revenue/revenue_yoy; foreign_net/trust_net/dealer_net; margin/short; per/pbr/dividend_yield; eps/roe/gross_margin/operating_margin/net_margin/filing_date).
- `backend/app/services/strategy/canslim/features.py` — the EXACT keys it reads:
  - `detail`: `_extract_month_revenue_yoy` accepts `detail["month_revenue_yoy"]` = list[float]; institutional via `foreign_net_5`/`trust_net_5`/`dealer_net_5` where each may be a **list of `{"date":..., "net":...}` dicts** (build_features applies its own T+1 lag through `_series_before_or_on_lagged_date`).
  - `fin_metrics`: `quarterly_eps_yoy`/`eps_yoy`, `annual_eps` (list, last 3), `roe`/`roe_ttm`, `op_margin_last4`/`operating_margins`, `pe_ttm`/`pe_ratio`. (`_normalize_ratio` divides by 100 when abs>1, so pass percents OR ratios consistently — match what the store holds.)
- `backend/app/services/strategy/canslim/observer.py` — `observe(...)` injection kwargs (`fin_metrics`, `detail`, `universe_returns_60d/252d`, `event_window_active`, `eps_filing_date`, `store`, `market`).
- `backend/app/services/strategy/canslim/walk_forward.py` (I2) — where signals are generated; this is the injection point.

## Build

### 1. `backend/app/services/strategy/canslim/pit_inputs.py`
```python
def build_pit_inputs(symbol, as_of_date, pit_store) -> tuple[dict, dict, str | None]:
    """Return (detail, fin_metrics, eps_filing_date) in observe()-compatible shapes, PIT-safe."""
```
- `detail`:
  - `month_revenue_yoy`: chronological list from `get_month_revenue_as_of` (use stored `revenue_yoy`; if null, compute YoY from the `revenue` series, ÷100 normalized consistently).
  - `foreign_net_5`/`trust_net_5`/`dealer_net_5`: from `get_institutional_as_of` as **lists of `{"date","net"}` dicts** (let build_features lag them). 
- `fin_metrics`:
  - `quarterly_eps_yoy`: from `get_financials_as_of` — latest filed quarter EPS vs same quarter prior year.
  - `annual_eps`: last 3 annual EPS (sum of 4 quarters per FY, or annual rows).
  - `roe`, `op_margin_last4` (last 4 quarters operating_margin), `net_margin`/`gross_margin` as available.
  - `pe_ttm`: latest from `get_per_as_of`.
- `eps_filing_date`: the latest financials `filing_date` ≤ as_of (for build_features' secondary gate).
- Any table empty → leave that field absent/None (build_features records missing + lowers confidence). Never fabricate.

### 2. Real-data walk-forward driver
Add a function in `walk_forward.py` (or a thin `canslim_realrun.py`) that, for each (stock, as_of_date), calls `build_pit_inputs(...)` + `observe(...)` with `store=HistoricalDataStore` (OHLCV) and `pit_store=PitFundamentalsStore`, generates `"CANSLIM觀察"` signals, and runs the existing I1/I2 trade sim + walk-forward. Universe = 53-stock `ai_tech_tw.json`. IS 2018–2022 / OOS 2023+. No live snapshot calls anywhere in this path.

## Tests — `backend/tests/strategy/canslim/test_phase_j2_pit_inputs.py` (≥5) — NO network
1. `build_pit_inputs` on a synthetic `PitFundamentalsStore` returns `detail`/`fin_metrics` with the expected keys + values; `observe()` consumes them without error and produces 3 graded cards.
2. PIT: a financial row filed after as_of is excluded from `fin_metrics` (no future EPS).
3. Institutional list-of-dicts path flows through build_features' T+1 lag correctly.
4. Empty tables → fields missing + the card's confidence drops / data_warnings present (no fabrication).
5. **Single-stock single-day sanity:** seed a small OHLCV `HistoricalDataStore` + matching `PitFundamentalsStore`, run the real-data path for one symbol/one date end-to-end, assert a sensible graded card (scores in range, rule-IDs attributed).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_j2_pit_inputs.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Report: the adapter key mapping, the real-run entry point, and test results. Then give the USER the exact 2-step command sequence: (1) backfill (`download_history` + `download_fundamentals`), (2) launch the real 53-stock walk-forward — and note to check the grade spread + signal frequency on real data afterward.

## STOP
When green, report. **CAN SLIM is then fully real-data-ready (A→J).**
