# API Contract: AI Stock Analysis Backend

**Base URL (local dev)**: `http://localhost:8000`
**Version**: 1.0.0
**Protocol**: HTTP/1.1, JSON

---

## GET /health

Returns service status.

### Request

```
GET /health HTTP/1.1
```

No parameters.

### Response 200

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

## GET /analyze

Runs the full stock analysis pipeline for a given ticker symbol.

### Request

```
GET /analyze?symbol=AAPL HTTP/1.1
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `symbol` | query string | yes | Stock ticker symbol, case-insensitive |

### Response 200

```json
{
  "symbol": "AAPL",
  "company_name": "Apple Inc.",
  "current_price": 189.84,
  "price_change_percent": 1.23,
  "trend": "bullish",
  "confidence": 0.78,
  "summary": "Apple continues to show strong fundamentals...",
  "risks": [
    "Supply chain exposure to Asia",
    "Regulatory headwinds in EU"
  ],
  "catalysts": [
    "Strong iPhone 16 cycle",
    "Services revenue growth"
  ],
  "recommendation": "Hold with positive bias",
  "recent_news": [
    {
      "title": "Apple Reports Record Q1 Revenue",
      "published_at": "2026-05-07T10:00:00Z",
      "source": "Reuters",
      "url": "https://example.com/article"
    }
  ],
  "financial_summary": {
    "market_cap": "$2.94T",
    "pe_ratio": "31.2",
    "52_week_high": "$199.62",
    "52_week_low": "$164.08",
    "volume": "58,234,100"
  },
  "chart_data": [
    { "time": "2025-11-07", "value": 172.40 },
    { "time": "2025-11-08", "value": 173.15 }
  ],
  "data_source": "live"
}
```

### Response 422 (invalid symbol)

```json
{
  "detail": "Invalid symbol. Must be 1-10 alphanumeric characters."
}
```

### Response 500

Only returned for unexpected server errors; data-source failures return 200
with `data_source: "mock"` instead.

---

## Schema Notes

- `trend` is always one of: `"bullish"`, `"bearish"`, `"neutral"`
- `confidence` is always in range `[0.0, 1.0]`
- `data_source` is `"live"` when at least one real data source was used,
  `"mock"` when all sources fell back to mock data
- `chart_data` is sorted ascending by `time`
- `financial_summary` keys may vary by available data provider; frontend
  should render all keys generically
- `url` in `NewsItem` may be `null`

---

## CORS

The backend exposes `Access-Control-Allow-Origin: *` for local development.
The frontend calls the backend via `axios` from `http://localhost:3000`.
