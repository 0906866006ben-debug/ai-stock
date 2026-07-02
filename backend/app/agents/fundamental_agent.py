"""
Fundamental Analysis Agent

Analyzes Taiwan stock fundamentals using PydanticAI.
Generates Traditional Chinese narrative explaining:
- Revenue trends and quality
- Profitability and margins
- Valuation levels
- Financial health (debt, liquidity, cash flow)
- Key risks and catalysts
"""
import os
from pydantic_ai import Agent
from backend.app.agents.retry import run_with_backoff
from backend.app.services.gemini_diagnostics import resolve_ai_model_id
from backend.app.models.schemas import FundamentalAnalysis, FundamentalMetrics
from backend.app.services.fintech_fundamentals import get_tw_fundamentals

_SYSTEM_PROMPT = (
    "你是一位專業的台灣股票基本面分析師。"
    "根據提供的財務指標，以繁體中文撰寫結構化的基本面分析。"
    "必須分析："
    "1. 營收成長趨勢（改善、穩定、衰退）"
    "2. 獲利能力（淨利率、毛利率、營業利益率）"
    "3. 估值水準（便宜、合理、昂貴）及依據"
    "4. 財務健全度（債務風險、流動性、現金流品質）"
    "5. 主要風險與機會"
    "分析內容必須基於提供的數據，不得捏造。"
    "若數據不完整，請說明限制。"
    "本分析僅供參考，不構成投資建議。"
)


async def analyze_fundamental(
    symbol: str, company_name: str, current_price: float
) -> FundamentalAnalysis:
    """
    Perform fundamental analysis on a Taiwan stock.

    Args:
        symbol: Stock symbol (e.g., "2330")
        company_name: Company name (e.g., "台積電")
        current_price: Current stock price

    Returns:
        FundamentalAnalysis with structured output + narrative
    """
    # Fetch fundamental data
    metrics_dict, is_mock = await get_tw_fundamentals(symbol)

    # Convert 'N/A' strings to None for numeric fields
    for key in ["eps_latest", "eps_yoy", "pe_ratio", "pb_ratio", "roe", "roa",
                "gross_margin", "operating_margin", "net_margin", "dividend_yield",
                "payout_ratio", "debt_ratio", "current_ratio", "quick_ratio",
                "revenue_yoy", "revenue_mom"]:
        if metrics_dict.get(key) == "N/A":
            metrics_dict[key] = None

    metrics = FundamentalMetrics(**metrics_dict)

    # Build prompt with metrics
    metrics_text = _format_metrics_for_prompt(metrics, current_price)
    user_prompt = f"""
請分析以下台灣股票的基本面：

股票代碼：{symbol}
公司名稱：{company_name}
當前股價：{current_price:.2f} 元

=== 財務指標 ===
{metrics_text}

請提供：
1. 營收趨勢（改善/穩定/衰退）和品質評估
2. 估值水準（便宜/合理/昂貴）和支持依據
3. 財務健全度分析（債務風險、流動性、現金流）
4. 主要風險清單
5. 正向催化劑清單
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return _mock_fundamental_analysis(symbol, company_name, metrics, is_mock)

        agent = Agent(
            resolve_ai_model_id(),
            output_type=FundamentalAnalysis,
            system_prompt=_SYSTEM_PROMPT,
        )
        result = await run_with_backoff(agent, user_prompt)
        analysis = result.output

        # Ensure metrics and is_mock are set
        if not analysis.metrics:
            analysis.metrics = metrics
        analysis.is_mock = is_mock

        return analysis

    except Exception:
        return _mock_fundamental_analysis(symbol, company_name, metrics, is_mock)


def _format_metrics_for_prompt(metrics: FundamentalMetrics, current_price: float) -> str:
    """Format metrics dict into readable text for AI prompt."""
    lines = []

    if metrics.latest_revenue:
        lines.append(f"最新營收：{metrics.latest_revenue}")
    if metrics.revenue_yoy is not None:
        lines.append(f"營收 YoY：{metrics.revenue_yoy:+.2f}%")
    if metrics.revenue_mom is not None:
        lines.append(f"營收 MoM：{metrics.revenue_mom:+.2f}%")

    lines.append("")  # Blank line

    if metrics.eps_latest is not None:
        lines.append(f"每股盈餘（EPS）：{metrics.eps_latest:.2f} 元")
    if metrics.eps_yoy is not None:
        lines.append(f"EPS YoY：{metrics.eps_yoy:+.2f}%")

    lines.append("")

    if metrics.pe_ratio is not None:
        lines.append(f"本益比（PE）：{metrics.pe_ratio:.2f}x")
    if metrics.pb_ratio is not None:
        lines.append(f"股價淨值比（PB）：{metrics.pb_ratio:.2f}x")

    lines.append("")

    if metrics.roe is not None:
        lines.append(f"股東報酬率（ROE）：{metrics.roe:.2f}%")
    if metrics.roa is not None:
        lines.append(f"資產報酬率（ROA）：{metrics.roa:.2f}%")

    lines.append("")

    if metrics.gross_margin is not None:
        lines.append(f"毛利率：{metrics.gross_margin:.2f}%")
    if metrics.operating_margin is not None:
        lines.append(f"營業利益率：{metrics.operating_margin:.2f}%")
    if metrics.net_margin is not None:
        lines.append(f"淨利率：{metrics.net_margin:.2f}%")

    lines.append("")

    if metrics.dividend_yield is not None:
        lines.append(f"股利殖利率：{metrics.dividend_yield:.2f}%")
    if metrics.payout_ratio is not None:
        lines.append(f"配股率：{metrics.payout_ratio:.2f}%")

    lines.append("")

    if metrics.debt_ratio is not None:
        lines.append(f"債務比率：{metrics.debt_ratio:.2f}%")
    if metrics.current_ratio is not None:
        lines.append(f"流動比率：{metrics.current_ratio:.2f}x")
    if metrics.quick_ratio is not None:
        lines.append(f"速動比率：{metrics.quick_ratio:.2f}x")

    lines.append("")

    if metrics.operating_cf:
        lines.append(f"營運現金流：{metrics.operating_cf}")
    if metrics.free_cf:
        lines.append(f"自由現金流：{metrics.free_cf}")
    lines.append(f"現金流趨勢：{metrics.cf_trend}")

    return "\n".join(lines)


def _mock_fundamental_analysis(
    symbol: str, company_name: str, metrics: FundamentalMetrics, is_mock: bool
) -> FundamentalAnalysis:
    """Generate mock fundamental analysis when API unavailable."""

    # Determine trend based on metrics
    revenue_trend = "stable"
    if metrics.revenue_yoy is not None:
        if metrics.revenue_yoy > 10:
            revenue_trend = "improving"
        elif metrics.revenue_yoy < -5:
            revenue_trend = "declining"

    profitability_quality = "medium"
    if metrics.net_margin is not None and metrics.net_margin > 20:
        profitability_quality = "high"
    elif metrics.net_margin is not None and metrics.net_margin < 5:
        profitability_quality = "low"

    valuation_level = "fair"
    if metrics.pe_ratio is not None:
        if metrics.pe_ratio < 12:
            valuation_level = "cheap"
        elif metrics.pe_ratio > 25:
            valuation_level = "expensive"

    debt_risk = "medium"
    if metrics.debt_ratio is not None:
        if metrics.debt_ratio < 30:
            debt_risk = "low"
        elif metrics.debt_ratio > 60:
            debt_risk = "high"

    return FundamentalAnalysis(
        summary=f"基本面總體評估：{company_name}的營收趨勢{revenue_trend}，估值水準{valuation_level}，財務健全度評估為中等。",
        revenue_trend=revenue_trend,
        profitability={
            "trend": revenue_trend,
            "quality": profitability_quality,
            "metrics": {
                "net_margin": metrics.net_margin,
                "gross_margin": metrics.gross_margin,
                "operating_margin": metrics.operating_margin,
            },
        },
        valuation={
            "level": valuation_level,
            "support": f"本益比{metrics.pe_ratio:.1f}x，股價淨值比{metrics.pb_ratio:.1f}x",
            "interpretation": "估值處於合理水準",
        },
        financial_health={
            "debt_risk": debt_risk,
            "liquidity": "adequate" if (metrics.current_ratio or 2.0) > 1.5 else "weak",
            "cash_flow_quality": metrics.cf_trend,
        },
        risks=[
            f"營收波動率：{abs(metrics.revenue_yoy or 0):.1f}%",
            f"債務風險：{debt_risk}",
            "宏觀經濟風險" if symbol in ["2330"] else "行業競爭風險",
        ],
        catalysts=[
            "新產品推出" if symbol == "2330" else "市場需求回升",
            "股利發放",
            "業績改善",
        ],
        metrics=metrics,
        confidence=0.6,
        is_mock=is_mock,
    )
