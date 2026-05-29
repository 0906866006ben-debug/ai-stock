# Codex Task — Extend fundamentals backfill to the FULL OHLCV universe + coverage report

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Data acquisition only — no strategy/rule/score change. No look-ahead (financials filing-gated as in J1). Free-FinMind throttle, idempotent + RESUMABLE, never log token. Missing fundamentals → leave the gap + log (NEVER mock into the PIT store).

> Context: OHLCV store has 1,102 symbols but PIT fundamentals cover only ~390-410. The gap causes C/A/I = Insufficient_Data for uncovered symbols. The M2 backfill targeted `get_tech_universe_symbols()` which is narrower than the OHLCV pool. Fill the gap for whatever FinMind actually provides; honestly leave the rest empty.

## Build (small — extend the existing M2 script)
1. Add a universe option to `backend/scripts/download_fundamentals.py`: `--universe-source ohlcv` → symbol list = `HistoricalDataStore.list_stocks()` (the full ~1,102). Keep existing `ai_tech`/`broad` options unchanged (default unchanged).
2. Reuse the existing resume logic (skip stock+dataset already present ≥ start) so re-running only fills the ~700 not-yet-attempted; throttle as before; per-symbol failure → warn + continue (no mock).
3. Datasets: same five (MonthRevenue, InstitutionalInvestorsBuySell, Margin, PER, FinancialStatements), `--start 2010-01-01`.

## Coverage report — `backend/scripts/report_fundamentals_coverage.py` (+ `artifacts/data_probe/fundamentals_coverage.md`)
After backfill, report: for each dataset, how many of the OHLCV symbols now have data; the count of fully-covered symbols (all 5 datasets); a list (or count) of OHLCV symbols with NO fundamentals at all (likely ETFs/KY/too-new/FinMind-absent). This tells us the true screenable-universe size and what FinMind simply doesn't have.

## Tests — `backend/tests/strategy/canslim/test_fundamentals_coverage.py` (≥3) — NO network
1. `--universe-source ohlcv` resolves to `store.list_stocks()` (monkeypatched) and drives the loop.
2. Resume: already-covered stock+dataset is skipped on re-run.
3. Coverage report computes per-dataset coverage + fully-covered count correctly on a synthetic PIT store.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_fundamentals_coverage.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER: (a) the backfill command (`--universe-source ohlcv --start 2010-01-01`, resumable, est. time at free-tier throttle — note it only fetches the ~700 not yet present), and (b) the coverage-report command.

## STOP
When green, report the commands. The USER runs the (multi-hour, resumable) backfill, then the coverage report — so we see how many symbols are now fully screenable and how many FinMind genuinely lacks.
