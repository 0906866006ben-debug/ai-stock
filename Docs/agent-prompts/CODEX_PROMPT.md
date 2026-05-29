# Codex Handoff — Backtest System Comprehensive Review & Improvement

**Repo**: `c:\Users\09068\OneDrive\文件\GitHub\ai-stock` (Windows / PowerShell)
**Python**: `.venv\Scripts\python.exe`
**Tests**: `.venv\Scripts\python.exe -m pytest backend/tests/ -q` (currently **111 passing**)
**Today's date**: 2026-05-18

---

## CANSLIM long-term guardrails memory

Before implementing any CANSLIM aggregation, classification, entry, backtest, or optimization logic, read:

- `Docs/agent-prompts/canslim/CODEX_CANSLIM_GUARDRAILS.md`
- `Docs/agent-prompts/CANSLIM_LONG_TERM_MEMORY.md`

Core memory: this project previously suffered from over-strict AND-gating and degenerate optimization that produced near-zero tradeable signals. CANSLIM must remain a graded scoring system, not an all-rules-must-pass filter. Only explicitly allowed blockers may suppress new-entry observations, and every future gate/classifier/entry threshold needs signal-frequency diagnostics before shipping.

---

## 0. What this prompt asks you to do

This repo contains a **systematic quantitative backtest + parameter optimizer** for a Taiwan AI-industry stock strategy. Over the past several days, the team (user + Claude Code) has gone through 9 phases of design iteration. **Your job**:

1. **Read** everything documented below so you fully understand the strategy, the system architecture, and prior decisions
2. **Critically evaluate** the current implementation — what's elegant, what's hacky, what's likely to break, what's slow
3. **Propose 2-4 concrete improvements** ranked by impact × effort
4. **Implement the top 1-2** with full tests and a written-up report
5. **Preserve all 111 existing tests** and the production `/analyze` endpoint behavior

**Optimize for robustness > speed > elegance.** The user has been burned by reward-hacking before, so be conservative with anything that changes evaluation semantics.

---

## 1. The Strategy Being Modeled

### User's discretionary edge (their words)

> "前期主力表態 (10-30% rally over ~2 months) → 縮量盤整 (~1 month sideways, volume dry-up) → EMA 5/10/20 收斂後微翹 (tight convergence then upturn) → 突破箱型上緣當日進場 (enter on breakout day)"

### Maps to: O'Neil "Flat Base" + EMA convergence filter

After Phase 9.5–9.7 research, this strategy was definitively identified as **William J. O'Neil's 1988 "Flat Base" pattern** (CANSLIM family) with a unique EMA quality filter. Verified by:

- IBD official: Flat Base = prior 20-30%+ advance + 5-7 week sideways + ≤15% depth + breakout on 1.4× 50d avg volume
- Bulkowski: Measured Move target = **0.85 × base_height** achieves **85% hit rate** (empirically validated)
- O'Neil 1995-2021 backtest: +3.2% / 3 month return on top-sector + not-thin breakouts → 87% success rate

### Universe

53 Taiwan AI tech stocks across 6 sub-sectors (file: `backend/data/sectors/ai_tech_tw.json`):
- `cat_1_silicon_ip` (12): IC設計 / IP / 記憶體 (聯發科, 信驊, 力旺...)
- `cat_2_foundry` (3): 台積電, 聯電, 世界先進
- `cat_3_packaging` (10): 日月光, 京元電, 力成... (this is the "highest edge sub-sector")
- `cat_4_components` (15): 散熱, ABF載板, PCB, 網通 (奇鋐, 健策, 智邦...)
- `cat_5_system_integration` (9): 廣達, 緯創, 鴻海... (ODM)
- `cat_6_cloud_software` (5): 華碩, 緯軟...

### Strategy positioning

- **Time frame**: Mid-Swing (10-40 days typical) but **no time limit** in code (user's thesis: hold until target or stop)
- **Target = Measured Move**: `entry + (base_high - base_low) × multiplier` (default 0.85 = O'Neil/Bulkowski standard)
- **Stop = -10% from entry** (user's thesis; slightly looser than O'Neil's -7~8%)

---

## 2. Phase History (research + implementation chronology)

| Phase | Topic | Key output |
|---|---|---|
| **0-5** | Earlier work (before this thread) | OHLCV downloader, screener, signal_replay, trade_simulator, random-search optimizer |
| **6** | Built Claude API closed-loop optimizer | `optimization_loop.py`, `llm_search_space_advisor.py`, `search_space_validator.py` |
| **6.5** | First closed-loop run (5×30) | Found candidate but cat3-only n=10 too thin |
| **7** | Result interpretation + DD analysis | Identified need for exit logic improvements |
| **9** | Phase 9: General quant research | `artifacts/research/phase9_quant_research.md` — VCP, CANSLIM, 7 sins, Kelly, TW specifics |
| **9.5** | Strategy-specific deep dive | `artifacts/research/phase9_5_strategy_deep_dive.md` — Pocket Pivot, Trend Template (LATER PARTIALLY CORRECTED) |
| **9.6** | Time frame analysis | `artifacts/research/phase9_6_timeframe_analysis.md` — Strategy is Mid-Swing |
| **9.7 ⭐** | Strategy framework correction | `artifacts/research/phase9_7_corrected_strategy_framework.md` — **Confirmed = O'Neil Flat Base** (KEY TURNING POINT) |
| **9.8** | Flat Base quant spec + implementation | `artifacts/research/phase9_8_flat_base_quant_spec.md`. Code changes: schema migration, `_compute_base_features` extraction, dynamic Measured Move, breakout_today event-trigger gate, no time-limit option, etc. |
| **9.9 ⭐** | Empirical validation | `artifacts/research/phase9_9_quantification_validation.md` — Verified each parameter against industry data. **System rated A- (8 As + 2 Bs)** |
| **9.8.1** | Speed optimizations | Cross-iter pool persistence, fast-fail pre-filter, SQLite WAL, skip intermediate DB writes |

**Read order if confused**: `artifacts/research/INDEX.md` first, then 9.7 → 9.8 → 9.9.

---

## 3. Current Implementation Architecture

### File structure

```
backend/
├── app/services/
│   ├── screener_service.py            # Main strategy evaluator (1990 lines)
│   │   ├── _compute_base_features()     # Extracted in Phase 9.8 — param-INDEPENDENT
│   │   │                                  ~50 indicators that don't depend on
│   │   │                                  thresholds Claude tunes (cacheable)
│   │   ├── evaluate_surge_candidate()   # Main entry; takes optional precomputed_features
│   │   └── _classify_candidate()        # Determines candidate_type incl. "起漲前觀察"
│   ├── screener_rules.py              # Loads rules YAML with lru_cache + env override
│   └── backtest/
│       ├── historical_data_store.py     # SQLite OHLCV + CachedHistoricalDataStore (in-mem)
│       ├── signal_replay.py             # Point-in-time signal generation
│       │                                # Module-level _FEATURE_CACHE keyed by shape_hash
│       │                                # NEW: fast-fail pre-filter for 起漲前觀察
│       ├── trade_simulator.py           # Entry next-day-open, dynamic Measured Move target
│       ├── optimizer.py                 # Random search + multiprocess Pool
│       │                                # external_pool support for cross-iter cache reuse
│       ├── optimizer_config.py          # OptimizerConfig, GateConfig, TrialResult
│       ├── optimization_loop.py         # Claude-API closed-loop state machine
│       ├── optimization_summary.py      # Compact payload (~3KB) for Claude API
│       ├── llm_search_space_advisor.py  # Anthropic SDK wrapper (Opus 4.7)
│       ├── search_space_validator.py    # Strict JSON validator for Claude responses
│       ├── allowed_bounds.yaml          # Parameter whitelist + bounds + core_invariants
│       └── optimizer_search_space.yaml  # Search space Claude/random samples from
├── scripts/
│   ├── auto_optimize.py               # CLI entry for closed-loop runner
│   └── download_history.py            # OHLCV downloader (yfinance + FinMind)
└── technical_analyzer/v1/registry/
    └── rules_v1.yaml                  # Production strategy rules (53 stocks defaults)

artifacts/
├── README.md                          # Navigation hub
├── research/                          # 6 phase reports + INDEX
├── strategy_optimization/             # Last run's iter_NN/ outputs
└── _archived_smoke/                   # 6 historical smoke tests
```

### Single-trial execution flow

```
Optimizer samples params → temp YAML override → env var → cache clear
   ↓
signal_replay (PARAM-INDEPENDENT compute is CACHED):
   for date in trading_dates:
     for stock in universe:
       df_slice = data_store.get_ohlcv_as_of(stock, date, lookback=150)  ← in-memory cache
       cached_features = _FEATURE_CACHE.get((shape_hash, stock, date))    ← cache hit
       if cached_features is None:
           cached_features = _compute_base_features(df_slice, market, rules)  ← cache fill
       
       # NEW Phase 9.8.1: fast-fail check (skip evaluate when basic gates fail)
       if range_90d / return_20d / etc. don't match 起漲前觀察 → continue
       
       result = evaluate_surge_candidate(precomputed_features=cached_features, rules)
       if result.candidate_type == "起漲前觀察":
           emit signal
   ↓
trade_simulator:
   for signal:
     entry_price = next_day_open × (1 + slippage)
     dynamic_target = entry + (base_high - base_low) × multiplier  ← NEW: Measured Move
     walk forward bar by bar:
       if low ≤ entry × (1-stop): exit stop_loss
       if high ≥ target: exit target_reached
       if max_hold_days > 0 and hold ≥ max_hold: exit time
     calc gross + net (after 0.685% Taiwan round-trip cost)
   ↓
compute SplitMetrics (train / val) + composite objective
   ↓
TrialResult
```

### Closed-loop state machine

```
LoopConfig (CLI args via auto_optimize.py)
  ↓
Build shared worker Pool (NEW in 9.8.1: persists across iters → caches stay warm)
  ↓
For each iter (up to max_iterations):
  1. Random-sample N parameter sets from current search space → run as trials
  2. Aggregate into compact summary (best/top/bottom + dim_analysis + train/val gap)
  3. Call Claude API (Opus 4.7) — returns strict JSON patch for next search space
  4. Validate via allowed_bounds.yaml whitelist + core_invariants
  5. Apply patch → next iter
  6. Check stop conditions: stop_on_success / stagnation / regression
  ↓
Persist global_best_params.yaml + global_best_summary.json + all_iterations_summary.csv
```

---

## 4. All Speedups Already Implemented

| # | Speedup | What | Impact |
|---|---|---|---|
| **#1** | Multiprocess workers | `multiprocessing.Pool` for parallel trials | ~4× on 4-core |
| **#2** | Universe filter | `list_codes_by_category()` allows scoping | Available, currently not used (full 53 stocks) |
| **#3+#4** | OHLCV in-memory cache | `CachedHistoricalDataStore` pre-loads universe | Skip SQLite reads per trial |
| **#5** | Feature cache | `_FEATURE_CACHE` keyed by `(shape_hash, stock_id, as_of_date)`. Param-independent metrics cached across all trials of session | Skip ~50 indicator computations per (stock, date) |
| **WAL** | SQLite tuning | `PRAGMA journal_mode=WAL + synchronous=NORMAL + cache_size=64MB` | Reduce write contention |
| **In-mem df** | Skip DB intermediate | `signal_replay` returns `signal_rows` directly → `trade_simulator` reads df | Save 2 DB roundtrips/trial |
| **Schema once** | `_SCHEMA_INITIALIZED` set | Skip repeat PRAGMA queries | Tiny but free |
| **Cross-iter pool** | Worker pool survives across iters in `run_closed_loop` | Caches stay warm | Save ~3 min cache warmup × N iters |
| **lookup_days cap** | `max_hold_days=0` was → 365 days lookup, now → 180 | 50% reduce trade-sim data fetch | 2× trade_simulator |
| **Fast-fail filter** (NEW) | Pre-check 9 basic gates before full evaluate | Skip 80-90% of (stock, date) pairs in ~0.05 ms | 5-10× per-trial speed |

**Equivalence test**: `backend/tests/test_feature_cache.py` verifies cached path produces **bit-perfect identical** output to legacy path on synthetic OHLCV. This is the critical correctness guarantee.

---

## 5. Strategy Parameters & Search Space

### Core invariants (CANNOT be changed by Claude)

From `backend/app/services/backtest/allowed_bounds.yaml`:
- 90-day range must stay in [10%, 30%] (Bull Flag / Flat Base pole+flag identity)
- Volume contraction during base must stay ≤ 1.0 (i.e., must contract)
- EMA 5/10/20 spread must stay ≤ 0.08 (糾結 condition)
- EMA transition score ≥ 30 (cannot loosen below)

### Current search space (`optimizer_search_space.yaml`)

23 parameters, recently pruned to remove "too strict" values that produce 0-trade outcomes when randomly combined:

```yaml
# Price / 起漲前未漲
price_position.min_return_60d:          [-0.20, -0.15, -0.10, -0.05]
price_position.pre_breakout_range_90d_min:  [0.05, 0.08, 0.10]
price_position.pre_breakout_range_90d_max:  [0.25, 0.30, 0.35]
price_position.pre_breakout_return_20d_strict_max: [0.06, 0.08, 0.10, 0.12]
price_position.pre_breakout_return_60d_strict_max: [0.10, 0.15, 0.20]
price_position.pre_breakout_return_90d_min: [-0.20, -0.15, -0.10]

# EMA
ema.pre_breakout_close_ema20_max:       [0.04, 0.05, 0.06, 0.08]
ema.pre_breakout_ema_spread_max:        [0.025, 0.03, 0.04, 0.05]
ema.overheated_close_ema20_min:         [0.10, 0.12, 0.15]
ema.overheated_ema_spread_min:          [0.06, 0.08, 0.10]

# Volume contraction
volume.pre_breakout_volume_contraction_max: [0.75, 0.85, 0.95]

# Classification thresholds
classification.pre_breakout_score_min:          [50, 55, 60]
classification.pre_breakout_ema_score_min:      [40, 50]
classification.pre_breakout_ema_transition_score_min: [20, 30, 40]
classification.pre_breakout_base_score_min:     [40, 50]
classification.pre_breakout_close_to_base_high_max: [1.03, 1.05, 1.08]
classification.pre_breakout_risk_score_max:     [60, 65, 70]
classification.pre_breakout_min_turnover:       [30M, 50M, 100M]

# Phase 9.8 Flat Base event trigger
classification.breakout_pivot_buffer:      [0.001, 0.002, 0.003]   # 突破幅度
classification.breakout_volume_ratio_min:  [1.2, 1.3, 1.4]         # 突破量爆倍數
classification.base_depth_max:             [0.13, 0.15, 0.18]      # base 深度

# Exit rules (NEW in 9.8)
trade_rules.max_hold_days:             [0, 60, 120]
trade_rules.stop_loss_pct:             [0.07, 0.08, 0.10]
trade_rules.measured_move_multiplier:  [0.70, 0.85, 1.00]
```

### Composite objective formula

```
score = val_gates_passed × 100
      + val.win_rate × 30
      + val.avg_return_pct × 500
      + min(val.profit_factor, 5.0) × 8
      + val.expectancy × 200
      - abs(train.wr - val.wr) × 50          (overfit penalty)
      - abs(train.avg_ret - val.avg_ret) × 200  (overfit penalty)
      - (min_trades - val_n)^1.5 × 5         (low-sample penalty, quadratic)
      - excess_drawdown_penalty
      + target_bonus (cat3 specific gates × 50)

if val.n_trades < 3: return -2000.0   ← HARD REJECT reward-hacking
```

### Known reward-hack failure modes (already patched)

| Failure | Pattern | Patch |
|---|---|---|
| `val_n=1, PF=999, obj=178.9` | 1-trade gaming | Hard reject `n<3`, degenerate guard in `optimization_loop` |
| `val_dd=0% on n=1` | Single trade hits target | Hard reject |
| All-strict combo → 0 trades | Random sampled all extreme values | Search space pruned (Phase 9.8.1) |

---

## 6. Known Remaining Issues (these are what to improve!)

### 🔴 Issue A: signal_replay still has Python-loop overhead

Even with fast-fail + feature cache, the inner loop processes 53 stocks × 800 dates = ~42,400 (stock, date) one at a time in Python. With fast-fail saving 80%, we still do ~4,000 full evaluates. Each is ~5-7 ms → ~25 sec per trial compute. Could be improved by **vectorizing across stocks per date**.

### 🟡 Issue B: Random sampling is brittle to bad-region selection

Even after pruning, ~15-20% of random samples produce val_n=0/1. **Bayesian optimization (Optuna TPE)** could learn good regions adaptively and reduce this further.

### 🟡 Issue C: Single train/val 70/30 split

Statistical robustness is weak. Real **walk-forward analysis** (5 rolling windows × 2 yr train / 6 mo test) would give more confident OOS estimates. Should add Walk-Forward Efficiency metric (OOS / IS).

### 🟢 Issue D: No Taiwan price-limit modeling

Stop = -10% but actual fill may be ≤ -10% if next day gaps limit-down (-10%). Currently trade_simulator just exits at stop_price. Real fills could be -15 to -19% on consecutive limit-down days.

### 🟢 Issue E: Multi-objective trade-offs are scalarized

Composite objective hides trade-offs. **Pareto-front multi-objective** (val_n, WR, PF, DD as separate objectives) might surface better candidates.

### 🟢 Issue F: No regime filter

Strategy enters in any market regime. Adding **TAIEX > 30-week MA filter** (Weinstein Stage 2) would skip bear markets entirely, likely cutting DD significantly.

### 🟢 Issue G: Validation of NEW params doesn't include sensitivity analysis

When Claude proposes new search space, we just trust it. Could add: for each new param set, run trial with ±10% perturbation and check stability.

---

## 7. Constraints (DO NOT BREAK)

| Constraint | Why |
|---|---|
| All 111 existing pytest tests must pass | Equivalence + behavioral regression suite |
| Don't change `evaluate_surge_candidate` behavior when `precomputed_features=None` | Production `/analyze` endpoint depends on it |
| Point-in-time invariant: on any `as_of_date`, only OHLCV with `date <= as_of_date` is visible | Look-ahead bias is the #1 enemy |
| Keep `core_invariants` in `allowed_bounds.yaml` enforced | Strategy identity locks |
| Don't bypass `search_space_validator.validate()` for Claude responses | Prevents Claude from violating bounds |
| Use only the Python venv at `.venv\Scripts\python.exe` | Project conventions |
| Don't add heavy dependencies (>50MB) without strong justification | Existing: pandas, numpy, anthropic, yaml, sqlite3 |
| Don't make backtest faster by removing transaction cost / slippage modeling | These are realistic |

---

## 8. Tasks Ranked by Impact × Feasibility (pick 1-2 to implement)

| # | Task | Effort | Impact |
|---|---|---|---|
| **A** | **Vectorize signal_replay** — for each date, build a wide DataFrame of all stocks' features and apply gates as boolean masks instead of inner Python loop | 4-8 hr | 🔥 5-20× per-trial speedup |
| **B** | **Optuna TPE sampler** replacing pure random search in `optimizer.py` (keep Claude API outer loop for direction-changing) | 3-5 hr | 🔥 30-50% reduce wasted trials |
| **C** | **Walk-forward 5 windows** replacing single 70/30 split | 4-6 hr | 🔥 OOS robustness, walk-forward efficiency metric |
| D | TAIEX 30-week MA regime filter as new condition gate | 1-2 hr | Medium DD reduction |
| E | TW price-limit simulation in `trade_simulator` (cap exit at -10%) | 2 hr | More realistic DD |
| F | Pareto-front multi-objective (pymoo / Optuna multi-objective) | 6-10 hr | Better candidate exploration |
| G | Sensitivity-analysis-on-Claude-proposed-params (perturb ±10%, check stability) | 3-4 hr | Robustness audit |
| H | Persistent disk feature cache across sessions (pickle / parquet) | 1-2 hr | Save cold-start time only |

**Pick A or B as the headline task. They're the highest leverage. C is the most important for scientific correctness but less of a "speedup".**

---

## 9. Success Criteria

After your changes:

1. ✅ All 111 existing pytest tests still pass (run them, confirm)
2. ✅ Add ≥ 10 new tests for your code, including:
   - Equivalence with prior path on representative inputs
   - Edge cases (empty universe, no signals, etc.)
3. ✅ **Speed target**: full closed-loop with `--target all --max-iterations 15 --trials-per-iter 80 --workers 4` should complete in **≤ 30 minutes** wall time (currently estimated ~30-45 min after Phase 9.8.1)
4. ✅ Document in `artifacts/research/phase10_codex_improvements.md`:
   - What you found in your evaluation
   - What you changed
   - Benchmark numbers (before/after)
   - Why each change was correct (point-in-time preserved, equivalence verified)
5. ✅ Update `artifacts/README.md` to mention Phase 10

---

## 10. How to Run Things

```powershell
# Run all tests
.venv\Scripts\python.exe -m pytest backend/tests/ -q

# Run only backtest / optimizer tests (fast subset)
.venv\Scripts\python.exe -m pytest backend/tests/test_optimizer.py backend/tests/test_auto_optimize.py backend/tests/test_feature_cache.py backend/tests/test_backtest.py backend/tests/test_screener.py -q

# Smoke test of full closed-loop (~10-15 min after current speedups)
.venv\Scripts\python.exe -m backend.scripts.auto_optimize --target all --max-iterations 3 --trials-per-iter 30 --workers 4 --start 2024-01-01 --end 2025-12-31 --output-dir artifacts/codex_smoke --auto-dir artifacts/codex_smoke/auto

# Full overnight run
.venv\Scripts\python.exe -m backend.scripts.auto_optimize --target all --max-iterations 15 --trials-per-iter 80 --workers 4 --stagnation-iters 5 --min-improvement 0.5
```

---

## 11. Reading Order (skim in this order before coding)

1. **`artifacts/README.md`** (2 min) — navigation
2. **`artifacts/research/INDEX.md`** (3 min) — research path
3. **`artifacts/research/phase9_7_corrected_strategy_framework.md`** (10 min) — strategy identity (THE most important doc)
4. **`artifacts/research/phase9_8_flat_base_quant_spec.md`** (15 min) — implementation spec
5. **`artifacts/research/phase9_9_quantification_validation.md`** (15 min) — empirical validation
6. **`backend/app/services/backtest/v1/optimizer.py`** (15 min) — legacy optimizer engine
7. **`backend/app/services/backtest/signal_replay.py`** (10 min, 320 lines) — signal generation (look at the fast-fail block from Phase 9.8.1)
8. **`backend/app/services/backtest/v1/optimization_loop.py`** (15 min) — legacy closed-loop
9. **`backend/app/services/screener_service.py`** (skim, focus on `_compute_base_features` and `evaluate_surge_candidate`)

---

## 12. Anti-patterns (please avoid)

- ❌ Don't replace `evaluate_surge_candidate` wholesale — it's used by production `/analyze` too. Build NEW functions instead, route the optimizer to use them
- ❌ Don't disable WAL/PRAGMA setup — they're for concurrency
- ❌ Don't change `core_invariants` in `allowed_bounds.yaml`
- ❌ Don't bypass `search_space_validator.validate()` for Claude responses
- ❌ Don't aim for "perfect overfit" — the goal is robustness, not best in-sample numbers
- ❌ Don't add hidden global state without `module._GLOBAL_VAR` naming convention
- ❌ Don't break the `_FEATURE_CACHE` cache invariants — read `_cache_namespace()` first

---

## 13. Quick Architecture Self-Test

**Question for you to answer in your phase10 report**: trace what happens (file-by-file, function-by-function) when this CLI command runs:

```powershell
.venv\Scripts\python.exe -m backend.scripts.auto_optimize --target all --max-iterations 2 --trials-per-iter 5 --workers 2
```

Specifically:
1. Where is the worker pool created?
2. When is the OHLCV cache loaded into each worker?
3. When is the feature cache populated?
4. What guarantees the fast-fail filter is point-in-time safe?
5. How does Claude API get called and what does it return?

If you can answer all 5 confidently, you've understood the system. If not, read more before coding.

---

## 14. Final Notes

- The user is technically literate (knows quant concepts: WR, PF, R/R, Kelly, Pareto, walk-forward) but appreciates clear plain-language explanations
- Conservative changes > aggressive rewrites. Prefer additive code (new files / new functions) over modifying existing ones
- If you encounter ambiguity, add a `# TODO(codex)` comment and continue with the conservative choice
- Each significant change should have a corresponding test
- Your phase10 markdown report will be the "evidence" the user reviews before approving — make it clear and benchmark-driven

**The user explicitly said**: "讓他可以了解我們的所有想法並且實作看會不會更好" → understand all our thinking AND implement to see if it can be better. Don't just refactor for the sake of refactoring. Make the system **measurably better** on at least one of: speed, robustness, or insight quality.
