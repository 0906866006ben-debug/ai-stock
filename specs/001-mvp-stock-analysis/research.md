# Research: AI Stock Analysis Platform MVP

**Feature**: 001-mvp-stock-analysis
**Date**: 2026-05-07
**Status**: Complete — all NEEDS CLARIFICATION resolved

---

## Decision 1: Python Runtime & Package Versions

**Decision**: Python 3.14 with installed packages confirmed from `.venv`
**Rationale**: Environment already provisioned; no installation needed.
**Packages confirmed**:
- FastAPI 0.136.1
- Pydantic v2 (2.13.4) — use `model_config = ConfigDict(...)` not class-level `Config`
- PydanticAI 1.90.0 — uses `output_type=` parameter (not `result_type`)
- LangGraph 1.1.10 — `StateGraph` + `TypedDict` state + `.compile()` + `.invoke()`
- Uvicorn 0.46.0
- Anthropic SDK 0.100.0
- yfinance 1.3.0
- polygon-api-client 1.16.3
- finnhub-python 2.4.28
- financialmodelingprep 0.0.2

**Alternatives considered**: N/A — environment is pre-provisioned.

---

## Decision 2: LangGraph Workflow Pattern

**Decision**: Use `StateGraph` with a `TypedDict`-based state class. Nodes are
plain async functions. Compile to a runnable and call `.ainvoke()`.

**Rationale**: This is the standard LangGraph 1.x pattern. `StateGraph` accepts
any `TypedDict` as its state schema. Edges connect nodes; `END` terminates the
graph.

**Pattern**:
```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AnalysisState(TypedDict):
    symbol: str
    market_data: dict | None
    news_data: list | None
    financial_data: dict | None
    ai_result: dict | None

graph = StateGraph(AnalysisState)
graph.add_node("fetch_market", fetch_market_node)
graph.add_node("fetch_news", fetch_news_node)
graph.add_node("fetch_financials", fetch_financials_node)
graph.add_node("ai_analysis", ai_analysis_node)
graph.set_entry_point("fetch_market")
graph.add_edge("fetch_market", "fetch_news")
graph.add_edge("fetch_news", "fetch_financials")
graph.add_edge("fetch_financials", "ai_analysis")
graph.add_edge("ai_analysis", END)
compiled = graph.compile()
result = await compiled.ainvoke({"symbol": "AAPL", ...})
```

**Alternatives considered**: LangChain chains — rejected; LangGraph provides
explicit state + simpler async orchestration for this use case.

---

## Decision 3: PydanticAI Structured Output

**Decision**: Use `Agent(model, output_type=StockAIAnalysis)` where
`StockAIAnalysis` is a `BaseModel` subclass. Call `await agent.run(prompt)` and
access `result.output`.

**Rationale**: PydanticAI 1.90.0 uses `output_type=` (not the older
`result_type=`). The agent automatically validates and coerces the model's
JSON output into the Pydantic model.

**Pattern**:
```python
from pydantic_ai import Agent
from pydantic import BaseModel

class StockAIAnalysis(BaseModel):
    summary: str
    trend: str
    confidence: float
    risks: list[str]
    catalysts: list[str]
    recommendation: str

agent = Agent("anthropic:claude-sonnet-4-6", output_type=StockAIAnalysis)
result = await agent.run(f"Analyse {symbol}: {data_context}")
analysis: StockAIAnalysis = result.output
```

**Fallback**: When `ANTHROPIC_API_KEY` is absent, `ai_analysis.py` catches
`UserError`/`Exception` and returns a static mock `StockAIAnalysis`.

**Alternatives considered**: OpenAI — available but Anthropic is the
constitutional default for this project.

---

## Decision 4: Finance Data Hierarchy

**Decision**: Primary source is `yfinance` (no API key required). Polygon,
Finnhub, and FMP are used when their keys are present. Each service module
returns mock data if its data source is unavailable.

**Rationale**: yfinance provides market data, historical OHLCV, and basic
financials with zero configuration. It is the most reliable fallback baseline.

**Source priority**:
1. yfinance (always available — no key needed)
2. Polygon (if `POLYGON_API_KEY` set)
3. Finnhub (if `FINNHUB_API_KEY` set)
4. FMP (if `FMP_API_KEY` set)

**Mock data trigger**: Any `Exception` from a data source → return hardcoded
mock dict for that module's output.

---

## Decision 5: Frontend Architecture

**Decision**: Dashboard is a single `'use client'` page component. Chart is a
separate `'use client'` component using lightweight-charts v5 `createChart`.

**Rationale**: The dashboard needs `useState` for symbol input and loading
state, plus `useEffect` for the chart (DOM manipulation via lightweight-charts).
Next.js 16 App Router defaults to Server Components; interactive pages need the
`'use client'` directive.

**lightweight-charts v5 API confirmed**:
```typescript
import { createChart } from 'lightweight-charts';

const chart = createChart(containerRef.current, { width, height });
const series = chart.addLineSeries();  // or addAreaSeries()
series.setData([{ time: '2024-01-01', value: 150.0 }, ...]);
chart.timeScale().fitContent();
```

**Alternatives considered**: Plotly for the price chart — rejected for the
primary chart (heavyweight); reserved for potential future analysis overlays.
Recharts — same as Plotly, available if needed for secondary charts.

---

## Decision 6: Backend Directory Structure

**Decision**: `backend/` at repo root. Entry point: `backend/app/main.py`.
Run with: `cd /path/to/project && uvicorn backend.app.main:app --reload`
(from repo root) or `uvicorn app.main:app --reload` (from `backend/`).

**Rationale**: Separates backend from frontend clearly. `backend/` is a Python
package root; `app/` inside it contains the FastAPI application.

**Alternatives considered**: Flat `app/` at repo root — rejected because the
frontend already uses `ai-stock-frontend/` subdirectory; a `backend/` mirror
keeps parity.

---

## Decision 7: CORS Configuration

**Decision**: Enable `CORSMiddleware` with `allow_origins=["*"]` for local
development. This can be tightened to `http://localhost:3000` via env var.

**Rationale**: Frontend (Next.js on :3000) and backend (FastAPI on :8000) run
on different ports in development. CORS is required for browser-initiated
`axios` calls to succeed.

---

## All NEEDS CLARIFICATION Resolved

No open clarifications remain.
