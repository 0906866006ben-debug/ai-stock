# Research Platform Risk Register

| ID | Severity | Risk | Current evidence | Mitigation / gate |
|---|---|---|---|---|
| R-01 | Critical | Lookahead from incomplete higher-timeframe bars | Existing live mirror intentionally uses partial higher bars in places | Research DSL declares bar policy; strict baseline uses completed bars; property tests lock behavior. |
| R-02 | Critical | Locked-test leakage | Cache and reports contain dates after 2026-06-01 | Dataset permissions prevent optimizer access; imports are labeled evidence-only. |
| R-03 | Critical | Missing historical OI misrepresented as zero | Current cache has no OI table | Null-only contract; Tier gate blocks full-five-factor runs. |
| R-04 | High | Survivorship bias | Historical exchange snapshots not stored | Start snapshots now; disclose incomplete history; no robust-candidate promotion until coverage is adequate. |
| R-05 | High | Wrong data path | Repo DB is empty; real DB is outside repo | Explicit setting and catalog fingerprint; fail closed on zero-byte DB. |
| R-06 | High | Overfitting / multiple testing | Many variants and symbols already explored | Generation counters, locked test, walk-forward, penalties and plateau gate. |
| R-07 | High | Cost model optimism | Fill behavior varies by liquidity/regime | Conservative same-bar rule and 1x/1.25x/1.5x/2x stress tests. |
| R-08 | High | Secret leakage through dashboard or logs | Backend and deployment tokens are planned | BFF-only token, redaction, no `NEXT_PUBLIC_*` secrets, API response tests and secret scan. |
| R-09 | High | Accidental live order | Trading scripts exist in same repository | Research package does not import order modules; `LIVE_TRADING_ENABLED=false` hard default. |
| R-10 | Medium | OneDrive SQLite locking/corruption | Large cache and journal files are on synced paths | Discovery/import is read-only; production writes use PostgreSQL/Parquet atomic commits. |
| R-11 | Medium | 24/7 services not verified | Docker and Cloudflared are not installed | Keep status `NOT_VERIFIED`; provide host prerequisites and post-install smoke checks. |
| R-12 | Medium | OpenAI model/key unavailable or budget exceeded | Key currently empty | Event mode fails closed; local research continues; hard-stop enforced before calls. |
| R-13 | Medium | Legacy report metrics lack common provenance | Existing reports are text/CSV artifacts | Import immutable raw path/hash plus inferred limitations; do not promote legacy runs. |
| R-14 | Medium | Existing dirty worktree mixed into phase commits | Numerous user changes are present | Stage only newly created research-platform paths; never rewrite or revert unrelated files. |

