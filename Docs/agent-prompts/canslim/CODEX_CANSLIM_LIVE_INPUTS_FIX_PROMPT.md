# Codex Task — Fix "Insufficient_Data too often": assemble cross-sectional inputs in live screening

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Screening-layer + live-adapter only — do NOT change the validated signal/rule/score/aggregator/regime math. No buy/sell/hold/target-price. Missing data still → Insufficient honestly; the goal is to STOP being Insufficient when the data actually exists but wasn't assembled.

## Root cause (audit)
`live_screening.screen_symbol()` calls `build_screening_result()` WITHOUT `universe_returns_60d/252d` → `rs_60d_pct`/`rs_252d_pct` are always None → **L pillar is always Insufficient_Data**. Also `build_market_features()` is called without a universe → breadth is missing → M is degraded. And fundamentals only cover ~390 symbols (PIT store) of the 1102 OHLCV pool, so symbols outside that set return C/A/I Insufficient — which should be clearly communicated, not look like a bug.

## Fixes

### 1. Compute & pass universe RS returns — `live_screening.py`
- Build `universe_returns_60d` and `universe_returns_252d` as `dict[symbol -> N-day return]` at `as_of_date`, over the **screenable universe** (the fundamentals-covered set; see #3). Compute each symbol's return PIT from the OHLCV store via `get_ohlcv_as_of` (close[-1]/close[-N] - 1); skip symbols with insufficient bars.
- Pass both dicts into `build_screening_result(...)`. Now `rs_*_pct` populate → L can produce Pass/Weak/Fail.
- **Cache** the universe-returns dicts per `as_of_date` (module-level cache keyed by (as_of_date, universe-hash)) so a single-symbol call doesn't recompute the whole universe every time and a future batch reuses it.

### 2. Pass universe to `build_market_features` for breadth — `live_screening.py`
- Provide the screenable universe to `build_market_features(as_of_date, store=store, universe=...)` so `breadth_above_ma60_pct` is computed → M-3 / severe detection work. (If `build_market_features` doesn't accept a universe param, add it additively without changing its math.)

### 3. Define & expose the screenable universe — `live_screening.py` (+ small helper)
- A `screenable_universe(pit_store, ohlcv_store) -> list[str]` = symbols that have BOTH OHLCV history AND PIT fundamentals (the ~390). Use it for the universe-returns/breadth computation.
- When the requested `symbol` is NOT in the fundamentals-covered set: still return a `ScreeningResult`, but add a clear data_warning like `"{symbol} has no PIT fundamentals coverage; C/A/I pillars cannot be evaluated"` and let those pillars be Insufficient_Data honestly (this is correct, not a bug). Do NOT mark is_mock just for coverage gaps.

### 4. (verify) RS percentile needs the symbol IN the universe dict
- Ensure the screened symbol is included in the universe-returns dicts (so its own percentile is computed). If it has enough OHLCV history, include it even if outside the fundamentals set (so L can still be assessed for any liquid symbol); fundamentals pillars stay Insufficient for uncovered names.

## Tests — extend `test_live_screening.py` (≥4, NO network)
1. With a seeded multi-symbol OHLCV store, `screen_symbol` computes universe RS returns and the L pillar is NOT Insufficient (Pass/Weak/Fail) for a symbol with history.
2. Breadth flows into market features (M not Insufficient when indices + universe present).
3. A symbol with OHLCV but NO PIT fundamentals → L can still be assessed; C/A/I → Insufficient + the coverage data_warning; is_mock stays False.
4. Universe-returns cache: second call for the same as_of_date reuses the cached dict (assert it isn't recomputed, e.g. via a spy/counter).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_live_screening.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then run a real `GET /tw/screen?symbol=2330` and report which pillars now resolve vs Insufficient, and the coverage of the screenable universe (count).

## STOP
When green, report: L now resolves, breadth wired, screenable-universe size, and which pillars still Insufficient for an uncovered symbol. Do NOT build W2 batch yet (but the universe-returns cache should make it cheap later).
