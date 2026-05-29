# Codex Task — CAN SLIM Phase M1: broad tech universe + long-history OHLCV/index backfill + PIT universe builder

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Data-expansion specifics:
> - **Survivorship bias is the #1 risk.** We are moving OFF the hand-picked 53-stock winner list to a MECHANICAL universe (tech/electronics sectors + per-date liquidity floor) precisely to remove winner-selection bias. Universe membership must be decided PER DATE from data available AT THAT DATE — never from today's knowledge of which stocks won.
> - No look-ahead, no fabricated data, free-FinMind throttle, idempotent + resumable (this is a large backfill).
> - Known residual caveat to DOCUMENT: this still excludes already-delisted names (FinMind free lists current securities), so a partial survivorship bias remains — record it in the module docstring; do NOT pretend it's fully PIT.

> **Phase M, part 1 of 3.** CAN SLIM A→J complete + measurement done (529 suite green). **Do ONLY M1.** PIT fundamentals backfill is M2; multi-cycle walk-forward + re-attribution is M3. Stop when M1 tests green + the backfill command is reported.

## Why

The 3-window real walk-forward exhausted its information (1 bull + 1 bear). To validate regime-conditional behavior we need MULTIPLE independent cycles (2011/2015/2018/2020/2022 corrections). That requires (a) longer history and (b) a bias-free mechanical universe.

## Read first
- `backend/scripts/download_history.py` — extend its pattern (longer `--days`, broader stock list).
- `backend/app/services/finmind_company.py` / `tw_stocks_list.py` — how `TaiwanStockInfo` (industry_category) is fetched; reuse to enumerate tech/electronics/semiconductor categories.
- `backend/app/services/backtest/historical_data_store.py` — store + `get_ohlcv_as_of`.

## Build

### 1. Broad tech universe list
`backend/app/services/strategy/canslim/universe_source.py`:
- `get_tech_universe_symbols() -> list[str]`: from `TaiwanStockInfo`, all TWSE+TPEX stocks in tech-relevant `industry_category` values (semiconductor 半導體, 電子零組件, 光電, 電腦及週邊, 通信網路, 電子通路, 其他電子, 資訊服務 — enumerate the actual category strings present). Exclude ETFs/warrants. This is the candidate pool (~hundreds of names), NOT the per-date universe.

### 2. Long-history OHLCV + index backfill
- Extend `download_history.py` (or a new `download_history_broad.py`) to accept this broad symbol list + `--days` long enough to reach ~2010 (e.g. `--days 5800`). Backfill OHLCV for the broad pool + indices `TAIEX`, `TPEX` into the existing `HistoricalDataStore`. Reuse throttle/idempotent/resume. Log per-symbol row counts; symbols with short history just get fewer bars (fine).

### 3. Per-date (PIT) mechanical universe builder
`backend/app/services/strategy/canslim/pit_universe.py`:
- `get_universe_as_of(as_of_date, store, *, turnover_floor=30_000_000, candidate_symbols=None) -> list[str]`: from the candidate pool, return symbols whose `avg_turnover_20` (computed from `get_ohlcv_as_of`, bars ≤ as_of) ≥ `turnover_floor` AND with ≥ N bars of history at that date. Membership is decided ONLY from data ≤ as_of (PIT). Threshold from YAML if present (`backtest.canslim.universe_turnover_floor`), else the existing liquidity floor.
- Document the residual survivorship caveat (delisted names excluded).

## Tests — `backend/tests/strategy/canslim/test_pit_universe.py` (≥4) — NO network
1. `get_universe_as_of` includes only symbols above the turnover floor at that date; a symbol that becomes liquid only LATER is excluded at an earlier date (PIT correctness).
2. A symbol with insufficient history at the date is excluded.
3. Universe membership changes correctly across two dates as liquidity changes.
4. `get_tech_universe_symbols` parsing of a mocked `TaiwanStockInfo` payload returns the expected tech categories, excludes ETFs (no network).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_pit_universe.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER: (a) the broad OHLCV/index backfill command + rough size/time estimate at free-tier throttle (note it may take hours; resumable), and (b) confirm `get_universe_as_of` works against the backfilled store for a sample date.

## STOP
When green, report the universe size, store growth, and the backfill command. Do NOT start M2 (PIT fundamentals backfill for the broad pool).
