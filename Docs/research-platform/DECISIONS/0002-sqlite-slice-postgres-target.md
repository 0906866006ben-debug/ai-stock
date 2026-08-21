# ADR 0002: Use SQLite for the local vertical slice, retain PostgreSQL as production target

Status: Accepted with migration requirement

## Context

The existing crypto market cache and backtest artifacts are SQLite/files, while PostgreSQL and Redis are not configured on the host and Docker is not installed. Blocking the first slice on unavailable infrastructure would prevent validation of the real data-to-dashboard flow.

## Decision

Use a dedicated SQLite metadata repository for the local vertical slice and persistent single-host job queue. Keep table ownership, schemas and repository methods isolated so production adapters can migrate metadata to PostgreSQL and distributed locks/queues to Redis without changing API contracts.

SQLite is not approved for distributed workers. Candidate validation, locked-test ownership and multi-worker optimization remain disabled until the PostgreSQL/Redis migration and parity tests pass.

## Consequences

- The real cache, evidence import, API, BFF and dashboard can be tested now.
- Restart recovery and idempotent jobs work on one host.
- Docker production and distributed worker claims remain blocked and visible in system status.

