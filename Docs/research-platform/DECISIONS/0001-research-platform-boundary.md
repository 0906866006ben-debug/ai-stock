# ADR 0001: Isolate the autonomous research platform

Status: Accepted

## Context

The repository already serves a Taiwan-stock decision-support product and contains crypto scanning, demo trading and experimental backtesting scripts. The autonomous research workload has different data, uptime, security and validation requirements.

## Decision

Place new backend code under `backend/app/research_platform/`, expose only `/api/v1` research routes, and create the dashboard as a sibling Git repository named `ai-stock-research-dashboard`.

The research package may consume existing data/backtest artifacts through explicit adapters. It must not import order placement, mutate source caches during cataloging, change existing stock API contracts or share frontend bundles with `ai-stock-frontend`.

## Consequences

- Existing product behavior can be tested and deployed independently.
- The dashboard can use a server-side BFF token without exposing it to browsers.
- Legacy scripts require adapters before their evidence is eligible for candidate gates.
- Duplicate framework setup is accepted to preserve deployment and security isolation.

