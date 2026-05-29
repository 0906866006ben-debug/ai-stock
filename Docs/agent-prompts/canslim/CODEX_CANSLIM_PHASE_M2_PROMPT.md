# Codex Task — CAN SLIM Phase M2: PIT fundamentals/chip backfill for the broad universe

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Specifics: no look-ahead (financials gated by filing_date), no fabricated data (missing → leave gap, log it), free-FinMind throttle, idempotent + RESUMABLE (this is a multi-hour run over ~1,100 symbols), never log the token.

> **Phase M, part 2 of 3.** M1 done: broad tech pool + long-history OHLCV/indices in `HistoricalDataStore` (1,102 symbols, 3.35M rows, back to ~2011). PIT fundamentals store + `download_fundamentals.py` already exist from J1 (53-stock scale). **Do ONLY M2.** Multi-cycle walk-forward + re-attribution is M3. Stop when tests green + the backfill command/estimate is reported.

## Goal

Backfill the dated PIT fundamentals/chip datasets for the BROAD tech universe (from M1's `universe_source.get_tech_universe_symbols()`), into the existing `PitFundamentalsStore`, so M3's multi-cycle walk-forward has fundamentals for whichever stocks the per-date liquidity universe selects.

## Read first
- `backend/scripts/download_fundamentals.py` (J1) — the existing backfill (currently defaults to the 53-stock `ai_tech_tw.json`). Extend it to target the broad pool.
- `backend/app/services/strategy/canslim/universe_source.py` (M1) — `get_tech_universe_symbols()`.
- `backend/app/services/backtest/pit_fundamentals_store.py` (J1) — `PitFundamentalsStore` + `upsert_*` + filing-date gate.

## Build (mostly scale + resume, minimal new code)

1. Add a universe option to `download_fundamentals.py`: `--universe-source {ai_tech|broad}` (or `--universe-file`), where `broad` = `get_tech_universe_symbols()`. Default stays `ai_tech` (don't change existing behavior).
2. **Resumability for the large run:** before fetching a (stock, dataset), skip if the store already has rows for that stock+dataset covering the requested start (track via a simple per-(stock,dataset) max-date check or a small progress table). Re-running must continue, not restart. Throttle (`--rate-limit`, default 1.0s). Tolerate per-symbol FinMind failures (warn + continue; leave the gap, never mock).
3. Datasets: `TaiwanStockMonthRevenue`, `TaiwanStockInstitutionalInvestorsBuySell`, `TaiwanStockMarginPurchaseShortSale`, `TaiwanStockPER`, `TaiwanStockFinancialStatements` (financials filing-date gated as in J1). Allow `--datasets` subset so the user can stage it (e.g. institutional+revenue first, financials+per next).
4. Log progress (i/N), per-dataset row counts, and elapsed.

## Tests — `backend/tests/strategy/canslim/test_phase_m2_broad_backfill.py` (≥3) — NO network
1. `--universe-source broad` resolves to `get_tech_universe_symbols()` (monkeypatched) and drives the backfill loop over those symbols.
2. Resume logic: a (stock, dataset) already present up to the start date is SKIPPED on re-run (assert no duplicate fetch).
3. Per-symbol fetch failure → warn + continue (no crash, no mock rows written).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_m2_broad_backfill.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER: the broad backfill command(s), a realistic time estimate at free-tier throttle (≈ symbols × datasets / rate; note it may run several hours and is resumable — suggest staging via `--datasets`), and how to verify row counts per dataset afterward.

## STOP
When green, report. Do NOT start M3 (multi-cycle walk-forward + re-attribution).
