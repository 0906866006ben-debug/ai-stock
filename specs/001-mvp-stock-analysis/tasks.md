---
description: "Task list for AI Stock Analysis Platform MVP"
---

# Tasks: AI Stock Analysis Platform MVP

**Input**: Design documents from `/specs/001-mvp-stock-analysis/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/api.md ✅

**Tests**: Not explicitly requested — no test tasks included in this plan.

**Organization**: Tasks grouped by user story to enable independent implementation
and testing of each story.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths included in all task descriptions

## Path Conventions

- Backend: `backend/` at repository root
- Frontend: `ai-stock-frontend/` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project file structure and shared type definitions — no business
logic yet.

- [x] T001 Create backend directory structure: `backend/__init__.py`, `backend/app/__init__.py`, `backend/app/models/__init__.py`, `backend/app/services/__init__.py`, `backend/app/graphs/__init__.py`, `backend/.env.example`
- [x] T002 [P] Create `backend/app/models/schemas.py` — define all Pydantic v2 models: `HealthResponse`, `ChartPoint`, `NewsItem`, `StockAIAnalysis`, `StockAnalysisResponse` per `data-model.md`
- [x] T003 [P] Create `ai-stock-frontend/lib/api.ts` — axios wrapper: `analyzeStock(symbol: string)` calling `GET /analyze?symbol=`, `checkHealth()` calling `GET /health`; export response types matching `StockAnalysisResponse`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Backend API fully operational before any frontend story can be
implemented.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T004 Create `backend/app/main.py` — FastAPI app, `CORSMiddleware` (`allow_origins=["*"]`), `GET /health` returning `HealthResponse`, stub `GET /analyze` returning 200 (will be wired in T010)
- [x] T005 [P] Create `backend/app/services/market_data.py` — `get_market_data(symbol: str) -> dict`: use `yfinance.Ticker(symbol).history(period="6mo")` for `chart_data` + `.info` for price/change/company_name; catch all exceptions and return mock dict with `data_source="mock"`
- [x] T006 [P] Create `backend/app/services/news_data.py` — `get_news_data(symbol: str) -> list[dict]`: use `finnhub.Client(api_key=FINNHUB_API_KEY).company_news(symbol, ...)` if key present; catch all exceptions and return list of 3 mock `NewsItem` dicts
- [x] T007 [P] Create `backend/app/services/financial_data.py` — `get_financial_data(symbol: str) -> dict`: use `yfinance.Ticker(symbol).info` for P/E, market cap, 52-week range, volume; catch all exceptions and return mock `financial_summary` dict
- [x] T008 Create `backend/app/services/ai_analysis.py` — `get_ai_analysis(symbol: str, context: dict) -> dict`: define `StockAIAnalysis` prompt; create `Agent("anthropic:claude-sonnet-4-6", output_type=StockAIAnalysis)` via PydanticAI; run `await agent.run(prompt)`; catch `UserError`/`Exception` (missing key or API failure) and return mock `StockAIAnalysis` dict
- [x] T009 Create `backend/app/graphs/stock_analysis_graph.py` — `AnalysisState` TypedDict; `StateGraph(AnalysisState)` with 4 async nodes: `fetch_market`, `fetch_news`, `fetch_financials`, `ai_analysis`; sequential edges; compile to `stock_graph`; export `async def run_analysis(symbol: str) -> AnalysisState`
- [x] T010 Wire `GET /analyze` in `backend/app/main.py` — validate `symbol` (1–10 alphanumeric chars, return 422 otherwise); call `run_analysis(symbol)` from `stock_analysis_graph`; assemble and return `StockAnalysisResponse`

**Checkpoint**: `curl http://localhost:8000/health` returns `{"status":"ok","version":"1.0.0"}`; `curl "http://localhost:8000/analyze?symbol=AAPL"` returns populated JSON — foundation ready.

---

## Phase 3: User Story 1 — Stock Lookup & Full Analysis (Priority: P1) 🎯 MVP

**Goal**: User types a symbol, submits, and sees company name, price, change%,
AI summary, trend, confidence, risks, and catalysts on the dashboard.

**Independent Test**: Open `localhost:3000`, type `AAPL`, press Enter. Dashboard
populates with company info and AI analysis card within 10 seconds.

### Implementation for User Story 1

- [x] T011 [P] [US1] Create `ai-stock-frontend/app/components/SearchBar.tsx` — `'use client'`; controlled input for ticker symbol; calls `onSearch(symbol)` prop on submit; shows empty-input validation; mobile-first Tailwind styling
- [x] T012 [P] [US1] Create `ai-stock-frontend/app/components/AnalysisCard.tsx` — `'use client'`; accepts `StockAnalysisResponse` prop; renders: company name + symbol heading, current price + change% badge (green/red), trend badge, confidence progress bar, AI summary paragraph, risks list, catalysts list; Tailwind mobile-first layout
- [x] T013 [US1] Replace `ai-stock-frontend/app/page.tsx` with dashboard Client Component — `'use client'`; `useState` for `symbol`, `result`, `loading`, `error`; calls `analyzeStock(symbol)` from `lib/api.ts` on search; renders `SearchBar` + conditional `AnalysisCard` (or loading spinner or error message)

**Checkpoint**: US1 independently functional — search any valid symbol → populated
analysis card. Mock data badge visible when API keys not set.

---

## Phase 4: User Story 2 — Price Chart Display (Priority: P2)

**Goal**: Historical price chart renders inline on the analysis page.

**Independent Test**: After a successful search, a line chart of 6-month price
history appears in the chart section without any extra user action.

### Implementation for User Story 2

- [x] T014 [US2] Create `ai-stock-frontend/app/components/StockChart.tsx` — `'use client'`; `useRef` for container div; `useEffect` to call `createChart(ref.current, options)`, `chart.addLineSeries()`, `series.setData(chartData)`, `chart.timeScale().fitContent()`; call `chart.remove()` on cleanup; shows "No chart data" placeholder when `chartData` is empty; props: `chartData: Array<{time: string, value: number}>`
- [x] T015 [US2] Add `StockChart` to `ai-stock-frontend/app/page.tsx` — import and render `<StockChart chartData={result.chart_data} />` below `AnalysisCard`; pass empty array when `result` is null

**Checkpoint**: US2 independently testable — `chart_data` present in response →
line chart renders; empty array → placeholder message, no crash.

---

## Phase 5: User Story 3 — News & Financial Summary (Priority: P3)

**Goal**: Recent news headlines and key financial metrics appear on the analysis
page alongside the AI analysis.

**Independent Test**: After a successful search, news section shows headline list
(with timestamps) and financial section shows metric key-value pairs. If news is
empty, "No recent news available" placeholder renders.

### Implementation for User Story 3

- [x] T016 [P] [US3] Create `ai-stock-frontend/app/components/NewsSection.tsx` — `'use client'`; accepts `news: NewsItem[]` prop; renders list of headlines with title, source, published_at timestamp; clickable link when `url` is present; shows "No recent news available" when list is empty
- [x] T017 [P] [US3] Create `ai-stock-frontend/app/components/FinancialSummary.tsx` — `'use client'`; accepts `summary: Record<string, string>` prop; renders all key-value pairs as a responsive grid; handles empty object with "No financial data available" message
- [x] T018 [US3] Add `NewsSection` and `FinancialSummary` to `ai-stock-frontend/app/page.tsx` — render below `StockChart` when `result` is available; pass `result.recent_news` and `result.financial_summary`
- [x] T019 [US3] Add financial disclaimer to `ai-stock-frontend/app/page.tsx` — render disclaimer text "This is financial analysis support only, not financial advice." in a clearly visible footer area (constitution Principle IX)

**Checkpoint**: US3 independently testable — all three stories work together:
analysis card, chart, news, and financial summary all render on one scrollable
page.

---

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that apply across all stories.

- [x] T020 [P] Add `data_source` badge to `ai-stock-frontend/app/page.tsx` — show "Live Data" (green) when `result.data_source === "live"`, "Demo Data" (amber) when `"mock"`; display next to company name
- [x] T021 [P] Add loading spinner and error display to `ai-stock-frontend/app/page.tsx` — show spinner while `loading === true`; show red error banner with message when `error` is set; clear error on new search
- [x] T022 [P] Update `ai-stock-frontend/app/layout.tsx` — set page `<title>` to `"AI Stock Analysis"`, add descriptive `<meta description>`, keep existing Tailwind globals
- [x] T023 Smoke test backend: run `curl http://localhost:8000/health` and `curl "http://localhost:8000/analyze?symbol=AAPL"` from terminal; confirm both return HTTP 200 with valid JSON matching `contracts/api.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately; T002 and T003 can run in parallel after T001
- **Foundational (Phase 2)**: Depends on Phase 1 completion — T005, T006, T007 can run in parallel after T004; T008 and T009 can run in parallel; T010 depends on T009
- **User Stories (Phase 3–5)**: All depend on Foundational phase — can proceed in priority order once Phase 2 checkpoint passes
- **Polish (Phase N)**: Depends on all user story phases complete

### User Story Dependencies

- **US1 (P1)**: Depends only on Foundational — T011 and T012 can run in parallel; T013 depends on both
- **US2 (P2)**: Depends on US1 complete — T014 must precede T015
- **US3 (P3)**: Depends on US2 complete — T016 and T017 can run in parallel; T018 and T019 depend on both

### Within Each Phase

- Models before services
- Services before graph
- Graph before endpoint wiring
- Endpoint before any frontend story

### Parallel Opportunities

- T002 and T003 (Setup): different files, no dependency
- T005, T006, T007 (Foundational): different service files
- T011 and T012 (US1): different component files
- T016 and T017 (US3): different component files
- T020, T021, T022 (Polish): different concerns

---

## Parallel Example: User Story 1

```bash
# T011 and T012 can run simultaneously:
Task: "Create SearchBar.tsx"
Task: "Create AnalysisCard.tsx"

# Then T013 depends on both being done:
Task: "Replace page.tsx with dashboard Client Component"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational — ⚠️ CRITICAL checkpoint before anything frontend
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: curl backend + open browser, confirm search works
5. Demo if ready

### Incremental Delivery

1. Setup + Foundational → backend API green
2. US1 → dashboard with full analysis card → Demo (MVP!)
3. US2 → add price chart → Demo
4. US3 → add news + financials → Demo
5. Polish → finalize UX

---

## Notes

- `[P]` = parallelizable (different files, no shared state dependencies)
- `[Story]` maps to spec.md user stories for traceability
- All tasks produce independently testable increments when checkpoints are reached
- No test tasks — add TDD tasks if `/speckit-tasks --tdd` is requested in future
- Backend runs from repo root: `uvicorn backend.app.main:app --reload --port 8000`
- Frontend runs from `ai-stock-frontend/`: `npm run dev`
