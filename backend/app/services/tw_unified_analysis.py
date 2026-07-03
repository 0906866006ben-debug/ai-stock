"""Unified single-call TW analysis.

Replaces the 6-8 sequential per-pillar model calls (fundamental / technical /
chip / news / synthesis / equity-research agents) with ONE structured model
call that returns every narrative at once.

Why: the multi-agent pipeline took minutes per symbol (each call carries its
own heavy output schema and retries) and burned tokens re-sending overlapping
context. Here all real data is gathered first (same services the individual
agents used), formatted into one prompt, and the model fills a compact
narrative-only schema. The rich structured fields on each pillar
(metrics/momentum dicts, key levels, sentiment aggregates) are computed
deterministically from the raw data by reusing the agents' mock builders, so
the UI keeps its data-rich sections without asking the model to re-emit them.

Fallback contract is unchanged: any failure degrades to the deterministic
mock builders — never crash, never fabricate.
"""
import asyncio
import os

from pydantic import BaseModel
from pydantic_ai import Agent

from backend.app.agents.retry import run_with_backoff
from backend.app.agents.fundamental_agent import (
    _format_metrics_for_prompt,
    _mock_fundamental_analysis,
)
from backend.app.agents.technical_agent import (
    _format_indicators_for_prompt,
    _mock_technical_analysis,
)
from backend.app.agents.chip_agent import _format_chip_for_prompt, _mock_chip_analysis
from backend.app.agents.news_agent import _format_news_for_prompt, _mock_news_analysis
from backend.app.models.schemas import ComprehensiveAnalysis, FundamentalMetrics
from backend.app.services.gemini_diagnostics import resolve_ai_model_id
from backend.app.services.finmind_market import get_tw_market_data
from backend.app.services.finmind_company import get_tw_company_info
from backend.app.services.fintech_fundamentals import get_tw_fundamentals
from backend.app.services.tw_chip_analysis import get_tw_chip_analysis
from backend.app.services.tw_news_sentiment import get_tw_news, calculate_sentiment_aggregate
from backend.app.services.tw_technical_extended import compute_extended_indicators

_NUMERIC_METRIC_KEYS = [
    "eps_latest", "eps_yoy", "pe_ratio", "pb_ratio", "roe", "roa",
    "gross_margin", "operating_margin", "net_margin", "dividend_yield",
    "payout_ratio", "debt_ratio", "current_ratio", "quick_ratio",
    "revenue_yoy", "revenue_mom",
]

_SYSTEM_PROMPT = (
    "你是一位專業的台灣股票分析師，需一次完成四大面向（基本面、技術面、籌碼面、消息面）"
    "的判讀與綜合結論。以繁體中文撰寫。"
    "每個面向給出：2-3句摘要、方向（偏多/偏空/中性）、信心（0-1）、風險與正面因素各2-3點。"
    "綜合結論需整合四面向、指出面向間的衝突與解讀。"
    "分析內容必須基於提供的數據，不得捏造數字。若數據不完整，請說明限制。"
    "本分析僅供參考，不構成投資建議。"
)


class _PillarOut(BaseModel):
    summary: str
    direction: str  # 偏多 | 偏空 | 中性
    confidence: float
    risks: list[str]
    positives: list[str]


class UnifiedAnalysisOutput(BaseModel):
    fundamental: _PillarOut
    technical: _PillarOut
    chip: _PillarOut
    news: _PillarOut
    # synthesis
    overall_direction: str  # bullish | bearish | neutral
    confirmation_score: float  # 0-1 how many pillars agree
    composite_confidence: float  # 0-1
    target_price: float
    stop_loss: float
    timeframe: str  # 短期 | 中期 | 長期
    conviction_level: str  # 低 | 中 | 高
    synthesis_summary: str
    recommendation: str
    key_risks: list[str]
    catalyst_timeline: list[str]
    conflicts: list[str]
    conflict_resolution: str


def _unified_model_id() -> str:
    """Model for the unified pillars call.

    Defaults to TW_AI_MODEL, but can be pointed at a faster model via
    TW_AI_MODEL_UNIFIED: the four pillar narratives are describe-the-data
    tasks where a fast model (Haiku) cuts wall time ~2-3x, while the main
    summary card stays on the stronger TW_AI_MODEL.
    """
    override = os.getenv("TW_AI_MODEL_UNIFIED")
    if override and override.strip():
        return override.strip()
    return resolve_ai_model_id()


def _provider_key_available() -> bool:
    from backend.app.services.gemini_diagnostics import _provider_key_present
    return _provider_key_present(_unified_model_id())


def _build_metrics(metrics_dict: dict) -> FundamentalMetrics:
    cleaned = dict(metrics_dict)
    for key in _NUMERIC_METRIC_KEYS:
        if cleaned.get(key) == "N/A":
            cleaned[key] = None
    return FundamentalMetrics(**cleaned)


async def run_unified_analysis(symbol: str) -> dict:
    """One-call replacement for run_comprehensive_analysis.

    Returns the same state keys main.py reads: fundamental_analysis,
    technical_analysis, chip_analysis, news_analysis, comprehensive_analysis,
    equity_research (always None here).
    """
    # ── Gather all real data in parallel (same sources as the old agents) ──
    market_task = asyncio.create_task(get_tw_market_data(symbol))
    company_task = asyncio.create_task(get_tw_company_info(symbol))
    fund_task = asyncio.create_task(get_tw_fundamentals(symbol))
    chip_task = asyncio.create_task(get_tw_chip_analysis(symbol))
    news_task = asyncio.create_task(get_tw_news(symbol))

    (market, market_mock), (company, _), (metrics_dict, fund_mock), (chip_dict, chip_mock), (news_list, news_mock) = (
        await asyncio.gather(market_task, company_task, fund_task, chip_task, news_task)
    )

    company_name = company.get("company_name", symbol)
    current_price = float(market.get("current_price", 0.0) or 0.0)
    candles = market.get("chart_data") or []
    indicators = compute_extended_indicators(candles) if candles else {}
    sentiment = calculate_sentiment_aggregate(news_list)
    metrics = _build_metrics(metrics_dict)

    def _mock_state(comprehensive=None) -> dict:
        return {
            "fundamental_analysis": _mock_fundamental_analysis(symbol, company_name, metrics, fund_mock),
            "technical_analysis": (
                _mock_technical_analysis(symbol, company_name, candles, indicators) if candles else None
            ),
            "chip_analysis": _mock_chip_analysis(symbol, company_name, chip_dict, chip_mock),
            "news_analysis": _mock_news_analysis(symbol, company_name, news_list, sentiment, news_mock),
            "comprehensive_analysis": comprehensive,
            "equity_research": None,
        }

    if not _provider_key_available():
        return _mock_state()

    # ── One prompt containing every pillar's data ──
    prompt = f"""請一次完成以下台灣股票的四大面向分析與綜合結論：

股票代碼：{symbol}
公司名稱：{company_name}
當前股價：{current_price:.2f} 元
當日漲跌幅：{float(market.get('price_change_percent', 0.0) or 0.0):+.2f}%

=== 基本面數據 ===
{_format_metrics_for_prompt(metrics, current_price)}

=== 技術面指標 ===
{_format_indicators_for_prompt(candles, indicators) if candles else '無K線資料。'}

=== 籌碼面數據 ===
{_format_chip_for_prompt(chip_dict)}

=== 消息面 ===
{_format_news_for_prompt(news_list)}
情緒聚合：看好{sentiment['bullish_count']}篇 / 中立{sentiment['neutral_count']}篇 / 看壞{sentiment['bearish_count']}篇，評分{sentiment['overall_score']:.2f}，趨勢{sentiment['trend']}
"""

    try:
        agent = Agent(
            _unified_model_id(),
            output_type=UnifiedAnalysisOutput,
            system_prompt=_SYSTEM_PROMPT,
        )
        result = await run_with_backoff(agent, prompt)
        out: UnifiedAnalysisOutput = result.output
    except Exception as e:  # noqa: BLE001 - degrade to deterministic mocks
        print(f"Unified analysis error for {symbol}: {e}; using mock fallback")
        return _mock_state()

    # ── Map narratives onto the deterministic (data-backed) pillar skeletons ──
    fundamental = _mock_fundamental_analysis(symbol, company_name, metrics, fund_mock)
    fundamental.summary = out.fundamental.summary
    fundamental.risks = out.fundamental.risks
    fundamental.catalysts = out.fundamental.positives
    fundamental.confidence = out.fundamental.confidence
    fundamental.is_mock = fund_mock

    technical = None
    if candles:
        technical = _mock_technical_analysis(symbol, company_name, candles, indicators)
        technical.summary = out.technical.summary
        technical.risks = out.technical.risks
        technical.opportunities = out.technical.positives
        technical.confidence = out.technical.confidence
        technical.is_mock = market_mock

    chip = _mock_chip_analysis(symbol, company_name, chip_dict, chip_mock)
    chip.summary = out.chip.summary
    chip.risks = out.chip.risks
    chip.signals = out.chip.positives
    chip.confidence = out.chip.confidence
    chip.is_mock = chip_mock

    news = _mock_news_analysis(symbol, company_name, news_list, sentiment, news_mock)
    news.summary = out.news.summary
    news.risks = out.news.risks
    news.opportunities = out.news.positives
    news.confidence = out.news.confidence
    news.is_mock = news_mock

    comprehensive = ComprehensiveAnalysis(
        summary=out.synthesis_summary,
        overall_direction=out.overall_direction,
        confirmation_pillars={
            "基本面": out.fundamental.direction,
            "技術面": out.technical.direction,
            "籌碼面": out.chip.direction,
            "消息面": out.news.direction,
        },
        confirmation_score=out.confirmation_score,
        conflicts=out.conflicts,
        composite_confidence=out.composite_confidence,
        target_price=out.target_price,
        stop_loss=out.stop_loss,
        timeframe=out.timeframe,
        conviction_level=out.conviction_level,
        recommendation=out.recommendation,
        key_risks=out.key_risks,
        catalyst_timeline=out.catalyst_timeline,
        conflict_resolution=out.conflict_resolution,
        is_mock=False,
    )

    return {
        "fundamental_analysis": fundamental,
        "technical_analysis": technical,
        "chip_analysis": chip,
        "news_analysis": news,
        "comprehensive_analysis": comprehensive,
        "equity_research": None,
    }
