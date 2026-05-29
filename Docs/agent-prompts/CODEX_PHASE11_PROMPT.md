# Codex Handoff — Phase 11: Tiered Entry System

**Repo**: `c:\Users\09068\OneDrive\文件\GitHub\ai-stock` (Windows / PowerShell)
**Python**: `.venv\Scripts\python.exe`
**Date assigned**: 2026-05-19

---

## 0. TL;DR — What you need to do

The current backtest produces **0 validation trades** in most random parameter samples because **16 hard gates AND'd together** is too restrictive. Implement a **3-tier entry classification** so signals are graded by quality (CORE / QUALITY / PREMIUM) with corresponding position-size multipliers. This expands signal count 10-30× while preserving high-conviction edge via position sizing.

Full design: **READ FIRST** → [`../../artifacts/research/phase11_tiered_entry_design.md`](../../artifacts/research/phase11_tiered_entry_design.md)

After reading the design doc, implement it. Estimated 7 hours of focused work.

---

## 1. Mandatory pre-reading (in order, ~30 min total)

| Order | File | Time | Purpose |
|---|---|---|---|
| 1 | `../../artifacts/research/phase11_tiered_entry_design.md` | 15 min | **The design you're implementing** |
| 2 | `../../artifacts/research/phase9_7_corrected_strategy_framework.md` | 5 min | Strategy thesis = O'Neil Flat Base |
| 3 | `../../artifacts/research/phase9_8_flat_base_quant_spec.md` | 5 min | Current implementation spec |
| 4 | `../../artifacts/research/phase10_codex_improvements.md` | 5 min | Your own previous work (adaptive sampler) |
| 5 | `backend/app/services/screener_service.py` lines 854-1500 | scan | Where you'll add `_compute_entry_tier` |
| 6 | `backend/app/services/backtest/signal_replay.py` | scan | Schema + persist tier |
| 7 | `backend/app/services/backtest/trade_simulator.py` | scan | Position multiplier application |

---

## 2. Strategy context (60 seconds)

User's discretionary strategy = **O'Neil "Flat Base" breakout** (1988 IBD pattern):

> "前期主力表態 (10-30% rally over ~2 months) → 縮量盤整 (~1 month sideways, volume dry-up) → EMA 5/10/20 收斂後微翹 → 突破箱型上緣當日進場"

Applied to **53 Taiwan AI tech stocks** (6 sub-sectors: IC設計 / foundry / packaging / components / system / cloud-software).

Universe file: `backend/data/sectors/ai_tech_tw.json`.

**Critical invariants** (cannot be relaxed by any code change):
- 90-day range must stay in [10%, 30%]
- Volume contraction during base must require contraction (`ratio ≤ 1.0`)
- EMA spread cannot exceed 0.08
- EMA transition score min ≥ 30 (`allowed_bounds.yaml` enforces this on Claude responses)

---

## 3. Implementation Plan

### 3.1 Add `_compute_entry_tier()` to `screener_service.py`

Insert immediately before `_classify_candidate` (around line 730):

```python
def _compute_entry_tier(
    features: dict[str, Any],
    rules: dict[str, Any],
    risk_score: int,
) -> int:
    """Phase 11: Tier 0=no entry, 1=CORE, 2=QUALITY, 3=PREMIUM.

    Tier 1 (CORE): Basic Flat Base structure passed — small position
    Tier 2 (QUALITY): + EMA convergence + base depth + decent score — standard position
    Tier 3 (PREMIUM): + 1.5× volume + high scores + Trend Template — full conviction position

    Features dict comes from `_compute_base_features` (Phase 9.8). The pre_breakout_score
    and other score fields are passed via the features dict to avoid recomputation.
    """
    pp = rules.get("price_position", {})
    cls = rules.get("classification", {})

    # ── Tier 1 hard gates (CORE structure) ──────────────────────────────
    r90 = features["range_90d"]
    if not (
        float(pp.get("pre_breakout_range_90d_min", 0.10))
        <= r90
        <= float(pp.get("pre_breakout_range_90d_max", 0.30))
    ):
        return 0
    if features["volume_contraction_ratio"] > 1.0:
        return 0
    # Breakout event: close > base_high × 1.001
    breakout_buffer = float(cls.get("breakout_pivot_buffer", 0.001))
    if features["close_today"] <= features["base_high"] * (1.0 + breakout_buffer):
        return 0
    # Not extended beyond buy zone
    if features["close_to_base_high_ratio"] > 1.08:
        return 0
    # Liquidity
    if features["avg_turnover_20"] < 30_000_000:
        return 0
    # Not in deep bear (return_90d cushion)
    if features["return_90d"] < -0.25:
        return 0

    tier = 1   # Tier 1 passed

    # ── Tier 2 quality filters ──────────────────────────────────────────
    tier2_pass = (
        features["ema_spread"] <= 0.05
        and features["ema5_slope"] >= 0
        and features["ema10_slope"] >= 0
        and features["ema20_slope"] >= 0
        and features["base_range_pct"] <= 0.15
        and features["volume_today_shares"] >= features["avg_volume_50_shares"] * 1.2
        and features.get("pre_breakout_score", 0) >= 50
        and risk_score < 70
    )
    if tier2_pass:
        tier = 2

    # ── Tier 3 premium filters ──────────────────────────────────────────
    if tier == 2:
        tier3_pass = (
            features["volume_today_shares"] >= features["avg_volume_50_shares"] * 1.5
            and features.get("pre_breakout_score", 0) >= 60
            and features.get("ema_micro_upturn_score", 0) >= 60
            and features.get("base_compression_score", 0) >= 60
            and features.get("ema_down_to_up_transition_score", 0) >= 50
            and features["avg_turnover_20"] >= 100_000_000
            and features.get("trend_template_ok", False)
        )
        if tier3_pass:
            tier = 3

    return tier
```

**Important**: `pre_breakout_score`, `ema_micro_upturn_score`, `base_compression_score`, `ema_down_to_up_transition_score` are NOT currently in the features dict returned by `_compute_base_features`. You have two options:

**Option A (recommended)**: After scores are computed in `evaluate_surge_candidate`, stuff them into the features dict before calling `_compute_entry_tier`:
```python
# In evaluate_surge_candidate, after scores/pre_breakout_score are computed:
features_with_scores = {
    **features,
    "pre_breakout_score": pre_breakout_score,
    "ema_micro_upturn_score": ema_micro_upturn_score,
    "base_compression_score": scores.base_compression_score,
    "ema_down_to_up_transition_score": ema_down_to_up_transition_score,
}
entry_tier = _compute_entry_tier(features_with_scores, rules, risk_score)
```

**Option B**: Pass scores as separate args to `_compute_entry_tier`. Less clean but more explicit.

Pick whichever you prefer, but document choice in your phase11 report.

### 3.2 Add EMA50/150/200 + Trend Template to `_compute_base_features`

In `screener_service.py`, inside `_compute_base_features` after EMA5/10/20 computation:

```python
# Phase 11: Trend Template (Minervini SEPA / Weinstein Stage 2) — premium tier gate
trend_template_ok = False
if len(normalized) >= 200:
    ema50_series = _ema(normalized["close"], 50)
    ema150_series = _ema(normalized["close"], 150)
    ema200_series = _ema(normalized["close"], 200)
    ema50_last = float(ema50_series.iloc[-1])
    ema150_last = float(ema150_series.iloc[-1])
    ema200_last = float(ema200_series.iloc[-1])
    # Classic Trend Template: close > EMA50 > EMA150 > EMA200 AND EMA200 trending up
    ema200_30bars_ago = float(ema200_series.iloc[-30]) if len(ema200_series) > 30 else ema200_last
    trend_template_ok = (
        close_today > ema50_last
        and ema50_last > ema150_last
        and ema150_last > ema200_last
        and ema200_last > ema200_30bars_ago   # EMA200 trending up over last 30 bars
    )
```

Add `trend_template_ok` to the returned features dict.

**CRITICAL**: Trend Template needs 200+ bars of history. Current `lookback_bars=150` in `signal_replay.ReplayConfig`. Update default to `220` so EMA200 can compute. Add fallback: if `len(normalized) < 200`, `trend_template_ok=False` (treats as "premium tier unavailable").

### 3.3 Modify `evaluate_surge_candidate` to compute and return tier

Add after existing classification logic:

```python
# Phase 11: Compute entry tier (0/1/2/3)
features_with_scores = {
    **(precomputed_features or features),  # use precomputed if provided
    "pre_breakout_score": pre_breakout_score,
    "ema_micro_upturn_score": ema_micro_upturn_score,
    "base_compression_score": scores.base_compression_score,
    "ema_down_to_up_transition_score": ema_down_to_up_transition_score,
}
entry_tier = _compute_entry_tier(features_with_scores, rules, risk_score)
```

Store `entry_tier` in `CandidateMetrics` — you'll need to add it as a new field:

```python
# In backend/app/models/screener_schemas.py — CandidateMetrics class:
class CandidateMetrics(BaseModel):
    # ... existing fields ...
    entry_tier: int = 0  # Phase 11: 0=no entry, 1=CORE, 2=QUALITY, 3=PREMIUM
```

⚠️ **DO NOT change production behavior**: `entry_tier` defaults to 0 so any existing code paths that don't set it still work.

### 3.4 Add `entry_tier` column to `backtest_signals` schema

In `signal_replay.py`:

```python
# In _SCHEMA_SQL:
CREATE TABLE IF NOT EXISTS backtest_signals (
    ... existing columns ...
    entry_tier INTEGER DEFAULT 0,
    ...
);

# In _migrate_signals_schema:
for col, typ in (
    ("base_high", "REAL"),
    ("base_low", "REAL"),
    ("avg_volume_50", "REAL"),
    ("entry_tier", "INTEGER DEFAULT 0"),  # Phase 11
):
    ...
```

In `replay_signals` where rows_to_persist is built, add:
```python
"entry_tier": result.metrics.entry_tier,
```

Update INSERT SQL and the row dict construction.

### 3.5 Modify `trade_simulator.py` for position sizing by tier

```python
@dataclass
class TradeRules:
    # ... existing fields ...
    # Phase 11: position multiplier by entry_tier
    tier_position_multipliers: dict[int, float] = field(
        default_factory=lambda: {1: 0.5, 2: 1.0, 3: 1.5}
    )
    min_entry_tier: int = 1  # Filter: only enter if tier >= this (0 = accept all incl. legacy)
```

In `simulate_trades`:

```python
for _, sig in signals_df.iterrows():
    # Phase 11: filter by min_entry_tier
    sig_tier = int(sig.get("entry_tier", 0) or 0)
    if sig_tier > 0 and sig_tier < rules.min_entry_tier:
        skipped += 1
        trades.append(_skip_record(run_id, next_trade_id, stock_id, signal_date,
                                    EntryStatus.SKIPPED_TIER_LOW, sig))
        next_trade_id += 1
        continue
    # ... existing entry logic ...

    # Phase 11: scale gross_return by tier multiplier
    pos_mult = rules.tier_position_multipliers.get(sig_tier, 1.0) if sig_tier > 0 else 1.0
    effective_gross = gross_return * pos_mult
    net_return = effective_gross - rules.commission_pct * 2 - rules.transaction_tax_pct

    trades.append({
        ... existing fields ...
        "entry_tier": sig_tier,
        "position_multiplier": pos_mult,
        ...
    })
```

Add new `EntryStatus.SKIPPED_TIER_LOW = "skipped_tier_below_min"`.

Add columns `entry_tier` + `position_multiplier` to `backtest_trades` schema (migrate idempotently).

### 3.6 CLI exposure in `auto_optimize.py`

```python
parser.add_argument(
    "--min-entry-tier", type=int, default=1, choices=[1, 2, 3],
    help="Phase 11: minimum entry tier to accept (1=CORE, 2=QUALITY, 3=PREMIUM). Lower = more signals."
)
```

Wire into `LoopConfig`:
```python
@dataclass
class LoopConfig:
    # ... existing ...
    min_entry_tier: int = 1  # Phase 11
```

Pass through to `OptimizerConfig`, then to TradeRules creation in `optimizer.py`:
```python
trade_rules = TradeRules(
    # ... existing ...
    min_entry_tier=config.min_entry_tier,
)
```

### 3.7 Add `trade_rules.min_entry_tier` to search space (optional)

In `optimizer_search_space.yaml`:
```yaml
trade_rules.min_entry_tier: [1, 2]
```

This lets the optimizer try both "accept Tier 1+" and "Tier 2+ only" within the same run.

Update `allowed_bounds.yaml`:
```yaml
parameter_mapping:
  min_entry_tier: trade_rules.min_entry_tier

allowed_bounds:
  min_entry_tier: [1, 3]
```

### 3.8 Update `_split_trade_rules_overrides` in `optimizer.py`

```python
effective = TradeRules(
    ... existing ...
    min_entry_tier=int(tr_overrides.get("min_entry_tier", base_trade_rules.min_entry_tier)),
    tier_position_multipliers=base_trade_rules.tier_position_multipliers,
    ...
)
```

---

## 4. Tests to add (6 new tests, target ~30 min each)

Create `backend/tests/test_entry_tier.py`:

1. **`test_entry_tier_zero_when_basic_gates_fail`** — range_90d outside [0.10, 0.30] → return 0
2. **`test_entry_tier_one_for_basic_breakout`** — synthetic OHLCV passing only CORE conditions → return 1
3. **`test_entry_tier_two_with_quality_filters`** — CORE + EMA convergence + scores → return 2
4. **`test_entry_tier_three_premium`** — CORE + QUALITY + 1.5× vol + Trend Template → return 3
5. **`test_trend_template_ok_requires_200_bars`** — short history → trend_template_ok=False
6. **`test_tier_position_multiplier_in_simulator`** — verify trade.net_return reflects multiplier 0.5/1.0/1.5

Create `backend/tests/test_phase11_e2e.py`:

7. **`test_min_entry_tier_filter_skips_low_tier`** — set `min_entry_tier=2`, verify Tier 1 signals are skipped in trade_simulator

8. **`test_phase11_integration_smoke`** — small E2E: 3 trials × 1-year window → verify signal_replay writes `entry_tier` column, trade_simulator filters correctly, no point-in-time leaks

---

## 5. Verification commands

```powershell
# After each major step, run targeted tests
.venv\Scripts\python.exe -m pytest backend/tests/test_entry_tier.py -q
.venv\Scripts\python.exe -m pytest backend/tests/test_phase11_e2e.py -q

# Full regression — MUST pass before declaring done (target: 117+ tests)
.venv\Scripts\python.exe -m pytest backend/tests/ -q --ignore=backend/tests/test_external_news.py --ignore=backend/tests/test_synthesis_agent.py --ignore=backend/tests/test_technical_agent.py

# Smoke test the actual integration (should produce > 0 trades)
.venv\Scripts\python.exe -m backend.scripts.auto_optimize --target all --max-iterations 2 --trials-per-iter 10 --workers 2 --min-entry-tier 1 --start 2024-01-01 --end 2025-12-31 --output-dir artifacts/phase11_smoke --auto-dir artifacts/phase11_smoke/auto

# Verify: artifacts/phase11_smoke/iter_01/optimization_runs.csv should show val_n > 10 in most trials
```

---

## 6. Constraints (DO NOT BREAK)

| Constraint | Why |
|---|---|
| **All existing tests must pass** (111+ in optimizer/auto_optimize/screener/backtest/feature_cache) | Regression suite |
| **Production `/analyze` endpoint behavior MUST be unchanged** when no `precomputed_features` is provided AND no tier-aware code path is triggered | Production uses `evaluate_surge_candidate` too |
| **Point-in-time invariant**: `_compute_entry_tier` MUST only use features from `_compute_base_features` (which is already PIT-safe) | Look-ahead bias is the #1 enemy |
| **Don't change core invariants** in `allowed_bounds.yaml` | Strategy identity locks |
| **`entry_tier=0` is the safe default** for all backwards-compat paths | Old data without tier column should still work |
| **Lookback_bars change 150 → 220** is required for Trend Template (EMA200), but verify older tests still work since `_compute_base_features` handles `< 200` gracefully (sets trend_template_ok=False) | EMA200 needs warmup |
| **Don't modify the existing `evaluate_surge_candidate` signature** | Other code paths may call it |

---

## 7. Success criteria

After your implementation:

1. ✅ **All existing tests pass** (no regressions) — currently 111 in core subset; should be ≥111 still
2. ✅ **6+ new tests pass** (entry_tier behavior + e2e)
3. ✅ **Smoke test produces signals**: running the example command in Section 5 should yield `val_n ≥ 10` in most trials (vs current ~0-5)
4. ✅ **No production regression**: existing `/tw/analyze` endpoint output is byte-identical for the same inputs (verify with one targeted test)
5. ✅ **Document changes** in `artifacts/research/phase11_codex_implementation.md` including:
   - What you implemented (file-by-file diff summary)
   - Smoke test before/after numbers
   - Any deviations from the design doc (with rationale)
   - Performance impact (per-trial wall time)
6. ✅ **Update `artifacts/research/INDEX.md`** to add Phase 11 entry

---

## 8. Recommended implementation order

1. **Read the design doc** (`phase11_tiered_entry_design.md`) — 15 min
2. Add `_compute_entry_tier` function + unit tests for tier logic (tests 1-4) — 1.5 hr
3. Add EMA50/150/200 + Trend Template in `_compute_base_features` + test 5 — 1 hr
4. Add `entry_tier` to `CandidateMetrics` schema + integrate in `evaluate_surge_candidate` — 30 min
5. Add `entry_tier` column to `backtest_signals` + persist — 30 min
6. Modify `trade_simulator` for position multiplier + tier filter + test 6 — 1 hr
7. Wire CLI flag + LoopConfig + OptimizerConfig — 30 min
8. Integration smoke test (test 7) + run actual auto_optimize smoke — 1 hr
9. Write `phase11_codex_implementation.md` + update INDEX — 30 min

**Total: ~6.5-7 hours**

---

## 9. Anti-patterns (avoid these)

- ❌ **Don't change `_compute_base_features` signature** — only ADD new keys to the returned dict
- ❌ **Don't move score computations into `_compute_entry_tier`** — they belong in `evaluate_surge_candidate` and can't be cached
- ❌ **Don't bypass `core_invariants` checking** — the Tier 1 gates RESPECT them (range 10-30%, vol contraction ≤ 1.0)
- ❌ **Don't make tier computation a slow path** — it's pure Python comparisons, should be < 0.1 ms per call
- ❌ **Don't break the equivalence test** `test_cached_features_match_uncached` in `test_feature_cache.py`
- ❌ **Don't add Optuna or other heavy dependencies** — Phase 10 already has the sampler infrastructure
- ❌ **Don't change `pre_breakout_score_min` defaults in `rules_v1.yaml`** — Phase 11 is additive; the existing classification path stays valid

---

## 10. Key facts to remember

- **Universe**: 53 stocks in `backend/data/sectors/ai_tech_tw.json`
- **Date range**: 2022-11-01 to 2026-05-15 by default
- **Train/val split**: chronological 70/30
- **Current speedups**: parallel workers, OHLCV cache, feature cache, fast-fail filter, cross-iter pool
- **Hard-reject in objective**: `val.n_trades < 3` → -2000.0 (don't change this)
- **Composite objective formula**: in `optimizer.py:OBJECTIVE_FORMULA` constant
- **Phase 10 adaptive sampler**: `optimizer.py:_run_adaptive_trials()` — already integrated, default sampler
- **Anthropic API**: Claude Opus 4.7 via `llm_search_space_advisor.py`. ANTHROPIC_API_KEY in `.env`
- **Test fixtures**: `make_candidate_df` in `test_screener.py` is your friend for synthetic OHLCV
- **`_FEATURE_CACHE`**: in `signal_replay.py`, keyed by `(shape_hash, stock_id, as_of_date)`. Don't pollute its namespace

---

## 11. Output format for your phase11_codex_implementation.md

```markdown
# Phase 11 — Codex Implementation Report
**Date**: 2026-05-XX

## Summary
- What was added: ...
- Files changed: ...
- New tests: ...

## Design decisions / deviations
- (anything you did differently from the spec, with rationale)

## Smoke test results

### Before Phase 11
- Command: ...
- val_n distribution: ...
- 0-trade rate: ...

### After Phase 11
- Command: ... (same as above + --min-entry-tier 1)
- val_n distribution: ...
- 0-trade rate: ...

## Performance impact
- Per-trial wall time before: X sec
- Per-trial wall time after: Y sec
- (per-trial slowdown / speedup explanation)

## Tier distribution (from a representative run)
- Tier 1 signals: X (~Y% of all)
- Tier 2 signals: ...
- Tier 3 signals: ...

## Outstanding work / known limitations
- ...
```

---

## 12. Final note

The user has explicitly stated they want **tiered trading** because requiring all conditions at once is unrealistic. This matches:
- **William O'Neil**'s A/B/C base rating in CANSLIM
- **Mark Minervini**'s position-sizing by setup conviction
- **Kelly criterion** fractional sizing (Quarter/Half/Full)

Your job is to implement this cleanly without breaking the existing strategy semantics. **Tier 2 ≈ current Phase 9.8 strict classification**, so users who want the "old behavior" can run `--min-entry-tier 2` and get essentially the same results as before. Phase 11 just adds Tier 1 (loosen) and Tier 3 (tighten + premium gates) as additional options.

**Make it work, make it tested, make it documented. Don't over-engineer.**

Good luck. — Claude Code (Phase 9-10 builder)
