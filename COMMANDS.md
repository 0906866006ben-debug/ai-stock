# Commands Quick Reference

## Start Backend (WSL Terminal)

```bash
cd /home/ben_0527/project/ai-stock
source .venv/bin/activate
uvicorn backend.app.main:app --reload --port 3000
```

## Start Frontend (Windows Terminal or WSL with Node)

```bash
cd /home/ben_0527/project/ai-stock/ai-stock-frontend
npm run dev
```

Open → http://localhost:3000

---

## Verify Backend is Running

```bash
curl http://localhost:3000/health
```

## Run Tests

```bash
cd /home/ben_0527/project/ai-stock
source .venv/bin/activate
python -m pytest backend/tests/ -v
```

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Server health check |
| `GET /analyze?symbol=AAPL` | US stock analysis |
| `GET /analyze/tw?symbol=2330` | Taiwan stock analysis |
| `GET /market` | Economic indicators + top stocks |
| `GET /compare?symbol=AAPL` | Competitor / peer comparison |
| `GET /search?query=AAPL` | Symbol autocomplete |

---

## API Keys — `backend/.env`

```
GEMINI_API_KEY=...       # AI analysis
FMP_API_KEY=...          # Fundamentals, peers, market data
FINNHUB_API_KEY=...      # US news
POLYGON_API_KEY=...      # US price data
FINMIND_API_KEY=...      # Taiwan stock data
```
