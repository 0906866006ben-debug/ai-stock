# Autonomous Alpha Research Implementation Spec

## Objective

Add a crypto research platform beside the Taiwan-stock product without changing the existing recommendation or trading surfaces. The first deliverable is a real vertical slice:

`existing SQLite cache -> catalog and quality summary -> immutable baseline evidence -> research metadata store -> /api/v1 -> independent dashboard`

The system searches for evidence about Funding, OI, EMA, Volume and RSI. It never claims alpha from in-sample results, one symbol, mock data or an unvalidated parameter peak.

## Module boundary

New backend code lives under `backend/app/research_platform/` and exposes a router through `backend/app/api/routes/research.py`. It may read existing crypto artifacts through adapters, but it must not import testnet or live-order modules.

Core services:

- `settings`: allowlisted paths, auth token, safety limits and feature flags.
- `catalog`: inspect SQLite/Parquet assets read-only, calculate coverage and Data Tier.
- `repository`: persist system state, runs, metrics, factor findings, candidates and jobs.
- `universe`: fetch current Binance USD-M perpetual metadata and save timestamped snapshots.
- `strategy_dsl`: versioned, validated definitions with explicit data requirements and invalidation.
- `evidence_import`: parse existing run reports/trades without rewriting source artifacts.
- `orchestrator`: persistent idempotent jobs, heartbeat, stale recovery and pause/resume.
- `budget`: OpenAI event and monthly hard-stop enforcement; no API call when a key is absent.
- `api`: stable Pydantic contracts, request IDs, bearer auth and explicit data timestamps.

## Data contracts

All timestamps are timezone-aware ISO 8601 in API responses and UTC milliseconds at market-data storage boundaries. Every result records `source`, `observed_at`, `data_version`, `engine_version`, `is_mock`, `is_stale` and warnings.

Data tiers:

- `DATA_TIER_A_FULL_DERIVATIVES`: OHLCV, settled funding, premium and historical OI.
- `DATA_TIER_B_NO_HISTORICAL_OI`: OHLCV and funding, but OI unavailable or insufficient.
- `DATA_TIER_C_PRICE_FUNDING_ONLY`: price and settled funding without other derivatives history.
- `DATA_TIER_D_PRICE_ONLY`: price only.
- `INVALID_DATA`: schema or quality failure.

The current cache is at most Tier B and usually Tier C until premium history is added. Missing OI is null, never zero.

## Baseline strategy contract

`BASELINE_FUNDING_OI_MEAN_REVERSION_V1` has a long and short branch, an intraday horizon, explicit setup/armed/trigger/cancel rules, next-bar-open execution, conservative same-bar stop/target resolution, fee, slippage and funding payments. Full-five-factor execution requires Tier A. A no-OI research family is separately identified and cannot be presented as validation of the full strategy.

The first imported evidence uses the existing no-OI baseline and is labeled `FUNDING_PRICE_TECHNICAL_PROXY`, not `FULL_FIVE_FACTOR`.

## Candidate gate

A candidate cannot exceed `EXPERIMENTAL` from imported legacy evidence alone. Promotion requires positive OOS expectancy, PF >= 1.15, adequate trades across symbols, mostly positive walk-forward folds, cost robustness, no critical data finding and explicit locked-test provenance. `ROBUST_CANDIDATE` additionally requires locked test, 1.5x costs, parameter plateau, multi-symbol stability and acceptable drawdown.

When no strategy passes, API and dashboard return `NO ROBUST EDGE FOUND`.

## API slice

Initial routes:

- `GET /api/v1/health`
- `GET /api/v1/system/status`
- `POST /api/v1/system/pause`
- `POST /api/v1/system/resume`
- `GET /api/v1/dashboard/overview`
- `GET /api/v1/market/data-health`
- `GET /api/v1/research/experiments`
- `GET /api/v1/strategies/candidates`
- `GET /api/v1/strategies/{id}/factor-findings`
- `GET /api/v1/workers`
- `GET /api/v1/jobs`
- `GET /api/v1/openai/usage`

Mutating routes require a bearer token and remain unavailable when no backend token is configured. Read routes may be configured private in production.

## Non-goals for the first vertical slice

- No Binance mainnet order creation or live-trading enablement.
- No automatic use of the sealed OOS/locked-test segment.
- No claim that missing historical OI was reconstructed.
- No OpenAI-generated changes to the engine, costs, data validator or risk hard limits.
- No modification of the existing Taiwan-stock frontend or trading bots.
- No mock production dashboard data.

## Test plan

- Unit: tiers, missing OI, DSL validation, candidate gate, budget hard stop, report parser.
- Property: future mutation cannot change earlier signals; higher fees/slippage cannot improve net return.
- API: auth, stable error shape, timestamps/source fields, no secret fields.
- Integration: read-only import from a temporary SQLite cache and real artifact parser.
- Frontend: loading, error, empty/no-edge and source timestamp states; no direct backend token in client bundle.
- Build: backend focused pytest, frontend lint/type check/build and browser smoke test.

