# Research Platform Implementation Status

Last updated: 2026-07-10

## Current verdict

`NO ROBUST EDGE FOUND`

The latest inspected legacy baseline evidence has negative total R and PF below 1.0. No candidate has passed OOS, walk-forward, cost, plateau and locked-test gates in the new platform.

## Phase status

| Phase | Status | Evidence / next gate |
|---|---|---|
| 0 Asset inventory and specification | COMPLETE | Inventory, spec, migration plan, risk register and ADRs created. |
| 1 Real vertical slice | COMPLETE | Real cache -> catalog -> legacy evidence -> metadata -> FastAPI -> BFF -> dashboard verified. |
| 2 Catalog / universe / tiers | PARTIAL | Current 654-contract snapshot and Tier C catalog implemented; historical universe/OI/premium remain missing. |
| 3 DSL / state / event backtest | PARTIAL | Versioned five-factor DSL and legacy engine guardrail tests exist; full OI replay remains blocked. |
| 4 Baseline / factor families | NOT_STARTED | Legacy evidence only; full OI family blocked by missing data. |
| 5 Parameter search / plateau | NOT_STARTED | Must not access locked test. |
| 6 Walk-forward / ablation / stress | NOT_STARTED | Required before candidate promotion. |
| 7 24/7 orchestrator | PARTIAL | Persistent idempotent queue, heartbeat, retry, stale recovery and graceful shutdown verified on one host; Docker/distributed mode unavailable. |
| 8 OpenAI council | BLOCKED_BY_CONFIGURATION | `OPENAI_API_KEY` is empty; local research must continue. |
| 9 Independent dashboard | COMPLETE_LOCAL | Independent sibling repo, auth, BFF and real-data browser E2E verified. |
| 10 Production deployment | BLOCKED_BY_PREREQUISITES | Docker, Vercel CLI and Cloudflared unavailable. |

## Verified checks

- `python -m pytest backend/scripts/tests/test_crypto_backtester.py -q`: 4 passed.
- `python -m py_compile backend/scripts/crypto_bt_data.py backend/scripts/crypto_backtester.py`: passed.
- External cache opened read-only and schema/counts recorded in the inventory.
- Real API returned 9,498,316 klines, 664,756 funding rows, five imported experiments and a 654-contract current universe.
- Persistent orchestrator completed catalog and universe jobs and returned to `IDLE`.
- Dashboard typecheck, ESLint, production build, npm audit and desktop/mobile browser E2E passed.
- No deployment, 24/7 runtime or OpenAI call has been claimed.
