from pydantic import BaseModel, Field, field_validator
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
    chart_data: list["CandlePoint"]
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
    # Phase 2 enrichments (backward-compatible — nullable)
    next_dividend: Optional["DividendEvent"] = None
    etf_holdings: Optional["ETFHoldingsResponse"] = None
    # Phase 3: 4-pillar comprehensive analysis (backward-compatible — nullable)
    fundamental: Optional["FundamentalAnalysis"] = None
    technical: Optional["TechnicalAnalysis"] = None
    chip: Optional["ChipAnalysis"] = None
    news: Optional["NewsAnalysis"] = None
    comprehensive_analysis: Optional["ComprehensiveAnalysis"] = None
    # Phase 4: elite equity research framework (backward-compatible — nullable)
    equity_research: Optional["EquityResearch"] = None


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
    indicators: Optional["IndicatorsBundle"] = None


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


# ── Technical indicators (price-history extension) ────────────────────────────

class MACDBundle(BaseModel):
    macd: list[Optional[float]] = []
    signal: list[Optional[float]] = []
    histogram: list[Optional[float]] = []


class IndicatorsBundle(BaseModel):
    ma5: Optional[list[Optional[float]]] = None
    ma20: Optional[list[Optional[float]]] = None
    ma60: Optional[list[Optional[float]]] = None
    ma120: Optional[list[Optional[float]]] = None
    ma240: Optional[list[Optional[float]]] = None
    rsi: Optional[list[Optional[float]]] = None
    macd: Optional[MACDBundle] = None
    volume: Optional[list[int]] = None
    kd: Optional[dict] = None               # {"%K": [...], "%D": [...]}
    bollinger_bands: Optional[dict] = None  # {"upper": [...], "middle": [...], "lower": [...]}
    atr: Optional[list[Optional[float]]] = None
    support_resistance: Optional[dict] = None  # {"support": [...], "resistance": [...]}


# ── TW Calendar ───────────────────────────────────────────────────────────────

class DividendEvent(BaseModel):
    stock_code: str
    company_name: Optional[str] = None
    ex_date: Optional[str] = None
    payment_date: Optional[str] = None
    announcement_date: Optional[str] = None
    cash_per_share: Optional[float] = None
    stock_per_share: Optional[float] = None
    type: str = "cash"  # cash | stock | mixed


class DividendCalendarResponse(BaseModel):
    events: list[DividendEvent]
    data_source: str = "live"


class EarningsEvent(BaseModel):
    stock_code: str
    fiscal_year: int
    fiscal_quarter: int
    deadline: str
    actual_filing_date: Optional[str] = None
    eps: Optional[float] = None
    is_upcoming: bool = True


class EarningsCalendarResponse(BaseModel):
    events: list[EarningsEvent]
    data_source: str = "live"


# ── ETF Holdings ──────────────────────────────────────────────────────────────

class ETFHolding(BaseModel):
    stock_code: Optional[str] = None
    company_name: str
    weight_pct: Optional[float] = None
    shares: Optional[int] = None


class ETFSectorWeight(BaseModel):
    sector: str
    weight_pct: float


class ETFHoldingsResponse(BaseModel):
    symbol: str
    fund_name: Optional[str] = None
    total_constituents: Optional[int] = None
    last_updated: Optional[str] = None
    holdings: list[ETFHolding] = []
    sector_weights: list[ETFSectorWeight] = []
    status: str = "live"  # live | mock | unsupported


# ── Telegram watchlist ────────────────────────────────────────────────────────

class TelegramWatchlistSyncRequest(BaseModel):
    action: str  # "add" or "remove"
    stock_code: str
    stock_name: Optional[str] = None


class TelegramWatchlistSyncResponse(BaseModel):
    status: str
    message: str


# ── 4-Pillar Analysis Schemas ────────────────────────────────────────────────

class FundamentalMetrics(BaseModel):
    """Key fundamental financial metrics."""
    latest_revenue: Optional[str] = None  # e.g., "196.8B"
    revenue_yoy: Optional[float] = None  # Year-over-year % change
    revenue_mom: Optional[float] = None  # Month-over-month % change
    eps_latest: Optional[float] = None  # Latest earnings per share
    eps_yoy: Optional[float] = None  # EPS YoY % change
    pe_ratio: Optional[float] = None  # Price-to-Earnings
    pb_ratio: Optional[float] = None  # Price-to-Book
    roe: Optional[float] = None  # Return on Equity %
    roa: Optional[float] = None  # Return on Assets %
    gross_margin: Optional[float] = None  # Gross profit margin %
    operating_margin: Optional[float] = None  # Operating margin %
    net_margin: Optional[float] = None  # Net profit margin %
    dividend_yield: Optional[float] = None  # Annual dividend yield %
    payout_ratio: Optional[float] = None  # Dividend payout ratio %
    debt_ratio: Optional[float] = None  # Total debt / assets
    current_ratio: Optional[float] = None  # Current assets / current liabilities
    quick_ratio: Optional[float] = None  # Quick assets / current liabilities
    operating_cf: Optional[str] = None  # Operating cash flow (e.g., "1.2T")
    free_cf: Optional[str] = None  # Free cash flow
    cf_trend: str = "stable"  # strong | stable | declining


class FundamentalAnalysis(BaseModel):
    """Fundamental analysis output from agent."""
    summary: str  # Traditional Chinese narrative
    revenue_trend: str  # improving | stable | declining
    profitability: dict  # Keys: trend, quality, metrics
    valuation: dict  # Keys: level, support, interpretation
    financial_health: dict  # Keys: debt_risk, liquidity, cash_flow_quality
    risks: list[str]  # List of fundamental risks
    catalysts: list[str]  # Positive catalysts
    metrics: FundamentalMetrics  # Raw metrics
    confidence: float = 0.5  # 0-1 confidence level
    is_mock: bool = False  # Whether data is mocked


class TechnicalAnalysis(BaseModel):
    """Technical analysis output from agent."""
    summary: str  # Traditional Chinese narrative
    trend: str  # uptrend | downtrend | sideways
    momentum: dict  # Keys: rsi, rsi_signal, macd_signal, trend_confirmation
    volatility: dict  # Keys: atr, bb_position, volatility_level
    key_levels: dict  # Keys: support, resistance, breakout_potential
    risks: list[str]  # Technical risks (e.g., overbought, divergence)
    opportunities: list[str]  # Trading opportunities
    confidence: float = 0.5  # 0-1 confidence level
    is_mock: bool = False  # Whether data is mocked


class ChipAnalysis(BaseModel):
    """Chip/institutional analysis output from agent."""
    summary: str  # Traditional Chinese narrative
    institutional_sentiment: dict  # Keys: foreign, domestic_fund, dealer with trends
    chip_position: dict  # Keys: overall_trend, abnormal_movement, interpretation
    risk_indicators: dict  # Keys: margin_ratio, short_interest, concentration_risk
    liquidity: dict  # Keys: daily_turnover, liquidity_risk
    risks: list[str]  # Chip-related risks
    signals: list[str]  # Bullish/bearish chip signals
    confidence: float = 0.5  # 0-1 confidence level
    is_mock: bool = False  # Whether data is mocked


class NewsAnalysis(BaseModel):
    """News & sentiment analysis output from agent."""
    summary: str  # Traditional Chinese narrative
    recent_headlines: list[dict]  # List of {title, source, date, sentiment, impact, relevance}
    sentiment_aggregate: dict  # Keys: bullish_count, neutral_count, bearish_count, overall_score, trend
    key_catalysts: list[dict]  # Upcoming events {event, date, potential_impact, direction}
    macro_impact: dict  # Keys: relevant_factors, impact_on_stock
    risks: list[str]  # News-driven risks
    opportunities: list[str]  # News-driven opportunities
    confidence: float = 0.5  # 0-1 confidence level
    is_mock: bool = False  # Whether data is mocked


class ComprehensiveAnalysis(BaseModel):
    """Synthesis of all 4 pillars with final recommendation."""
    summary: str  # Traditional Chinese narrative
    overall_direction: str  # bullish | bearish | neutral
    confirmation_pillars: dict  # Keys: 基本面, 技術面, 籌碼面, 消息面 with their directions
    confirmation_score: float  # 0-1, how many pillars agree on direction
    conflicts: list[str]  # Conflict descriptions between pillars
    composite_confidence: float  # 0-1 averaged confidence across pillars
    target_price: float  # Recommended target price
    stop_loss: float  # Recommended stop loss level
    timeframe: str  # 短期|中期|長期 recommendation horizon
    conviction_level: str  # 低|中|高 conviction strength
    recommendation: str  # Investment action narrative
    key_risks: list[str]  # Aggregated risks from all pillars
    catalyst_timeline: list[str]  # Aggregated catalysts
    conflict_resolution: str  # How to interpret conflicts
    is_mock: bool = False  # Whether synthesis was mocked


# ── Elite Equity Research Framework ──────────────────────────────────────────

class ScenarioPrice(BaseModel):
    """Price target scenario for equity research."""
    target_price: float  # Target price for this scenario
    rationale: str  # 1-2 sentence justification (Traditional Chinese)
    key_risk: str  # Primary risk to this scenario
    upside_pct: Optional[float] = None  # Percentage upside from current price
    timeframe: str = ""  # Time horizon (e.g., "3-6 months", "1-2 years")


class SentimentScore(BaseModel):
    """Numeric sentiment analysis with engagement metrics."""
    score: int
    stage: str
    avg_likes_per_post: Optional[int] = None
    avg_comments_per_post: Optional[int] = None
    source: str = "mock"


class AnalystEntry(BaseModel):
    """Individual analyst firm's rating and target."""
    firm: str
    rating: str
    target_price: Optional[float] = None


class AnalystConsensus(BaseModel):
    """Aggregate analyst consensus with individual firm data."""
    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    target_low: Optional[float] = None
    target_median: Optional[float] = None
    target_high: Optional[float] = None
    entries: list[AnalystEntry] = Field(default_factory=list)


class CatalystRow(BaseModel):
    """Individual catalyst event with impact assessment."""
    time_horizon: str
    event: str
    data_point: str
    impact: str


class RiskRow(BaseModel):
    """Individual risk with probability and mitigation."""
    risk: str
    probability_pct: int
    mitigation: str


class CategoryRating(BaseModel):
    """Per-dimension investment rating."""
    category: str
    label_zh: str
    stars: int


class SourceCitation(BaseModel):
    """Data source with optional hyperlink."""
    title: str
    url: Optional[str] = None
    source: str


class EquityResearch(BaseModel):
    """Elite equity research report synthesizing all pillars."""
    # [1] Market Narrative
    social_sentiment: str  # Summary of retail/forum sentiment (Traditional Chinese)
    sentiment_stage: str  # euphoric | fearful | skeptical | early-stage
    catalysts: list[str]  # Specific events with dates and numbers
    institutional_view: str  # Analyst consensus + institutional positioning
    narrative_conclusion: str  # "Stock moving because X, market underestimates Y"
    sentiment_data: Optional[SentimentScore] = None
    analyst_consensus_data: Optional[AnalystConsensus] = None
    catalyst_table: Optional[list[CatalystRow]] = None
    risk_table: Optional[list[RiskRow]] = None
    category_ratings: Optional[list[CategoryRating]] = None
    source_citations: Optional[list[SourceCitation]] = None
    # [2] Fundamental Snapshot
    valuation_verdict: str  # overvalued | fairly valued | undervalued
    valuation_assumptions: str  # Assumptions + math justification
    financial_risks: list[str]  # Top 3 financial risks
    # [3] Technical Snapshot
    technical_verdict: str  # momentum strengthening | weakening | consolidating
    institutional_positioning: str  # accumulating | distributing | neutral
    setup_suitability: str  # swing trader | long-term | both | neither
    # [4] Scenario Framework
    scenario_bear: ScenarioPrice  # Bear case: -15% to -25%
    scenario_base: ScenarioPrice  # Base case: +10% to +15%
    scenario_bull: ScenarioPrice  # Bull case: +25% to +50%
    scenario_stretched: ScenarioPrice  # Stretched case: +50%+ (unlikely)
    # [5] Actionable Framework
    entry_zone: str  # Recommended entry price range (e.g., "145-155 TWD")
    add_zone: str  # Add more position at this zone
    profit_taking: str  # Take profits at these levels
    thesis_break: str  # Exit if this condition occurs
    key_catalyst: str  # Most important upcoming catalyst
    hidden_risk: str  # Less obvious risk that could derail thesis
    # Meta
    investment_rating: str = "Hold"  # Strong Buy | Buy | Hold | Sell | Strong Sell
    summary: str  # Executive summary (Traditional Chinese, 3-4 sentences)
    confidence: float = 0.5  # 0-1 confidence in the research
    is_mock: bool = False  # Whether research was AI-generated or mocked
