import re
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request, Body
from fastapi.concurrency import run_in_threadpool

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from fastapi.middleware.cors import CORSMiddleware

from .models.schemas import (
    HealthResponse,
    StockAnalysisResponse, TaiwanStockAnalysisResponse,
    AgentAnalysisRequest, AgentAnalysisResponse,
    NewsItem,
    FundamentalsData, AnalystTarget, LastEarnings, ESGData,
    CompetitorResponse, PeerStock,
    MarketOverviewResponse, EconomicIndicator, TopStock,
    SearchResponse, SearchResult,
    # New TW detail schemas
    RevenueSummary, ValuationSummary, InstitutionalSummary,
    ChipRiskSummary, CashFlowSummary, MacroEnvironmentSummary, ETFSummary,
    CanslimSummary,
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
from .models.screener_schemas import CanslimFullResult, ScreeningResult
from .graphs.stock_analysis_graph import run_analysis
from .graphs.tw_stock_graph import run_tw_analysis
from .services.tw_unified_analysis import run_unified_analysis
from .services.fmp_market import get_market_overview
from .services.fmp_peers import get_competitors
from .services.fmp_client import fmp_get
from .services.finmind_detail import get_tw_detail, detect_is_etf
from .services.tw_macro import get_macro_summary
from .services.tw_stocks_list import get_tw_stocks
from .services.yahoo_news import get_external_news, get_tw_stock_news
from .services.telegram_service import sync_watchlist, handle_webhook
from .services.finmind_market import get_tw_market_data, get_tw_price_history
from .services.tw_candles import RANGE_CONFIG, normalize_range, aggregate_candles, trim_to_max
from .services.tw_indicators import build_indicators, parse_indicator_query
from .services.tw_calendar import (
    get_dividend_events, get_earnings_events, get_next_dividend_live,
    get_next_dividend_for,
)
from .services.tw_etf_holdings import get_etf_holdings
from .services.fmp_price_history import get_us_price_history
from backend.technical_analyzer.v1.contracts.input_contract import ContextBundle, OHLCVBar, OHLCVSeries
from backend.technical_analyzer.v1.orchestration import AIAnalysisResultBuilder
from .api.routes import quality_watch, screeners
from backend.screeners.multi_factor_surge.api import router as multi_factor_surge_router
from backend.app.services.strategy.canslim.observer import observe as observe_canslim
from backend.app.services.strategy.canslim.live_screening import (
    durability_metrics_for_symbol,
    screen_symbol,
    screen_symbol_full,
    screen_symbol_local_snapshot,
)
from backend.app.services.strategy.canslim.types import MarketFeatures
from backend.app.services.multi_agent_analysis import run_multi_agent_analysis
from backend.app.services import file_cache

app = FastAPI(title="AI Stock Analysis API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(screeners.router)
app.include_router(quality_watch.router)
app.include_router(multi_factor_surge_router)

SYMBOL_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")
TW_SYMBOL_RE = re.compile(r"^\d{4,6}$")

# In-memory cache for price history and stocks list
_tw_price_cache: dict[str, tuple[dict, float]] = {}
_stocks_cache: tuple[dict | None, float] = (None, 0.0)
_PRICE_CACHE_TTL = 300
_STOCKS_CACHE_TTL = 86400
_STOCKS_CACHE_LIMIT = 10000


def _is_reusable_tw_analysis_cache(payload: dict) -> bool:
    """Only reuse AI analysis generated from real market data.

    A model response generated successfully over fallback OHLCV is still a mock
    analysis and must not be pinned in the daily cache.
    """
    return payload.get("analysis_source") == "ai" and payload.get("data_source") == "live"


def _ohlcv_series_from_tw_candles(symbol: str, candles: list[dict], is_mock: bool) -> OHLCVSeries:
    bars: list[OHLCVBar] = []
    previous_close: Decimal | None = None
    source = "mock" if is_mock else "live"
    for raw in candles:
        close = Decimal(str(raw["close"]))
        volume = int(raw.get("volume") or 0)
        bars.append(OHLCVBar(
            date=date.fromisoformat(str(raw["time"])),
            open=Decimal(str(raw["open"])),
            high=Decimal(str(raw["high"])),
            low=Decimal(str(raw["low"])),
            close=close,
            volume=volume,
            turnover_value=close * Decimal(volume),
            is_adjusted=True,
            data_source=source,
            previous_close=previous_close,
        ))
        previous_close = close
    if not bars:
        raise ValueError("empty TW candle list")
    return OHLCVSeries(symbol, bars)


def _tw_news_items_from_analysis(news_analysis: object | None) -> list[NewsItem]:
    """Map TW news agent headlines to the public recent_news shape."""
    if not news_analysis:
        return []

    headlines = getattr(news_analysis, "recent_headlines", None)
    if not headlines and isinstance(news_analysis, dict):
        headlines = news_analysis.get("recent_headlines")
    if not headlines:
        return []

    items: list[NewsItem] = []
    for raw in headlines[:8]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        items.append(NewsItem(
            title=title,
            published_at=str(raw.get("published_at") or raw.get("date") or ""),
            source=str(raw.get("source") or "市場新聞"),
            url=raw.get("url"),
        ))
    return items


class _CandleStoreAdapter:
    def __init__(self, symbol: str, candles: list[dict]) -> None:
        self.symbol = str(symbol)
        self.candles = list(candles or [])

    def get_ohlcv_as_of(self, stock_id: str, as_of_date: str, lookback_bars: int):
        import pandas as pd

        if str(stock_id) != self.symbol or not self.candles:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        frame = pd.DataFrame(self.candles).copy()
        if "time" in frame and "date" not in frame:
            frame["date"] = frame["time"]
        if "date" not in frame:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        cutoff = pd.to_datetime(as_of_date)
        frame = frame[frame["date"].notna() & (frame["date"] <= cutoff)].tail(lookback_bars).copy()
        frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
        if "turnover" not in frame and "close" in frame and "volume" in frame:
            frame["turnover"] = frame["close"].astype(float) * frame["volume"].astype(float)
        return frame.reset_index(drop=True)


def _canslim_summary_from_cards(cards: dict, durability_metrics: dict | None = None) -> CanslimSummary:
    warnings: list[str] = []
    grades: dict[str, str] = {}
    scores: dict[str, dict] = {}
    hard_blocked: dict[str, bool] = {}
    for horizon, card in cards.items():
        grades[horizon] = str(card.scores.get("grade", "C"))
        scores[horizon] = {
            "signal": card.scores.get("signal"),
            "signal_raw": card.scores.get("signal_raw"),
            "signal_achievable_max": card.scores.get("signal_achievable_max"),
            "risk": card.scores.get("risk"),
            "confidence": card.scores.get("confidence"),
        }
        hard_blocked[horizon] = bool(card.scores.get("hard_blocked", False))
        warnings.extend(card.data_warnings)
    return CanslimSummary(
        grades=grades,
        scores=scores,
        hard_blocked=hard_blocked,
        data_warnings=list(dict.fromkeys(warnings)),
        is_mock=False,
        durability_score=durability_metrics.get("score") if durability_metrics else None,
        durability_components=durability_metrics.get("components", {}) if durability_metrics else {},
        durability_metrics=durability_metrics,
    )


def _canslim_summary_from_full(full: CanslimFullResult) -> CanslimSummary:
    return CanslimSummary(
        grades={"screening": full.grade},
        scores={
            "screening": {
                "overall_score": full.overall_score,
                "risk_level": full.risk_level,
                "confidence": full.confidence,
                "pass_status": full.pass_status,
            }
        },
        hard_blocked={"screening": full.pass_status == "FAIL"},
        data_warnings=list(full.missing_data),
        is_mock=full.is_mock_or_fallback_data,
        durability_score=full.durability_score,
        durability_components=dict(full.durability_components or {}),
        durability_metrics=full.durability_metrics,
    )


def _mock_canslim_summary(message: str) -> CanslimSummary:
    return CanslimSummary(
        grades={horizon: "C" for horizon in ("short_term", "swing_term", "long_term")},
        scores={
            horizon: {"signal": 0, "signal_raw": 0, "signal_achievable_max": 1, "risk": 0, "confidence": 0}
            for horizon in ("short_term", "swing_term", "long_term")
        },
        hard_blocked={horizon: False for horizon in ("short_term", "swing_term", "long_term")},
        data_warnings=[message],
        is_mock=True,
    )


def _detail_to_canslim_inputs(detail: dict) -> tuple[dict, dict]:
    rev = detail.get("revenue_summary") or {}
    val = detail.get("valuation_summary") or {}
    inst = detail.get("institutional_summary") or {}
    fin_metrics = {
        "eps_yoy": detail.get("eps_yoy"),
        "annual_eps": detail.get("annual_eps"),
        "roe": detail.get("roe"),
        "op_margin_last4": detail.get("op_margin_last4"),
        "pe_ttm": val.get("per"),
    }
    detail_inputs = {
        "month_revenue_yoy": [rev.get("yoy_pct")] if rev.get("yoy_pct") is not None else None,
        "foreign_net_5": [inst.get("foreign_net_5d")] if inst.get("foreign_net_5d") is not None else None,
        "trust_net_5": [inst.get("trust_net_5d")] if inst.get("trust_net_5d") is not None else None,
        "dealer_net_5": [inst.get("dealer_net_5d")] if inst.get("dealer_net_5d") is not None else None,
    }
    return fin_metrics, detail_inputs


async def _build_canslim_summary_for_symbol(
    symbol: str,
    *,
    market: dict | None = None,
    detail: dict | None = None,
    durability_metrics: dict | None = None,
) -> CanslimSummary:
    market = market if market is not None else (await get_tw_market_data(symbol))[0]
    detail = detail if detail is not None else await get_tw_detail(symbol)
    chart_data = market.get("chart_data", [])
    as_of_date = str(chart_data[-1]["time"]) if chart_data else date.today().isoformat()
    fin_metrics, canslim_detail = _detail_to_canslim_inputs(detail)
    durability_metrics = (
        durability_metrics
        if durability_metrics is not None
        else await run_in_threadpool(durability_metrics_for_symbol, symbol, as_of_date)
    )
    cards = observe_canslim(
        symbol,
        as_of_date,
        store=_CandleStoreAdapter(symbol, chart_data),
        market=MarketFeatures(),
        fin_metrics=fin_metrics,
        detail=canslim_detail,
        event_window_active=False,
        eps_filing_date=None,
    )
    return _canslim_summary_from_cards(cards, durability_metrics)


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
    symbol: str = Query(..., description="Taiwan stock symbol (4–6 digits, e.g. 2330)"),
    include_canslim: bool = Query(False, description="Include optional CAN SLIM observation summary"),
    include_screening: bool = Query(False, description="Include optional CAN SLIM screening result"),
) -> TaiwanStockAnalysisResponse:
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).",
        )

    # Same (symbol, UTC-day, flags) is served from disk so a repeat request does not
    # re-run the Gemini agents. Only AI-backed responses are cached (see save below),
    # so a mock fallback is never pinned for the day.
    _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _cache_key = f"{symbol}_{_today}_{int(include_canslim)}_{int(include_screening)}"
    _cached = file_cache.load("analyze_tw", _cache_key)
    if isinstance(_cached, dict) and _is_reusable_tw_analysis_cache(_cached):
        try:
            return TaiwanStockAnalysisResponse(**_cached)
        except Exception:
            pass  # corrupt/old shape -> recompute

    import asyncio as _asyncio
    state_task = _asyncio.create_task(run_tw_analysis(symbol))
    detail_task = _asyncio.create_task(get_tw_detail(symbol))
    macro_task = _asyncio.create_task(get_macro_summary())
    dividend_task = _asyncio.create_task(get_next_dividend_live(symbol))
    # Single-call unified analysis (all pillars + synthesis in one model call);
    # replaces the multi-agent comprehensive graph that took minutes per symbol.
    comprehensive_task = _asyncio.create_task(run_unified_analysis(symbol))
    news_task = _asyncio.create_task(get_tw_stock_news(symbol))

    state, detail, macro_raw, next_div_raw, comprehensive_state, tw_news_raw = await _asyncio.gather(
        state_task, detail_task, macro_task, dividend_task, comprehensive_task, news_task,
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

    cf = detail.get("cashflow_summary", {})
    revenue_summary = RevenueSummary(**rev) if rev else None
    valuation_summary = ValuationSummary(**val) if val else None
    institutional_summary = InstitutionalSummary(**inst) if inst else None
    chip_risk_summary = ChipRiskSummary(**chip) if chip else None
    cashflow_summary = CashFlowSummary(**cf) if cf else None
    macro_summary = MacroEnvironmentSummary(**macro_raw) if macro_raw else None

    next_dividend = None
    if next_div_raw:
        next_dividend = DividendEvent(**next_div_raw)

    etf_holdings_resp = None
    if is_etf:
        raw_h = await get_etf_holdings(symbol)
        if raw_h.get("status") != "unsupported":
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

    fundamental_analysis = None
    technical_analysis = None
    chip_analysis = None
    news_analysis = None
    if comprehensive_state:
        fundamental_analysis = comprehensive_state.get("fundamental_analysis")
        technical_analysis = comprehensive_state.get("technical_analysis")
        chip_analysis = comprehensive_state.get("chip_analysis")
        news_analysis = comprehensive_state.get("news_analysis")

    # Prefer live Yahoo Finance news; fall back to news_analysis agent headlines
    if tw_news_raw:
        recent_news = [
            NewsItem(
                title=item["title"],
                published_at=item.get("published_at") or "",
                source=item.get("source") or "Yahoo Finance",
                url=item.get("url"),
            )
            for item in tw_news_raw
        ]
    else:
        recent_news = _tw_news_items_from_analysis(news_analysis)

    equity_research = None
    if comprehensive_state and comprehensive_state.get("equity_research"):
        equity_research = comprehensive_state["equity_research"]

    screening_result = None
    canslim_full = None
    if include_screening:
        try:
            canslim_full = await screen_symbol_full(symbol)
            screening_result = canslim_full.screening_result
        except Exception:
            screening_result = None

    canslim_summary = None
    if include_canslim:
        try:
            canslim_summary = await _build_canslim_summary_for_symbol(
                symbol,
                market=market,
                detail=detail,
                durability_metrics=(
                    canslim_full.durability_metrics
                    if canslim_full is not None and canslim_full.durability_metrics is not None
                    else None
                ),
            )
        except Exception as exc:
            canslim_summary = _mock_canslim_summary(f"CANSLIM unavailable: {exc}")
    elif canslim_full is not None:
        canslim_summary = _canslim_summary_from_full(canslim_full)

    response = TaiwanStockAnalysisResponse(
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
        recent_news=recent_news,
        chart_data=market.get("chart_data", []),
        data_source="mock" if state.get("data_is_mock") else "live",
        analysis_source="mock" if state.get("analysis_is_mock") else "ai",
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        is_etf=is_etf,
        revenue_summary=revenue_summary,
        valuation_summary=valuation_summary,
        institutional_summary=institutional_summary,
        chip_risk_summary=chip_risk_summary,
        cashflow_summary=cashflow_summary,
        macro_summary=macro_summary,
        next_dividend=next_dividend,
        etf_holdings=etf_holdings_resp,
        fundamental=fundamental_analysis,
        technical=technical_analysis,
        chip=chip_analysis,
        news=news_analysis,
        comprehensive_analysis=comprehensive_analysis,
        equity_research=equity_research,
        canslim_summary=canslim_summary,
        screening_result=screening_result,
        canslim_full=canslim_full,
    )

    if _is_reusable_tw_analysis_cache(response.model_dump(mode="json")):
        file_cache.save("analyze_tw", _cache_key, response.model_dump(mode="json"))
    return response


@app.get("/tw/canslim-summary", response_model=CanslimSummary)
async def canslim_summary_tw(
    symbol: str = Query(..., description="Taiwan stock symbol (4–6 digits, e.g. 2330)"),
) -> CanslimSummary:
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).",
        )
    try:
        return await _build_canslim_summary_for_symbol(symbol)
    except Exception as exc:
        return _mock_canslim_summary(f"CANSLIM unavailable: {exc}")


@app.get("/tw/screen", response_model=ScreeningResult)
async def screen_tw(
    symbol: str = Query(..., description="Taiwan stock symbol (4–6 digits, e.g. 2330)"),
    as_of_date: str | None = Query(None, description="Optional YYYY-MM-DD as-of date"),
    source_mode: str = Query(
        "live",
        pattern="^(live|batch)$",
        description="live uses single-symbol live enrichment; batch uses the same local-store source contract as full-universe scanning.",
    ),
) -> ScreeningResult:
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).",
        )
    if source_mode == "batch":
        return await run_in_threadpool(screen_symbol_local_snapshot, symbol, as_of_date)
    return await screen_symbol(symbol, as_of_date=as_of_date)


@app.get("/tw/screen/full", response_model=CanslimFullResult)
async def screen_tw_full(
    symbol: str = Query(..., description="Taiwan stock symbol (4–6 digits, e.g. 2330)"),
    as_of_date: str | None = Query(None, description="Optional YYYY-MM-DD as-of date"),
) -> CanslimFullResult:
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).",
        )
    return await screen_symbol_full(symbol, as_of_date=as_of_date)


@app.get("/tw/entry-context")
async def entry_context_tw(
    symbol: str = Query(..., description="Taiwan stock symbol (4–6 digits, e.g. 2330)"),
):
    """Verb-free entry timing/价位 conditions (Task 1A): 貴不貴 (extension + valuation
    percentile), 等哪裡 (support/confluence), 能不能加 (structure gate). NOT a buy/sell signal."""
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).")
    from dataclasses import asdict
    from backend.app.services.strategy.canslim.entry_context import entry_context_for_symbol
    try:
        ctx = await run_in_threadpool(entry_context_for_symbol, symbol)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"entry-context unavailable: {type(exc).__name__}")
    return asdict(ctx)


@app.post("/tw/allocate")
async def allocate_tw(payload: dict = Body(...)):
    """Verb-free capital ALLOCATION calculator (Task 1B): given the user's portfolio_parameters
    + chosen symbols, returns base allocation / pyramiding-ladder / risk-dashboard tables. It is
    arithmetic on the user's own inputs — NOT a buy/sell recommendation."""
    from dataclasses import asdict
    from backend.app.services.strategy.canslim.allocation import allocate_for_watchlist
    symbols = [str(s).strip() for s in (payload.get("symbols") or []) if str(s).strip()]
    params = payload.get("portfolio_parameters") or {}
    sectors = payload.get("sectors") or {}
    if not symbols:
        raise HTTPException(status_code=422, detail="symbols[] required")
    for s in symbols:
        if not TW_SYMBOL_RE.match(s):
            raise HTTPException(status_code=422, detail=f"invalid symbol: {s}")
    try:
        res = await run_in_threadpool(lambda: allocate_for_watchlist(symbols, params, sectors=sectors))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"allocation unavailable: {type(exc).__name__}")
    return asdict(res)


@app.get("/tw/agent-analysis", response_model=AgentAnalysisResponse)
async def tw_agent_analysis_get(
    symbol: str = Query(..., description="Taiwan stock symbol (4–6 digits, e.g. 2330)"),
    question: str | None = Query(None, description="Optional user question for Gemini/Claude"),
) -> AgentAnalysisResponse:
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).",
        )
    _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _cache_key = f"{symbol}_{_today}_{question or 'default'}"
    _cached = file_cache.load("tw_agent_analysis", _cache_key)
    if isinstance(_cached, dict):
        try:
            return AgentAnalysisResponse(**_cached)
        except Exception:
            pass
    response = await run_multi_agent_analysis(symbol, question=question)
    if any(stage.status == "completed" for stage in response.analysis.agents[1:]):
        file_cache.save("tw_agent_analysis", _cache_key, response.model_dump(mode="json"))
    return response


@app.post("/tw/agent-analysis", response_model=AgentAnalysisResponse)
async def tw_agent_analysis_post(request: AgentAnalysisRequest) -> AgentAnalysisResponse:
    symbol = request.symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).",
        )
    _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _cache_key = f"{symbol}_{_today}_{request.question or 'default'}"
    _cached = file_cache.load("tw_agent_analysis", _cache_key)
    if isinstance(_cached, dict):
        try:
            return AgentAnalysisResponse(**_cached)
        except Exception:
            pass
    response = await run_multi_agent_analysis(symbol, question=request.question)
    if any(stage.status == "completed" for stage in response.analysis.agents[1:]):
        file_cache.save("tw_agent_analysis", _cache_key, response.model_dump(mode="json"))
    return response


@app.get("/tw/adjusted-price")
async def tw_adjusted_price(
    symbol: str = Query(..., description="Taiwan stock symbol"),
    days: int = Query(250, ge=20, le=2000),
) -> dict:
    """Self-computed dividend-adjusted (還原) close series for one stock (free)."""
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail="Invalid Taiwan symbol.")
    from backend.app.services.tw_adjusted_prices import get_adjusted_prices
    return get_adjusted_prices(symbol, days=days)


@app.get("/tw/market/heatmap")
async def tw_market_heatmap() -> dict:
    """Sector heatmap (板塊熱力圖) computed from the local OHLCV store (free)."""
    from backend.app.services.tw_market_heatmap import get_market_heatmap
    return await get_market_heatmap()


@app.get("/tw/finmind/datasets")
async def tw_finmind_datasets() -> dict:
    """Curated, grouped FinMind dataset list for the in-app playground."""
    from backend.app.services.finmind_query import DATASET_GROUPS
    return {"groups": DATASET_GROUPS}


@app.get("/tw/finmind/query")
async def tw_finmind_query(
    dataset: str = Query(..., description="FinMind dataset name (must be allow-listed)"),
    data_id: str = Query("", description="Stock/contract id, e.g. 2330"),
    start_date: str = Query("", description="YYYY-MM-DD"),
    end_date: str = Query("", description="YYYY-MM-DD"),
) -> dict:
    """Server-side FinMind dataset query (token stays server-side, loop-free)."""
    from backend.app.services.finmind_query import query_finmind
    return await query_finmind(dataset, data_id=data_id, start_date=start_date, end_date=end_date)


@app.get("/ai-analysis/tw")
async def ai_analysis_tw(
    symbol: str = Query(..., description="Taiwan stock symbol (4–6 digits, e.g. 2330)")
) -> dict:
    """Return the unified technical-analyzer v1 AIAnalysisResult contract."""
    symbol = symbol.strip()
    if not TW_SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=422,
            detail="Invalid Taiwan symbol. Must be 4–6 digits (e.g. 2330, 00878).",
        )

    candles, is_mock = await get_tw_price_history(symbol, 220)
    try:
        ohlcv = _ohlcv_series_from_tw_candles(symbol, candles, is_mock)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="No candle data available for AI analysis.") from exc

    stock_name = symbol
    try:
        stock_list = await get_tw_stocks(q=symbol, limit=10)
        exact = next((stock for stock in stock_list.get("stocks", []) if stock.get("stock_code") == symbol), None)
        if exact:
            stock_name = exact.get("company_name") or symbol
    except Exception:
        stock_name = symbol

    context = ContextBundle(
        market_cap_bucket="large",
        liquidity_bucket="high",
        disposition_status="normal",
    )
    result = AIAnalysisResultBuilder().build(
        symbol,
        ohlcv,
        context,
        symbol_name=stock_name,
        sector_tag="TWSE",
    )
    return result.to_dict()


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
    # Only cache the unfiltered full list; request-specific limits are applied after cache lookup.
    if not q and not stock_type and not industry:
        if cached and (_time.time() - cached_at) < _STOCKS_CACHE_TTL:
            data = cached
        else:
            data = await get_tw_stocks(limit=_STOCKS_CACHE_LIMIT)
            _stocks_cache = (data, _time.time())
    else:
        data = await get_tw_stocks(q=q, stock_type=stock_type, industry=industry, limit=limit)

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
    raw = await get_etf_holdings(symbol)
    return ETFHoldingsResponse(
        symbol=raw["symbol"],
        fund_name=raw.get("fund_name"),
        total_constituents=raw.get("total_constituents"),
        last_updated=raw.get("last_updated"),
        holdings=[ETFHolding(**h) for h in raw.get("holdings", [])],
        sector_weights=[ETFSectorWeight(**s) for s in raw.get("sector_weights", [])],
        status=raw.get("status", "unsupported"),
    )
