# Codex Task — CAN SLIM Phase E: Three-score aggregator + S/A/B/C grading

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md`. This phase is where the anti-zero-signal rules matter MOST:
> - This is a **SCORING system, not an AND-gate.** Never require all pillars positive. Partial matches must still produce a graded result.
> - **Map the composite Signal score into S/A/B/C grades** (user's design). A C-grade is still a signal — keep it visible. The ONLY way a name is removed from new-entry consideration is an explicit hard block (R-4 / R-5 short_term / R-6).
> - Hard-block whitelist is fixed: a hard block sets `hard_blocked=True` but the scores are STILL reported (Signal does not cancel Risk, Risk does not cancel Signal — report all three independently).

> **Phase E.** A–D done (119 canslim tests, full suite 463). **Do ONLY Phase E.** No regime assembly (F), no observer (G). Stop when E tests green.

## Build — `backend/app/services/strategy/canslim/aggregator.py`

Pure function over rule results, **per horizon** (horizon pipelines stay separate):
```python
def aggregate(
    rule_results: list[RuleResult],   # already filtered to this horizon's applicable rules
    base: BasePattern,
    horizon: str,
    params,
) -> AggregateResult: ...
```

### `AggregateResult` (Pydantic v2 frozen)
`horizon`, `signal_score: int` (0–100), `risk_score: int` (0–100), `confidence_score: int` (0–100), `grade: Literal["S","A","B","C"]`, `hard_blocked: bool`, `blocking_rule_ids: list[str]`, `low_confidence: bool`, `triggered_rule_ids: list[str]`, `pillar_breakdown: dict[str,int]`, `data_warnings: list[str]`.

### Signal score — sum `signal_delta` per pillar, cap at YAML `scoring.signal.pillar_caps`
Pillar membership: growth_quality = G-1..G-5; technical_leadership = T-1,T-3; breakout_catalyst = T-2,T-4,T-5 **plus** base pattern (map `base.quality_score`: add `round(quality_score/100 * remaining_breakout_cap)` contribution, then cap pillar at 20); supply_demand = SD-1,SD-2; institutional = I-1,I-2,I-3. Sum capped pillars → signal_score (≤100).

### Risk score — sum `risk_delta` per component, cap at YAML `scoring.risk.components`
market_regime = M-1,R-5; institutional_reversal = R-3; technical_overheat = R-1,R-2; event_window = R-4; daytrade_divergence = SD-3,R-7; valuation_mismatch = R-8. Sum capped components → risk_score.

### Confidence — YAML `scoring.confidence`
baseline 50; `+complete_data_bonus_each` (10) and `−missing_data_penalty_each` (10) applied from the sum of `confidence_delta` across rule results (use the deltas the rules already returned); `hard_block_penalty` (−20) once if any hard block active; clamp [0,100]; `low_confidence = score < low_confidence_below` (40).

### Hard block
`hard_blocked = any(r.hard_block for r in rule_results)`; `blocking_rule_ids` = their rule_ids. **Scores are still computed and reported** — hard_block does not zero signal/confidence.

### S/A/B/C grade — add a NEW `scoring.grades` block to the YAML (mark `tunable: true`)
```yaml
scoring:
  grades:
    tunable: true
    S_signal_min: 75
    A_signal_min: 55
    B_signal_min: 35
    C_signal_min: 0      # everything else is still C, never discarded
```
`grade` = highest band whose `_signal_min` the signal_score meets. Even signal_score 0 → grade "C" (still surfaced). hard_blocked does NOT change the grade — it's reported separately so the consumer sees both "grade B" and "blocked for new entry".

## Tests — `backend/tests/strategy/canslim/test_phase_e_aggregator.py` (≥6)
1. Pillar caps enforced (oversized deltas clamp to cap).
2. Hard-block present → `hard_blocked True`, blocking_rule_ids correct, **signal_score still > 0** (independence).
3. Confidence floor/ceiling + low_confidence flag.
4. Grade banding S/A/B/C from signal_score (read thresholds from params).
5. **Anti-zero-signal:** a partial match (only 2–3 rules triggered, no hard block) still yields a non-"none" result with grade C/B and signal_score > 0.
6. Base pattern quality_score contributes to breakout_catalyst pillar (graded).
Build `RuleResult`/`BasePattern` lists directly; read expected numbers from `load_params()`.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_e_aggregator.py -q
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
When green, report AggregateResult shape, the YAML `scoring.grades` addition, and test results. Do NOT start Phase F.
