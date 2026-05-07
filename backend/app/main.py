import re
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models.schemas import HealthResponse, StockAnalysisResponse, TaiwanStockAnalysisResponse
from .graphs.stock_analysis_graph import run_analysis
from .graphs.tw_stock_graph import run_tw_analysis

app = FastAPI(title="AI Stock Analysis API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

SYMBOL_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")
TW_SYMBOL_RE = re.compile(r"^\d{4,6}$")


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


@app.get("/analyze/tw", response_model=TaiwanStockAnalysisResponse)
async def analyze_tw(
    symbol: str = Query(..., description="Taiwan stock symbol (4–6 digits, e.g. 2330)")
) -> TaiwanStockAnalysisResponse:
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).",
        )

    state = await run_tw_analysis(symbol)

    market = state.get("market_data") or {}
    company = state.get("company_data") or {}
    ai = state.get("ai_result") or {}

    return TaiwanStockAnalysisResponse(
        symbol=symbol,
        company_name=company.get("company_name", symbol),
        market_type=company.get("market_type", "UNKNOWN"),
        current_price=float(market.get("current_price", 0.0)),
        price_change_percent=float(market.get("price_change_percent", 0.0)),
        volume=int(market.get("volume", 0)),
        trend=ai.get("trend", "中立"),
        confidence=float(ai.get("confidence", 0.5)),
        summary=ai.get("summary", ""),
        risks=ai.get("risks", []),
        catalysts=ai.get("catalysts", []),
        recommendation=ai.get("recommendation", ""),
        recent_news=[],
        chart_data=market.get("chart_data", []),
        data_source="mock" if state.get("data_is_mock") else "live",
        analysis_source="mock" if state.get("analysis_is_mock") else "ai",
        analyzed_at=datetime.now(timezone.utc).isoformat(),
    )
