# Feature Layer Plan

Date: 2026-06-03  
Status: design only. This plan does not require wiring into `/analyze/tw` yet.

## Goals

- Build a local SQLite feature layer on top of OHLCV and PIT fundamentals.
- Make screening and backtests faster and more reproducible.
- Preserve point-in-time discipline.
- Keep AI analysis downstream of rule-based features, not upstream of features.
- Support conditional, horizon-separated Taiwan stock analysis.

## Non-goals

- Do not replace SQLite with PostgreSQL/MySQL.
- Do not remove JSON cache.
- Do not change API response schemas.
- Do not use AI text as a backtestable data source.
- Do not generate absolute buy/sell/hold commands.

## Proposed Table: `daily_stock_features`

Purpose: store daily technical, chip, valuation, risk, and confidence fields.

```sql
CREATE TABLE IF NOT EXISTS daily_stock_features (
    stock_id TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL,
    volume INTEGER,
    ma5 REAL,
    ma20 REAL,
    ma60 REAL,
    ma120 REAL,
    ma240 REAL,
    rsi14 REAL,
    macd REAL,
    macd_signal REAL,
    macd_hist REAL,
    volume_ma20 REAL,
    volume_ratio_20d REAL,
    foreign_net_buy_1d REAL,
    foreign_net_buy_5d REAL,
    investment_trust_net_buy_1d REAL,
    investment_trust_net_buy_5d REAL,
    dealer_net_buy_1d REAL,
    dealer_net_buy_5d REAL,
    margin_balance_change_5d REAL,
    short_balance_change_5d REAL,
    per REAL,
    pbr REAL,
    technical_score REAL,
    chip_score REAL,
    valuation_score REAL,
    risk_score REAL,
    confidence_score REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (stock_id, date)
);
```

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_daily_stock_features_date_stock
ON daily_stock_features (date, stock_id);

CREATE INDEX IF NOT EXISTS idx_daily_stock_features_scores
ON daily_stock_features (date, confidence_score, risk_score);
```

PIT rules:

- OHLCV features may use bars where `ohlcv.date <= feature.date`.
- Financial statement features must use `filing_date <= feature.date`.
- Monthly revenue should use `available_date <= feature.date` after an `available_date` column exists.
- Institutional and margin data need an explicit post-close or next-session availability policy.
- Missing inputs must reduce `confidence_score`.

## Proposed Table: `stock_dynamic_tags`

Purpose: store daily machine-readable tags for screening and AI explanation.

```sql
CREATE TABLE IF NOT EXISTS stock_dynamic_tags (
    stock_id TEXT NOT NULL,
    date TEXT NOT NULL,
    tag TEXT NOT NULL,
    category TEXT NOT NULL,
    strength REAL,
    reason TEXT,
    source_table TEXT,
    source_fields TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (stock_id, date, tag)
);
```

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_stock_dynamic_tags_date_category
ON stock_dynamic_tags (date, category, tag);

CREATE INDEX IF NOT EXISTS idx_stock_dynamic_tags_tag_date
ON stock_dynamic_tags (tag, date);
```

Tag examples:

| Category | Example tag | Source |
|---|---|---|
| technical | `price_above_ma20_ma60` | `ohlcv`, computed MA fields |
| technical | `overextended_from_ma20` | `daily_stock_features.close`, `ma20` |
| chip | `foreign_5d_net_buy` | `institutional.foreign_net` |
| chip | `trust_support_confirmed` | `institutional.trust_net` |
| risk | `margin_balance_rising_fast` | `margin.margin_balance` |
| valuation | `per_above_recent_band` | `per.per` |
| data_quality | `missing_financials` | source table coverage check |

Rules:

- `reason` should cite rule inputs, not AI prose.
- `source_fields` should be a compact JSON array or comma-separated list.
- Tags should be recalculable from source data.
- Tags should avoid aggressive wording in user-facing surfaces.

## Proposed Table: `analysis_snapshots`

Purpose: store daily/horizon-separated analysis snapshots for historical tracking.

```sql
CREATE TABLE IF NOT EXISTS analysis_snapshots (
    stock_id TEXT NOT NULL,
    date TEXT NOT NULL,
    horizon TEXT NOT NULL,
    technical_score REAL,
    chip_score REAL,
    fundamental_score REAL,
    valuation_score REAL,
    risk_score REAL,
    confidence_score REAL,
    recommendation_status TEXT,
    invalidation_signal TEXT,
    summary_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (stock_id, date, horizon)
);
```

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_date_horizon
ON analysis_snapshots (date, horizon);

CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_stock_horizon_date
ON analysis_snapshots (stock_id, horizon, date);
```

Snapshot rules:

- `horizon` must be explicit: `short_term`, `swing_term`, or `long_term`.
- `recommendation_status` must remain conditional, such as `observe_only`, `wait_for_breakout`, `wait_for_pullback`, or `bullish_but_avoid_chasing`.
- `invalidation_signal` is required for any bullish status.
- `summary_json` may include structured explanation and source metadata.
- AI-generated narrative can be stored for display, but backtests should consume scores/tags/rules only.

## Build Flow

1. Read OHLCV from `backend/historical_data.db`.
2. Read PIT fundamentals/chip data from `backend/pit_fundamentals.db`.
3. Join with strict as-of rules.
4. Compute deterministic feature values.
5. Write `daily_stock_features`.
6. Generate deterministic tags into `stock_dynamic_tags`.
7. Optionally generate `analysis_snapshots` after rules and quality gates pass.

## Data Availability Rules

| Source | Market date field | Required PIT gate |
|---|---|---|
| OHLCV | `date` | `date <= as_of` |
| Institutional | `date` | define post-close or next-session availability |
| Margin | `date` | define publication-delay policy |
| PER/PBR | `date` | `date <= as_of`, with source timing documented |
| Monthly revenue | `date` today; future `available_date` needed | use `available_date <= as_of` once available |
| Financials | `period_end`, `filing_date` | `filing_date <= as_of` |
| Balance sheet | `period_end`, `filing_date` | `filing_date <= as_of` |
| Cash flow | `period_end`, `filing_date` | `filing_date <= as_of` |

## Confidence Policy

Confidence should decrease when:

- required data is missing,
- data is stale,
- provider source is fallback or mock,
- feature windows have insufficient bars,
- financial data has no valid `filing_date`,
- monthly revenue has no verified availability date,
- chip data timing is ambiguous.

Mock/fallback/stale data must not produce high-confidence analysis.

## Rollout Plan

1. Keep all current APIs unchanged.
2. Add schema migration for the three new tables after index migration is verified.
3. Build a separate feature-generation script with explicit `--as-of` and `--symbols`.
4. Validate feature rows against hand-built PIT fixtures.
5. Add backtest tests for no future joins.
6. Compare screening speed and output before using the feature layer in production endpoints.
7. Only then optionally add read fallback from feature tables for screening, not `/analyze/tw` first.

## Acceptance Criteria

- Feature generation is idempotent by `(stock_id, date)`.
- Tag generation is idempotent by `(stock_id, date, tag)`.
- Snapshot generation is idempotent by `(stock_id, date, horizon)`.
- No AI text is used as a source feature.
- No financial data is visible before `filing_date`.
- Missing data is represented and lowers confidence.
- All rules remain explainable and backtestable.

