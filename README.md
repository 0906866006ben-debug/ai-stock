# AI Stock Assistant

An AI-powered stock analysis platform covering both **Taiwan** and **US** markets. FastAPI backend orchestrates multi-source data via LangGraph and PydanticAI; Next.js frontend renders a dashboard with sidebar navigation.

Every external data source has a mock fallback — the system runs end-to-end with **zero API keys** configured.

---

## Features

### AI analysis
- US stocks via FMP / Finnhub / Polygon (`/analyze?symbol=AAPL`)
- TW stocks via FinMind (`/analyze/tw?symbol=2330`)
- Structured output (summary, trend, confidence, risks, catalysts, recommendation) via Gemini 2.5 + PydanticAI
- Peer comparison for US tickers (`/compare`)
- Live macro snapshot for the US (FMP) and TW analysis (yfinance: USD/TWD, US10Y, gold, oil, S&P, Nasdaq)

### Taiwan market deep-dive
- Detailed sub-summaries on every TW analysis: revenue (YoY/MoM), valuation (PER/PBR/yield), institutional flows (foreign/trust/dealer 5d & 10d net), chip risk (margin/short balance, derived risk level), macro environment
- "即將除息" banner showing the next dividend ex-date / cash & stock per share / payment date
- ETF holdings + sector weights for 0050 / 0056 / 00878 / 00919 (curated, stable empty-fields fallback for unsupported codes)

### Charts (lightweight-charts v5)
- Multi-pane K 線圖 with synchronized time scales: price + volume + RSI + MACD
- 日線 / 週線 / 月線 / 年線 granularity — daily candles aggregated into the chosen bucket on the backend
- Indicator overlays toggleable per-chart: MA5 / MA20 / MA60 / 成交量 / RSI / MACD
- Indicators recomputed on the **aggregated** series, so MA20 means "20 weeks" on 週線 etc.

### Calendar
- Dividend events from FinMind `TaiwanStockDividend` (ex-date, payment date, cash & stock per share)
- Earnings windows: TW regulatory deadlines (Q1≤5/15, Q2≤8/14, Q3≤11/14, FY≤3/31) plus past EPS pulled from `TaiwanStockFinancialStatements`

### Stock directory & news
- Full TW stock directory with search + market type filters (上市/上櫃/ETF/興櫃/創新板)
- Yahoo Finance news classified into 8 macro categories (大盤 / 利率 / 匯率 / 產業 / 國際 / 原物料 / 地緣 / 政策)

### Portfolio & watchlist (client-side only)
- Track positions with cost-basis P&L, return %, total market value
- Favorites + recent searches persisted to `localStorage`

### Telegram integration (optional)
- SQLite-backed watchlist with bot commands: `/add`, `/remove`, `/list`, `/report`, `/help`
- Web-UI favorites sync to the watchlist via `/tw/telegram/watchlist/sync`

---

## Tech stack

| Layer | Stack |
|---|---|
| Backend | Python 3.14 · FastAPI 0.136 · Pydantic v2 · PydanticAI 1.x · LangGraph · httpx · yfinance |
| Frontend | Next.js 16 (App Router) · TypeScript · Tailwind CSS v4 · lightweight-charts v5 · axios |
| AI | Google Gemini 2.5 (via `pydantic-ai`) for structured analysis |
| Data | Financial Modeling Prep · Finnhub · Polygon · FinMind · Yahoo Finance |
| Storage | None for users — Telegram watchlist uses local SQLite |

---

## Quick start

```bash
# 1. Backend
cp backend/.env.example backend/.env   # fill keys you have, or leave empty for mock mode
.venv/bin/uvicorn backend.app.main:app --reload --port 8000

# 2. Frontend (in another terminal)
cd ai-stock-frontend && npm install && npm run dev
# → open http://localhost:3000
```

Tests:

```bash
.venv/bin/python -m pytest backend/tests/ -q
```

All API keys in `backend/.env` are **optional** — anything missing falls back to mock data:

```
GEMINI_API_KEY=     # AI analysis (without this, mock summary)
FMP_API_KEY=        # US fundamentals, peers, market overview
FINNHUB_API_KEY=    # US news
POLYGON_API_KEY=    # US prices
FINMIND_API_KEY=    # TW prices, financials, dividends
TELEGRAM_BOT_TOKEN= # Telegram bot (only for /tw/telegram/* endpoints)
TELEGRAM_WEB_CHAT_ID=
```

---

## API surface

### Core
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Server status |
| GET | `/search?query=` | US symbol autocomplete |
| GET | `/market` | US economic indicators + top stocks |
| GET | `/analyze?symbol=` | US stock analysis |
| GET | `/compare?symbol=` | US peer comparison |
| GET | `/analyze/tw?symbol=` | TW analysis (incl. all detail summaries, next dividend, ETF holdings) |

### Taiwan-specific
| Method | Path | Purpose |
|---|---|---|
| GET | `/tw/stocks?q=&stock_type=&industry=&limit=` | Stock directory with filters |
| GET | `/tw/price-history?stock_code=&range=D\|W\|M\|Y&include_indicators=ma,rsi,macd,volume` | OHLC candles + indicators |
| GET | `/tw/external-news?category=` | Yahoo news by 8-category classifier |
| GET | `/tw/calendar/dividends?symbol=&start=&end=` | Dividend events (FinMind) |
| GET | `/tw/calendar/earnings?symbol=` | Past EPS + upcoming filing windows |
| GET | `/tw/etf/holdings?symbol=` | Top holdings + sector weights |
| POST | `/tw/telegram/watchlist/sync` | Sync favorites to Telegram bot |
| POST | `/tw/telegram/webhook` | Telegram bot webhook |

---

## Project structure

```
ai-stock/
├─ backend/
│  ├─ app/
│  │  ├─ main.py              # All FastAPI routes
│  │  ├─ models/schemas.py    # All Pydantic request/response models
│  │  ├─ graphs/              # LangGraph state machines (US + TW)
│  │  └─ services/            # Per-provider modules (mock fallback contract)
│  │     ├─ fmp_*.py          # Financial Modeling Prep
│  │     ├─ finmind_*.py      # FinMind (TW)
│  │     ├─ tw_indicators.py  # Pure SMA/EMA/RSI/MACD math
│  │     ├─ tw_candles.py     # Daily → weekly/monthly/yearly aggregation
│  │     ├─ tw_calendar.py    # Dividends + earnings windows
│  │     ├─ tw_etf_holdings.py
│  │     ├─ tw_macro.py       # Macro via yfinance
│  │     ├─ yahoo_news.py
│  │     └─ telegram_service.py
│  ├─ tests/                  # pytest suite (asyncio_mode=auto)
│  └─ .env.example
├─ ai-stock-frontend/
│  ├─ app/
│  │  ├─ page.tsx             # Single-page app w/ sidebar nav
│  │  └─ components/          # Per-view React components
│  └─ lib/{api,types}.ts      # Backend client + shared types
└─ specs/001-mvp-stock-analysis/   # Original speckit plan (historical)
```

---

## Design notes

- **Mock-fallback is the default path.** Every external service catches failure and returns mock data, never raising. Routes surface a `data_source` / `is_mock` / `status` flag so the UI shows "● Live" vs "● Mock" badges.
- **Schemas are extended additively.** New fields on existing responses are always optional + nullable so older clients keep working.
- **AI output is structured JSON.** PydanticAI agents declare an `output_type` and return that exact model — no free-form text.
- **`/analyze/tw` is a parallel pipeline.** It fans out market data, company info, AI analysis (LangGraph), detailed financials, macro snapshot, and next-dividend lookup concurrently via `asyncio.gather`.
- **TW chart granularity drives both lookback and aggregation.** Selecting 月線 fetches 5 years of daily data, buckets into monthly OHLCV, then computes indicators on the aggregated series.
- **Disclaimer.** This is analysis support, not financial advice. The TW response always includes `disclaimer: "本分析僅供參考，不構成投資建議。"`.

---

## License

Personal project — no license assigned. See `CLAUDE.md` for contribution guardrails.
