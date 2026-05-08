import os

from ..models.schemas import StockAIAnalysis

MOCK_RESULT = {
    "summary": (
        "Based on available mock data, this stock shows typical market patterns. "
        "Live analysis requires a valid GEMINI_API_KEY."
    ),
    "trend": "neutral",
    "confidence": 0.50,
    "risks": ["Market volatility", "Sector headwinds", "Macroeconomic uncertainty"],
    "catalysts": ["Potential earnings growth", "Market expansion opportunities"],
    "recommendation": "Hold — insufficient live data for a definitive recommendation (demo mode).",
}


def _build_fmp_section(fmp: dict) -> str:
    metrics = fmp.get("financial_metrics", {})
    analyst = fmp.get("analyst", {})
    next_earnings = fmp.get("next_earnings_date")
    last_earnings = fmp.get("last_earnings", {})
    esg = fmp.get("esg", {})

    lines = []

    if metrics:
        lines.append("=== Fundamental Metrics (FMP) ===")
        for k, v in metrics.items():
            lines.append(f"- {k.replace('_', ' ').title()}: {v}")

    if analyst.get("consensus"):
        lines.append("\n=== Analyst Price Targets ===")
        lines.append(f"- Consensus Target: {analyst['consensus']}")
        if analyst.get("high"):
            lines.append(f"- High Target: {analyst['high']}")
        if analyst.get("low"):
            lines.append(f"- Low Target: {analyst['low']}")

    if next_earnings:
        lines.append(f"\nNext Earnings Date: {next_earnings}")

    if last_earnings.get("eps_actual") is not None:
        lines.append(
            f"Last EPS: Actual {last_earnings['eps_actual']:.2f} vs "
            f"Estimated {last_earnings.get('eps_estimated', 'N/A')}"
        )

    if esg.get("total") is not None:
        lines.append(f"\nESG Score: {esg['total']:.1f} "
                     f"(E:{esg.get('environmental', 'N/A'):.1f} "
                     f"S:{esg.get('social', 'N/A'):.1f} "
                     f"G:{esg.get('governance', 'N/A'):.1f})")

    return "\n".join(lines) if lines else "No FMP fundamental data available."


async def get_ai_analysis(symbol: str, context: dict) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return MOCK_RESULT

    try:
        from pydantic_ai import Agent

        agent = Agent("google-gla:gemini-2.5-flash", output_type=StockAIAnalysis)

        market = context.get("market_data") or {}
        news = context.get("news_data") or []
        financials = context.get("financial_data") or {}
        fmp = context.get("fmp_data") or {}

        news_summary = "\n".join(
            f"- {item.get('title', '')} ({item.get('source', '')})"
            for item in news[:5]
        )

        fmp_section = _build_fmp_section(fmp)

        basic_financials = "\n".join(f"- {k}: {v}" for k, v in financials.items()) or "No basic financial data."

        prompt = f"""You are a financial analyst assistant. Analyse the following stock data for {symbol}.
Use ONLY the data provided — never invent financial facts.
State explicitly if any data field is missing or unavailable.
This analysis is support only, not financial advice.

=== Market Data ===
Company: {market.get('company_name', 'N/A')}
Current Price: {market.get('current_price', 'N/A')}
Price Change: {market.get('price_change_percent', 'N/A')}%

=== Recent News ===
{news_summary or 'No recent news available.'}

=== Basic Financial Data ===
{basic_financials}

{fmp_section}

Provide a structured analysis with: summary, trend (bullish/bearish/neutral),
confidence (0.0-1.0), risks (list), catalysts (list), recommendation.
Where analyst price targets are available, reference them in your recommendation."""

        result = await agent.run(prompt)
        analysis: StockAIAnalysis = result.output

        return {
            "summary": analysis.summary,
            "trend": analysis.trend,
            "confidence": analysis.confidence,
            "risks": analysis.risks,
            "catalysts": analysis.catalysts,
            "recommendation": analysis.recommendation,
        }
    except Exception:
        return MOCK_RESULT
