# Codex Task — CAN SLIM Phase G: 3-horizon observation builder (END-TO-END / "通" gate)

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This phase composes everything into user-facing cards:
> - Output is **conditional observation cards only — NO buy/sell/hold verbs** (買/賣/持有, buy/sell/hold) in any string. A test must assert this.
> - Every `evidence_based_reason` must cite triggered rule IDs (for backtest attribution).
> - Grades S/A/B/C come through from the aggregator; a C-grade is still surfaced. Only R-4/R-5short/R-6 hard-block marks a name "blocked for new entry" — reported separately, the card still shows.

> **Phase G.** A–F done (132 canslim tests, full suite 476). **Do ONLY Phase G.** No surge/API wiring (H), no backtest (I). Stop when G tests green.

## Build — `backend/app/services/strategy/canslim/observer.py`

```python
def observe(symbol: str, as_of_date: str, *, store=None, market=None, fin_metrics=None, detail=None,
            universe_returns_60d=None, universe_returns_252d=None, event_window_active=None,
            eps_filing_date=None) -> dict[str, HorizonObservation]: ...
```
Injectable deps (offline-testable). Pipeline:
1. `features = build_features(...)` (Phase B/extended).
2. `market = market or build_market_features(as_of_date, ...)` (Phase F).
3. `base = detect_base(bars, params)` (Phase D).
4. For each horizon in `["short_term","swing_term","long_term"]`: select the rules whose YAML `horizons` include it (across G/T/SD/I/M/R pillars), evaluate each → `RuleResult` list, then `aggregate(rule_results, base, horizon, params)` (Phase E).
5. Build a `HorizonObservation` (type from `types.py`) per horizon from the `AggregateResult` + triggered rules.

### Mapping AggregateResult → HorizonObservation
- `scores` = {signal, risk, confidence}; `triggered_rule_ids` from results.
- `status`: derive from grade + hard_block — e.g. hard_blocked → "watching"; grade S/A with breakout rule triggered → "trigger_proximity"; invalidation rule active → "invalidating"; else "neutral"/"watching". Keep deterministic; document the mapping.
- `direction_hint`: up if signal high & risk not dominant; down if risk-off/invalidating; sideways/unclear otherwise.
- `risk_level`: low/moderate/elevated/high from risk_score bands. `confidence_level`: low/moderate/high from confidence_score (low if `low_confidence`).
- `evidence_based_reasons`: the triggered rules' `reason` strings (already cite rule_ids). `invalidation_signals`: always populated (per research doc §9 — from the rules' invalidation semantics / a small static map). `data_warnings`: collected from features + market + rules.
- Apply the §10 conflict scenarios where they affect status/direction (implement at least: strong-fundamentals+short-overheat; breakout-without-fundamentals; hard-block-regime; foreign-buy+trust-sell divergence).

## Tests — `backend/tests/strategy/canslim/test_phase_g_observer.py` (≥6)
1. **END-TO-END "通" test (required):** one realistic fixture stock (build OHLCV via a temp `HistoricalDataStore` + injected fin_metrics/detail/market), run `observe()`, assert: 3 horizons returned, each score in [0,100], grade ∈ {S,A,B,C}, triggered_rule_ids present, `invalidation_signals` non-empty.
2. **Verb-free:** assert no card string contains 買/賣/持有/buy/sell/hold (case-insensitive).
3. Hard-block (R-6 liquidity) → card still returned, scores present, status reflects blocked.
4. Partial match → grade C/B, still a card (anti-zero-signal).
5. ≥2 conflict scenarios produce the documented status/direction.
6. Rule-ID attribution: every `evidence_based_reason` references at least one rule_id.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_g_observer.py -q
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
Report the observe() pipeline, the status/direction mapping, and the end-to-end test result (this proves the pipeline is "通"). Do NOT start Phase H.
