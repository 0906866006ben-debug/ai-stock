# Codex Handoff — Phase 12: Optimization System v2 (Greenfield Rewrite)

**Repo**: `c:\Users\09068\OneDrive\文件\GitHub\ai-stock` (Windows / PowerShell)
**Python**: `.venv\Scripts\python.exe`
**Tests**: `.venv\Scripts\python.exe -m pytest backend/tests/ -q` (currently 131+ passing)
**Date assigned**: 2026-05-20

---

## 0. TL;DR — Your Mission

After 4 phases of patches (9, 10, 11, 11.1) the existing optimizer has accumulated technical debt. **Rewrite the optimization system as a clean `v2/` package** alongside the existing code (don't delete the old). The new system must:

1. Use **4-tier S/A/B/C entry classification** (replacing Phase 11's int 1/2/3 tiers)
2. Implement **walk-forward analysis** (5 rolling windows by default)
3. Use a **modular sampler** (RandomSampler, AdaptiveSampler, OptunaSampler — pick at CLI)
4. Output a **Pareto front** for multi-objective trade-off transparency
5. Model **TW daily price limits** (±10% can't fill stop on gap day)
6. Be testable in isolation (each component a pure function or single-responsibility class)
7. **Coexist with v1**: old `auto_optimize.py` still works; new `auto_optimize_v2.py` is opt-in

**Full design**: READ FIRST → [`../../artifacts/research/phase12_optimization_v2_design.md`](../../artifacts/research/phase12_optimization_v2_design.md) (~10 min read, has everything you need)

Estimated work: **~24 focused hours**, broken into 11 sub-phases (Section 7 of design doc).

---

## 1. Mandatory pre-reading (45 min total)

| # | File | Time | Purpose |
|---|---|---|---|
| 1 | `../../artifacts/research/phase12_optimization_v2_design.md` | 15 min | **THE design you're implementing** |
| 2 | `../../artifacts/research/phase9_7_corrected_strategy_framework.md` | 10 min | Strategy thesis = O'Neil Flat Base |
| 3 | `../../artifacts/research/phase11_tiered_entry_design.md` | 5 min | Phase 11 tier design (your starting point for v2 tiers) |
| 4 | `../../artifacts/research/phase10_codex_improvements.md` | 5 min | Phase 10 adaptive sampler (reuse for v2) |
| 5 | `../../backend/app/services/backtest/v1/optimizer.py` | 10 min | v1 code |

---

## 2. Strategy Context (90 seconds)

User's strategy = **O'Neil "Flat Base" breakout** (1988 IBD pattern) applied to 53 Taiwan AI tech stocks.

**Discretionary thesis** (user's words):
> 前期主力表態 (10-30% rally over ~2 months) → 縮量盤整 (~1 month sideways) → EMA 5/10/20 收斂後微翹 → 突破箱型上緣當日進場

**Universe**: 53 stocks across 6 sub-sectors (`backend/data/sectors/ai_tech_tw.json`).

**Critical invariants** (cannot be relaxed):
- 90-day range must stay in [10%, 30%]
- Volume contraction during base ≤ 1.0 (must contract)
- EMA spread cannot exceed 0.08
- EMA transition score min ≥ 30 (enforced in `allowed_bounds.yaml`)

---

## 3. v2 File Structure (NEW code only — don't modify v1 unless to move)

```
backend/app/services/backtest/
├── v1/                              ← Move existing files here (just file moves, no logic changes)
│   ├── __init__.py                  ← Re-export from v1 for backward compat
│   ├── optimizer.py
│   ├── optimization_loop.py
│   ├── optimization_summary.py
│   ├── llm_search_space_advisor.py
│   ├── search_space_validator.py
│   ├── allowed_bounds.yaml
│   └── optimizer_search_space.yaml
├── v2/                              ← NEW (your work)
│   ├── __init__.py
│   ├── tier_classifier.py           ← S/A/B/C cascading tier
│   ├── sampler.py                   ← RandomSampler / AdaptiveSampler / OptunaSampler
│   ├── walk_forward.py              ← 5-window rolling splits
│   ├── evaluator.py                 ← Pure function: (params, splits) → metrics
│   ├── pareto.py                    ← Non-dominated trial filtering
│   ├── objective.py                 ← Multi-component + composite + WFE
│   ├── persistence.py               ← Feature cache + disk pickle
│   ├── loop.py                      ← Main orchestration
│   ├── config.py                    ← LoopConfigV2 dataclass
│   └── tier_thresholds.yaml         ← Configurable per-tier thresholds
├── historical_data_store.py         ← Shared (unchanged)
├── signal_replay.py                 ← Shared but extract `_compute_base_features` to make pure
└── trade_simulator.py               ← Shared but add v2 wrapper for TW price limits

backend/scripts/
├── auto_optimize.py                 ← v1 entry (unchanged)
└── auto_optimize_v2.py              ← NEW v2 entry

backend/tests/
├── test_v2_tier_classifier.py       ← NEW (~10 tests)
├── test_v2_walk_forward.py          ← NEW (~6 tests)
├── test_v2_sampler.py               ← NEW (~8 tests)
├── test_v2_evaluator.py             ← NEW (~6 tests)
├── test_v2_pareto.py                ← NEW (~5 tests)
├── test_v2_e2e.py                   ← NEW (~3 tests)
└── ... (existing 131 tests stay GREEN)

artifacts/research/
└── phase12_codex_implementation.md  ← YOUR final report
```

---

## 4. Implementation Order (11 sub-phases, run pytest after each)

### Phase 12.1: Reorganize v1 (1 hr)

1. Create `backend/app/services/backtest/v1/` directory + `__init__.py`
2. **Move** (don't copy) these files into `v1/`:
   - `optimizer.py`
   - `optimization_loop.py`
   - `optimization_summary.py`
   - `llm_search_space_advisor.py`
   - `search_space_validator.py`
   - `allowed_bounds.yaml`
   - `optimizer_search_space.yaml`
3. Update **all** imports in the codebase to reference `v1` path:
   - `from backend.app.services.backtest.optimizer import ...` → `from backend.app.services.backtest.v1.optimizer import ...`
   - Or: `v1/__init__.py` re-exports everything → keep existing imports working
4. Run `pytest backend/tests/ -q` — **all 131 tests must still pass**

### Phase 12.2: Tier Classifier (`v2/tier_classifier.py`) (2 hr)

```python
from enum import IntEnum

class EntryTier(IntEnum):
    NONE = 0
    C = 1   # 基本 Core
    B = 2   # 合格 Quality
    A = 3   # 優質 Strong
    S = 4   # 頂級 Premium

# tier_thresholds.yaml format:
# tiers:
#   C:
#     range_90d_min: 0.10
#     range_90d_max: 0.30
#     ema_spread_max: 0.08
#     ...
#   B: { ... extends C ... }
#   A: { ... extends B ... }
#   S: { ... extends A ... }
# position_multipliers:
#   C: 0.3
#   B: 0.7
#   A: 1.0
#   S: 1.5

def classify_tier(features: dict, scores: dict, risk_score: int,
                   thresholds: dict) -> EntryTier:
    """Cascading classification. Returns highest tier where ALL conditions pass.
    
    Implementation: start at S, check all conditions; if fail any, drop to A;
    if fail A's, drop to B; etc. Return NONE if even C fails.
    """

def position_multiplier(tier: EntryTier, multipliers: dict) -> float:
    """Position size = multipliers[tier_name]. Defaults: C=0.3, B=0.7, A=1.0, S=1.5."""
```

**Conditions per tier**: See Section 5 of `../../artifacts/research/phase12_optimization_v2_design.md` (25 total conditions across 4 tiers).

**Tests** (`test_v2_tier_classifier.py`):
1. `test_tier_none_when_basic_invariant_fails`
2. `test_tier_c_basic_flat_base_passes`
3. `test_tier_b_with_ema_convergence`
4. `test_tier_a_with_volume_confirmation`
5. `test_tier_s_full_premium_with_trend_template`
6. `test_cascading_demotes_on_failed_condition` (S conditions pass except one → still A)
7. `test_position_multiplier_returns_correct_value`
8. `test_tier_thresholds_loaded_from_yaml`
9. `test_int_enum_comparison_works` (S > A > B > C)
10. `test_legacy_int_input_compat` (`min_entry_tier=2` ≡ B)

### Phase 12.3: Walk-Forward (`v2/walk_forward.py`) (1.5 hr)

```python
@dataclass
class Split:
    name: str        # e.g. "win_2_train", "win_2_test"
    start_date: str  # YYYY-MM-DD inclusive
    end_date: str    # YYYY-MM-DD inclusive
    is_test: bool    # True if this is OOS test segment

def make_walk_forward_splits(
    start: str,
    end: str,
    n_windows: int = 5,
    train_ratio: float = 0.8,   # 80% train, 20% test PER WINDOW
    step_size: Optional[int] = None,  # default: shift by test window length
) -> list[Split]:
    """Generate rolling train/test windows.
    
    For start=2022-11-01, end=2026-05-15 (3.5 yr), n_windows=5, train_ratio=0.8:
      Each window covers (total_days / n_windows) ≈ 256 days = ~12 months
      train = 80% = ~205 days, test = ~51 days
      Window 0: [2022-11-01, train: ..., test: ...]
      ...
    """
```

**Tests** (`test_v2_walk_forward.py`):
1. `test_5_windows_no_overlap`
2. `test_train_ratio_respected`
3. `test_chronological_order_preserved`
4. `test_no_lookahead_in_test_window` (test_start > train_end)
5. `test_single_window_equivalent_to_legacy_70_30`
6. `test_total_coverage_matches_input_range`

### Phase 12.4: Sampler (`v2/sampler.py`) (3 hr)

```python
class Sampler(Protocol):
    def sample(self, n: int) -> list[dict]: ...
    def update(self, params: dict, result: TrialResult) -> None: ...
    def reset(self) -> None: ...

class RandomSampler:
    """Uniform random from search space."""

class AdaptiveSampler:
    """TPE-style: weight values by elite trial frequency.
    Reuse logic from Phase 10's `_run_adaptive_trials` and
    `build_adaptive_value_weights` in v1/optimizer.py."""

class OptunaSampler:
    """Real TPE via Optuna. Optional dep:
        try: import optuna; OPTUNA_AVAILABLE = True
        except ImportError: OPTUNA_AVAILABLE = False
    If not available, fall back to AdaptiveSampler with a warning log."""

def build_sampler(method: str = "adaptive",
                  search_space: dict = None) -> Sampler:
    if method == "optuna":
        if not OPTUNA_AVAILABLE:
            logger.warning("optuna not installed; falling back to adaptive")
            method = "adaptive"
    ...
```

**Tests** (`test_v2_sampler.py`):
1. `test_random_sampler_covers_all_dims`
2. `test_random_sampler_no_duplicates_in_dense_space`
3. `test_adaptive_sampler_learns_from_elites`
4. `test_adaptive_sampler_explore_exploit_balance`
5. `test_optuna_sampler_falls_back_when_unavailable`
6. `test_sampler_protocol_interface`
7. `test_sampler_reset_clears_history`
8. `test_unique_sampling_avoids_duplicates`

### Phase 12.5: Evaluator (`v2/evaluator.py`) (3 hr)

```python
@dataclass
class TrialMetrics:
    n_trades: int
    win_rate: float
    avg_return_pct: float
    profit_factor: float
    max_drawdown: float
    sharpe: float
    sortino: float
    tier_distribution: dict[int, int]  # {S:5, A:12, B:28, C:50}
    avg_position_multiplier: float

def evaluate(
    params: dict,
    splits: list[Split],
    *,
    universe: list[str],
    data_store_factory,  # callable returning HistoricalDataStore
    rules: dict,
    tier_thresholds: dict,
) -> dict[str, TrialMetrics]:
    """Pure function. Returns {split_name: TrialMetrics}.
    
    Internally:
      For each split:
        1. Run signal_replay over split.start ~ split.end
        2. For each signal, classify_tier → assign tier
        3. Filter by min_entry_tier
        4. Run trade_simulator with tier-aware position sizing
        5. Compute TrialMetrics
    """
```

**Tests** (`test_v2_evaluator.py`):
1. `test_evaluate_pure_function_no_side_effects`
2. `test_metrics_computed_for_each_split`
3. `test_tier_distribution_in_metrics`
4. `test_sharpe_sortino_calculation`
5. `test_empty_split_returns_zero_metrics`
6. `test_point_in_time_preserved_across_splits`

### Phase 12.6: Pareto (`v2/pareto.py`) (2 hr)

```python
@dataclass
class ObjectiveValue:
    name: str
    value: float
    maximize: bool   # True if higher is better, False if lower

def is_dominated(a: list[ObjectiveValue], b: list[ObjectiveValue]) -> bool:
    """True if b dominates a (b is >= a on all objectives AND > on at least one)."""

def pareto_front(
    trials: list[TrialResult],
    objectives: list[str] = ["net_return", "n_trades", "win_rate"],
    minimize: list[str] = ["max_drawdown"],   # gets sign-flipped
) -> list[TrialResult]:
    """Return non-dominated trials."""

def rank_by_objective(
    trials: list[TrialResult],
    objective: str,
    descending: bool = True,
) -> list[TrialResult]:
    """Sort by single objective."""
```

**Tests** (`test_v2_pareto.py`):
1. `test_pareto_front_includes_best_each_objective`
2. `test_dominated_trial_excluded`
3. `test_minimize_objective_inverted_correctly`
4. `test_single_trial_returns_itself`
5. `test_pareto_excludes_reward_hack_n_1` (high PF but n=1 dominated by n=50 PF=2)

### Phase 12.7: Objective + WFE (`v2/objective.py`) (1.5 hr)

```python
@dataclass
class WalkForwardEfficiency:
    """OOS / IS ratio. WFE > 0.5 = acceptable robustness."""
    train_score: float
    test_score: float
    wfe_ratio: float          # test/train, capped at 2.0

@dataclass
class ObjectiveScore:
    primary: float            # composite for ranking
    components: dict[str, float]  # raw for Pareto
    overfit_penalty: float
    sample_penalty: float
    wfe: WalkForwardEfficiency

def compute_objective(
    train_metrics_per_window: list[TrialMetrics],
    test_metrics_per_window: list[TrialMetrics],
    weights: dict[str, float] = None,
) -> ObjectiveScore:
    """Aggregate across walk-forward windows.
    
    primary = mean(test_window_scores) - std_penalty - overfit_penalty
    where overfit_penalty = max(0, mean_train - mean_test) * weight
    """
```

### Phase 12.8: Loop + Claude integration (`v2/loop.py`) (3 hr)

```python
@dataclass
class LoopConfigV2:
    target: str
    universe_categories: list[str]
    max_iterations: int
    trials_per_iter: int
    walk_forward_windows: int
    sampler_method: str   # "random" | "adaptive" | "optuna"
    min_entry_tier: EntryTier
    objective_method: str  # "composite" | "pareto"
    ...

def run_optimization_v2(
    *,
    config: LoopConfigV2,
    advisor: Optional[ClaudeAdvisor] = None,
) -> OptimizationResultV2:
    """Main orchestration:
      1. Build walk-forward splits
      2. Initialize sampler + feature cache
      3. For each iter:
         a. sampler.sample(N) → param sets
         b. evaluate(params, splits) → metrics per window
         c. compute aggregated objective + WFE
         d. update sampler with results
         e. compute Pareto front
         f. (optional) Claude advise next search space
      4. Persist outputs:
         - pareto_front.csv (top 20 trials)
         - best_by_objective.yaml (best for each obj)
         - global_best.yaml + global_best.json
         - all_iterations_summary.csv
    """
```

### Phase 12.9: CLI (`auto_optimize_v2.py`) (1.5 hr)

```python
# Mirror v1's auto_optimize.py CLI flags + add new ones:
parser.add_argument("--walk-forward-windows", type=int, default=5)
parser.add_argument("--sampler", choices=["random", "adaptive", "optuna"], default="adaptive")
parser.add_argument("--min-entry-tier", default="C",
                    help="C/B/A/S or 1/2/3/4 (legacy)")
parser.add_argument("--objective-method", choices=["composite", "pareto"], default="pareto")
parser.add_argument("--include-tw-price-limit", action="store_true", default=True,
                    help="Model TW ±10% daily limit in trade simulation")
```

### Phase 12.10: TW Price-Limit + Misc (1 hr)

In `trade_simulator.py` (shared but new logic):

```python
def _adjust_for_tw_price_limit(
    entry_price: float, stop_price: float, target_price: float,
    next_bar: pd.Series,
) -> Tuple[float, str]:
    """If stop would fill below -10% of prev close (limit-down day),
    actual fill is next_day_open instead. May result in worse fill.
    
    Returns (actual_fill_price, exit_reason_suffix)."""
```

### Phase 12.11: E2E Tests + Report (3 hr)

**E2E tests** (`test_v2_e2e.py`):
1. `test_v2_full_pipeline_with_fake_advisor` — small synthetic run
2. `test_v2_pareto_output_includes_diverse_trials`
3. `test_v2_no_regression_vs_v1_single_window_mode`

**Report**: `artifacts/research/phase12_codex_implementation.md` with sections:
- Summary (files changed, lines added/removed)
- Smoke test results (before/after numbers)
- Performance impact (per-trial wall time)
- Walk-forward efficiency metrics observed
- Tier distribution histograms
- Pareto front of representative run
- Open questions / known limitations

---

## 5. Constraints (DO NOT BREAK)

| Constraint | Why |
|---|---|
| **All 131+ existing tests must pass** after Phase 12.1 (v1 file moves) | Regression suite |
| **`evaluate_surge_candidate` signature unchanged** | Production `/analyze` uses it |
| **Point-in-time invariant**: `_compute_base_features` only sees `date <= as_of_date` | Look-ahead bias = #1 enemy |
| **Core invariants in `allowed_bounds.yaml` enforced** | Strategy identity locks |
| **v1 CLI (`auto_optimize.py`) still works** | Old runs should be reproducible |
| **No new heavy deps without flag** (optuna OK as OPTIONAL) | Project uses pandas/numpy/anthropic/yaml |
| **`historical_data_store.py` stays in `backtest/` root** (shared) | Both v1 and v2 use it |
| **Don't refactor `screener_service.py` core logic** | Too risky; treat as black box |

---

## 6. Success Criteria

After your implementation:

1. ✅ **131+ tests still pass** (no regressions)
2. ✅ **≥30 new tests in `test_v2_*.py` files**, all passing
3. ✅ **v2 smoke test produces signals**:
   ```powershell
   .venv\Scripts\python.exe -m backend.scripts.auto_optimize_v2 --target all --max-iterations 3 --trials-per-iter 30 --workers 4 --min-entry-tier C --walk-forward-windows 3 --start 2024-01-01 --end 2025-12-31 --output-dir artifacts/v2_smoke
   ```
   Should: complete in < 5 min, produce val_n > 20 per window in most trials, write `pareto_front.csv` with ≥ 5 non-dominated trials
4. ✅ **v1 smoke test still works** (regression check):
   ```powershell
   .venv\Scripts\python.exe -m backend.scripts.auto_optimize --target all --max-iterations 2 --trials-per-iter 10 --workers 2 --min-entry-tier 1 --start 2024-01-01 --end 2025-12-31 --output-dir artifacts/v1_regression
   ```
5. ✅ **`phase12_codex_implementation.md` written** with all sections from Section 12.11
6. ✅ **`artifacts/README.md` and `artifacts/research/INDEX.md` updated** to reference v2

---

## 7. Anti-patterns (avoid these)

- ❌ Don't change v1 code semantics; only move files and update import paths
- ❌ Don't make v2 depend on optuna without fallback (OptunaSampler must gracefully degrade)
- ❌ Don't bypass point-in-time in walk-forward splits (test_start > train_end)
- ❌ Don't make tier classifier slow (it's called per signal — must be < 0.1 ms)
- ❌ Don't share global state between v2 components (each is pure or has clear ownership)
- ❌ Don't break the Phase 9.8 fast-fail pre-filter in `signal_replay.py`
- ❌ Don't change `_FEATURE_CACHE` invariants (keyed by shape_hash)
- ❌ Don't add multi-objective Pareto in `loop.py` — keep `pareto.py` as a pure component

---

## 8. Verification Commands

```powershell
# After Phase 12.1 (v1 move): ALL existing tests must pass
.venv\Scripts\python.exe -m pytest backend/tests/ -q

# Per-phase: incremental test
.venv\Scripts\python.exe -m pytest backend/tests/test_v2_tier_classifier.py -q
.venv\Scripts\python.exe -m pytest backend/tests/test_v2_walk_forward.py -q
# etc.

# After Phase 12.10: V1 regression
.venv\Scripts\python.exe -m backend.scripts.auto_optimize --target cat3 --max-iterations 2 --trials-per-iter 5 --workers 2

# After Phase 12.11: V2 smoke
.venv\Scripts\python.exe -m backend.scripts.auto_optimize_v2 --target all --max-iterations 3 --trials-per-iter 30 --workers 4 --min-entry-tier C --walk-forward-windows 3 --start 2024-01-01 --end 2025-12-31 --output-dir artifacts/v2_smoke

# Final: full test suite
.venv\Scripts\python.exe -m pytest backend/tests/ -q
```

---

## 9. Key Facts (cheat sheet)

- Universe: 53 stocks in `backend/data/sectors/ai_tech_tw.json`
- Default date range: 2022-11-01 to 2026-05-15
- Train/test ratio per window: 0.8 (configurable)
- Tier multipliers: C=0.3, B=0.7, A=1.0, S=1.5
- Trend Template (S tier): `close > EMA50 > EMA150 > EMA200 AND EMA200 trending up 30 bars`
- Position multiplier scales BOTH gross_return AND trade_cost (commission/tax are trade-value based)
- Anthropic API: Claude Opus 4.7 via `llm_search_space_advisor.py`. Key in `.env` as `ANTHROPIC_API_KEY`
- Phase 9.8 speedups already integrated: parallel workers, OHLCV cache, feature cache, WAL mode, fast-fail filter, cross-iter pool
- `_FEATURE_CACHE` in `signal_replay.py`: keyed by (shape_hash, stock_id, as_of_date) — preserves across iters
- Test fixtures: `make_candidate_df` in `test_screener.py` for synthetic OHLCV

---

## 10. Output Format: `phase12_codex_implementation.md`

Use this structure:

```markdown
# Phase 12 — Optimization System v2 Implementation
**Date**: 2026-05-XX

## Summary
- Files added: ...
- Files moved (v1 reorganization): ...
- Files modified (shared code touched): ...
- New tests: X (total now Y)

## Sub-phase completion log
- ✅ Phase 12.1 (v1 move): 131 tests pass
- ✅ Phase 12.2 (tier classifier): 10 new tests pass
- ✅ Phase 12.3 (walk forward): 6 new tests pass
- ... (etc.)

## Smoke test results

### V2 smoke
- Command: `...`
- Wall time: X min
- Trials with val_n > 20: Y%
- Pareto front size: Z

### V1 regression
- Command: `...`
- Result: pass

## Performance impact
- Per-trial wall time v1: X sec
- Per-trial wall time v2: Y sec
- Walk-forward windows: 5 (each adds Z sec overhead)

## Walk-forward efficiency (sample run)
- Train mean: ...
- Test mean: ...
- WFE ratio: ...
- Stability std: ...

## Tier distribution (representative trial)
- S signals: X (Y%)
- A signals: ...
- B signals: ...
- C signals: ...

## Pareto front (top 5 non-dominated trials)
| trial_id | n_trades | win_rate | profit_factor | max_drawdown | tier_mix |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... |

## Design decisions / deviations from spec
- (anything you did differently with rationale)

## Outstanding work / known limitations
- ...
```

---

## 11. Final Note

This is a **greenfield rewrite** in coexistence with v1. The user is technically literate (knows quant concepts: walk-forward, Pareto, Kelly, Sharpe, Sortino, TPE) and has accumulated 4 phases of patches they're now consolidating.

**Be disciplined**:
- Implement each sub-phase fully + pytest before next
- Keep components pure (functions over classes where possible)
- Document any judgment calls in your phase12 report

**Don't over-engineer**:
- Optuna is optional — adaptive sampler is fine as default
- Walk-forward 5 windows is fine; don't add expanding windows or anchored variants
- Pareto with 3-4 objectives is enough; don't add 10
- TW price-limit modeling can be a simple `if next_open ≥ prev_close × 0.91 and gap >= 9%` check

The end product should let the user run:

```powershell
.venv\Scripts\python.exe -m backend.scripts.auto_optimize_v2 \
  --target all --max-iterations 10 --trials-per-iter 50 \
  --workers 4 --walk-forward-windows 5 \
  --sampler adaptive --min-entry-tier B
```

…and get a robust Pareto-front output in < 30 min with **meaningful trade counts per tier** and **WFE > 0.5** for stability.

Make it happen. — Claude Code (Phase 9-11 builder)
