"""
Chip/Institutional Analysis Agent

Analyzes Taiwan stock institutional flows using PydanticAI.
Generates Traditional Chinese narrative explaining:
- Foreign investor, 投信, dealer flows
- Accumulation vs distribution trends
- Margin and short interest levels
- Shareholder concentration
- Liquidity and chip positioning
"""
import os
from pydantic_ai import Agent
from backend.app.agents.retry import run_with_backoff
from backend.app.services.gemini_diagnostics import resolve_ai_model_id
from backend.app.models.schemas import ChipAnalysis
from backend.app.services.tw_chip_analysis import get_tw_chip_analysis

_SYSTEM_PROMPT = (
    "你是一位專業的台灣股票籌碼分析師。"
    "根據提供的機構持股數據，以繁體中文撰寫結構化的籌碼面分析。"
    "必須分析："
    "1. 外資、投信、自營商的買賣方向（5日、10日、20日）"
    "2. 機構籌碼整體方向（持續買進、緩慢賣出、觀望）"
    "3. 融資融券風險（高風險預警、正常、低風險）"
    "4. 大股東持股集中度和異常變動"
    "5. 市場流動性評估"
    "6. 籌碼面風險與信號"
    "分析內容必須基於提供的數據，不得捏造。"
    "本分析僅供參考，不構成投資建議。"
)


async def analyze_chip(symbol: str, company_name: str) -> ChipAnalysis:
    """
    Perform chip/institutional analysis on a Taiwan stock.

    Args:
        symbol: Stock symbol (e.g., "2330")
        company_name: Company name (e.g., "台積電")

    Returns:
        ChipAnalysis with structured output + narrative
    """
    # Fetch chip data
    chip_dict, is_mock = await get_tw_chip_analysis(symbol)

    # Build prompt with chip data
    chip_text = _format_chip_for_prompt(chip_dict)
    user_prompt = f"""
請分析以下台灣股票的籌碼面：

股票代碼：{symbol}
公司名稱：{company_name}

=== 籌碼數據 ===
{chip_text}

請提供：
1. 外資、投信、自營商的整體方向評估
2. 機構籌碼整體位置（買進、觀望、賣出）
3. 融資融券和短線風險評級
4. 主要風險清單
5. 籌碼訊號清單（正向/負向）
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return _mock_chip_analysis(symbol, company_name, chip_dict, is_mock)

        agent = Agent(
            resolve_ai_model_id(),
            output_type=ChipAnalysis,
            system_prompt=_SYSTEM_PROMPT,
        )
        result = await run_with_backoff(agent, user_prompt)
        analysis = result.output
        analysis.is_mock = is_mock
        analysis.institutional_sentiment = _normalize_institutional_sentiment(
            analysis.institutional_sentiment,
            chip_dict,
        )
        return analysis

    except Exception:
        return _mock_chip_analysis(symbol, company_name, chip_dict, is_mock)


def _normalize_institutional_sentiment(sentiment: dict, chip_dict: dict) -> dict:
    """Keep the public schema stable even when an LLM omits a sub-key."""
    normalized = dict(sentiment or {})
    normalized.setdefault(
        "foreign",
        {
            "5d_net": chip_dict.get("foreign_5d_net", 0),
            "trend": chip_dict.get("foreign_accumulation_trend", "neutral"),
            "signal": "moderate",
        },
    )
    normalized.setdefault(
        "domestic_fund",
        {
            "5d_net": chip_dict.get("trust_5d_net", 0),
            "trend": chip_dict.get("trust_accumulation_trend", "neutral"),
        },
    )
    normalized.setdefault(
        "dealer",
        {
            "5d_net": chip_dict.get("dealer_5d_net", 0),
            "activity": "normal",
        },
    )
    return normalized


def _format_chip_for_prompt(chip_dict: dict) -> str:
    """Format chip data into readable text for AI prompt."""
    lines = []

    lines.append("【外資】")
    lines.append(f"  5日淨買：{chip_dict.get('foreign_5d_net', 0):,}")
    lines.append(f"  10日淨買：{chip_dict.get('foreign_10d_net', 0):,}")
    lines.append(f"  20日淨買：{chip_dict.get('foreign_20d_net', 0):,}")
    lines.append(f"  趨勢：{chip_dict.get('foreign_accumulation_trend', 'neutral')}")
    fhr = chip_dict.get("foreign_holding_ratio")
    if fhr is not None:
        chg = chip_dict.get("foreign_holding_ratio_change")
        chg_txt = f"（{chg:+.2f}%）" if isinstance(chg, (int, float)) else ""
        lines.append(f"  外資持股比例：{fhr:.2f}%{chg_txt}")

    lines.append("")

    lines.append("【投信】")
    lines.append(f"  5日淨買：{chip_dict.get('trust_5d_net', 0):,}")
    lines.append(f"  10日淨買：{chip_dict.get('trust_10d_net', 0):,}")
    lines.append(f"  趨勢：{chip_dict.get('trust_accumulation_trend', 'neutral')}")

    lines.append("")

    lines.append("【自營商】")
    lines.append(f"  5日淨買：{chip_dict.get('dealer_5d_net', 0):,}")
    lines.append(f"  10日淨買：{chip_dict.get('dealer_10d_net', 0):,}")
    lines.append(f"  趨勢：{chip_dict.get('dealer_trend', 'neutral')}")

    lines.append("")

    lines.append("【融資融券】")
    margin_balance = chip_dict.get('margin_balance', 0)
    margin_change = chip_dict.get('margin_balance_change', 0)
    lines.append(f"  融資餘額：{margin_balance:,} 千元")
    lines.append(f"  變化：{margin_change:+,} 千元")
    margin_risk = "高風險" if margin_balance > 1000 else ("低風險" if margin_balance < 300 else "正常")
    lines.append(f"  風險評級：{margin_risk}")

    lines.append("")

    lines.append("【融券】")
    short_interest = chip_dict.get('short_interest', 0)
    short_change = chip_dict.get('short_interest_change', 0)
    lines.append(f"  融券餘額：{short_interest:,} 千元")
    lines.append(f"  變化：{short_change:+,} 千元")

    lines.append("")

    lines.append("【股東結構】")
    lines.append(f"  持股集中度：{chip_dict.get('shareholder_concentration', 'moderate')}")
    lines.append(f"  主要股東數：{chip_dict.get('major_shareholders_count', 5)} 家")

    return "\n".join(lines)


def _mock_chip_analysis(symbol: str, company_name: str, chip_dict: dict, is_mock: bool) -> ChipAnalysis:
    """Generate mock chip analysis when API unavailable."""

    foreign_trend = chip_dict.get("foreign_accumulation_trend", "neutral")
    trust_trend = chip_dict.get("trust_accumulation_trend", "neutral")
    dealer_trend = chip_dict.get("dealer_trend", "neutral")

    overall_trend = "accumulation" if foreign_trend == "accumulating" else ("distribution" if foreign_trend == "distributing" else "neutral")

    foreign_5d = chip_dict.get("foreign_5d_net", 0)
    trust_5d = chip_dict.get("trust_5d_net", 0)
    margin_balance = chip_dict.get("margin_balance", 0)

    return ChipAnalysis(
        summary=f"籌碼面評估：外資{foreign_trend}，投信{trust_trend}，自營{dealer_trend}。融資餘額處於{'高位' if margin_balance > 1000 else '正常' if margin_balance > 300 else '低位'}。",
        institutional_sentiment={
            "foreign": {
                "5d_net": foreign_5d,
                "trend": foreign_trend,
                "signal": "strong" if abs(foreign_5d) > 2000000 else "moderate" if abs(foreign_5d) > 500000 else "weak",
            },
            "domestic_fund": {
                "5d_net": trust_5d,
                "trend": trust_trend,
            },
            "dealer": {
                "5d_net": chip_dict.get("dealer_5d_net", 0),
                "activity": "active" if abs(chip_dict.get("dealer_5d_net", 0)) > 500000 else "normal",
            },
        },
        chip_position={
            "overall_trend": overall_trend,
            "abnormal_movement": abs(foreign_5d) > 3000000 or abs(trust_5d) > 2000000,
            "interpretation": f"機構籌碼呈{overall_trend}態勢"
        },
        risk_indicators={
            "margin_ratio": "warning" if margin_balance > 1000 else ("normal" if margin_balance > 300 else "low"),
            "short_interest": "elevated" if chip_dict.get("short_interest", 0) > 100 else "normal",
            "concentration_risk": chip_dict.get("shareholder_concentration", "moderate"),
        },
        liquidity={
            "daily_turnover": "normal",
            "liquidity_risk": "low" if foreign_trend != "distributing" else "medium",
        },
        risks=[
            f"融資餘額{('過高' if margin_balance > 1000 else '正常')}",
            f"外資{'持續買進' if foreign_trend == 'accumulating' else '持續賣出' if foreign_trend == 'distributing' else '觀望'}",
            f"股東集中度{chip_dict.get('shareholder_concentration', 'moderate')}",
        ],
        signals=[
            "機構買進" if foreign_trend == "accumulating" or trust_trend == "accumulating" else "機構賣出",
            "融資警示" if margin_balance > 1000 else "融資正常",
            "短線風險" if chip_dict.get("short_interest", 0) > 100 else "短線平靜",
        ],
        confidence=0.6,
        is_mock=is_mock,
    )
