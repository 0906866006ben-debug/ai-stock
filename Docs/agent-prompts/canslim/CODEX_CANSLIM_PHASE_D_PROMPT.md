# Codex Task — CAN SLIM Phase D: Cup-and-Handle / Flat-Base geometry detector

> **BEFORE YOU START:** read `CODEX_CANSLIM_GUARDRAILS.md` (repo root). Key point for this phase: the base detector outputs a **graded `quality_score` (0–100), NOT a pass/fail gate.** `pattern_type="none"` must NEVER by itself block or zero a stock's signal — the aggregator (Phase E) treats the base pattern as one *contributor* to the N/L pillar, not a filter. Do not turn pattern detection into a hard requirement.

> **Phase D.** Phases A, B, C (all 6 rule pillars) are done and green (113 canslim tests, full suite 457). **Do ONLY Phase D.** No aggregation (E), no regime (F). Stop when D tests are green.

## Background

Encode the Cup-and-Handle / Flat-Base geometry (from O'Neil + the Gemini research) as a **pure, self-contained detector**. It reads OHLCV bars (from `HistoricalDataStore.get_ohlcv_as_of`) and thresholds from `params["base_geometry"]`. It does NOT import or modify `screener_service`.

### Read first (for reconciliation, do not modify)
- `backend/app/services/screener_service.py` → `_compute_base_features()` (~line 936) and `_compute_recent_base()`. The existing flat-base there is a **simple box**: `base_period = close[-60:-19]`, `base_high/base_low = max/min`, `base_range_pct`, plus a contraction-ratio helper. The CAN SLIM detector is **richer** (cup + handle + volume dry-up). 
- **Document the overlap** in the module docstring of `base_detector.py`: existing = simple box gate inside the surge classifier; canslim = full cup/handle geometry, complementary and standalone. Do NOT duplicate or import the screener logic; reimplement cleanly from YAML. Note that future unification is Open Question #10 — out of scope here.
- `params["base_geometry"]` keys: `cup_and_handle.{cup_depth_min 0.12, cup_depth_max 0.35, handle_pullback_max_preferred 0.10, handle_pullback_max_upper 0.15, handle_location "upper_half", base_length_min_weeks 7, handle_volume_dryup_min 0.20, breakout_volume_increase_min 0.40, breakout_volume_increase_preferred 0.50}`, `flat_base.{box_range_pct_max 0.15, breakout_multiplier 1.005}`.

## What to build — `backend/app/services/strategy/canslim/base_detector.py`

### `BasePattern` (Pydantic v2 frozen, all value fields `| None`)
- `pattern_type: Literal["cup_and_handle", "flat_base", "none"]`
- `cup_depth: float | None`, `handle_pullback: float | None`, `handle_in_upper_half: bool | None`
- `base_length_weeks: float | None`, `handle_volume_dryup: float | None`
- `breakout_confirmed: bool | None`, `pivot_price: float | None`
- `quality_score: int` (0–100, graded — see below)
- `missing_fields: list[str]`, `data_warnings: list[str]`

### `detect_base(bars: pd.DataFrame, params) -> BasePattern`
Pure function. `bars` = chronological OHLCV (open/high/low/close/volume). Deterministic detection:

1. **Insufficient data** (`< base_length_min_weeks * 5` bars, ~35) → `pattern_type="none"`, `quality_score=0`, missing_fields note. (Not an error, not a block.)
2. **Cup-and-handle attempt** (deterministic, keep it simple):
   - Left peak = max close in the first third of the window; cup bottom = min close between left peak and the recent region; right peak = max close after the bottom.
   - `cup_depth = (left_peak - bottom) / left_peak`. Valid cup when `cup_depth_min <= cup_depth <= cup_depth_max`.
   - Handle = the pullback after the right peak: `handle_pullback = (right_peak - recent_low_after_right_peak) / right_peak`; valid when `<= handle_pullback_max_upper` (0.15). `handle_in_upper_half` = handle low sits in the upper half of the cup range.
   - `handle_volume_dryup` = `1 - mean(volume during handle) / mean(volume during cup)`; want `>= handle_volume_dryup_min` (0.20).
   - `pivot_price` = right peak (handle high). `breakout_confirmed` = last close `> pivot_price` AND last-bar volume `>= mean(handle volume) * (1 + breakout_volume_increase_min)` (1.40).
   - If cup_depth valid → `pattern_type="cup_and_handle"`.
3. **Flat-base fallback** (if not a cup): box over the base window; `box_range_pct = (high-low)/low`. Valid flat base when `box_range_pct <= box_range_pct_max` (0.15). `pivot_price` = box high; `breakout_confirmed` = last close `> box_high * breakout_multiplier` (1.005). → `pattern_type="flat_base"`.
4. Else → `pattern_type="none"`.

### `quality_score` (graded, 0–100 — NOT a gate)
Award partial credit so partial matches still surface (anti-zero-signal):
- base structure present (cup or flat) → +40
- depth/range within preferred band → +20
- handle valid (pullback ok + upper half) → +15
- volume dry-up met → +15
- breakout confirmed → +10
Cap 100. A weak/partial base still yields a non-zero score; "none" → 0. The aggregator decides how to use it; the detector never blocks.

## Tests — `backend/tests/strategy/canslim/test_phase_d_base.py` (≥6)
Synthetic OHLCV fixtures: (1) clean valid cup-and-handle → `pattern_type="cup_and_handle"`, high quality_score, `breakout_confirmed`; (2) cup too deep (>35%) → not cup, lower score; (3) handle pullback too large → handle invalid, partial score; (4) base too short (<7wk) → "none", score 0; (5) clean flat base → `pattern_type="flat_base"`; (6) no breakout volume → `breakout_confirmed False` but pattern still detected with partial score. Build bars with pandas DataFrames directly. Read thresholds from `load_params()`.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_d_base.py -q
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\ -q
.venv\Scripts\python -m pytest backend\tests\ -q
```

## STOP
When green, report `BasePattern`, the detector behavior, the overlap note vs `_compute_base_features`, and test results. Do NOT start Phase E (aggregator).
