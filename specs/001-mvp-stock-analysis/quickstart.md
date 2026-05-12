# Quickstart: AI Stock Analysis Platform MVP

**Feature**: 001-mvp-stock-analysis

---

## Prerequisites

- Python `.venv` already provisioned at project root
- Node.js 20.9+ installed
- `npm` available

---

## 1. Configure Environment Variables

Create `backend/.env` (never commit this file):

```env
# Required for live AI analysis (falls back to mock if absent)
ANTHROPIC_API_KEY=sk-ant-...

# Optional — each falls back to mock data if absent
POLYGON_API_KEY=...
FINNHUB_API_KEY=...
FMP_API_KEY=...
```

---

## 2. Start the Backend

From the repository root:

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload --port 8000
```

Verify:

```bash
curl http://localhost:8000/health
# → {"status":"ok","version":"1.0.0"}

curl "http://localhost:8000/analyze?symbol=AAPL"
# → JSON with full analysis
```

---

## 3. Start the Frontend

```bash
cd ai-stock-frontend
npm run dev
```

Open `http://localhost:3000` in a browser.

---

## 4. Smoke Test

1. Type `AAPL` in the search box and press **Enter** or click **Analyze**.
2. Verify the dashboard populates with:
   - Company name and price
   - AI summary, trend badge, and confidence bar
   - Risks and catalysts lists
   - News headlines
   - Financial summary metrics
   - Price chart
3. Check `data_source` label — `mock` is expected when API keys are not set.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'backend'` | Run uvicorn from repo root, not from `backend/` |
| CORS error in browser | Confirm backend is on port 8000; check `CORS_ORIGINS` env var |
| Chart doesn't render | Confirm `chart_data` array is non-empty in network response |
| AI returns mock data | Set `ANTHROPIC_API_KEY` in `backend/.env` |
