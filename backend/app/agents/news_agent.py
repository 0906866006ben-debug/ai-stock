"""
News & Sentiment Analysis Agent

Analyzes Taiwan stock news using PydanticAI.
Generates Traditional Chinese narrative explaining:
- Recent headlines and sentiment
- Overall market sentiment trend
- Key catalysts and timeframes
- Macro economic impacts
"""
import os
from pydantic_ai import Agent
from backend.app.agents.retry import run_with_backoff
from backend.app.services.gemini_diagnostics import resolve_ai_model_id
from backend.app.models.schemas import NewsAnalysis
from backend.app.services.tw_news_sentiment import get_tw_news, calculate_sentiment_aggregate

_SYSTEM_PROMPT = (
    "你是一位專業的台灣股票新聞分析師。"
    "根據提供的新聞標題和情緒分析，以繁體中文撰寫結構化的消息面分析。"
    "必須分析："
    "1. 最近的新聞標題及其情緒（看好/看壞/中立）"
    "2. 整體市場情緒趨勢（改善/穩定/惡化）"
    "3. 主要催化劑及時間表"
    "4. 宏觀經濟因素對該股票的影響"
    "5. 新聞相關風險與機會"
    "分析內容必須基於提供的新聞，不得捏造。"
    "本分析僅供參考，不構成投資建議。"
)


async def analyze_news(symbol: str, company_name: str) -> NewsAnalysis:
    """
    Perform news and sentiment analysis on a Taiwan stock.

    Args:
        symbol: Stock symbol (e.g., "2330")
        company_name: Company name (e.g., "台積電")

    Returns:
        NewsAnalysis with structured output + narrative
    """
    # Fetch news
    news_list, is_mock = await get_tw_news(symbol)

    # Calculate sentiment aggregate
    sentiment = calculate_sentiment_aggregate(news_list)

    # Build prompt
    news_text = _format_news_for_prompt(news_list)
    user_prompt = f"""
請分析以下台灣股票的消息面：

股票代碼：{symbol}
公司名稱：{company_name}

=== 最新新聞 ===
{news_text}

情緒聚合：
看好新聞：{sentiment['bullish_count']}篇
中立新聞：{sentiment['neutral_count']}篇
看壞新聞：{sentiment['bearish_count']}篇
整體情緒評分：{sentiment['overall_score']:.2f}（0-1）
情緒趨勢：{sentiment['trend']}

請提供：
1. 新聞總結和整體市場情緒評估
2. 短期vs長期的影響區分
3. 主要催化劑和預計時間
4. 宏觀經濟背景和對該股票的影響
5. 新聞相關的風險清單
6. 新聞相關的機會清單
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return _mock_news_analysis(symbol, company_name, news_list, sentiment, is_mock)

        agent = Agent(
            resolve_ai_model_id(),
            output_type=NewsAnalysis,
            system_prompt=_SYSTEM_PROMPT,
        )
        result = await run_with_backoff(agent, user_prompt)
        analysis = result.output
        analysis.sentiment_aggregate = _normalize_sentiment_aggregate(
            analysis.sentiment_aggregate,
            sentiment,
        )
        analysis.is_mock = is_mock
        return analysis

    except Exception:
        return _mock_news_analysis(symbol, company_name, news_list, sentiment, is_mock)


def _normalize_sentiment_aggregate(raw: dict, fallback: dict) -> dict:
    """Normalize LLM-shaped sentiment keys back to the internal schema."""
    normalized = dict(fallback)
    if isinstance(raw, dict):
        normalized.update(raw)

    if "overall_score" not in normalized:
        for alias in ("score", "sentiment_score", "aggregate_score"):
            if alias in normalized:
                normalized["overall_score"] = normalized[alias]
                break

    alias_pairs = {
        "bullish_count": ("positive", "positive_count", "bullish"),
        "neutral_count": ("neutral", "neutral_count"),
        "bearish_count": ("negative", "negative_count", "bearish"),
    }
    for canonical, aliases in alias_pairs.items():
        if canonical in normalized:
            continue
        for alias in aliases:
            if alias in normalized:
                normalized[canonical] = normalized[alias]
                break

    try:
        score = float(normalized.get("overall_score", fallback.get("overall_score", 0.5)))
    except (TypeError, ValueError):
        score = float(fallback.get("overall_score", 0.5))
    normalized["overall_score"] = max(0.0, min(1.0, score))

    if normalized.get("trend") not in {"improving", "stable", "deteriorating"}:
        if normalized["overall_score"] > 0.65:
            normalized["trend"] = "improving"
        elif normalized["overall_score"] < 0.35:
            normalized["trend"] = "deteriorating"
        else:
            normalized["trend"] = "stable"

    for key in ("bullish_count", "neutral_count", "bearish_count"):
        try:
            normalized[key] = int(normalized.get(key, fallback.get(key, 0)))
        except (TypeError, ValueError):
            normalized[key] = int(fallback.get(key, 0))

    return normalized


def _format_news_for_prompt(news_list: list[dict]) -> str:
    """Format news list into readable text."""
    if not news_list:
        return "目前沒有可靠新聞資料"

    lines = []
    for i, item in enumerate(news_list[:10], 1):  # Show top 10
        title = item.get("title", "")
        source = item.get("source", "")
        date = item.get("date", "")
        sentiment = item.get("sentiment", "neutral")
        sentiment_zh = {"positive": "看好", "negative": "看壞", "neutral": "中立"}.get(sentiment, "中立")

        lines.append(f"{i}. [{sentiment_zh}] {title} ({source}, {date})")

    return "\n".join(lines)


def _mock_news_analysis(
    symbol: str, company_name: str, news_list: list[dict], sentiment: dict, is_mock: bool
) -> NewsAnalysis:
    """Generate mock news analysis."""

    # Identify catalysts
    catalysts = []
    for news in news_list[:3]:
        if news.get("sentiment") == "positive":
            catalysts.append({
                "event": news.get("title", ""),
                "date": news.get("date", ""),
                "potential_impact": "medium" if news.get("relevance", 0) > 0.7 else "low",
                "direction": "bullish",
            })

    # Macro factors
    macro_factors = ["宏觀景氣", "匯率波動", "利率變化"]
    if any("芯片" in n.get("title", "") for n in news_list):
        macro_factors.append("芯片產業周期")
    if any("美國" in n.get("title", "") for n in news_list):
        macro_factors.append("美中貿易關係")

    return NewsAnalysis(
        summary=f"消息面評估：{company_name}相關新聞呈{sentiment['trend']}趨勢。整體情緒評分{sentiment['overall_score']:.2f}。",
        recent_headlines=news_list[:5],
        sentiment_aggregate=sentiment,
        key_catalysts=catalysts if catalysts else [{
            "event": "後續業績公佈",
            "date": "TBD",
            "potential_impact": "medium",
            "direction": "neutral",
        }],
        macro_impact={
            "relevant_factors": macro_factors,
            "impact_on_stock": "正面" if sentiment["overall_score"] > 0.6 else ("負面" if sentiment["overall_score"] < 0.4 else "中性"),
        },
        risks=[
            f"情緒指數{'低' if sentiment['overall_score'] < 0.4 else '正常'}",
            "國際貿易政策不確定性",
            "產業景氣週期波動",
        ],
        opportunities=[
            "正面新聞催化" if sentiment["bullish_count"] > 0 else "等待好消息",
            "基本面改善機會" if sentiment["trend"] == "improving" else "價格調整",
        ],
        confidence=0.6,
        is_mock=is_mock,
    )
