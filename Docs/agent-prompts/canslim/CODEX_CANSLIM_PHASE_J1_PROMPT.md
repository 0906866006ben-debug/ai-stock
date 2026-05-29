# Codex Task — CAN SLIM Phase J1: PIT fundamentals/chip store + FinMind backfill script

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Data-integration specifics:
> - **NO look-ahead.** Every PIT read returns only rows whose effective date ≤ as_of. Financial statements are available only after their filing date, not their period-end.
> - **Do NOT reuse the live snapshot functions** (`finmind_detail.get_tw_detail`, `tw_financial_metrics.fetch_real_metrics`) for backtest — they return CURRENT values and would leak the future. This phase builds the dated PIT store that replaces them in backtest.
> - **Free FinMind tier:** one date-range request per (stock, dataset); throttle; idempotent + resumable. Never print the token.

> **Phase J, part 1 of 2.** CAN SLIM A→I complete (500 suite green). **Do ONLY J1** (PIT store + backfill script). The as-of readers + walk-forward wiring are J2 — do NOT do them here. Stop when J1 tests green.

## Goal

Mirror the existing OHLCV pattern (`backend/app/services/backtest/historical_data_store.py` + `backend/scripts/download_history.py`) to acquire and store DATED fundamentals/chip history into a local point-in-time SQLite store, so walk-forward (2018→now) reads locally with zero API calls and zero look-ahead.

### Read first
- `historical_data_store.py` — copy its SQLite WAL pattern (`_connect`, `_initialize_schema`, `upsert_rows`, the `get_ohlcv_as_of(... date <= as_of ...)` PIT idiom).
- `download_history.py` — copy its CLI/throttle/idempotent structure.
- `finmind_detail.py::_fetch_dataset(dataset, data_id, start_date, token)` — the FinMind request shape (returns date-keyed `data` rows). Reuse it.
- `tw_calendar.py` — TW filing deadlines / `actual_filing_date` logic (for the financials PIT gate).
- Universe: `backend/data/sectors/ai_tech_tw.json` (53 stocks).

## Build

### 1. `backend/app/services/backtest/pit_fundamentals_store.py`
A `PitFundamentalsStore` class (SQLite WAL, same PRAGMAs as historical_data_store). One table per dataset, each row carries `stock_id` + an effective date:
- `month_revenue` (date = revenue month; columns: revenue, plus raw fields needed for YoY/MoM).
- `institutional` (date; foreign_net, trust_net, dealer_net).
- `margin` (date; margin_balance, short_balance).
- `per` (date; per, pbr, dividend_yield).
- `financials` (period_end, **filing_date**, eps, roe, gross_margin, operating_margin, net_margin, …).

Methods: `upsert_<table>(rows)` (INSERT OR REPLACE → idempotent) and PIT readers `get_<table>_as_of(stock_id, as_of_date, limit=N)`:
- For dated series: rows with `date <= as_of` (most recent N).
- For `financials`: rows with **`filing_date <= as_of`** (NOT period_end) — this is the look-ahead gate. If FinMind doesn't supply an explicit filing date, derive it from TW deadlines via `tw_calendar` (Q1→~05/15, Q2→~08/14, Q3→~11/14, FY→~03/31 of next year) and store that as `filing_date`.

### 2. `backend/scripts/download_fundamentals.py`
Mirror `download_history.py`:
- Args: `--start` (default `2017-01-01`, for warmup before 2018 IS), `--stocks`, `--universe-file`, `--db`, `--rate-limit` (default `1.0` s for free tier), `--datasets` (subset), `--verbose`.
- Token from `os.environ["FINMIND_API_KEY"]` (or FinMind token env already used in repo) — never log it.
- For each (stock, dataset): ONE `_fetch_dataset(dataset, data_id=stock, start_date=args.start, token)` call, normalize rows, upsert, `sleep(rate_limit)`. Resumable: re-running only fills/replaces (idempotent).
- Datasets to pull: `TaiwanStockMonthRevenue`, `TaiwanStockInstitutionalInvestorsBuySell`, `TaiwanStockMarginPurchaseShortSale`, `TaiwanStockPER`, `TaiwanStockFinancialStatements`. (Indices TAIEX/TPEX already via `screener_market_loader`; SOX/Nasdaq via yfinance in regime — out of scope here.)
- Log progress + per-dataset row counts; on FinMind error, warn and continue (mock fallback is NOT acceptable for a real backtest store — leave the gap, log it).

## Tests — `backend/tests/strategy/canslim/test_phase_j1_pit_store.py` (≥5) — NO network
1. `upsert` + `get_<table>_as_of` returns only rows with date ≤ as_of (PIT correctness) for each dated table.
2. `financials` PIT: a statement whose `filing_date` is after as_of is NOT returned (even if period_end ≤ as_of).
3. Idempotent: upserting the same rows twice doesn't duplicate.
4. Backfill script with `_fetch_dataset` monkeypatched to a fixture (no HTTP) writes the expected rows into the store.
5. Token is never logged (assert no token in captured log output).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_j1_pit_store.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Report: store schema, the financials filing-date gate approach, and test results. Then give the exact command the USER runs to backfill real data (e.g. `python -m backend.scripts.download_fundamentals --start 2017-01-01`), noting it needs `FINMIND_API_KEY` and ~5–10 min at 1s throttle.

## STOP
When green, report. Do NOT start J2 (as-of readers in observe()-compatible shapes + walk_forward wiring + 53-stock sanity).
