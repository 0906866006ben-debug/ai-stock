# Research Platform Migration Plan

## Principles

Migration is additive. Existing stock APIs, crypto scanner, testnet bot and backtest artifacts remain operational. Source market data is read-only during discovery/import, and all new jobs are idempotent.

## Stages

1. **Catalog only**: register the external SQLite cache and existing run artifacts without copying or mutating them.
2. **Vertical slice metadata**: persist catalog, imported experiments and service state in a research repository with versioned migrations.
3. **API isolation**: mount `/api/v1` routes without changing existing response models or paths.
4. **Universe snapshots**: fetch current Binance exchange metadata and persist each snapshot; explicitly flag incomplete historical reconstruction.
5. **Strategy contracts**: register baseline/proxy families and prevent Tier B/C data from running the full-five-factor strategy.
6. **Research validation**: add ablation, parameter search, walk-forward and locked-test services with separate dataset permissions.
7. **Production stores**: migrate metadata to PostgreSQL and queue/locks to Redis. Market history remains partitioned Parquet/DuckDB after parity checks.
8. **Independent dashboard**: deploy only after BFF auth, API HTTPS tunnel and production no-mock checks pass.
9. **24/7 services**: enable restart policies, heartbeats and stale recovery after Docker and host prerequisites are installed.

## Compatibility and rollback

- Existing routes are untouched; removing the research router restores the previous API.
- New database objects use a `research_` ownership boundary or dedicated database.
- A failed import leaves source files unchanged and records an error finding.
- Production schema migrations must be forward-only with a documented down/restore procedure.
- Dashboard deployment can be rolled back independently because it is a separate repository.

## Manual prerequisites

- Install Docker Desktop or Docker Engine before Compose verification.
- Install Cloudflared and establish an authenticated tunnel before exposing the API.
- Configure PostgreSQL/Redis URLs and a strong backend bearer token.
- Configure Vercel project variables server-side only.
- Explicitly approve any locked-test execution and any future demo-trading transition.

