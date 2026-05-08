from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from ..services.market_data import get_market_data
from ..services.news_data import get_news_data
from ..services.financial_data import get_financial_data
from ..services.fmp_fundamentals import get_fmp_fundamentals
from ..services.ai_analysis import get_ai_analysis

MOCK_SENTINEL = "N/A (demo)"


class AnalysisState(TypedDict):
    symbol: str
    market_data: Optional[dict]
    news_data: Optional[list]
    financial_data: Optional[dict]
    fmp_data: Optional[dict]
    ai_result: Optional[dict]
    is_mock: bool


async def fetch_market(state: AnalysisState) -> dict:
    data = await get_market_data(state["symbol"])
    is_mock = data.get("company_name") == "Demo Company Inc."
    return {"market_data": data, "is_mock": is_mock}


async def fetch_news(state: AnalysisState) -> dict:
    data = await get_news_data(state["symbol"])
    return {"news_data": data}


async def fetch_financials(state: AnalysisState) -> dict:
    data = await get_financial_data(state["symbol"])
    is_mock = list(data.values())[0].endswith("(demo)") if data else True
    return {"financial_data": data, "is_mock": state.get("is_mock", False) and is_mock}


async def fetch_fmp(state: AnalysisState) -> dict:
    data = await get_fmp_fundamentals(state["symbol"])
    return {"fmp_data": data}


async def ai_analysis(state: AnalysisState) -> dict:
    context = {
        "market_data": state.get("market_data"),
        "news_data": state.get("news_data"),
        "financial_data": state.get("financial_data"),
        "fmp_data": state.get("fmp_data"),
    }
    result = await get_ai_analysis(state["symbol"], context)
    return {"ai_result": result}


_graph = StateGraph(AnalysisState)
_graph.add_node("fetch_market", fetch_market)
_graph.add_node("fetch_news", fetch_news)
_graph.add_node("fetch_financials", fetch_financials)
_graph.add_node("fetch_fmp", fetch_fmp)
_graph.add_node("ai_analysis", ai_analysis)

_graph.set_entry_point("fetch_market")
_graph.add_edge("fetch_market", "fetch_news")
_graph.add_edge("fetch_news", "fetch_financials")
_graph.add_edge("fetch_financials", "fetch_fmp")
_graph.add_edge("fetch_fmp", "ai_analysis")
_graph.add_edge("ai_analysis", END)

_compiled = _graph.compile()


async def run_analysis(symbol: str) -> AnalysisState:
    initial: AnalysisState = {
        "symbol": symbol,
        "market_data": None,
        "news_data": None,
        "financial_data": None,
        "fmp_data": None,
        "ai_result": None,
        "is_mock": False,
    }
    return await _compiled.ainvoke(initial)
