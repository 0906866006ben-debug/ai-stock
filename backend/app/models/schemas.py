from pydantic import BaseModel, field_validator
from typing import Optional, Literal, Any


class HealthResponse(BaseModel):
    status: str
    version: str


class ChartPoint(BaseModel):
    time: str  # "YYYY-MM-DD"
    value: float


class NewsItem(BaseModel):
    title: str
    published_at: str
    source: str
    url: Optional[str] = None


class StockAIAnalysis(BaseModel):
    """PydanticAI output model — internal use only."""
    summary: str
    trend: str
    confidence: float
    risks: list[str]
    catalysts: list[str]
    recommendation: str

    @field_validator("trend")
    @classmethod
    def validate_trend(cls, v: str) -> str:
        allowed = {"bullish", "bearish", "neutral"}
        v = v.lower().strip()
        return v if v in allowed else "neutral"

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


# ── FMP fundamentals sub-models ──────────────────────────────────────────────

class AnalystTarget(BaseModel):
    consensus: Optional[str] = None
    high: Optional[str] = None
    low: Optional[str] = None
    median: Optional[str] = None


class LastEarnings(BaseModel):
    date: Optional[str] = None
    eps_actual: Optional[float] = None
    eps_estimated: Optional[float] = None


class ESGData(BaseModel):
    environmental: Optional[float] = None
    social: Optional[float] = None
    governance: Optional[float] = None
    total: Optional[float] = None


class FundamentalsData(BaseModel):
    financial_metrics: dict[str, str] = {}
    analyst: AnalystTarget = AnalystTarget()
    next_earnings_date: Optional[str] = None
    last_earnings: LastEarnings = LastEarnings()
    esg: ESGData = ESGData()


# ── US stock response ─────────────────────────────────────────────────────────

class StockAnalysisResponse(BaseModel):
    symbol: str
    company_name: str
    current_price: float
    price_change_percent: float
    trend: str
    confidence: float
    summary: str
    risks: list[str]
    catalysts: list[str]
    recommendation: str
    recent_news: list[NewsItem]
    financial_summary: dict[str, str]
    chart_data: list[ChartPoint]
    data_source: str
    fundamentals: Optional[FundamentalsData] = None


# ── Taiwan analysis detail sub-models ────────────────────────────────────────

class RevenueSummary(BaseModel):
    latest_revenue: Optional[str] = None
    yoy_pct: Optional[float] = None
    mom_pct: Optional[float] = None
    available_months: int = 0
    status: str = "no_data"


class ValuationSummary(BaseModel):
    per: Optional[float] = None
    pbr: Optional[float] = None
    dividend_yield: Optional[float] = None
    status: str = "no_data"  # cheap / fair / expensive / no_data


class InstitutionalSummary(BaseModel):
    foreign_net_5d: Optional[int] = None
    foreign_net_10d: Optional[int] = None
    trust_net_5d: Optional[int] = None
    trust_net_10d: Optional[int] = None
    dealer_net_5d: Optional[int] = None
    direction: str = "unknown"
    status: str = "no_data"


class ChipRiskSummary(BaseModel):
    margin_balance: Optional[int] = None
    short_balance: Optional[int] = None
    lending_balance: Optional[int] = None
    chip_direction: str = "unknown"
    risk_level: str = "unknown"
    status: str = "no_data"


class MacroEnvironmentSummary(BaseModel):
    usd_twd: Optional[float] = None
    fed_rate: Optional[float] = None
    us_10y_yield: Optional[float] = None
    gold_price: Optional[float] = None
    oil_wti: Optional[float] = None
    sp500: Optional[float] = None
    nasdaq: Optional[float] = None
    status: str = "no_data"


class ETFSummary(BaseModel):
    nav: Optional[float] = None
    premium_discount_pct: Optional[float] = None
    dividend_yield: Optional[float] = None
    dividend_frequency: Optional[str] = None
    tracking_index: Optional[str] = None
    status: str = "no_data"


# ── Taiwan stock response ─────────────────────────────────────────────────────

class CandlePoint(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class TaiwanStockAIAnalysis(BaseModel):
    """PydanticAI structured output — internal use only."""
    summary: str
    trend: Literal["看漲", "看跌", "中立"]
    confidence: float
    risks: list[str]
    catalysts: list[str]
    recommendation: str

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class TaiwanStockAnalysisResponse(BaseModel):
    symbol: str
    company_name: str
    market_type: str
    currency: str = "TWD"
    current_price: float
    price_change_percent: float
    volume: int
    trend: str
    confidence: float
    summary: str
    risks: list[str]
    catalysts: list[str]
    recommendation: str
    recent_news: list[NewsItem] = []
    chart_data: list[CandlePoint]
    data_source: str
    analysis_source: str
    disclaimer: str = "本分析僅供參考，不構成投資建議。"
    analyzed_at: str
    # Detailed analysis fields
    is_etf: bool = False
    revenue_summary: Optional[RevenueSummary] = None
    valuation_summary: Optional[ValuationSummary] = None
    institutional_summary: Optional[InstitutionalSummary] = None
    chip_risk_summary: Optional[ChipRiskSummary] = None
    macro_summary: Optional[MacroEnvironmentSummary] = None
    etf_summary: Optional[ETFSummary] = None


# ── Competitor / peers ────────────────────────────────────────────────────────

class PeerStock(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    price: Optional[float] = None
    market_cap: Optional[str] = None
    market_cap_fmt: Optional[str] = None
    pe_ratio: Optional[str] = None
    gross_margin: Optional[str] = None
    net_margin: Optional[str] = None
    roe: Optional[str] = None
    ev_ebitda: Optional[str] = None


class CompetitorResponse(BaseModel):
    symbol: str
    peers: list[PeerStock]


# ── Market overview ───────────────────────────────────────────────────────────

class EconomicIndicator(BaseModel):
    name: str
    label: str
    value: Optional[float] = None
    date: Optional[str] = None


class TopStock(BaseModel):
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    price: Optional[float] = None
    market_cap: Optional[float] = None
    sector: Optional[str] = None
    volume: Optional[int] = None
    beta: Optional[float] = None


class MarketOverviewResponse(BaseModel):
    economic_indicators: list[EconomicIndicator]
    top_stocks: list[TopStock]
    data_source: str


# ── Symbol search ─────────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    symbol: str
    name: str
    exchange: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


# ── TW Stock directory ────────────────────────────────────────────────────────

class StockInfo(BaseModel):
    stock_code: str
    company_name: str
    market_type: str
    industry: Optional[str] = None


class StockListResponse(BaseModel):
    stocks: list[StockInfo]
    total: int
    returned: int
    data_source: str = "live"


# ── TW Price history ──────────────────────────────────────────────────────────

class PriceHistoryResponse(BaseModel):
    stock_code: str
    range: str
    candles: list[CandlePoint]
    is_mock: bool


# ── External news ─────────────────────────────────────────────────────────────

class ExternalNewsItem(BaseModel):
    title: str
    url: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[str] = None
    category: str


class ExternalNewsResponse(BaseModel):
    categories: dict[str, list[ExternalNewsItem]]
    total: int
    status: str = "live"


# ── Telegram watchlist ────────────────────────────────────────────────────────

class TelegramWatchlistSyncRequest(BaseModel):
    action: str  # "add" or "remove"
    stock_code: str
    stock_name: Optional[str] = None


class TelegramWatchlistSyncResponse(BaseModel):
    status: str
    message: str
