# Taiwan Stock Analysis — Feature Design

**Date:** 2026-05-07
**Branch:** `001-mvp-stock-analysis`
**Status:** Approved — ready for implementation planning

---

## Summary

Add Taiwan stock analysis to the existing AI stock platform. The backend exposes a new
`GET /analyze/tw?symbol=` endpoint backed by FinMind as the sole data source. The
frontend auto-routes numeric 4–6 digit symbols to this endpoint and renders a
Traditional Chinese dashboard. All existing US stock functionality is untouched.

---

## 1. Architecture

**Approach:** Option A — dedicated Taiwan endpoint, parallel to the existing US flow.

New backend files (nothing existing is modified except registering the new route):

```
backend/app/
├── services/
│   ├── finmind_market.py      # FinMind OHLCV + price summary
│   ├── finmind_company.py     # FinMind company info + market_type
│   └── tw_ai_analysis.py      # PydanticAI agent, Traditional Chinese output
├── graphs/
│   └── tw_stock_graph.py      # LangGraph StateGraph for Taiwan flow
└── main.py                    # minimal: register /analyze/tw route only
```

New frontend files:

```
ai-stock-frontend/
├── app/
│   ├── components/
│   │   └── TwSearchBar.tsx    # Taiwan symbol input with client-side validation
│   └── page.tsx               # auto-routes numeric vs alpha symbols (minimal change)
└── lib/
    ├── api.ts                 # add analyzeTW() export
    └── types.ts               # TaiwanStockAnalysisResponse + CandlePoint interfaces
```

`StockChart.tsx`, `AnalysisCard.tsx`, `NewsSection.tsx`, `FinancialSummary.tsx` are
updated in-place with Taiwan-aware behaviour.

---

## 2. API Contract

### Endpoint

```
GET /analyze/tw?symbol=2330
```

Symbol is a 4–6 digit numeric string. Treated as a string throughout — never cast to
int (leading zeros in ETF codes like `0050`, `00878` must be preserved).

### Response — `TaiwanStockAnalysisResponse`

| Field | Type | Notes |
|---|---|---|
| `symbol` | `str` | As provided, e.g. `"2330"` |
| `company_name` | `str` | Chinese name from FinMind |
| `market_type` | `str` | `"TWSE"` or `"TPEx"` or `"UNKNOWN"` |
| `currency` | `str` | Always `"TWD"` |
| `current_price` | `float` | Last close, TWD |
| `price_change_percent` | `float` | (close − prev_close) / prev_close × 100 |
| `volume` | `int` | Trading_Volume of latest day |
| `trend` | `str` | `"看漲"` \| `"看跌"` \| `"中立"` |
| `confidence` | `float` | 0.0 – 1.0 |
| `summary` | `str` | Traditional Chinese |
| `risks` | `list[str]` | Traditional Chinese |
| `catalysts` | `list[str]` | Traditional Chinese |
| `recommendation` | `str` | Traditional Chinese |
| `recent_news` | `list[NewsItem]` | Default `[]`; never omitted |
| `chart_data` | `list[CandlePoint]` | 6 months of OHLCV |
| `data_source` | `str` | `"live"` or `"mock"` |
| `analysis_source` | `str` | `"ai"` or `"mock"` |
| `disclaimer` | `str` | `"本分析僅供參考，不構成投資建議。"` |
| `analyzed_at` | `str` | ISO 8601 UTC timestamp |

### `CandlePoint`

```python
class CandlePoint(BaseModel):
    time: str     # "YYYY-MM-DD"
    open: float
    high: float
    low: float
    close: float
    volume: int
```

`NewsItem` is reused from the existing schema unchanged.

---

## 3. Backend — Pydantic Schemas

Appended to `backend/app/models/schemas.py` (no existing code modified):

```python
from typing import Literal
from pydantic import field_validator

class CandlePoint(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int

class TaiwanStockAIAnalysis(BaseModel):
    """PydanticAI output — internal use only."""
    summary: str
    trend: Literal["看漲", "看跌", "中立"]
    confidence: float
    risks: list[str]
    catalysts: list[str]
    recommendation: str

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

class TaiwanStockAnalysisResponse(BaseModel):
    symbol: str
    company_name: str
    market_type: str
    currency: str = "TWD"
    current_price: float
    price_change_percent: float
    volume: int
    trend: str
    confidence: float
    summary: str
    risks: list[str]
    catalysts: list[str]
    recommendation: str
    recent_news: list[NewsItem] = []
    chart_data: list[CandlePoint]
    data_source: str
    analysis_source: str
    disclaimer: str = "本分析僅供參考，不構成投資建議。"
    analyzed_at: str
```

---

## 4. Backend — FinMind Service Layer

### Auth

Token passed as query parameter:
```
?token=<FINMIND_API_KEY>
```
Read from `.env` via `os.getenv("FINMIND_API_KEY")`. If missing, skip live call and
return mock data immediately.

### `finmind_market.py`

- Dataset: `TaiwanStockPrice`
- Date range: past 6 months from today
- Field mapping (FinMind → `CandlePoint`):

| FinMind field | CandlePoint field |
|---|---|
| `date` | `time` |
| `open` | `open` |
| `max` | `high` |
| `min` | `low` |
| `close` | `close` |
| `Trading_Volume` | `volume` |

- Derives `current_price` (last row `close`), `price_change_percent`
  ((last_close − prev_close) / prev_close × 100), `volume` (last row `Trading_Volume`).
- Returns sorted `list[CandlePoint]`.
- Mock fallback on any exception: 6 months of synthetic candles.

### `finmind_company.py`

- Dataset: `TaiwanStockInfo` (no date range required)
- Returns `company_name` and `market_type`
- Market type mapping:

| FinMind `type` | Response `market_type` |
|---|---|
| `"twse"` | `"TWSE"` |
| `"tpex"` or `"otc"` | `"TPEx"` |
| anything else | raw value or `"UNKNOWN"` |

- Mock fallback: `{"company_name": symbol, "market_type": "TWSE"}`.

### Symbol normalization

Done once at route level before calling either service:
- Strip whitespace
- Validate `/^\d{4,6}$/`; reject otherwise with HTTP 422
- Pass as-is (string) to all services — never cast to int

---

## 5. Backend — AI Analysis

**`tw_ai_analysis.py`**

- Uses PydanticAI with `output_type=TaiwanStockAIAnalysis`
- Model: Claude via Anthropic SDK; key read from `ANTHROPIC_API_KEY` in `.env`
- Falls back to hardcoded mock if key is missing or on any exception

**Prompt context assembled from:**
- Company name, symbol, market_type
- current_price, price_change_percent, volume vs 20-day average volume
- 5-day OHLCV summary
- 5-day price change and 20-day price change (if enough data)
- Whether price is above or below MA5 / MA20 (simple arithmetic — no external library)
- News headlines as bullet list, or `"目前沒有可靠新聞資料。"` if empty

**System prompt** (Traditional Chinese): instructs Claude to output structured JSON
in Traditional Chinese. Includes disclaimer text. Trend must be one of
`看漲 | 看跌 | 中立`.

**Mock fallback:**
```python
TaiwanStockAIAnalysis(
    summary="目前無法取得 AI 分析，以下為模擬資料。",
    trend="中立",
    confidence=0.5,
    risks=["資料不完整", "市場波動風險"],
    catalysts=["待補充"],
    recommendation="建議等待更多資訊後再做決策。",
)
```

**`data_source` vs `analysis_source`:** set independently so FinMind live data +
AI mock is a valid combination (`data_source="live"`, `analysis_source="mock"`).

---

## 6. Backend — LangGraph Graph

**`tw_stock_graph.py`** — sequential, same pattern as existing US graph:

```
fetch_market → fetch_company → ai_analysis → END
```

State (`TaiwanAnalysisState` TypedDict):
- `symbol`, `market_data`, `company_data`, `ai_result`
- `data_is_mock: bool`, `analysis_is_mock: bool`

Assembles `TaiwanStockAnalysisResponse` after `ai_analysis` node.
`analyzed_at` is set at assembly time (UTC ISO 8601).

---

## 7. Frontend

### TypeScript types (`lib/types.ts`)

Interfaces matching backend response exactly:

```ts
interface CandlePoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface NewsItem {
  title: string;
  published_at: string;
  source: string;
  url?: string;
}

interface TaiwanStockAnalysisResponse {
  symbol: string;
  company_name: string;
  market_type: string;
  currency: string;
  current_price: number;
  price_change_percent: number;
  volume: number;
  trend: string;
  confidence: number;
  summary: string;
  risks: string[];
  catalysts: string[];
  recommendation: string;
  recent_news: NewsItem[];
  chart_data: CandlePoint[];
  data_source: string;
  analysis_source: string;
  disclaimer: string;
  analyzed_at: string;
}
```

### `lib/api.ts`

Add one export:
```ts
export async function analyzeTW(symbol: string): Promise<TaiwanStockAnalysisResponse>
// GET /analyze/tw?symbol=<symbol>
```

### `TwSearchBar.tsx`

- Input validated with `/^\d{4,6}$/` before submit
- Symbol kept as string — never parsed to number
- Placeholder: `輸入股票代碼，例如 2330`
- Button: `分析`
- Inline error if format invalid

### `page.tsx` (minimal change)

Auto-routes on submit:
- `/^\d{4,6}$/` → `analyzeTW()` → render Taiwan dashboard
- Otherwise → existing US flow (zero changes to US path)
- On error: show friendly Traditional Chinese message; keep previous valid result visible

### Component updates

**`StockChart.tsx`**
- Taiwan: render lightweight-charts `CandlestickSeries` from `chart_data`
  (time, open, high, low, close)
- US: existing line chart path unchanged
- Volume displayed as text in `FinancialSummary` for MVP; no volume bars

**`AnalysisCard.tsx`**
- Add `analysis_source` badge: `AI分析` (ai) or `模擬資料` (mock)
- Add `data_source` small label: `即時/實際資料` (live) or `模擬資料` (mock)
- All other rendering unchanged

**`NewsSection.tsx`**
- If `recent_news` is empty, render a single line: `目前沒有可靠新聞資料。`
- Do not hide the section; always render the heading and the placeholder
- Modify the component only if it currently hides itself on empty input

**`FinancialSummary.tsx`**
- For Taiwan results, display with Chinese labels:
  - 幣別: TWD
  - 市場: TWSE / TPEx
  - 最新收盤價
  - 漲跌幅
  - 成交量

**Dashboard (inline in `page.tsx` or layout)**
- `market_type` badge next to company name
- `disclaimer` pinned at bottom: `本分析僅供參考，不構成投資建議。`
- `analyzed_at` shown as small timestamp near header

### UI language

All labels for Taiwan stock results in Traditional Chinese.
US stock results: existing English labels, untouched.

### Error handling

If `GET /analyze/tw` fails:
- Show friendly error in Traditional Chinese
- Do not crash the page
- Keep previous valid result visible if available

---

## 8. Out of Scope (MVP)

- Volume bars in the candlestick chart (show as text first)
- News fetching from FinMind (field is stable but returns `[]` in MVP)
- Gemini / OpenAI fallback for AI analysis
- Authentication, caching, database
- US stock changes beyond the minimal routing condition in `page.tsx`
