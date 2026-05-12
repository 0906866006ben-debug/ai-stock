from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from ..services.finmind_market import get_tw_market_data
from ..services.finmind_company import get_tw_company_info
from ..services.tw_ai_analysis import get_tw_ai_analysis
from ..services.tw_technical_analysis import compute_all_indicators


class TaiwanAnalysisState(TypedDict):
    symbol: str
    market_data: Optional[dict]
    company_data: Optional[dict]
    indicators_data: Optional[dict]
    ai_result: Optional[dict]
    data_is_mock: bool
    analysis_is_mock: bool


async def fetch_market(state: TaiwanAnalysisState) -> dict:
    data, is_mock = await get_tw_market_data(state["symbol"])
    return {"market_data": data, "data_is_mock": is_mock}


async def fetch_company(state: TaiwanAnalysisState) -> dict:
    data, _is_mock = await get_tw_company_info(state["symbol"])
    return {"company_data": data}


async def compute_indicators(state: TaiwanAnalysisState) -> dict:
    """Compute technical indicators from market data."""
    market = state.get("market_data") or {}
    chart_data = market.get("chart_data", [])

    if not chart_data:
        return {"indicators_data": None}

    indicators = compute_all_indicators(chart_data)
    return {"indicators_data": indicators}


async def run_ai(state: TaiwanAnalysisState) -> dict:
    market = state.get("market_data") or {}
    company = state.get("company_data") or {}
    ai_result, source = await get_tw_ai_analysis(
        symbol=state["symbol"],
        company_name=company.get("company_name", state["symbol"]),
        market_type=company.get("market_type", "UNKNOWN"),
        current_price=market.get("current_price", 0.0),
        price_change_percent=market.get("price_change_percent", 0.0),
        chart_data=market.get("chart_data", []),
        news=[],
    )
    return {"ai_result": ai_result, "analysis_is_mock": source == "mock"}


_graph = StateGraph(TaiwanAnalysisState)
_graph.add_node("fetch_market", fetch_market)
_graph.add_node("fetch_company", fetch_company)
_graph.add_node("compute_indicators", compute_indicators)
_graph.add_node("run_ai", run_ai)

_graph.set_entry_point("fetch_market")
_graph.add_edge("fetch_market", "fetch_company")
_graph.add_edge("fetch_company", "compute_indicators")
_graph.add_edge("compute_indicators", "run_ai")
_graph.add_edge("run_ai", END)

_compiled = _graph.compile()


async def run_tw_analysis(symbol: str) -> TaiwanAnalysisState:
    initial: TaiwanAnalysisState = {
        "symbol": symbol,
        "market_data": None,
        "company_data": None,
        "indicators_data": None,
        "ai_result": None,
        "data_is_mock": False,
        "analysis_is_mock": False,
    }
    return await _compiled.ainvoke(initial)
