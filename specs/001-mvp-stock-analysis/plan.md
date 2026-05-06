# Implementation Plan: AI Stock Analysis Platform MVP

**Branch**: `001-mvp-stock-analysis` | **Date**: 2026-05-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-mvp-stock-analysis/spec.md`

## Summary

Build the MVP of an AI-powered stock analysis platform. The backend is a
FastAPI service that orchestrates a LangGraph workflow across four service
modules (market data, news, financials, AI analysis) and returns a single
structured `StockAnalysisResponse`. The frontend is a Next.js 16 App Router
dashboard page that accepts a ticker symbol, calls the backend `/analyze`
endpoint, and renders all response fields including a lightweight-charts v5
price chart. All data sources gracefully fall back to mock data when API keys
are absent.

## Technical Context

**Language/Version**: Python 3.14 (backend), Node.js 20.9+ / TypeScript 5 (frontend)
**Primary Dependencies**: FastAPI 0.136.1, Pydantic v2.13.4, PydanticAI 1.90.0,
LangGraph 1.1.10, Uvicorn 0.46.0, yfinance 1.3.0, Anthropic 0.100.0 (backend);
Next.js 16.2.4, Tailwind CSS v4, lightweight-charts v5, Axios 1.16.0 (frontend)
**Storage**: None — stateless per-request pipeline
**Testing**: pytest (backend), no frontend test suite in MVP
**Target Platform**: Local development (Linux/WSL2); Linux server for deployment
**Project Type**: Full-stack web service (REST API backend + SPA frontend)
**Performance Goals**: Analysis response within 10 seconds under normal conditions
**Constraints**: No auth, no DB, no caching in MVP; graceful mock fallback required
**Scale/Scope**: Single user (local dev); 5 MVP features per constitution Principle VII

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. FastAPI Backend Stack | Backend uses FastAPI + Pydantic + PydanticAI + LangGraph | ✅ PASS |
| II. Next.js Frontend Stack | Frontend uses Next.js App Router + TypeScript + Tailwind + lightweight-charts | ✅ PASS |
| III. Stable API Contracts | All responses use Pydantic schemas; contract documented in contracts/api.md | ✅ PASS |
| IV. Structured AI Output | PydanticAI `output_type=StockAIAnalysis`; no free-form text | ✅ PASS |
| V. Finance Data Integration | yfinance + Polygon + Finnhub + FMP used additively | ✅ PASS |
| VI. Resilient Fallback | Each service module catches all exceptions and returns mock data | ✅ PASS |
| VII. MVP Scope | Only: stock lookup, chart, news, financials, AI analysis | ✅ PASS |
| VIII. API Key Security | Keys read from `.env`; never in code or responses | ✅ PASS |
| IX. Financial Analysis Disclaimer | Disclaimer shown in UI; AI model instructed per spec | ✅ PASS |
| X. Minimal Rewrite Policy | Building from scratch per scope; no over-engineering | ✅ PASS |

All gates pass. No complexity violations.

## Project Structure

### Documentation (this feature)

```text
specs/001-mvp-stock-analysis/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 research findings
├── data-model.md        # Entity definitions
├── quickstart.md        # How to run
├── contracts/
│   └── api.md           # REST API contract
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
backend/
├── .env                    # Secret keys (never commit)
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI app, CORS, /health, /analyze routes
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py      # Pydantic: StockAnalysisResponse, NewsItem,
│   │                       #           ChartPoint, HealthResponse,
│   │                       #           StockAIAnalysis
│   ├── services/
│   │   ├── __init__.py
│   │   ├── market_data.py  # yfinance/Polygon price + chart data
│   │   ├── news_data.py    # Finnhub/FMP news headlines
│   │   ├── financial_data.py # FMP/yfinance financial metrics
│   │   └── ai_analysis.py  # PydanticAI agent, mock fallback
│   └── graphs/
│       ├── __init__.py
│       └── stock_analysis_graph.py  # LangGraph StateGraph workflow

ai-stock-frontend/
├── app/
│   ├── layout.tsx          # Root layout (Server Component)
│   ├── page.tsx            # Dashboard page ('use client')
│   └── components/
│       ├── SearchBar.tsx       # Stock symbol input ('use client')
│       ├── StockChart.tsx      # lightweight-charts v5 ('use client')
│       ├── AnalysisCard.tsx    # AI summary + trend + confidence
│       ├── NewsSection.tsx     # News headlines list
│       └── FinancialSummary.tsx # Key metrics grid
└── lib/
    └── api.ts              # axios wrapper for backend calls
```

**Structure Decision**: Web application layout (Option 2). Backend and frontend
are separate subdirectories at the repo root. No monorepo tooling needed for MVP.

## Complexity Tracking

> No constitution violations. No complexity justifications required.
