import re
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from fastapi.middleware.cors import CORSMiddleware

from .models.schemas import (
    HealthResponse,
    StockAnalysisResponse, TaiwanStockAnalysisResponse,
    FundamentalsData, AnalystTarget, LastEarnings, ESGData,
    CompetitorResponse, PeerStock,
    MarketOverviewResponse, EconomicIndicator, TopStock,
    SearchResponse, SearchResult,
    # New TW detail schemas
    RevenueSummary, ValuationSummary, InstitutionalSummary,
    ChipRiskSummary, MacroEnvironmentSummary, ETFSummary,
    # New endpoint schemas
    StockInfo, StockListResponse,
    PriceHistoryResponse, CandlePoint,
    ExternalNewsItem, ExternalNewsResponse,
    TelegramWatchlistSyncRequest, TelegramWatchlistSyncResponse,
    # Phase 2 schemas
    IndicatorsBundle, MACDBundle,
    DividendEvent, DividendCalendarResponse,
    EarningsEvent, EarningsCalendarResponse,
    ETFHolding, ETFSectorWeight, ETFHoldingsResponse,
    # Phase 3: 4-pillar comprehensive analysis
    ComprehensiveAnalysis,
    # Phase 4: elite equity research
    EquityResearch,
)
from .graphs.stock_analysis_graph import run_analysis
from .graphs.tw_stock_graph import run_tw_analysis
from .graphs.comprehensive_analysis_graph import run_comprehensive_analysis
from .services.fmp_market import get_market_overview
from .services.fmp_peers import get_competitors
from .services.fmp_client import fmp_get
from .services.finmind_detail import get_tw_detail, detect_is_etf
from .services.tw_macro import get_macro_summary
from .services.tw_stocks_list import get_tw_stocks
from .services.yahoo_news import get_external_news
from .services.telegram_service import sync_watchlist, handle_webhook
from .services.finmind_market import get_tw_market_data, get_tw_price_history
from .services.tw_candles import RANGE_CONFIG, normalize_range, aggregate_candles, trim_to_max
from .services.tw_indicators import build_indicators, parse_indicator_query
from .services.tw_calendar import (
    get_dividend_events, get_earnings_events, get_next_dividend_live,
    get_next_dividend_for,
)
from .services.tw_etf_holdings import get_etf_holdings, is_supported_etf
from .services.fmp_price_history import get_us_price_history

app = FastAPI(title="AI Stock Analysis API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

SYMBOL_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")
TW_SYMBOL_RE = re.compile(r"^\d{4,6}$")

# In-memory cache for price history and stocks list
_tw_price_cache: dict[str, tuple[dict, float]] = {}
_stocks_cache: tuple[dict | None, float] = (None, 0.0)
_PRICE_CACHE_TTL = 300
_STOCKS_CACHE_TTL = 86400


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version="3.0.0")


@app.get("/search", response_model=SearchResponse)
async def search_symbols(
    query: str = Query(..., min_length=1, max_length=20, description="Symbol or company name to search")
) -> SearchResponse:
    query = query.strip()
    raw = await fmp_get("search-symbol", {"query": query, "limit": 8})
    results = []
    if isinstance(raw, list):
        for item in raw:
            sym = item.get("symbol", "")
            if sym and re.match(r"^[A-Z0-9.]{1,15}$", sym):
                results.append(SearchResult(
                    symbol=sym,
                    name=item.get("name", sym),
                    exchange=item.get("exchange", ""),
                ))
    return SearchResponse(query=query, results=results)


@app.get("/market", response_model=MarketOverviewResponse)
async def market_overview() -> MarketOverviewResponse:
    data = await get_market_overview()
    return MarketOverviewResponse(
        economic_indicators=[
            EconomicIndicator(**ind) for ind in data.get("economic_indicators", [])
        ],
        top_stocks=[
            TopStock(**s) for s in data.get("top_stocks", [])
        ],
        data_source=data.get("data_source", "mock"),
    )


@app.get("/compare", response_model=CompetitorResponse)
async def compare(
    symbol: str = Query(..., description="US stock ticker to compare against peers")
) -> CompetitorResponse:
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail="Invalid symbol.")
    data = await get_competitors(symbol)
    peers = [PeerStock(**p) for p in data.get("peers", [])]
    return CompetitorResponse(symbol=symbol, peers=peers)


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
    fmp = state.get("fmp_data") or {}
    chart_raw = market.get("chart_data", [])

    fmp_metrics = fmp.get("financial_metrics", {})
    merged_summary = {**{k: str(v) for k, v in financials.items()}, **fmp_metrics}

    raw_analyst = fmp.get("analyst", {})
    raw_last = fmp.get("last_earnings", {})
    raw_esg = fmp.get("esg", {})
    fundamentals = FundamentalsData(
        financial_metrics=fmp_metrics,
        analyst=AnalystTarget(**raw_analyst) if raw_analyst else AnalystTarget(),
        next_earnings_date=fmp.get("next_earnings_date"),
        last_earnings=LastEarnings(**raw_last) if raw_last else LastEarnings(),
        esg=ESGData(**{k: v for k, v in raw_esg.items() if v is not None}) if raw_esg else ESGData(),
    )

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
        financial_summary=merged_summary,
        chart_data=[CandlePoint(**p) for p in chart_raw],
        data_source=data_source,
        fundamentals=fundamentals,
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

    import asyncio as _asyncio
    state_task = _asyncio.create_task(run_tw_analysis(symbol))
    detail_task = _asyncio.create_task(get_tw_detail(symbol))
    macro_task = _asyncio.create_task(get_macro_summary())
    dividend_task = _asyncio.create_task(get_next_dividend_live(symbol))
    comprehensive_task = _asyncio.create_task(run_comprehensive_analysis(symbol))

    state, detail, macro_raw, next_div_raw, comprehensive_state = await _asyncio.gather(
        state_task, detail_task, macro_task, dividend_task, comprehensive_task,
        return_exceptions=False,
    )
    # Fall back to mock if live lookup returned nothing
    if next_div_raw is None:
        next_div_raw = get_next_dividend_for(symbol)

    market = state.get("market_data") or {}
    company = state.get("company_data") or {}
    ai = state.get("ai_result") or {}

    is_etf = detect_is_etf(symbol)

    # Build detail sub-objects
    rev = detail.get("revenue_summary", {})
    val = detail.get("valuation_summary", {})
    inst = detail.get("institutional_summary", {})
    chip = detail.get("chip_risk_summary", {})

    revenue_summary = RevenueSummary(**rev) if rev else None
    valuation_summary = ValuationSummary(**val) if val else None
    institutional_summary = InstitutionalSummary(**inst) if inst else None
    chip_risk_summary = ChipRiskSummary(**chip) if chip else None
    macro_summary = MacroEnvironmentSummary(**macro_raw) if macro_raw else None

    next_dividend = None
    if next_div_raw:
        next_dividend = DividendEvent(**next_div_raw)

    etf_holdings_resp = None
    if is_etf and is_supported_etf(symbol):
        raw_h = get_etf_holdings(symbol)
        etf_holdings_resp = ETFHoldingsResponse(
            symbol=raw_h["symbol"],
            fund_name=raw_h.get("fund_name"),
            total_constituents=raw_h.get("total_constituents"),
            last_updated=raw_h.get("last_updated"),
            holdings=[ETFHolding(**h) for h in raw_h.get("holdings", [])],
            sector_weights=[ETFSectorWeight(**s) for s in raw_h.get("sector_weights", [])],
            status=raw_h.get("status", "mock"),
        )

    comprehensive_analysis = None
    if comprehensive_state and comprehensive_state.get("comprehensive_analysis"):
        comprehensive_analysis = comprehensive_state["comprehensive_analysis"]

    equity_research = None
    if comprehensive_state and comprehensive_state.get("equity_research"):
        equity_research = comprehensive_state["equity_research"]

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
        is_etf=is_etf,
        revenue_summary=revenue_summary,
        valuation_summary=valuation_summary,
        institutional_summary=institutional_summary,
        chip_risk_summary=chip_risk_summary,
        macro_summary=macro_summary,
        next_dividend=next_dividend,
        etf_holdings=etf_holdings_resp,
        comprehensive_analysis=comprehensive_analysis,
        equity_research=equity_research,
    )


# ── Taiwan stock directory ────────────────────────────────────────────────────

@app.get("/tw/stocks", response_model=StockListResponse)
async def tw_stocks(
    q: str | None = Query(None, description="Search by stock code or name"),
    stock_type: str | None = Query(None, description="Market type: 上市, 上櫃, ETF, etc."),
    industry: str | None = Query(None, description="Industry category"),
    limit: int = Query(100, ge=1, le=10000, description="Max results"),
) -> StockListResponse:
    global _stocks_cache
    import time as _time

    cached, cached_at = _stocks_cache
    # Only cache the unfiltered list
    if not q and not stock_type and not industry and cached and (_time.time() - cached_at) < _STOCKS_CACHE_TTL:
        data = cached
    else:
        data = await get_tw_stocks(q=q, stock_type=stock_type, industry=industry, limit=limit)
        if not q and not stock_type and not industry:
            _stocks_cache = (data, _time.time())

    stocks = [StockInfo(**s) for s in data["stocks"][:limit]]
    return StockListResponse(
        stocks=stocks,
        total=data["total"],
        returned=len(stocks),
        data_source=data.get("data_source", "mock"),
    )


# ── US price history ──────────────────────────────────────────────────────────

@app.get("/price-history", response_model=PriceHistoryResponse)
async def us_price_history(
    symbol: str = Query(..., description="US stock symbol"),
    range: str = Query("D", description="Time range: D (Day), 5D (5 days), W (Week), M (Month), Y (Year)"),
    include_indicators: str | None = Query(
        None,
        description="Comma-separated indicators: ma,rsi,macd,volume (or 'all'). "
                    "'ma' expands to ma5,ma20,ma60.",
    ),
) -> PriceHistoryResponse:
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail="Invalid US stock symbol.")

    result = await get_us_price_history(symbol, range, include_indicators)
    candles = [CandlePoint(**c) for c in result.get("candles", [])]

    indicators_model = None
    if result.get("indicators"):
        ind = result["indicators"]
        macd_payload = ind.pop("macd", None)
        macd_model = MACDBundle(**macd_payload) if macd_payload else None
        indicators_model = IndicatorsBundle(macd=macd_model, **ind)

    return PriceHistoryResponse(
        stock_code=symbol,
        range=result.get("range", "D"),
        candles=candles,
        is_mock=result.get("is_mock", False),
        indicators=indicators_model,
    )


# ── Taiwan price history ──────────────────────────────────────────────────────

@app.get("/tw/price-history", response_model=PriceHistoryResponse)
async def tw_price_history(
    stock_code: str = Query(..., description="Taiwan stock code"),
    range: str = Query("D", description="K-bar granularity: D (日), W (週), M (月), Y (年)"),
    include_indicators: str | None = Query(
        None,
        description="Comma-separated indicators: ma,rsi,macd,volume (or 'all'). "
                    "'ma' expands to ma5,ma20,ma60.",
    ),
) -> PriceHistoryResponse:
    stock_code = stock_code.strip()
    if not TW_SYMBOL_RE.match(stock_code):
        raise HTTPException(status_code=422, detail="Invalid Taiwan stock code.")

    range = normalize_range(range)
    granularity, lookback_days, max_candles = RANGE_CONFIG[range]

    requested = parse_indicator_query(include_indicators)
    indicator_token = ",".join(sorted(requested)) if requested else ""

    import time as _time
    cache_key = f"{stock_code}:{range}:{indicator_token}"
    if cache_key in _tw_price_cache:
        cached_data, cached_at = _tw_price_cache[cache_key]
        if _time.time() - cached_at < _PRICE_CACHE_TTL:
            return PriceHistoryResponse(**cached_data)

    # Fetch enough daily history to cover the requested granularity
    daily_candles, is_mock = await get_tw_price_history(stock_code, lookback_days)

    # Aggregate into the chosen granularity
    candles = aggregate_candles(daily_candles, granularity)
    candles = trim_to_max(candles, max_candles)

    indicators_bundle = None
    if requested and candles:
        indicators_bundle = build_indicators(candles, requested)

    response_data: dict = {
        "stock_code": stock_code,
        "range": range,
        "candles": candles,
        "is_mock": is_mock,
        "indicators": indicators_bundle,
    }
    _tw_price_cache[cache_key] = (response_data, _time.time())

    indicators_model = None
    if indicators_bundle:
        macd_payload = indicators_bundle.pop("macd", None)
        macd_model = MACDBundle(**macd_payload) if macd_payload else None
        indicators_model = IndicatorsBundle(macd=macd_model, **indicators_bundle)

    return PriceHistoryResponse(
        stock_code=stock_code,
        range=range,
        candles=[CandlePoint(**c) for c in candles],
        is_mock=is_mock,
        indicators=indicators_model,
    )


# ── External news ─────────────────────────────────────────────────────────────

@app.get("/tw/external-news", response_model=ExternalNewsResponse)
async def external_news(
    category: str | None = Query(None, description="Filter by category key")
) -> ExternalNewsResponse:
    data = await get_external_news(category=category)
    categories = {
        cat: [ExternalNewsItem(**item) for item in items]
        for cat, items in data.get("categories", {}).items()
    }
    return ExternalNewsResponse(
        categories=categories,
        total=data.get("total", 0),
        status=data.get("status", "mock"),
    )


# ── Telegram ──────────────────────────────────────────────────────────────────

@app.post("/tw/telegram/watchlist/sync", response_model=TelegramWatchlistSyncResponse)
async def telegram_watchlist_sync(body: TelegramWatchlistSyncRequest) -> TelegramWatchlistSyncResponse:
    result = sync_watchlist(
        action=body.action,
        stock_code=body.stock_code,
        stock_name=body.stock_name,
    )
    return TelegramWatchlistSyncResponse(**result)


@app.post("/tw/telegram/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    background_tasks.add_task(handle_webhook, body)
    return {"ok": True}


# ── TW Calendar ───────────────────────────────────────────────────────────────

@app.get("/tw/calendar/dividends", response_model=DividendCalendarResponse)
async def calendar_dividends(
    symbol: str | None = Query(None, description="Optional TW stock code"),
    start: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    end: str | None = Query(None, description="YYYY-MM-DD; defaults to today + 90d"),
) -> DividendCalendarResponse:
    if symbol and not TW_SYMBOL_RE.match(symbol.strip()):
        raise HTTPException(status_code=422, detail="Invalid Taiwan stock code.")
    today = date.today()
    try:
        start_d = datetime.strptime(start, "%Y-%m-%d").date() if start else today
        end_d = datetime.strptime(end, "%Y-%m-%d").date() if end else today + timedelta(days=90)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")
    if end_d < start_d:
        raise HTTPException(status_code=422, detail="end must be on or after start.")

    data = await get_dividend_events(symbol.strip() if symbol else None, start_d, end_d)
    events = [DividendEvent(**e) for e in data["events"]]
    return DividendCalendarResponse(events=events, data_source=data.get("data_source", "mock"))


@app.get("/tw/calendar/earnings", response_model=EarningsCalendarResponse)
async def calendar_earnings(
    symbol: str | None = Query(None, description="Optional TW stock code"),
) -> EarningsCalendarResponse:
    if symbol and not TW_SYMBOL_RE.match(symbol.strip()):
        raise HTTPException(status_code=422, detail="Invalid Taiwan stock code.")
    data = await get_earnings_events(symbol.strip() if symbol else None)
    events = [EarningsEvent(**e) for e in data["events"]]
    return EarningsCalendarResponse(events=events, data_source=data.get("data_source", "mock"))


# ── TW ETF Holdings ───────────────────────────────────────────────────────────

@app.get("/tw/etf/holdings", response_model=ETFHoldingsResponse)
async def etf_holdings(
    symbol: str = Query(..., description="Taiwan ETF stock code (e.g. 0050, 0056)"),
) -> ETFHoldingsResponse:
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail="Invalid Taiwan stock code.")
    raw = get_etf_holdings(symbol)
    return ETFHoldingsResponse(
        symbol=raw["symbol"],
        fund_name=raw.get("fund_name"),
        total_constituents=raw.get("total_constituents"),
        last_updated=raw.get("last_updated"),
        holdings=[ETFHolding(**h) for h in raw.get("holdings", [])],
        sector_weights=[ETFSectorWeight(**s) for s in raw.get("sector_weights", [])],
        status=raw.get("status", "unsupported"),
    )
