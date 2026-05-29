# Codex Task — Make the screener usable: live single-symbol /tw/screen endpoint (W1)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This exposes the finished CANSLIM screener for LIVE use. Hard rules:
> - Output is `ScreeningResult` (condition-match per pillar) — **NO buy/sell/hold/target-price/prediction** (assert).
> - **Do NOT change** the validated signal math, the rules, or `build_screening_result`/`assemble_pillars` logic. This wires LIVE data INTO them.
> - Additive + backward-compatible: new endpoint + optional response field; existing 575 tests + `/analyze`,`/analyze/tw` stay green.
> - Follow the repo's live-service contract: missing API key / failed fetch → mock/graceful with `is_mock`/status flags, never crash (see CLAUDE.md).

> **W1 only** (single-symbol live screening). Batch universe screen is W2 — do NOT build it here.

## Context
`build_screening_result()` (screening.py) + `assemble_pillars()` (pillar_screening.py) are done and tested, but only exercised via injected fixtures. We now feed LIVE/current data so the user can screen a real symbol. The OHLCV `HistoricalDataStore` + `PitFundamentalsStore` are populated and current (through ~yesterday); reuse them as the "as-of latest" source, plus the live services for anything not in the stores.

## Build

### 1. Live input adapter — `backend/app/services/strategy/canslim/live_screening.py`
`async def screen_symbol(symbol: str, as_of_date: str | None = None) -> ScreeningResult`:
- Resolve `as_of_date` = latest available trading date in the OHLCV store if None.
- Gather inputs (reuse existing code, do NOT refetch what stores hold):
  - OHLCV via `HistoricalDataStore.get_ohlcv_as_of`.
  - fundamentals/institutional via `PitFundamentalsStore` + `build_pit_inputs` (already observe()-compatible), OR live `tw_financial_metrics.fetch_real_metrics` / `finmind_detail.get_tw_detail` if the store lacks the latest — prefer store, fall back to live, set `is_mock`/data_warning accordingly.
  - market regime via `build_market_features(as_of_date, store)` (uses TAIEX/TPEX in the store).
  - N pillar: the R3 news analyzer (live Yahoo news) — sourced evidence only; `AI_Review_Required` when none.
- Call `build_screening_result(...)` and return the `ScreeningResult`.
- Never crash on missing data → pillars become `Insufficient_Data` + data_warnings.

### 2. Endpoint — `GET /tw/screen` in `backend/app/main.py`
- Query: `symbol` (required), `as_of_date` (optional). Returns the `ScreeningResult` JSON.
- Also (optional, additive): add `screening_result: Optional[ScreeningResult] = None` to `TaiwanStockAnalysisResponse` and populate it in `/analyze/tw` only when cheaply available (else None). Do not slow the existing endpoint materially; if it adds latency, gate behind a query flag `include_screening=true`.

## Tests — `backend/tests/strategy/canslim/test_live_screening.py` + endpoint test (≥4) — NO network
1. `screen_symbol` on a seeded temp OHLCV + PIT store (monkeypatch live services) returns a valid `ScreeningResult` with all 7 pillars populated.
2. Missing fundamentals → those pillars `Insufficient_Data` + data_warnings; no crash.
3. `GET /tw/screen?symbol=2330` returns 200 + a verb-free `ScreeningResult` (assert no buy/sell/target-price); works with no API keys (mock path).
4. `/analyze/tw` still returns when screening not requested (backward-compat).

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_live_screening.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER a sample `curl`/browser URL to screen a symbol, and a note on what live data it used vs mock.

## STOP
When green, report the endpoint + a sample ScreeningResult shape. Do NOT build the batch universe screener (W2) yet.
