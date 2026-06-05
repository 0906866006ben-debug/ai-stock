# Database Audit Report

Date: 2026-06-03  
Scope: SQLite stores, SQLite access code, JSON cache policy, PIT/backtest readiness.  
Non-goals: no DB deletion, no DB rebuild, no PostgreSQL/MySQL migration, no API response schema changes, no `/analyze/tw` wiring changes.

## 1. Current Database Inventory

The project uses a hybrid local data layer:

| Layer | Current storage | Role | Canonical? |
|---|---|---|---|
| OHLCV / price-volume history | `backend/historical_data.db` | Local market data warehouse for price bars, backtest signals, and trades | Yes |
| PIT fundamentals / chip / valuation | `backend/pit_fundamentals.db` | Point-in-time foundation for backtests and CAN SLIM screening | Yes |
| Stock master | `backend/data/stock_master.db` | Persistent Taiwan stock directory cache | Yes |
| Quality snapshots | `backend/data/quality_snapshots.db` | Quarterly quality-watch snapshot store | Supporting store |
| AI / page / news / derived cache | `backend/data/cache/**/*.json` | Reusable JSON cache for non-tabular or response-shaped payloads | Cache only |
| Telegram watchlist | `backend/telegram_watchlist.db` | Runtime watchlist DB when initialized | Not present locally during audit |
| `backend/data/backtest/*.db` | Historical duplicate/alternate stores | Older or non-canonical backtest data stores | Not canonical |
| `artifacts/**/*.db` | Backtest run outputs | Experiment outputs with `backtest_trades` | Artifact only |

## 2. SQLite Files and Roles

| SQLite file | Size | Main tables | Managing service/script | Known users |
|---|---:|---|---|---|
| `backend/historical_data.db` | 916.8 MB | `ohlcv`, `backtest_signals`, `backtest_trades` | `HistoricalDataStore`, `signal_replay`, `trade_simulator`, `refresh_data.py` | backtests, CAN SLIM ranking/screening, heatmap, adjusted prices, entry context |
| `backend/pit_fundamentals.db` | 8.8 GB | `month_revenue`, `institutional`, `margin`, `per`, `financials`, `balance_sheet`, `cash_flow`, `fundamentals_backfill_progress` | `PitFundamentalsStore`, `download_fundamentals.py` | CAN SLIM PIT inputs, durability, ranking, walk-forward, screening fallback |
| `backend/data/stock_master.db` | 0.5 MB | `stock_master`, `stock_master_meta` | `StockMasterCache`, `tw_stocks_list.py` | `/tw/stocks`, stock directory/search |
| `backend/data/quality_snapshots.db` | 16 KB | `quality_snapshots` | `QualitySnapshotStore`, `generate_quality_snapshot.py` | quality-watch API/router |
| `backend/data/backtest/historical_data_store.db` | 401.9 MB | `ohlcv` | Same schema as `HistoricalDataStore` | Non-canonical local copy |
| `backend/data/backtest/pit_fundamentals_store.db` | 4.0 GB | PIT tables | Same schema as `PitFundamentalsStore` | Non-canonical local copy |
| `artifacts/_tmp/debug_live/ohlcv.db` | 57 KB | `ohlcv` | debug/test output | Artifact |
| `artifacts/_tmp/debug_live/pit.db` | 64 KB | PIT subset | debug/test output | Artifact |
| `artifacts/canslim_attribution/canslim_real_v1_attribution.db` | 1.9 MB | `backtest_trades` | CAN SLIM attribution run | Artifact |
| `artifacts/canslim_multicycle/canslim_multicycle_v1.db` | 6.6 MB | `backtest_trades` | CAN SLIM multicycle run | Artifact |
| `artifacts/canslim_real_walk_forward/*.db` | 28 KB-13 MB | `backtest_trades` | Walk-forward experiments | Artifact |

`backend/telegram_watchlist.db` is referenced by `telegram_service.py`, but the file was not present during this audit.

## 3. Table Schemas

### Canonical OHLCV Store

| Table | Columns | Primary key | Row count | Date fields | Stock field | Backtest suitability | Look-ahead risk |
|---|---|---|---:|---|---|---|---|
| `ohlcv` | `stock_id`, `date`, `open`, `high`, `low`, `close`, `volume`, `turnover` | `(stock_id, date)` | 7,054,513 | `date` | `stock_id` | Good for PIT price bars when queried `date <= as_of` | Low for historical bars; execution logic must avoid same-close assumptions |
| `backtest_signals` | `run_id`, `signal_date`, `stock_id`, scores/features, entry tier fields | `(run_id, signal_date, stock_id)` | 61,754 | `signal_date` | `stock_id` | Good as replay output, not raw market data | Medium if signals were generated with non-PIT inputs |
| `backtest_trades` | `run_id`, `trade_id`, `stock_id`, `signal_date`, `entry_date`, `exit_date`, returns, tier fields | `(run_id, trade_id)` | 61,754 | `signal_date`, `entry_date`, `exit_date` | `stock_id` | Good as experiment output | Depends on simulator assumptions and source signal PIT discipline |

### Canonical PIT Fundamentals Store

| Table | Columns | Primary key | Row count | Date fields | Stock field | Backtest suitability | Look-ahead risk |
|---|---|---|---:|---|---|---|---|
| `month_revenue` | `stock_id`, `date`, `revenue`, `revenue_yoy`, `revenue_mom`, `raw_json` | `(stock_id, date)` | 355,739 | `date` | `stock_id` | Usable, but needs announcement/available date for strict PIT | Medium: `date` is period/date, not necessarily market-available date |
| `institutional` | `stock_id`, `date`, `foreign_net`, `trust_net`, `dealer_net`, `raw_json` | `(stock_id, date)` | 5,006,273 | `date` | `stock_id` | Good for daily PIT if source is same-day post-close | Medium: same-day availability/execution timing must be explicit |
| `margin` | `stock_id`, `date`, `margin_balance`, `short_balance`, `raw_json` | `(stock_id, date)` | 5,904,969 | `date` | `stock_id` | Usable with delayed-availability assumption | Medium: publication delay can leak if treated as pre-open same day |
| `per` | `stock_id`, `date`, `per`, `pbr`, `dividend_yield`, `raw_json` | `(stock_id, date)` | 6,420,961 | `date` | `stock_id` | Good daily valuation snapshot | Low-medium: confirm whether date is close-of-day valuation |
| `financials` | `stock_id`, `period_end`, `filing_date`, `eps`, `roe`, margins, `raw_json` | `(stock_id, period_end)` | 114,520 | `period_end`, `filing_date` | `stock_id` | Good: reads gate on `filing_date <= as_of` | Low if all code keeps using `filing_date` |
| `balance_sheet` | `stock_id`, `period_end`, `filing_date`, `equity`, `equity_parent`, `raw_json` | `(stock_id, period_end)` | 106,872 | `period_end`, `filing_date` | `stock_id` | Good: reads gate on `filing_date <= as_of` | Low if all code keeps using `filing_date` |
| `cash_flow` | `stock_id`, `period_end`, `filing_date`, `cfo`, `raw_json` | `(stock_id, period_end)` | 70,602 | `period_end`, `filing_date` | `stock_id` | Good: reads gate on `filing_date <= as_of` | Low if all code keeps using `filing_date` |
| `fundamentals_backfill_progress` | `stock_id`, `dataset`, `start_date`, `completed_at`, `row_count` | `(stock_id, dataset, start_date)` | 17,799 | `start_date`, `completed_at` | `stock_id` | Operational metadata only | Not a strategy input |

### Supporting Stores

| Table | DB | Columns | Primary key | Row count | Role | Look-ahead risk |
|---|---|---|---|---:|---|---|
| `stock_master` | `backend/data/stock_master.db` | `stock_code`, `company_name`, `market_type`, `industry`, `source`, `raw_json`, `updated_at` | `stock_code` | 1,967 | Current stock directory cache | Survivorship risk if used as historical universe |
| `stock_master_meta` | `backend/data/stock_master.db` | `key`, `value` | `key` | 2 | Cache metadata | None |
| `quality_snapshots` | `backend/data/quality_snapshots.db` | `quarter`, `as_of_date`, `generated_at`, `snapshot_json`, `symbols_json` | `quarter` | 1 | Quality watch snapshots | Snapshot JSON must be treated as generated output |
| `watchlist` | `backend/telegram_watchlist.db` | `chat_id`, `stock_code`, `stock_name`, `created_at` | `(chat_id, stock_code)` | N/A | Telegram watchlist | Not present during audit |

## 4. Existing Indexes

| DB/table | Existing indexes |
|---|---|
| `ohlcv` | PK autoindex `(stock_id, date)`, `idx_ohlcv_date(date)`, `idx_ohlcv_stock(stock_id)` |
| `backtest_signals` | PK autoindex `(run_id, signal_date, stock_id)`, `idx_signals_date(signal_date)`, `idx_signals_type(candidate_type)` |
| `backtest_trades` | PK autoindex `(run_id, trade_id)`, `idx_trades_run(run_id)` |
| `month_revenue` | PK autoindex `(stock_id, date)`, `idx_month_revenue_date(stock_id, date)` |
| `institutional` | PK autoindex `(stock_id, date)`, `idx_institutional_date(stock_id, date)` |
| `margin` | PK autoindex `(stock_id, date)`, `idx_margin_date(stock_id, date)` |
| `per` | PK autoindex `(stock_id, date)`, `idx_per_date(stock_id, date)` |
| `financials` | PK autoindex `(stock_id, period_end)`, `idx_financials_filing(stock_id, filing_date)` |
| `balance_sheet` | PK autoindex `(stock_id, period_end)`, `idx_balance_sheet_filing(stock_id, filing_date)` |
| `cash_flow` | PK autoindex `(stock_id, period_end)`, `idx_cash_flow_filing(stock_id, filing_date)` |
| `stock_master` | PK autoindex `(stock_code)`, `idx_stock_master_market(market_type)`, `idx_stock_master_industry(industry)` |
| `quality_snapshots` | PK autoindex `(quarter)`, `idx_quality_snapshots_generated_at(generated_at)` |

Several named `(stock_id, date)` indexes duplicate primary-key indexes. They are not harmful, but future migrations should avoid adding more redundant stock-first indexes.

## 5. Query Plan Findings

| Query | Current plan summary | Verdict |
|---|---|---|
| Single-stock OHLCV range | `SEARCH ohlcv USING INDEX sqlite_autoindex_ohlcv_1 (stock_id=? AND date>? AND date<?)` | Good |
| Single-stock recent N OHLCV as-of | `SEARCH ohlcv USING INDEX sqlite_autoindex_ohlcv_1 (stock_id=? AND date<?)` | Good |
| All stocks on one OHLCV date | `SEARCH ohlcv USING INDEX idx_ohlcv_date (date=?)` | Good |
| Trading dates in range | `SEARCH ohlcv USING COVERING INDEX idx_ohlcv_date (date>? AND date<?)` | Good |
| Market heatmap latest two bars | Planner scanned `ohlcv` with `idx_ohlcv_stock` and used temp B-trees | Weak; likely scans more than needed |
| Backtest signals by run | `SEARCH backtest_signals USING INDEX sqlite_autoindex_backtest_signals_1 (run_id=?)` | Good |
| Backtest trades by run | `SEARCH backtest_trades USING INDEX sqlite_autoindex_backtest_trades_1 (run_id=?)` | Good |
| Single-stock `month_revenue` as-of | `SEARCH month_revenue USING INDEX idx_month_revenue_date (stock_id=? AND date<?)` | Good |
| Single-stock `institutional` as-of | `SEARCH institutional USING INDEX idx_institutional_date (stock_id=? AND date<?)` | Good |
| Single-stock `margin` as-of | `SEARCH margin USING INDEX idx_margin_date (stock_id=? AND date<?)` | Good |
| Single-stock `per` as-of | `SEARCH per USING INDEX idx_per_date (stock_id=? AND date<?)` | Good |
| Financials by filing date | Uses `idx_financials_filing`, then temp B-tree for `ORDER BY period_end DESC` | Acceptable; per-stock row set is small |
| Balance sheet by filing date | Uses `idx_balance_sheet_filing`, then temp B-tree for `ORDER BY period_end DESC` | Acceptable |
| Cash flow by filing date | Uses `idx_cash_flow_filing`, then temp B-tree for `ORDER BY period_end DESC` | Acceptable |
| `SELECT DISTINCT stock_id FROM financials` | Covering index scan on `idx_financials_filing` | Acceptable for occasional universe construction |
| Stock master market/industry filter | Uses filter index, then temp B-tree for `ORDER BY stock_code` | Weak but small table |
| Latest quality snapshot | Full scan + temp B-tree | Weak but currently only one row |

## 6. Missing / Weak Indexes

Recommended safe, idempotent index migration is limited to additional date-first and ordered-filter indexes:

| Proposed index | Reason | Risk |
|---|---|---|
| `ohlcv(date, stock_id)` | Faster all-stock daily scans and future feature generation; may help heatmap-style date windows | Large index on 7M rows; run only with enough disk/time |
| `month_revenue(date, stock_id)` | Cross-sectional monthly feature builds | Medium index build cost |
| `institutional(date, stock_id)` | Cross-sectional daily chip scans | Large index build cost |
| `margin(date, stock_id)` | Cross-sectional daily risk scans | Large index build cost |
| `per(date, stock_id)` | Cross-sectional daily valuation scans | Large index build cost |
| `financials(filing_date, stock_id, period_end)` | Cross-sectional PIT financial features by available date | Low-medium |
| `balance_sheet(filing_date, stock_id, period_end)` | Cross-sectional PIT balance-sheet features by available date | Low-medium |
| `cash_flow(filing_date, stock_id, period_end)` | Cross-sectional PIT cash-flow features by available date | Low-medium |
| `stock_master(market_type, stock_code)` | Avoid temp sort for market-filtered directory reads | Low |
| `stock_master(industry, stock_code)` | Avoid temp sort for industry-filtered directory reads | Low |

Do not run `VACUUM` automatically. For 8.8 GB PIT DBs, `VACUUM` may require substantial extra disk space and a long exclusive operation.

## 7. JSON Cache Classification

Current JSON cache under `backend/data/cache`:

| Namespace | Files | Size bytes | Classification | Recommendation |
|---|---:|---:|---|---|
| `analyze_tw` | 6 | 265,335 | AI/page response cache | Keep JSON with daily key and stale policy |
| `tw_agent_analysis` | 4 | 21,480 | LLM/agent response cache | Keep JSON; never use as backtest input |
| `n_pillar` | 39 | 211,863 | News/N-pillar derived cache | Keep JSON short term; store source news metadata separately if used in screening |
| `market_heatmap` | 1 | 7,748 | Quantifiable derived market snapshot | Candidate for SQLite if historical heatmap/trend analysis is needed |
| `dividend_result` | 2,517 | 4,925,849 | Quantifiable corporate action data | Candidate for SQLite table with `stock_id`, event dates, source, updated_at |
| `futures_sentiment` | 3 | 421 | Quantifiable sentiment snapshot | Candidate for SQLite if used in regime/backtests |
| `live_finmind_inputs` | 2 | 10,119 | Live decoded provider inputs | Candidate for PIT/table storage only if source dates and availability are explicit |
| `sector_map` | 1 | 156,474 | Reference/map cache | Keep JSON if mostly static; add source/updated_at policy |

Policy:

- Keep AI text, LLM responses, page-shaped responses, and one-off diagnostics in JSON.
- Move data that is queryable, sortable, backtestable, or screening-critical into SQLite over time.
- Every cache namespace needs a TTL or stale policy. `analyze_tw` is day-keyed; `stock_master` has TTL; several JSON namespaces need explicit documented stale behavior.

## 8. PIT / Look-ahead Bias Risks

| Area | Risk | Required guard |
|---|---|---|
| Financial statements | Using `period_end` as the availability date leaks future filings | Continue gating on `filing_date <= as_of` |
| Monthly revenue | Current table has `date` but no explicit `available_date` | Add `available_date` before strict historical revenue backtests |
| Margin and short balance | Publication timing may lag trading date | Define next-session availability for strategy replay |
| Institutional flow | Same-day data may be post-close | Do not allow same-day close entry using same-day flow unless execution assumption says next bar |
| Stock master | Current listed universe excludes delisted names | Document survivorship bias; use delisting/PIT universe for long backtests |
| JSON caches | AI text and page responses are not PIT data | Never feed AI text back into backtest features |
| `created_at` fields | Pipeline creation time is not market availability | Do not use `created_at` as PIT available date |
| `raw_json` fields | Provider schemas may change silently | Keep source dataset, field names, and timestamps traceable |

## 9. SQLite Connection Policy

Current patterns:

| Module | Pattern | Notes |
|---|---|---|
| `HistoricalDataStore` | Context manager, `row_factory`, WAL, `synchronous=NORMAL`, cache pragmas | Good for read-heavy backtest store; no explicit timeout/busy_timeout |
| `PitFundamentalsStore` | Context manager, `row_factory`, WAL, `synchronous=NORMAL`, cache pragmas | Good for read-heavy PIT store; no explicit timeout/busy_timeout |
| `StockMasterCache` | Context manager, `row_factory`, WAL | Good small cache; no explicit timeout/busy_timeout |
| `QualitySnapshotStore` | Context manager, `row_factory`, WAL | Fine; latest query could use composite order index later |
| `telegram_service` | `with sqlite3.connect`, WAL, no row_factory | Acceptable for tiny watchlist; add timeout/busy_timeout if concurrent webhooks grow |
| Backtest signal/trade modules | Direct connections, schema init, WAL | Works; future cleanup can reuse `connect_sqlite` |
| scripts | Direct connections for reporting/analysis | Acceptable but should close in `finally` or context |

WAL recommendation:

- Keep WAL for canonical read-heavy stores where current code already enables it.
- Do not newly force WAL from migration scripts; respect existing DB policy.
- WAL creates `.db-wal` and `.db-shm`; backup scripts must copy or checkpoint safely.
- For artifact DBs, WAL is optional and not worth normalizing.

## 10. Recommended Safe Migrations

Implemented as a script, not automatically executed in this audit:

`backend/app/db/migrations/001_sqlite_indexes.py`

Properties:

- Connects to `backend/historical_data.db`, `backend/pit_fundamentals.db`, and `backend/data/stock_master.db`.
- Checks DB/table/columns before creating indexes.
- Uses `CREATE INDEX IF NOT EXISTS`.
- Skips equivalent existing indexes.
- Logs status per index.
- Runs `PRAGMA optimize`.
- Does not run `VACUUM`.
- Does not modify API schemas or JSON cache.

Suggested command when ready:

```bash
python -m backend.app.db.migrations.001_sqlite_indexes
```

Because the PIT DB is large, run this when there is enough disk headroom and the backend is not under active write load.

## 11. Recommended Feature Layer

Add a future SQLite feature layer, but do not wire it into `/analyze/tw` until it is backfilled and validated:

| Table | Purpose | PIT requirement |
|---|---|---|
| `daily_stock_features` | Daily technical, chip, valuation, risk, confidence fields | All joins must use `date <= as_of` and filing/available dates |
| `stock_dynamic_tags` | Queryable daily tags for screening and AI explanation | Tags must cite source table/fields |
| `analysis_snapshots` | Horizon-separated analysis snapshot for historical tracking | Snapshots must store source quality and invalidation data |

Feature values must be rule-based and reproducible. AI text can summarize features, but must not become the feature source.

## 12. Recommended Tag / Score Layer

The tag/score layer should store machine-readable outputs:

| Layer | Examples | Source requirement |
|---|---|---|
| Technical tags | `ma_bullish_alignment`, `breakout_watch`, `overextended` | OHLCV date and indicator window |
| Chip tags | `foreign_5d_net_buy`, `trust_accumulation`, `margin_risk_rising` | `institutional`/`margin` date ranges |
| Valuation tags | `high_per_percentile`, `pbr_compression` | `per` date and historical window |
| Risk tags | `low_liquidity`, `price_limit_recent`, `event_window` | source table and timestamp |
| Confidence score | missing-data penalty, stale-data penalty, source quality | explicit missing fields and staleness |

Every tag should include `source_table`, `source_fields`, and a concise rule reason.

## 13. Recommended Follow-up Tasks

1. Run `001_sqlite_indexes.py` during a low-activity window and capture its status output.
2. Add `available_date` to monthly revenue only through a future idempotent migration and backfill plan.
3. Define exact availability rules for institutional, margin, PER/PBR, and monthly revenue.
4. Add a read-only audit CLI that emits markdown/JSON schema snapshots.
5. Design and backfill `daily_stock_features` from OHLCV/PIT stores.
6. Add feature-generation tests for no look-ahead joins.
7. Add cache metadata/stale policy for `dividend_result`, `n_pillar`, `market_heatmap`, and `futures_sentiment`.
8. Keep `/analyze/tw` live path unchanged until feature tables are complete and validated.
9. Document survivorship-bias limits of current `stock_master` for historical universe selection.

