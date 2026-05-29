# Codex Task — CAN SLIM Phase M3: continuous multi-cycle fixed-param backtest + re-attribution

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This is a MEASUREMENT/validation run, not optimization. Specifics:
> - **Fixed default params** (no tuning) — we are testing whether the regime-conditional momentum pattern holds across many cycles, not fitting.
> - No look-ahead: per-date PIT universe + PIT inputs only; financials filing-gated; institutional T+1 (reuse existing observe()/build_pit_inputs/build_features gating).
> - Output must be schema-compatible with the EXISTING attribution tools so they run unchanged.

> **Phase M, part 3 of 3.** M1 (broad OHLCV/indices to ~2011) + M2 (PIT fundamentals to 2010, ~390–410 symbols) done. **Do ONLY M3.** Stop when tests green + the run command + a first attribution read are reported.

## Why a CONTINUOUS backtest (not walk-forward windows)

The 3-window walk-forward exhausted its info (1 bull + 1 bear). For validating the regime hypothesis across 2011→2025 (2011 euro / 2015 / 2018Q4 / 2020 COVID / 2022 bear / 2023–24 bull), a single continuous fixed-param backtest with every trade tagged by regime gives maximum statistical power and avoids arbitrary window-chopping. WFE/acceptance was an optimization concept; here we MEASURE.

## Build — `backend/app/services/strategy/canslim/multicycle_backtest.py` + `backend/scripts/run_canslim_multicycle.py`

1. **Universe per date:** use `pit_universe.get_universe_as_of(as_of_date, store, turnover_floor=...)` (M1) restricted to the fundamentals-covered pool (~390 symbols). This prunes compute heavily in early years and keeps it bias-free.
2. **Cadence:** evaluate signals on a **weekly** as_of grid (configurable `--cadence-days 5`), not daily — cuts compute ~5x; swing/long horizon makes weekly fine.
3. **Signal + trade generation:** reuse `observe()` + `build_pit_inputs()` (PIT) + the existing trade simulator with FIXED default YAML params (`min_entry_grade`, `max_hold_days`, etc.). Regime entry policy: keep whatever is in YAML default; record it. (No optimizer, no grid.)
4. **Tag every OOS trade** with the SAME columns the attribution tools expect (`window`/segment label, `horizon`, `stock_id`, `entry_date`, `grade`, `regime_bucket_at_entry`, `net_return_pct`, `holding_days`) + extension metrics. Use a per-year (or per-named-cycle) `segment` label instead of `window`. Write `artifacts/canslim_multicycle/multicycle_tagged_trades.csv`.
5. **Resumable + progress:** process year-by-year, write incrementally, skip completed years on re-run; log progress + elapsed. Reuse feature caches.
6. **Named-cycle summary:** also bucket results into named regimes (e.g. 2011-H2 euro, 2015-H2, 2018-Q4, 2020-COVID, 2022-bear, 2023–24-bull) for a readable per-cycle table.

## Re-attribution (reuse existing tools, no new analysis logic)
After the run, the EXISTING scripts must work on the new tagged CSV:
- `run_canslim_extension_attribution`, `run_canslim_riskon_analysis`, `run_canslim_distday_analysis`, and the grade×regime attribution — pointed at `multicycle_tagged_trades.csv`. Confirm they run unchanged (adapt only the `--input` path / a small `segment` vs `window` column alias if needed).

## The question M3 answers
Across 2011→2025 multi-cycle data: **Does the momentum edge flip by regime consistently (risk_on positive, severe negative) across MULTIPLE independent cycles, or was it a 2022 artifact?** And: is risk_on-only a consistently positive cohort when measured over many bull phases (not just 2023 H1)?

## Tests — `backend/tests/strategy/canslim/test_multicycle_backtest.py` (≥4) — NO network
1. Weekly cadence grid generated correctly between two dates.
2. Per-date universe pruning integrates with the run (synthetic store: only liquid-at-date symbols evaluated).
3. Tagged-trade output schema matches what the attribution tools consume (column names/types).
4. Resume: a completed year is skipped on re-run; no duplicate trades. No YAML/param mutation.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_multicycle_backtest.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER: the multicycle run command (note: long run, several hours, resumable, weekly cadence) + the commands to re-run the existing attribution tools on the output. Report a rough compute estimate.

## STOP
When green, report the run command + attribution commands. The USER runs the multi-hour backtest; results interpreted together afterward. Do NOT change scoring/rules/gates based on results yet.
