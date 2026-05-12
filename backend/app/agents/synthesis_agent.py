"""
Synthesis Agent

Combines all 4 pillar analyses into a comprehensive assessment.
Detects conflicts, calculates confirmation scoring, generates final recommendation.
"""
import os
from pydantic_ai import Agent
from backend.app.models.schemas import (
    FundamentalAnalysis,
    TechnicalAnalysis,
    ChipAnalysis,
    NewsAnalysis,
    ComprehensiveAnalysis,
)

_SYSTEM_PROMPT = (
    "你是一位資深的台灣股票綜合分析師。"
    "你的任務是整合基本面、技術面、籌碼面、消息面四個分析柱，生成一份綜合投資建議。"
    "必須："
    "1. 識別各柱之間的衝突信號（例：基本面看好但技術面看壞）"
    "2. 計算確認度評分（有多少柱同意該方向）"
    "3. 評估每柱的可靠性和權重"
    "4. 生成綜合趨勢判斷和投資建議"
    "5. 提供目標價、停損價、時間框架"
    "分析內容必須基於提供的數據，不得捏造。"
    "本分析僅供參考，不構成投資建議。"
)


async def synthesize_analysis(
    symbol: str,
    company_name: str,
    current_price: float,
    fundamental: FundamentalAnalysis,
    technical: TechnicalAnalysis,
    chip: ChipAnalysis,
    news: NewsAnalysis,
) -> ComprehensiveAnalysis:
    """
    Synthesize all 4 pillar analyses into comprehensive assessment.

    Args:
        symbol: Stock symbol
        company_name: Company name
        current_price: Current stock price
        fundamental: Fundamental analysis output
        technical: Technical analysis output
        chip: Chip/institutional analysis output
        news: News/sentiment analysis output

    Returns:
        ComprehensiveAnalysis with synthesis, conflicts, confirmation, recommendation
    """

    # Extract trend directions from each pillar
    fundamental_direction = _extract_direction(fundamental.revenue_trend)
    technical_direction = _extract_technical_direction(technical.trend)
    chip_direction = _extract_chip_direction(chip.institutional_sentiment)
    news_direction = _extract_news_direction(news.sentiment_aggregate)

    # Calculate confirmation scoring
    confirmation = _calculate_confirmation(
        fundamental_direction, technical_direction, chip_direction, news_direction
    )

    # Detect conflicts
    conflicts = _detect_conflicts(
        fundamental_direction, technical_direction, chip_direction, news_direction
    )

    # Aggregate risks and catalysts
    all_risks = (
        fundamental.risks
        + technical.risks
        + chip.risks
        + news.risks
    )
    all_catalysts = (
        fundamental.catalysts
        + technical.opportunities
        + chip.signals
        + news.opportunities
    )

    # Calculate composite confidence
    confidences = [
        fundamental.confidence,
        technical.confidence,
        chip.confidence,
        news.confidence,
    ]
    composite_confidence = sum(confidences) / len(confidences)

    # Build prompt for synthesis
    user_prompt = f"""
請根據以下四個分析柱生成綜合投資建議：

股票代碼：{symbol}
公司名稱：{company_name}
目前股價：{current_price:.2f}元

=== 基本面分析 ===
趨勢：{fundamental.revenue_trend}
信心度：{fundamental.confidence:.2f}
摘要：{fundamental.summary[:200]}

=== 技術面分析 ===
趨勢：{technical.trend}
信心度：{technical.confidence:.2f}
摘要：{technical.summary[:200]}

=== 籌碼面分析 ===
機構情緒：外資{"買進" if chip.institutional_sentiment.get("foreign", {}).get("signal") in ["strong", "accumulating"] else "觀望"}
信心度：{chip.confidence:.2f}
摘要：{chip.summary[:200]}

=== 消息面分析 ===
情緒趨勢：{news.sentiment_aggregate.get("trend", "stable")}
情緒評分：{news.sentiment_aggregate.get("overall_score", 0.5):.2f}
信心度：{news.confidence:.2f}
摘要：{news.summary[:200]}

請提供：
1. 綜合判斷和投資建議
2. 各柱之間的衝突分析（如果有）
3. 確認度評分（0-100%）
4. 目標價（基於技術面阻力和基本面估值）
5. 停損價（基於技術面支撐）
6. 建議持倉時間框架（短期/中期/長期）
7. 投資信心度（低/中/高）
8. 關鍵風險清單
9. 催化劑時間表
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return _mock_comprehensive_analysis(
                symbol,
                company_name,
                current_price,
                fundamental_direction,
                technical_direction,
                chip_direction,
                news_direction,
                confirmation,
                conflicts,
                all_risks,
                all_catalysts,
                composite_confidence,
            )

        agent = Agent(
            "google-gla:gemini-2.5-flash",
            output_type=ComprehensiveAnalysis,
            system_prompt=_SYSTEM_PROMPT,
        )
        result = await agent.run(user_prompt)
        analysis = result.output
        analysis.confirmation_score = confirmation["score"]
        analysis.conflicts = conflicts
        analysis.is_mock = False
        return analysis

    except Exception:
        return _mock_comprehensive_analysis(
            symbol,
            company_name,
            current_price,
            fundamental_direction,
            technical_direction,
            chip_direction,
            news_direction,
            confirmation,
            conflicts,
            all_risks,
            all_catalysts,
            composite_confidence,
        )


def _extract_direction(revenue_trend: str) -> str:
    """Convert revenue trend to direction."""
    if revenue_trend == "improving":
        return "bullish"
    elif revenue_trend == "declining":
        return "bearish"
    else:
        return "neutral"


def _extract_technical_direction(technical_trend: str) -> str:
    """Convert technical trend to direction."""
    if technical_trend == "uptrend":
        return "bullish"
    elif technical_trend == "downtrend":
        return "bearish"
    else:
        return "neutral"


def _extract_chip_direction(institutional_sentiment: dict) -> str:
    """Determine chip direction from institutional sentiment."""
    foreign = institutional_sentiment.get("foreign", {})
    trust = institutional_sentiment.get("domestic_fund", {})

    foreign_trend = foreign.get("trend", "neutral")
    trust_trend = trust.get("trend", "neutral")

    accumulating_count = sum(
        1 for t in [foreign_trend, trust_trend] if t == "accumulating"
    )
    distributing_count = sum(
        1 for t in [foreign_trend, trust_trend] if t == "distributing"
    )

    if accumulating_count > distributing_count:
        return "bullish"
    elif distributing_count > accumulating_count:
        return "bearish"
    else:
        return "neutral"


def _extract_news_direction(sentiment_aggregate: dict) -> str:
    """Determine news direction from sentiment aggregate."""
    trend = sentiment_aggregate.get("trend", "stable")
    overall_score = sentiment_aggregate.get("overall_score", 0.5)

    if trend == "improving" or overall_score > 0.65:
        return "bullish"
    elif trend == "deteriorating" or overall_score < 0.35:
        return "bearish"
    else:
        return "neutral"


def _calculate_confirmation(
    fundamental: str, technical: str, chip: str, news: str
) -> dict:
    """
    Calculate confirmation scoring.

    Returns:
        {
            "bullish_pillars": int,
            "bearish_pillars": int,
            "neutral_pillars": int,
            "score": float (0-1),
            "dominant_direction": str
        }
    """
    directions = [fundamental, technical, chip, news]
    bullish = sum(1 for d in directions if d == "bullish")
    bearish = sum(1 for d in directions if d == "bearish")
    neutral = sum(1 for d in directions if d == "neutral")

    if bullish > bearish:
        dominant = "bullish"
        score = bullish / 4.0
    elif bearish > bullish:
        dominant = "bearish"
        score = bearish / 4.0
    else:
        dominant = "neutral"
        score = neutral / 4.0

    return {
        "bullish_pillars": bullish,
        "bearish_pillars": bearish,
        "neutral_pillars": neutral,
        "score": score,
        "dominant_direction": dominant,
    }


def _detect_conflicts(
    fundamental: str, technical: str, chip: str, news: str
) -> list[str]:
    """
    Detect conflicts between pillars.

    Returns:
        List of conflict descriptions
    """
    conflicts = []
    directions = {
        "基本面": fundamental,
        "技術面": technical,
        "籌碼面": chip,
        "消息面": news,
    }

    bullish_pillars = [p for p, d in directions.items() if d == "bullish"]
    bearish_pillars = [p for p, d in directions.items() if d == "bearish"]

    if bullish_pillars and bearish_pillars:
        conflicts.append(
            f"方向衝突：{', '.join(bullish_pillars)}看好，但{', '.join(bearish_pillars)}看壞"
        )

    return conflicts


def _mock_comprehensive_analysis(
    symbol: str,
    company_name: str,
    current_price: float,
    fundamental_direction: str,
    technical_direction: str,
    chip_direction: str,
    news_direction: str,
    confirmation: dict,
    conflicts: list[str],
    all_risks: list[str],
    all_catalysts: list[str],
    composite_confidence: float,
) -> ComprehensiveAnalysis:
    """Generate mock comprehensive analysis."""

    # Determine overall direction
    dominant = confirmation["dominant_direction"]
    if dominant == "bullish":
        recommendation = "建議布局"
        target_pct = 0.10 + (composite_confidence * 0.15)  # 10-25% upside
    elif dominant == "bearish":
        recommendation = "建議減碼或迴避"
        target_pct = -0.08 - (composite_confidence * 0.12)  # -8-20% downside
    else:
        recommendation = "建議觀望"
        target_pct = 0.0

    target_price = current_price * (1 + target_pct)
    stop_loss = current_price * (1 - 0.08)  # 8% stop loss

    timeframe = (
        "中期（3-6個月）"
        if confirmation["score"] > 0.6
        else (
            "長期（6-12個月）"
            if composite_confidence > 0.5
            else "短期（1-3個月）"
        )
    )

    conviction = (
        "高" if composite_confidence > 0.75 else ("中" if composite_confidence > 0.5 else "低")
    )

    return ComprehensiveAnalysis(
        summary=f"{company_name}綜合評估：{dominant.upper()}趨勢，{conviction}度信心。{recommendation}。",
        overall_direction=dominant,
        confirmation_pillars={
            "基本面": fundamental_direction,
            "技術面": technical_direction,
            "籌碼面": chip_direction,
            "消息面": news_direction,
        },
        confirmation_score=confirmation["score"],
        conflicts=conflicts,
        composite_confidence=composite_confidence,
        target_price=round(target_price, 2),
        stop_loss=round(stop_loss, 2),
        timeframe=timeframe,
        conviction_level=conviction,
        recommendation=recommendation,
        key_risks=all_risks[:5],  # Top 5 risks
        catalyst_timeline=all_catalysts[:5],  # Top 5 catalysts
        conflict_resolution=(
            "多數柱位看好，但少數柱位看壞，建議密切注意相關風險因素。"
            if conflicts
            else "四大柱位共識度高，信號一致。"
        ),
        is_mock=True,
    )
