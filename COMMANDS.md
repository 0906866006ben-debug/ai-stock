 Backend (FastAPI)

  cd /home/ben_0527/project/ai-stock
  .venv/bin/uvicorn backend.app.main:app --reload --port 8000

  What it does:
  - Starts FastAPI server on http://localhost:8000
  - Auto-reloads on code changes
  - Provides /health, /analyze/tw, /tw/price-history endpoints

  ---
  Frontend (Next.js)

  cd /home/ben_0527/project/ai-stock/ai-stock-frontend
  npm run dev

  What it does:
  - Starts Next.js dev server on http://localhost:3000
  - Auto-reloads on code changes
  - Provides Taiwan stock analysis UI

  ---
  Run All Tests

  cd /home/ben_0527/project/ai-stock
  .venv/bin/python -m pytest backend/tests/ -q

  Output: 48 tests pass in ~15 seconds

  ---
  TypeScript Check

  cd /home/ben_0527/project/ai-stock/ai-stock-frontend
  npx tsc --noEmit

  Output: No errors found

  ---
  Quick Health Check (Backend Running)

  curl http://localhost:8000/health

  Expected Response:
  {"status": "ok", "version": "3.0.0"}

  ---
  Test Taiwan Stock Analysis

  curl "http://localhost:8000/analyze/tw?symbol=2330"

  Expected Response: Company: 台積電, Market: TWSE, Trend: 中立, etc.

  ---
  Stop Services

  pkill -f "uvicorn"   # Stop backend
  pkill -f "npm"       # Stop frontend