# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

Two-app monorepo (no workspace tooling — each app manages its own deps):
- `backend/` — Python 3.14 FastAPI service
- `ai-stock-frontend/` — Next.js 16 App Router (TypeScript + Tailwind v4)
- `specs/001-mvp-stock-analysis/` — original speckit plan, kept for context only
- `.venv/` at the repo root is the backend venv (used by both `backend/` and root-level `pytest`)

## Commands

All backend commands run from the repo root (`/home/ben_0527/project/ai-stock`) so the package import `backend.app...` resolves.

```bash
# Backend dev server (auto-reload on save)
.venv/bin/uvicorn backend.app.main:app --reload --port 8000

# Frontend dev server (default port 3000; falls through to 3001 if busy)
cd ai-stock-frontend && npm run dev

# Run all backend tests
.venv/bin/python -m pytest backend/tests/ -q

# Run a single test file or test
.venv/bin/python -m pytest backend/tests/test_tw_indicators.py -q
.venv/bin/python -m pytest backend/tests/test_tw_indicators.py::test_rsi_warmup_is_none -q

# Frontend type-check (no test suite yet)
cd ai-stock-frontend && npx tsc --noEmit
```

`backend/pytest.ini` sets `asyncio_mode = auto`, so async tests don't need `@pytest.mark.asyncio`.

## Architecture

### Backend pipeline shape

US analysis (`/analyze`) and TW analysis (`/analyze/tw`) are both composed via **LangGraph state machines** in `backend/app/graphs/`. Each graph node calls one or more **service providers** in `backend/app/services/`, accumulates state, and the route handler in `backend/app/main.py` shapes the final Pydantic response.

Services are thin per-provider modules. The naming convention is `{provider}_{domain}.py`:
- `fmp_*` → Financial Modeling Prep (US fundamentals/peers/market)
- `finmind_*` → FinMind (TW market/company/detailed financials)
- `tw_*` → TW-specific aggregators or computations (no single provider)
- `yahoo_news`, `tw_macro` → yfinance / Yahoo query2

Every external-data service follows the same contract: **return mock data, never crash, when the relevant API key is missing or the request fails**. Mock fallback is the default path, not the exceptional one. Routes also surface `data_source` / `is_mock` / `status` flags so the UI can show a "● Live" vs "● Mock" badge.

### Schemas (Pydantic v2, backward-compatible)

`backend/app/models/schemas.py` is the single source of truth. Two rules when extending response models:
1. New fields on existing responses must be **optional + nullable** so existing clients ignoring unknown fields keep working.
2. Forward references between models in this file resolve automatically — no need to call `model_rebuild()`.

`TaiwanStockAnalysisResponse` has been extended in two phases — Phase 1 added `revenue_summary` / `valuation_summary` / `institutional_summary` / `chip_risk_summary` / `macro_summary` / `etf_summary`; Phase 2 added `next_dividend` / `etf_holdings`. Mirror the same pattern when adding more.

### TW-specific design points

- All TW-only endpoints live under the `/tw/*` prefix.
- **Indicators are pure math** in `services/tw_indicators.py` (SMA / EMA / RSI / MACD). Always returns arrays aligned with input length using `None` for warm-up periods. Tests in `tests/test_tw_indicators.py` use known fixtures — extend those when adding indicators.
- **Candle granularity** is handled by `services/tw_candles.py`. The `/tw/price-history` `range` query param accepts `D | W | M | Y` (legacy `1D/5D/1W/1M/1Y` are aliased). Each granularity drives both the FinMind lookback window and an aggregation step (daily → weekly/monthly/yearly buckets). Indicators are computed on the **aggregated** series so MA20 means "20 weeks" on 週線, "20 months" on 月線.
- **ETF holdings** in `services/tw_etf_holdings.py` are curated mock data for 0050 / 0056 / 00878 / 00919. Unknown ETFs get a stable empty-fields response with `status: "unsupported"` — the UI handles this without crashing.
- **Telegram bot** uses a SQLite file at `backend/telegram_watchlist.db`. Don't commit it (covered by `.gitignore`). The `/tw/telegram/webhook` route is a thin wrapper around `services/telegram_service.handle_webhook()` queued as a `BackgroundTasks` job.

### Frontend shape

The whole app is a single client-side page (`app/page.tsx`) with a sidebar that swaps between named views: `analysis` / `portfolio` / `directory` / `news` / `calendar` / `watchlist` / `add-position`. Portfolio and watchlist persist to `localStorage` only — there is no auth or backend persistence.

Charts use **lightweight-charts v5**. The dependency at the repo root `package.json` lists `plotly.js` and `react-plotly.js`, but they are unused in the current code — lightweight-charts handles all chart rendering. `PriceHistoryChart.tsx` uses multiple synchronized chart instances (price + volume + RSI + MACD) sharing a time axis via `subscribeVisibleLogicalRangeChange`. Bar spacing is set explicitly per range so candles stay readable; **do not call `fitContent()` on these panes** — it overrides the bar spacing.

### Important version notes

- **Next.js 16** has breaking changes vs. older versions in this codebase's training data. Per `ai-stock-frontend/AGENTS.md`: read `node_modules/next/dist/docs/` before changing routing, layouts, or config — APIs and conventions may differ.
- **Pydantic v2** + **PydanticAI 1.x** for structured AI outputs. AI agents must declare an `output_type` and return that exact model.
- **lightweight-charts v5** uses the `addSeries(SeriesType, options)` API (not the old `addCandlestickSeries`).

## Conventions worth keeping

- AI output is always structured JSON via PydanticAI — never free-form text — and includes `summary`, `trend`, `confidence`, `risks`, `catalysts`, `recommendation`.
- The `disclaimer` field on TW responses ("本分析僅供參考，不構成投資建議。") must remain — this is positioning info, not financial advice.
- Don't invent financial facts in prompts or fallbacks. If a data source is missing, the response should reflect that (`status: "no_data"`, empty arrays) rather than fabricated numbers.
- Backend reads env from `backend/.env` via `dotenv` at import time. Optional keys (all of them): `GEMINI_API_KEY`, `FMP_API_KEY`, `FINNHUB_API_KEY`, `POLYGON_API_KEY`, `FINMIND_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEB_CHAT_ID`. The system runs end-to-end with none of them set — it just returns mock data.
