# AI Stock Assistant Project Rules

## Project Goal

Build an AI-powered stock analysis platform with FastAPI backend and Next.js frontend.

## Backend

- Use FastAPI.
- Use Pydantic models for all request and response schemas.
- Use PydanticAI for structured AI output.
- Use LangGraph for multi-step stock analysis workflow.
- Keep API responses stable and frontend-friendly.
- Never expose API keys.
- Read environment variables from `.env`.

## Frontend

- Use Next.js App Router.
- Use TypeScript.
- Use Tailwind CSS.
- Use lightweight-charts for stock charts.
- Use Plotly or Recharts for analysis visualization.
- Keep UI mobile-first and dashboard-style.

## Finance Data

- Use Polygon, Finnhub, Financial Modeling Prep, and yfinance as available.
- If API key is missing, return mock data instead of crashing.
- Normalize all stock data before sending it to AI.

## AI Analysis

- AI output must be structured JSON.
- Include summary, trend, confidence, risks, catalysts, and recommendation.
- Never invent financial facts.
- Mention when data is missing or incomplete.
- This is analysis support, not financial advice.

## Git Safety

- Do not commit `.env`.
- Do not commit `.venv`.
- Do not commit node_modules.
- Do not rewrite the whole project unless explicitly requested.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
