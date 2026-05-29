# Codex Task — CAN SLIM Phase A: Scaffolding + YAML threshold file

> This is **Phase A of 9**. Do ONLY Phase A. Do not implement any rule logic, feature extraction, scoring, or detection — those are later phases. Stop when Phase A tests are green.

## Background

We are quantifying O'Neil's CAN SLIM / Flat-Base strategy into the existing Taiwan surge-analysis (飆股分析) backend. The full design lives in `Docs/research/canslim_oneil_strategy.md` (read it — sections 4 rule table, 6/7/8 score design, 9 observation schema). This is a **phased** build to avoid the prior one-shot failures. Phase A only lays down the skeleton + the single source of truth for all thresholds.

## Hard constraints (apply to every phase)

1. **All thresholds live in YAML** (`backend/data/strategy/canslim_thresholds_v1.yaml`), never hardcoded in `.py`. Top-level `meta: {version: v1, tuning_required: true}`.
2. New code is **additive** — do not touch `/analyze`, `/analyze/tw`, multi-factor-surge, frontend, or existing tests. Existing suite must stay green.
3. No buy/sell/hold verbs anywhere (not relevant yet, but keep in mind).
4. Treat all v1 thresholds as hypotheses requiring later backtest validation.

## Phase A goal

Create the empty package skeleton + the YAML threshold file + a loader + core types. No business logic.

### Files to create

1. `backend/app/services/strategy/__init__.py` (empty) and `backend/app/services/strategy/canslim/__init__.py` (empty).

2. `backend/data/strategy/canslim_thresholds_v1.yaml`
   - Encode **every** threshold from `Docs/research/canslim_oneil_strategy.md` §4 (rules G-1..G-5, T-1..T-5, SD-1..SD-4, I-1..I-4, M-1..M-4, R-1..R-8) plus the Cup-and-Handle geometry: cup depth 12–35%, handle pullback ≤10–15% (upper half), base length ≥7 weeks, handle volume dry-up ≥20%, breakout volume +40–50%; pyramiding 50/30/20 at +0/+2–3/+4–5%; -10% hard stop; liquidity floor 30,000,000 TWD; round-trip cost 0.685%.
   - Group by pillar (`growth:`, `technical:`, `supply:`, `institutional:`, `market:`, `risk:`, `base_geometry:`, `scoring:`, `backtest:`).
   - Top-level `meta: {version: "v1", tuning_required: true}`.

3. `backend/app/services/strategy/canslim/params.py`
   - `load_params(path: str | None = None) -> CanslimParams` — reads the YAML **once** (module-level cache), returns a frozen/immutable structure (frozen dataclass or `types.MappingProxyType`).
   - Default path resolves to the YAML above. No threshold literal may appear in this file except the default path string.

4. `backend/app/services/strategy/canslim/types.py`
   - `RuleResult`: `rule_id: str`, `triggered: bool`, `signal_delta: int = 0`, `risk_delta: int = 0`, `confidence_delta: int = 0`, `reason: str | None = None`, `data_warning: str | None = None`.
   - `HorizonObservation` (per research doc §9): `horizon` (Literal short_term/swing_term/long_term), `status` (Literal neutral/watching/trigger_proximity/invalidating), `direction_hint` (Literal up/down/sideways/unclear), `evidence_based_reasons: list[str]`, `triggered_rule_ids: list[str]`, `suitable_strategy_examples: list[str]`, `key_observation_conditions: list[str]`, `invalidation_signals: list[str]`, `risk_level` (Literal low/moderate/elevated/high), `confidence_level` (Literal low/moderate/high), `scores: dict`, `data_warnings: list[str]`.
   - Use dataclasses or Pydantic v2 (this repo uses Pydantic v2 — prefer it for `HorizonObservation`, plain dataclass fine for `RuleResult`).

### Tests to create (`backend/tests/strategy/canslim/test_phase_a_scaffold.py`)

1. `test_yaml_loads_and_has_meta` — YAML parses, `meta.version == "v1"`, `meta.tuning_required is True`.
2. `test_params_loader_returns_pillars` — `load_params()` returns all expected pillar keys; second call returns cached (same object id).
3. `test_types_instantiate` — `RuleResult(...)` and `HorizonObservation(...)` build with valid args; Literal fields reject invalid values.

Add `backend/tests/strategy/__init__.py` and `backend/tests/strategy/canslim/__init__.py` if the test layout needs them.

## Verification (run before declaring done)

```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_a_scaffold.py -q
.venv\Scripts\python -m pytest backend\tests\ -q   # full suite must stay green
```

## STOP

When the above is green, stop and report: files created, threshold count in YAML, test results. Do NOT begin Phase B (feature extractors).
