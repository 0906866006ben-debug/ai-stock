# Research Platform Implementation Status

Last updated: 2026-07-11

## Current verdict

`NO ROBUST EDGE FOUND`

The strict closed-bar TRAIN baseline produced 9 trades and 3.78 total R. The matched Funding ablation shows positive marginal expectancy of 0.15R versus Funding Disabled, but the smallest group has only 7 trades. This is low-strength, insufficient evidence, not alpha. No candidate has passed sample-size, OOS, walk-forward, cost, plateau and locked-test gates.

## Phase status

| Phase | Status | Evidence / next gate |
|---|---|---|
| 0 Asset inventory and specification | COMPLETE | Inventory, spec, migration plan, risk register and ADRs created. |
| 1 Real vertical slice | COMPLETE | Real cache -> catalog -> legacy evidence -> metadata -> FastAPI -> BFF -> dashboard verified. |
| 2 Catalog / universe / tiers | PARTIAL | Current 654-contract snapshot and Tier C catalog implemented; historical universe/OI/premium remain missing. |
| 3 DSL / state / event backtest | PARTIAL | Versioned five-factor DSL and legacy engine guardrail tests exist; full OI replay remains blocked. |
| 4 Baseline / factor families | PARTIAL | Strict Funding baseline and matched ablation completed; OI family remains blocked by missing history. |
| 5 Parameter search / plateau | BLOCKED_INSUFFICIENT_SAMPLE | Strict baseline has 9 trades; the enforced floor is 200. |
| 6 Walk-forward / ablation / stress | PARTIAL | Funding ablation is recorded but below the 100-trade evidence floor; walk-forward requires 300. |
| 7 24/7 orchestrator | PARTIAL | Persistent idempotent queue, heartbeat, retry, stale recovery and graceful shutdown verified on one host; Docker/distributed mode unavailable. |
| 8 OpenAI council | BLOCKED_BY_CONFIGURATION | `OPENAI_API_KEY` is empty; local research must continue. |
| 9 Independent dashboard | COMPLETE_LOCAL | Independent sibling repo, auth, BFF and real-data browser E2E verified. |
| 10 Production deployment | BLOCKED_BY_PREREQUISITES | Vercel authentication, Docker and Cloudflared are unavailable. |

## Verified checks

- `.venv/Scripts/python.exe -m pytest backend/scripts/tests/test_crypto_backtester.py -q`: 7 passed.
- `.venv/Scripts/python.exe -m pytest backend/tests/research_platform -q`: 20 passed.
- `python -m py_compile backend/scripts/crypto_bt_data.py backend/scripts/crypto_backtester.py`: passed.
- External cache opened read-only and schema/counts recorded in the inventory.
- Real API cataloged 9,498,881 klines, 664,756 funding rows and 11 imported experiments. The latest current-only universe snapshot is not historical-universe evidence.
- Strict pre-OOS Funding runs: baseline 9 trades / 3.78R / PF 4.13; disabled 10 / 2.70R / PF 2.18; required 7 / 4.98R / no losing trades. All remain insufficient evidence.
- API validation gates block factor promotion at 7/100 matched trades, parameter search at 9/200, and walk-forward/candidate promotion at 9/300.
- Persistent orchestrator completed catalog and universe jobs and returned to `IDLE`.
- Dashboard typecheck, ESLint, production build, npm audit and desktop/mobile browser E2E passed. Mobile has no horizontal overflow or text occlusion.
- No deployment, 24/7 runtime or OpenAI call has been claimed.
