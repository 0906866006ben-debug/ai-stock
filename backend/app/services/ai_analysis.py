import os

from ..models.schemas import StockAIAnalysis

MOCK_RESULT = {
    "summary": (
        "Based on available mock data, this stock shows typical market patterns. "
        "Live analysis requires a valid ANTHROPIC_API_KEY."
    ),
    "trend": "neutral",
    "confidence": 0.50,
    "risks": ["Market volatility", "Sector headwinds", "Macroeconomic uncertainty"],
    "catalysts": ["Potential earnings growth", "Market expansion opportunities"],
    "recommendation": "Hold — insufficient live data for a definitive recommendation (demo mode).",
}


async def get_ai_analysis(symbol: str, context: dict) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return MOCK_RESULT

    try:
        from pydantic_ai import Agent

        agent = Agent("anthropic:claude-sonnet-4-6", output_type=StockAIAnalysis)

        market = context.get("market_data") or {}
        news = context.get("news_data") or []
        financials = context.get("financial_data") or {}

        news_summary = "\n".join(
            f"- {item.get('title', '')} ({item.get('source', '')})"
            for item in news[:5]
        )

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

=== Financial Summary ===
{financials or 'No financial data available.'}

Provide a structured analysis with: summary, trend (bullish/bearish/neutral),
confidence (0.0-1.0), risks (list), catalysts (list), recommendation."""

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
