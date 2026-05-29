# Codex Task — Data-expansion AVAILABILITY PROBE (no backfill yet)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This is a PROBE only — do NOT build large backfills, do NOT change strategy/rules. Goal: find out, empirically, which datasets FinMind (free tier) + yfinance actually provide, how far back, and what fields — so we can design the right backfill next. Never log the FinMind token.

## Why
The user wants to add: (1) news/announcements/法說 (feeds the R3 N-pillar AI), (2) advanced chip — day-trade ratio + shareholder concentration/holder count (re-enable SD-3/SD-4), (3) external + sector indices (SOX/Nasdaq + TW sector indices, M-pillar), (4) a broader universe. Several of these may NOT exist on FinMind free tier or may not be point-in-time. Probe before committing.

## Build — `backend/scripts/probe_data_sources.py` (small, fast, sample fetches only)
Reuse the existing FinMind fetch pattern (`finmind_detail._fetch_dataset` / the dataset list endpoint) + yfinance. For each candidate source, do a SMALL sample request (one symbol like 2330, a short recent date range) and record availability.

Probe these (VERIFY actual dataset names against FinMind's dataset-list API — do not assume my strings are exact):
1. **News / announcements:** `TaiwanStockNews` (used by yahoo_news.py) — sample for 2330; report earliest date reachable on free tier, fields, and whether it carries a usable publish timestamp + url/source. Also check any 法說會 / announcement dataset.
2. **Day-trade ratio (當沖比):** look for `TaiwanStockDayTrading` (or similar). Available? fields? earliest date? free tier?
3. **Shareholder concentration / holder count:** look for 集保 / 股權分散 datasets (e.g. `TaiwanStockHoldingSharesPer`, `TaiwanStockSharesHolding`, or similar — verify). Available? cadence (weekly?)? fields? earliest?
4. **Sector / external indices:** TW sector index datasets on FinMind (verify names); SOX (`^SOX`) and Nasdaq (`^IXIC`) via yfinance — confirm fetchable + earliest date.
5. **Full universe size:** via `TaiwanStockInfo`, count all TWSE+TPEX listed stocks (vs the current ~1102 tech pool) to estimate the cost of a full-market expansion.

## Output — `artifacts/data_probe/availability_report.md` (+ .json)
A table: source | dataset name (verified) | available on free tier (Y/N) | earliest date | cadence | key fields | PIT-usable? | notes/caveats. Plus a short recommendation per source: backfill-worthy now / limited / not available.

## Tests — `backend/tests/test_data_probe.py` (≥2) — NO network
1. The probe's result-parsing/report-assembly works on a mocked FinMind/yfinance payload (no real HTTP in tests).
2. Token never appears in the report or logs.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\test_data_probe.py -q
.venv\Scripts\python -m pytest backend\tests\ -q
```
Then give the USER the command to RUN the real probe (needs FINMIND_API_KEY; fast — only sample requests), and where the report lands.

## STOP
When green, report the probe command. Do NOT build any backfill yet — we design backfills only for what the probe shows is actually available.
