from pydantic import BaseModel, field_validator
from typing import Optional, Literal


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
    data_source: str  # "live" or "mock"


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
