# Codex Task — Rigor fixes for single-symbol CANSLIM screening (audit remediation)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. Constraints:
> - **Do NOT change** the validated signal/rule/score/aggregator/regime math. These are SCREENING-LAYER + LIVE-ADAPTER fixes only.
> - No buy/sell/hold/target-price/prediction in output (assert).
> - Missing data → `Insufficient_Data` + data_warning, NEVER fabricate or silently degrade.
> - Additive/backward-compatible; existing 579 tests stay green. New thresholds go in YAML (`screening:`).

## Fixes (a code audit found these — implement all)

### 1. (CRITICAL) Data staleness check — `live_screening.py`
`_latest_as_of_date` uses the store's max date, but the store is backfilled (not live) → it silently screens on stale data as if current. Add: compare the resolved `as_of_date` to today; if the gap exceeds `screening.staleness.max_trading_days` (new YAML, default ~5 trading days / 10 calendar days), append a PROMINENT data_warning (e.g. `"data stale: latest as_of {date} is N days behind today; screening reflects stale market state"`). Always ensure `as_of_date` is present in the returned `ScreeningResult`. Do not crash.

### 2. (CRITICAL) `is_mock` semantics — `live_screening.py:81`
`is_mock = bool(is_mock or all_warnings)` makes is_mock ALWAYS True (S pillar always emits day-trade/chip warnings). Decouple: `is_mock` must be True ONLY when actual mock/fallback DATA was used (live mock fallback, fetch returned mock, full `_fallback_result`). Benign data_warnings (partial-pillar notes, staleness) must NOT set is_mock. Keep data_warnings as-is.

### 3. (CRITICAL) No fake single-point series — `live_screening.py:192-216`
`_detail_to_canslim_detail` builds 1-element `foreign_net_5`/`trust_net_5`/`month_revenue_yoy`, which breaks multi-period logic (I pillar needs ≥3 days → can never Pass; G-1 needs ≥3 months). Fix: do NOT synthesize series shorter than the length downstream requires. If only a single point is available, leave the series `None` (so the pillar honestly becomes `Insufficient_Data`) and add a data_warning like `"institutional 5-day series unavailable from live fallback; I pillar partial"`. Same for revenue.

### 4. (MODERATE) L pillar must use annual RS (rs_252d) — `pillar_screening.py:screen_L`
Currently only `rs_60d_pct`. O'Neil leadership is annual. Require BOTH: PASS = `rs_60d_pct ≥ l_rs_pass` AND `rs_252d_pct ≥ l_rs_pass` AND stage-2; FAIL = `rs_252d_pct < l_rs_fail` (annual is primary) OR `rs_60d_pct < l_rs_fail`; else WEAK. If `rs_252d_pct` is None → Insufficient (or Weak with a data_warning if 60d present — document the choice). Thresholds from YAML (reuse `l_rs_pass`/`l_rs_fail`, or add `l_rs_252d_*` if you want separate bands).

### 5. (MODERATE) C must not upgrade weak EPS to Pass — `pillar_screening.py:75-76`
Weak-band EPS (`[c_weak, c_pass)`) + G-1 revenue acceleration currently returns "Pass". Change to stay **"Weak"** with a reason note `"weak EPS band with revenue-acceleration support"`. Only `quarterly_eps_yoy ≥ c_pass` yields Pass.

### 6. (MINOR) Word-boundary verb scrub — `screening_language.py:clean_user_facing_text`
English replacements use `re.escape(old)` (substring) while detection uses `\b` — inconsistent; corrupts legit words (shareholding→share-carrying, buyback→…). Fix: wrap English term replacements with word boundaries (`\b`). Leave CJK terms (買/賣/持有…) as substring (no word boundaries in Chinese). Add a test that "shareholding"/"buyback"/"household" are NOT mangled while standalone "buy"/"sell"/"hold" ARE replaced.

### 7. (MINOR) I pillar: flat ≠ Fail — `pillar_screening.py:191`
Currently returns Fail when no net-positive confirmation even if flows are flat/mixed (not selling). Change: Fail ONLY on actual net-selling (`R-3` triggered OR both 3-day sums < 0); when flat/mixed (no confirmation, no selling) return **"Weak"** (or Neutral) with reason `"institutional flows flat/mixed"`.

### 8. (MINOR) as-of consistency note — `live_screening.py`
When live (current) fundamentals fallback is used while price/regime come from a stale store, append a data_warning that fundamentals and price as-of differ (don't silently blend dates).

## Tests — extend `test_pillar_screening.py` + `test_live_screening.py` + `test screening_language` (≥8 new, NO network)
- Staleness: stale store date → staleness data_warning present; fresh → none.
- is_mock False on a fully-real fixture that only has the S pillar partial warnings; True when live mock fallback used.
- Single-point live fallback → I and C/G-1 pillars become Insufficient_Data (not silently Weak/Fail), with data_warning.
- L: rs_252d below floor → not Pass even if rs_60d strong; both strong + stage2 → Pass.
- C: weak EPS + G-1 → stays Weak (not Pass); EPS ≥ c_pass → Pass.
- Verb scrub: "shareholding"/"buyback" unmangled; "buy"/"sell"/"hold" replaced.
- I: flat/mixed flows → Weak (not Fail); net-selling → Fail.
- Verb-free assertion still holds across all outputs.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
When green, report each fix + new YAML keys + test results.
