# Codex Task — CAN SLIM Phase B: Feature extractors (pure, PIT-safe)

> This is **Phase B of 9**. Phase A is done (package skeleton, YAML thresholds, `params.py`, `types.py` all green). Do ONLY Phase B. **No rule logic, no scoring, no thresholds applied** — that's Phase C. Stop when Phase B tests are green.

## Background

We are quantifying O'Neil's CAN SLIM / Flat-Base strategy into the Taiwan surge-analysis backend, phase by phase. Full design: `Docs/research/canslim_oneil_strategy.md` (§3 field mapping, §4 rule inputs). Phase B builds the **feature layer only**: a pure, point-in-time-safe adapter that maps the existing data layer into one flat `CanslimFeatures` object. It computes/derives raw feature values and records which fields are missing. It does NOT apply any threshold or effect from the YAML (Phase C does that).

## Hard constraints

1. **Pure + PIT-safe.** No look-ahead. OHLCV only via `HistoricalDataStore.get_ohlcv_as_of(stock_id, as_of_date, lookback_bars)` (returns chronological DataFrame: open/high/low/close/volume/turnover). Never read bars after `as_of_date`.
2. **Never fabricate.** Missing/unavailable data → field is `None` and its name is appended to `missing_fields`. Do not estimate or substitute.
3. **Injectable dependencies** so tests run without network (see signature).
4. **Additive only** — do not touch `/analyze`, `/analyze/tw`, surge flow, or existing tests. Full suite must stay green.
5. No thresholds hardcoded; Phase B doesn't need thresholds at all (it reads no YAML). Thresholds stay in `backend/data/strategy/canslim_thresholds_v1.yaml` for Phase C.

## What to build

`backend/app/services/strategy/canslim/features.py` with a Pydantic v2 model `CanslimFeatures` and a function `build_features(...)`.

### `CanslimFeatures` (all value fields `| None`)
- `symbol: str`, `as_of_date: str`
- Growth: `month_revenue_yoy: list[float] | None` (most recent ≥3, chronological), `quarterly_eps_yoy: float | None`, `eps_cagr_3y: float | None`, `roe_ttm: float | None`, `op_margin_last4: list[float] | None`
- Technical/leadership: `close: float | None`, `ma20/ma60/ma120: float | None`, `ma120_slope: float | None` (slope over last 20 bars), `high_252d: float | None`, `pct_from_52w_high: float | None`, `rs_60d_pct: float | None`, `rs_252d_pct: float | None` (rank percentile 0–1 vs universe)
- Supply/volume: `avg_volume_50: float | None`, `avg_turnover_20: float | None`, `up_down_volume_ratio_10: float | None`, `box_high_20: float | None`, `box_low_20: float | None`
- Institutional: `foreign_net_5: list[float] | None`, `trust_net_5: list[float] | None`, `dealer_net_5: list[float] | None`
- Always-None (not in repo): `day_trade_ratio: None`, `chip_concentration: None`
- Bookkeeping: `missing_fields: list[str]`, `data_warnings: list[str]`

### Signature
```python
def build_features(
    symbol: str,
    as_of_date: str,
    store: HistoricalDataStore,
    *,
    universe_returns_60d: dict[str, float] | None = None,
    universe_returns_252d: dict[str, float] | None = None,
    fin_metrics: dict | None = None,        # output shape of tw_financial_metrics.fetch_real_metrics
    detail: dict | None = None,             # output shape of finmind_detail.get_tw_detail
    eps_filing_date: str | None = None,     # actual_filing_date from tw_calendar, for PIT gate
) -> CanslimFeatures: ...
```
When a dependency is `None`, the fields it would feed become `None` and are appended to `missing_fields`. `build_features` itself does no network I/O — callers fetch and inject. (A thin async helper that gathers the deps may be added but is optional and untested in Phase B.)

### Derivations
- MA20/60/120 + `ma120_slope`: from `get_ohlcv_as_of` close series (need ≥120 bars for ma120, ≥252 for `high_252d`; insufficient → None + missing_fields).
- `pct_from_52w_high = close / high_252d - 1`.
- `avg_volume_50`, `avg_turnover_20`, `up_down_volume_ratio_10` (avg vol on up-close days ÷ avg vol on down-close days, last 10 bars), `box_high_20`/`box_low_20` (20-bar high/low).
- `rs_60d_pct` / `rs_252d_pct`: this symbol's N-day return ranked as a percentile within `universe_returns_Nd` (the 53-stock universe in `backend/data/sectors/ai_tech_tw.json`). Missing universe → None.
- Growth fields pulled from injected `fin_metrics` (`eps_yoy`, `roe`, margins…) and `detail` (monthly revenue). `eps_cagr_3y` derived if 3 annual EPS available, else None.

### PIT rules
- Quarterly EPS usable only when `eps_filing_date` is provided AND `eps_filing_date < as_of_date` (filing_date + 1 trading day ≤ as_of). Otherwise `quarterly_eps_yoy = None` + missing_fields entry.
- Institutional net series are T+1 lagged (only days strictly before/at the lagged date).
- `day_trade_ratio` and `chip_concentration` are ALWAYS `None`; append a `data_warnings` note ("day_trade_ratio unavailable in data layer", "chip_concentration unavailable").

## Tests — `backend/tests/strategy/canslim/test_phase_b_features.py` (~6)
1. All-deps-present fixture → expected MA/RS/volume/growth values.
2. Each missing dependency (`fin_metrics=None`, `detail=None`, `universe_returns=None`) → corresponding fields None + present in `missing_fields`.
3. PIT: `eps_filing_date` after `as_of_date` → `quarterly_eps_yoy is None`.
4. day_trade_ratio & chip_concentration always None + a `data_warnings` entry each.
5. Insufficient bars (<252) → `high_252d is None`; (<120) → `ma120 is None`.
6. RS percentile correct on a small synthetic `universe_returns` dict.

Build OHLCV fixtures with an in-memory or temp-file `HistoricalDataStore` (use `upsert_rows`). No network.

## Verify
```powershell
.venv\Scripts\python -m pytest backend\tests\strategy\canslim\test_phase_b_features.py -q
.venv\Scripts\python -m pytest backend\tests\ -q   # full suite must stay green
```

## STOP
When green, report: `features.py` field list, how each missing path is handled, test results. Do NOT begin Phase C (rule functions).
