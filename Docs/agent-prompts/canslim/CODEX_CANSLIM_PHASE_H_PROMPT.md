# Codex Task — CAN SLIM Phase H: Wire into surge-analysis + API (additive, non-breaking)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This phase wires the classifier into real flow — the mandatory **signal-frequency sanity check** applies: after wiring, run the new path over the 53-stock universe for a sample of dates and report how many cards land in each grade. **If S/A/B grades are ~0 across the universe, STOP and report — the thresholds are too strict.** Surface diagnostics; never ship a silent zero.

> **Phase H.** A–G done (140 canslim tests, full suite 484). **Do ONLY Phase H.** No backtest (I). Stop when green + the frequency check is reported.

## Constraints (per CLAUDE.md)
- **Do NOT break** `/analyze`, `/analyze/tw`, multi-factor-surge, or any of the 484 existing tests.
- New response fields must be **Optional + nullable**; existing clients ignoring them keep working.
- CAN SLIM path must be **opt-in** (flag/param) so default surge behavior is byte-identical.

## Changes

1. **Schema — `backend/app/models/schemas.py`**: add `canslim_summary: Optional[CanslimSummary] = None` to `TaiwanStockAnalysisResponse`. Define `CanslimSummary` (Pydantic v2): `grades: dict[str,str]` (horizon→S/A/B/C), `scores: dict[str,dict]` (horizon→{signal,risk,confidence}), `hard_blocked: dict[str,bool]`, `data_warnings: list[str]`, `is_mock: bool = False`. Keep it a thin projection of the 3 `HorizonObservation` cards. Forward refs resolve automatically in this file.

2. **`backend/app/models/screener_schemas.py`**: add OPTIONAL CAN SLIM fields to `CandidateMetrics`/`CandidateScores` (e.g. `canslim_grade: Optional[str] = None`, `canslim_signal: Optional[int] = None`) — nullable, default None.

3. **`backend/app/services/screener_service.py`**: add an opt-in path (param e.g. `include_canslim: bool = False`) that, when set, calls `observer.observe(symbol, as_of_date, ...)` and attaches a new candidate_type `"CANSLIM觀察"` / fills the optional metrics. Wire `event_window_active` from `tw_calendar`. Do NOT alter the existing classification path when the flag is off.

4. **`/analyze/tw` in `backend/app/main.py`**: populate `canslim_summary` ONLY when computed (else leave None). Reuse the deps already fetched by the endpoint (get_tw_detail, financial metrics) — inject them into `observe()` rather than refetching.

## Tests — `backend/tests/strategy/canslim/test_phase_h_wiring.py` (≥4) + keep existing green
1. `/analyze/tw` returns successfully with `canslim_summary = None` when the flag is off (backward-compat).
2. With CAN SLIM enabled on a fixture, `canslim_summary` populates with 3 horizons + grades.
3. `CandidateMetrics` optional CAN SLIM fields default None and don't break existing screener tests.
4. **Frequency sanity test:** run the CAN SLIM path over a small synthetic multi-stock fixture and assert a NON-zero spread of grades (not all "none"/blocked) — guards the zero-signal regression.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_h_wiring.py -q
.venv\Scripts\python -m pytest backend\tests\ -q   # ALL 484+ must stay green
```
Also report: grade distribution from the frequency check.

## STOP
Report schema additions, the opt-in wiring, the grade distribution, and full-suite status. Do NOT start Phase I.
