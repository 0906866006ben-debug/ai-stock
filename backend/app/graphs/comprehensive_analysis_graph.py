"""
Comprehensive Analysis Graph

LangGraph orchestration for 4-pillar Taiwan stock analysis:
1. Fundamental Analysis
2. Technical Analysis
3. Chip/Institutional Analysis
4. News/Sentiment Analysis
5. Synthesis & Recommendation
6. Elite Equity Research

All 4 pillars run in parallel, then synthesis combines them, then equity research synthesizes final report.
"""
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
import asyncio

from ..services.finmind_market import get_tw_market_data
from ..services.finmind_company import get_tw_company_info
from ..services.tw_market_research import fetch_market_research
from ..agents.fundamental_agent import analyze_fundamental
from ..agents.technical_agent import analyze_technical
from ..agents.chip_agent import analyze_chip
from ..agents.news_agent import analyze_news
from ..agents.synthesis_agent import synthesize_analysis
from ..agents.equity_research_agent import analyze_equity_research


class ComprehensiveAnalysisState(TypedDict):
    symbol: str
    company_name: str
    market_type: str
    current_price: float
    price_change_percent: float
    volume: int
    chart_data: Optional[list]
    data_is_mock: bool
    fundamental_analysis: Optional[object]
    technical_analysis: Optional[object]
    chip_analysis: Optional[object]
    news_analysis: Optional[object]
    comprehensive_analysis: Optional[object]
    equity_research: Optional[object]


async def fetch_market(state: ComprehensiveAnalysisState) -> dict:
    """Fetch Taiwan market data (price, volume, change %)."""
    data, is_mock = await get_tw_market_data(state["symbol"])
    return {
        "current_price": data.get("current_price", 0.0),
        "price_change_percent": data.get("price_change_percent", 0.0),
        "volume": data.get("volume", 0),
        "chart_data": data.get("chart_data", []),
        "data_is_mock": is_mock,
    }


async def fetch_company(state: ComprehensiveAnalysisState) -> dict:
    """Fetch company info (name, market type)."""
    data, _is_mock = await get_tw_company_info(state["symbol"])
    return {
        "company_name": data.get("company_name", state["symbol"]),
        "market_type": data.get("market_type", "UNKNOWN"),
    }




async def run_fundamental(state: ComprehensiveAnalysisState) -> dict:
    """Run fundamental analysis agent."""
    try:
        analysis = await analyze_fundamental(
            symbol=state["symbol"],
            company_name=state.get("company_name", state["symbol"]),
            current_price=state.get("current_price", 0.0),
        )
        return {"fundamental_analysis": analysis}
    except Exception as e:
        print(f"Fundamental analysis error: {e}")
        return {"fundamental_analysis": None}


async def run_technical(state: ComprehensiveAnalysisState) -> dict:
    """Run technical analysis agent."""
    try:
        chart_data = state.get("chart_data", [])
        if not chart_data:
            return {"technical_analysis": None}

        analysis = await analyze_technical(
            symbol=state["symbol"],
            company_name=state.get("company_name", state["symbol"]),
            candles=chart_data,
        )
        return {"technical_analysis": analysis}
    except Exception as e:
        print(f"Technical analysis error: {e}")
        return {"technical_analysis": None}


async def run_chip(state: ComprehensiveAnalysisState) -> dict:
    """Run chip/institutional analysis agent."""
    try:
        analysis = await analyze_chip(
            symbol=state["symbol"],
            company_name=state.get("company_name", state["symbol"]),
        )
        return {"chip_analysis": analysis}
    except Exception as e:
        print(f"Chip analysis error: {e}")
        return {"chip_analysis": None}


async def run_news(state: ComprehensiveAnalysisState) -> dict:
    """Run news/sentiment analysis agent."""
    try:
        analysis = await analyze_news(
            symbol=state["symbol"],
            company_name=state.get("company_name", state["symbol"]),
        )
        return {"news_analysis": analysis}
    except Exception as e:
        print(f"News analysis error: {e}")
        return {"news_analysis": None}


async def run_synthesis(state: ComprehensiveAnalysisState) -> dict:
    """Run synthesis agent combining all 4 pillars."""
    try:
        fundamental = state.get("fundamental_analysis")
        technical = state.get("technical_analysis")
        chip = state.get("chip_analysis")
        news = state.get("news_analysis")

        if not all([fundamental, technical, chip, news]):
            return {"comprehensive_analysis": None}

        analysis = await synthesize_analysis(
            symbol=state["symbol"],
            company_name=state.get("company_name", state["symbol"]),
            current_price=state.get("current_price", 0.0),
            fundamental=fundamental,
            technical=technical,
            chip=chip,
            news=news,
        )
        return {"comprehensive_analysis": analysis}
    except Exception as e:
        print(f"Synthesis error: {e}")
        return {"comprehensive_analysis": None}


async def run_equity_research(state: ComprehensiveAnalysisState) -> dict:
    """Run elite equity research agent synthesizing all pillars into research report."""
    # Off by default: this node runs a Gemini grounded-search + a very heavy
    # output schema, which dominates latency (minutes) and often retries to a
    # mock. The main summary + 4 pillars + synthesis already give a complete
    # analysis. Set TW_EQUITY_RESEARCH=true to re-enable.
    import os as _os
    if _os.getenv("TW_EQUITY_RESEARCH", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return {"equity_research": None}
    try:
        fundamental = state.get("fundamental_analysis")
        technical = state.get("technical_analysis")
        chip = state.get("chip_analysis")
        news = state.get("news_analysis")
        comprehensive = state.get("comprehensive_analysis")

        if not all([fundamental, technical, chip, news, comprehensive]):
            return {"equity_research": None}

        # Fetch market research data (Gemini grounded search + fallbacks)
        research_data = await fetch_market_research(
            symbol=state["symbol"],
            company_name=state.get("company_name", state["symbol"]),
        )

        # Run equity research agent
        analysis = await analyze_equity_research(
            symbol=state["symbol"],
            company_name=state.get("company_name", state["symbol"]),
            current_price=state.get("current_price", 0.0),
            fundamental=fundamental,
            technical=technical,
            chip=chip,
            news=news,
            comprehensive=comprehensive,
            research_data=research_data,
        )
        return {"equity_research": analysis}
    except Exception as e:
        print(f"Equity research error: {e}")
        return {"equity_research": None}


_graph = StateGraph(ComprehensiveAnalysisState)

# Add nodes
_graph.add_node("fetch_market", fetch_market)
_graph.add_node("fetch_company", fetch_company)
_graph.add_node("run_fundamental", run_fundamental)
_graph.add_node("run_technical", run_technical)
_graph.add_node("run_chip", run_chip)
_graph.add_node("run_news", run_news)
_graph.add_node("run_synthesis", run_synthesis)
_graph.add_node("run_equity_research", run_equity_research)

# Set entry point
_graph.set_entry_point("fetch_market")

# Add edges: fetch market and company in parallel
_graph.add_edge("fetch_market", "fetch_company")

# After company info, run all 4 analysis agents in parallel
_graph.add_edge("fetch_company", "run_fundamental")
_graph.add_edge("fetch_company", "run_technical")
_graph.add_edge("fetch_company", "run_chip")
_graph.add_edge("fetch_company", "run_news")

# After all 4 agents, run synthesis
_graph.add_edge("run_fundamental", "run_synthesis")
_graph.add_edge("run_technical", "run_synthesis")
_graph.add_edge("run_chip", "run_synthesis")
_graph.add_edge("run_news", "run_synthesis")

# After synthesis, run equity research
_graph.add_edge("run_synthesis", "run_equity_research")

# End after equity research
_graph.add_edge("run_equity_research", END)

_compiled = _graph.compile()


async def run_comprehensive_analysis(symbol: str) -> ComprehensiveAnalysisState:
    """
    Run comprehensive 4-pillar analysis for Taiwan stock.

    Args:
        symbol: Taiwan stock symbol (e.g., "2330")

    Returns:
        ComprehensiveAnalysisState with all analysis results
    """
    initial: ComprehensiveAnalysisState = {
        "symbol": symbol,
        "company_name": "",
        "market_type": "",
        "current_price": 0.0,
        "price_change_percent": 0.0,
        "volume": 0,
        "chart_data": None,
        "data_is_mock": False,
        "fundamental_analysis": None,
        "technical_analysis": None,
        "chip_analysis": None,
        "news_analysis": None,
        "comprehensive_analysis": None,
        "equity_research": None,
    }
    return await _compiled.ainvoke(initial)
