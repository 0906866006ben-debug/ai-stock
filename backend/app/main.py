import re
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models.schemas import HealthResponse, StockAnalysisResponse
from .graphs.stock_analysis_graph import run_analysis

app = FastAPI(title="AI Stock Analysis API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

SYMBOL_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version="1.0.0")


@app.get("/analyze", response_model=StockAnalysisResponse)
async def analyze(symbol: str = Query(..., description="Stock ticker symbol")) -> StockAnalysisResponse:
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail="Invalid symbol. Must be 1-10 alphanumeric characters.")

    state = await run_analysis(symbol)

    news = [
        {
            "title": item.get("title", ""),
            "published_at": item.get("published_at", ""),
            "source": item.get("source", ""),
            "url": item.get("url"),
        }
        for item in (state.get("news_data") or [])
    ]

    market = state.get("market_data") or {}
    ai = state.get("ai_result") or {}
    financials = state.get("financial_data") or {}
    chart_raw = market.get("chart_data", [])

    data_source = "mock" if state.get("is_mock") else "live"

    return StockAnalysisResponse(
        symbol=symbol,
        company_name=market.get("company_name", symbol),
        current_price=float(market.get("current_price", 0.0)),
        price_change_percent=float(market.get("price_change_percent", 0.0)),
        trend=ai.get("trend", "neutral"),
        confidence=float(ai.get("confidence", 0.5)),
        summary=ai.get("summary", ""),
        risks=ai.get("risks", []),
        catalysts=ai.get("catalysts", []),
        recommendation=ai.get("recommendation", ""),
        recent_news=news,
        financial_summary={k: str(v) for k, v in financials.items()},
        chart_data=[{"time": p["time"], "value": p["value"]} for p in chart_raw],
        data_source=data_source,
    )
