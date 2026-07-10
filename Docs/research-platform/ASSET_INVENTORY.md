# AI-Stock Research Platform Asset Inventory

Last verified: 2026-07-10 (Asia/Taipei)

## Runtime map

| Area | Current asset | Classification | Evidence / action |
|---|---|---|---|
| FastAPI | `backend/app/main.py` | REUSE_WITH_ADAPTER | Existing API remains intact; research routes mount under `/api/v1`. |
| Pydantic | `backend/app/models/` | REUSE_AS_IS | Add research-only schemas in a separate module. |
| SQLite utilities | `backend/app/db/sqlite_utils.py` | REUSE_WITH_ADAPTER | Useful patterns, but research metadata gets its own repository boundary. |
| Binance public client | `backend/scripts/crypto_bt_data.py` | REUSE_WITH_ADAPTER | Retry, rate-limit handling, klines and settled funding are already implemented. |
| Crypto data cache | `C:/Users/09068/.crypto_backtest/klines.db` | REUSE_AS_IS (read-only import) | Real cache; do not overwrite during catalog/import. |
| Repo crypto DB | `backend/data/crypto_backtest/klines.db` | DEPRECATE | Verified zero bytes; it must never shadow the real cache. |
| Crypto backtester | `backend/scripts/crypto_backtester.py` | REUSE_WITH_ADAPTER | Costs, funding payments, OOS seal and conservative same-bar fills are implemented. |
| Backtest tests | `backend/scripts/tests/test_crypto_backtester.py` | REUSE_AS_IS | Four focused tests passed on 2026-07-10. |
| Crypto run artifacts | `backend/data/crypto_backtest/runs/` | REUSE_WITH_ADAPTER | Thirteen run directories found; reports are imported as immutable evidence. |
| Taiwan stock engines | `backend/app/services/strategy/` | REUSE_AS_IS | Out of scope for research-platform changes. |
| Existing frontend | `ai-stock-frontend/` | REUSE_AS_IS | Must remain separate from the research dashboard. |
| Scheduler / worker | No general research worker found | REPLACE_WITH_REASON | Add a research-specific persistent job runner without changing trading bots. |
| PostgreSQL / Redis | URLs not configured in inspected allowlist | REPLACE_WITH_REASON | Add optional production adapters and Compose definitions; local slice uses a repository interface. |
| Docker / tunnel | CLI not installed | REPLACE_WITH_REASON | Supply configuration and exact manual prerequisites; do not claim runtime verification. |
| GitHub CLI | `C:/Program Files/GitHub CLI/gh.exe` | REUSE_AS_IS | Authentication must be checked before remote writes. |

## Existing market data

Primary source: `C:/Users/09068/.crypto_backtest/klines.db` (1,402,179,584 bytes at verification).

| Dataset | Rows | Symbols | First timestamp (ms UTC) | Last timestamp (ms UTC) | Schema |
|---|---:|---:|---:|---:|---|
| 1m klines | 6,381,688 | 91 | 1759248000000 | 1783586760000 | `sym,itv,open_ms,o,h,l,c,v,qv` |
| 15m klines | 125,860 | 79 | 1759254300000 | 1783586700000 | same |
| 1h klines | 2,868,851 | 522 | 1759017600000 | 1783584000000 | same |
| 1d klines | 121,917 | 551 | 1755388800000 | 1783555200000 | same |
| settled funding | 664,756 | 522 | 1759190400002 | 1783584000001 | `sym,ts,rate` |

Timestamps are Unix milliseconds and interpreted as UTC. OI, mark price, index price and premium-index history are not present in this store. Missing OI must remain null and prevents a `DATA_TIER_A_FULL_DERIVATIVES` classification.

The cache includes dates after the historical OOS boundary of 2026-06-01. Cataloging those rows is allowed; optimizers must not read them. Existing post-boundary reports are evidence only and must not be used to tune the same strategy generation.

## Existing research evidence

The latest inspected baseline report contains 119 trades, total R -16.64, profit factor 0.74 and net PnL -83.19 after costs. This is not evidence of alpha. The dashboard must show `NO ROBUST EDGE FOUND` unless a candidate passes all configured gates.

## Configuration and secrets

Only allowlisted variable names were inspected, never values. `GITHUB_TOKEN` is set and `OPENAI_API_KEY` is empty. Docker, Vercel CLI and Cloudflared are not installed. `LIVE_TRADING_ENABLED` must default to `false`; research code must not import order-placement modules.

## Data quality gaps

- The production cache lives outside the repository while the repo-local path is empty.
- Historical universe snapshots were not stored with the current cache; daily quote-volume reconstruction is an approximation, not complete delisting history.
- There is no historical OI dataset in the inspected cache.
- Existing 15m data is sparse relative to 1m and must be checked before reuse or rebuilt only from completed 1m bars.
- Existing run artifacts are file based and do not yet carry a common engine/data version contract.

