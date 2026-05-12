# Data Model: AI Stock Analysis Platform MVP

**Feature**: 001-mvp-stock-analysis
**Date**: 2026-05-07

---

## Entities

### StockAnalysisResponse

The top-level response object returned by `GET /analyze`. All fields are
required in the schema; fields that may lack real data are populated with
defaults or labelled mock values.

| Field | Type | Description |
|---|---|---|
| `symbol` | `str` | Ticker symbol, uppercased (e.g. `AAPL`) |
| `company_name` | `str` | Full company name |
| `current_price` | `float` | Latest trading price (USD) |
| `price_change_percent` | `float` | % change vs previous close, e.g. `1.23` |
| `trend` | `str` | One of: `"bullish"`, `"bearish"`, `"neutral"` |
| `confidence` | `float` | AI confidence score, 0.0–1.0 |
| `summary` | `str` | AI-generated narrative summary |
| `risks` | `list[str]` | List of identified risk factors |
| `catalysts` | `list[str]` | List of identified positive catalysts |
| `recommendation` | `str` | AI recommendation string |
| `recent_news` | `list[NewsItem]` | Up to 10 recent news items |
| `financial_summary` | `dict[str, str]` | Key financial metrics (provider-dependent) |
| `chart_data` | `list[ChartPoint]` | Historical OHLCV closing prices |
| `data_source` | `str` | `"live"` or `"mock"` — indicates data origin |

---

### NewsItem

A single news headline as returned within `recent_news`.

| Field | Type | Description |
|---|---|---|
| `title` | `str` | Headline text |
| `published_at` | `str` | ISO 8601 timestamp, e.g. `"2026-05-07T14:00:00Z"` |
| `source` | `str` | Publisher name or URL domain |
| `url` | `str \| None` | Optional link to full article |

---

### ChartPoint

A single historical price data point for rendering the price chart.

| Field | Type | Description |
|---|---|---|
| `time` | `str` | Date in `"YYYY-MM-DD"` format (lightweight-charts compatible) |
| `value` | `float` | Closing price for that date |

---

### HealthResponse

Returned by `GET /health`.

| Field | Type | Description |
|---|---|---|
| `status` | `str` | Always `"ok"` when service is running |
| `version` | `str` | API version string, e.g. `"1.0.0"` |

---

### StockAIAnalysis (internal — PydanticAI output model)

Used only within `ai_analysis.py` as the PydanticAI `output_type`. Not
exposed directly in the API — its fields are mapped into `StockAnalysisResponse`.

| Field | Type | Description |
|---|---|---|
| `summary` | `str` | Narrative analysis |
| `trend` | `str` | `"bullish"` / `"bearish"` / `"neutral"` |
| `confidence` | `float` | 0.0–1.0 |
| `risks` | `list[str]` | Risk factors |
| `catalysts` | `list[str]` | Positive catalysts |
| `recommendation` | `str` | Recommendation text |

---

## Validation Rules

- `symbol`: stripped, uppercased, 1–10 characters, alphanumeric
- `confidence`: clamped to `[0.0, 1.0]`
- `trend`: must be one of `"bullish"`, `"bearish"`, `"neutral"`
- `chart_data`: sorted ascending by `time`
- `current_price`: must be `>= 0.0`
- `price_change_percent`: no range restriction (can be negative)

---

## State Transitions (LangGraph)

```
[START]
  │
  ▼
fetch_market  →  (populates: symbol, company_name, current_price,
  │                           price_change_percent, chart_data)
  │
  ▼
fetch_news    →  (populates: recent_news)
  │
  ▼
fetch_financials → (populates: financial_summary)
  │
  ▼
ai_analysis   →  (populates: trend, confidence, summary,
  │                           risks, catalysts, recommendation)
  │
  ▼
[END]
```

Each node reads from state and writes its output back. If any node fails,
it writes mock data and sets `data_source = "mock"` in state.
