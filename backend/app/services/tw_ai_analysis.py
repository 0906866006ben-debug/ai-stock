import os

from ..models.schemas import TaiwanStockAIAnalysis

MOCK_AI_RESULT: dict = {
    "summary": "目前無法取得 AI 分析，以下為模擬資料。",
    "trend": "中立",
    "confidence": 0.5,
    "risks": ["資料不完整", "市場波動風險"],
    "catalysts": ["待補充"],
    "recommendation": "建議等待更多資訊後再做決策。",
}

_SYSTEM_PROMPT = (
    "你是一位專業的台灣股票市場分析師助理。"
    "請根據提供的市場數據，以繁體中文撰寫結構化的股票分析報告。"
    "僅使用提供的數據進行分析，不得憑空捏造財務數據。"
    "若數據不完整，請明確說明。"
    "本分析僅供參考，不構成投資建議。"
    "趨勢判斷必須為以下其中之一：看漲、看跌、中立。"
)


def _compute_indicators(chart_data: list[dict]) -> dict:
    closes = [r["close"] for r in chart_data]
    volumes = [r["volume"] for r in chart_data]
    n = len(closes)

    ma5 = sum(closes[-5:]) / min(5, n) if n > 0 else None
    ma20 = sum(closes[-20:]) / min(20, n) if n >= 20 else None

    price_5d_change = (
        (closes[-1] - closes[-6]) / closes[-6] * 100 if n >= 6 else None
    )
    price_20d_change = (
        (closes[-1] - closes[-21]) / closes[-21] * 100 if n >= 21 else None
    )

    avg_vol_20 = sum(volumes[-20:]) / min(20, n) if n > 0 else None
    latest_vol = volumes[-1] if n > 0 else None

    above_ma5 = (closes[-1] > ma5) if (ma5 is not None and n > 0) else None
    above_ma20 = (closes[-1] > ma20) if (ma20 is not None and n > 0) else None

    return {
        "ma5": ma5,
        "ma20": ma20,
        "price_5d_change": price_5d_change,
        "price_20d_change": price_20d_change,
        "avg_vol_20": avg_vol_20,
        "latest_vol": latest_vol,
        "above_ma5": above_ma5,
        "above_ma20": above_ma20,
        "ohlcv_summary": chart_data[-5:] if n >= 5 else chart_data,
    }


def _build_prompt(
    symbol: str, company_name: str, market_type: str,
    current_price: float, price_change_percent: float,
    chart_data: list[dict], news: list[dict],
) -> str:
    ind = _compute_indicators(chart_data)

    news_text = (
        "\n".join(
            f"- {item.get('title', '')} ({item.get('source', '')})"
            for item in news[:5]
        )
        if news
        else "目前沒有可靠新聞資料。"
    )

    def _fmt(val, fmt=".2f", suffix="") -> str:
        return f"{val:{fmt}}{suffix}" if val is not None else "N/A"

    ma5_str = _fmt(ind["ma5"])
    ma20_str = _fmt(ind["ma20"])
    p5_str = _fmt(ind["price_5d_change"], suffix="%")
    p20_str = _fmt(ind["price_20d_change"], suffix="%")

    def _above(flag) -> str:
        if flag is None:
            return "N/A"
        return "高於" if flag else "低於"

    vol_str = "N/A"
    if ind["latest_vol"] and ind["avg_vol_20"]:
        ratio = ind["latest_vol"] / ind["avg_vol_20"]
        vol_str = f"{ind['latest_vol']:,}（20日均量 {ind['avg_vol_20']:.0f} 的 {ratio:.1f} 倍）"

    ohlcv_lines = "\n".join(
        f"  {r['time']}: 開{r['open']} 高{r['high']} 低{r['low']} 收{r['close']} 量{r['volume']:,}"
        for r in ind["ohlcv_summary"]
    )

    return f"""請分析以下台灣股票數據：

=== 基本資料 ===
股票代碼：{symbol}
公司名稱：{company_name}
市場：{market_type}

=== 最新行情 ===
最新收盤價：{current_price:.2f} TWD
當日漲跌幅：{price_change_percent:+.2f}%
成交量：{vol_str}

=== 技術指標 ===
MA5：{ma5_str}（目前股價{_above(ind['above_ma5'])} MA5）
MA20：{ma20_str}（目前股價{_above(ind['above_ma20'])} MA20）
5日漲跌：{p5_str}
20日漲跌：{p20_str}

=== 近5日 OHLCV ===
{ohlcv_lines}

=== 近期新聞 ===
{news_text}

請提供：趨勢（看漲/看跌/中立）、信心指數（0.0-1.0）、摘要分析、風險因素列表、催化劑列表、投資建議。"""


async def get_tw_ai_analysis(
    symbol: str, company_name: str, market_type: str,
    current_price: float, price_change_percent: float,
    chart_data: list[dict], news: list[dict],
) -> tuple[dict, str]:
    """Return (result_dict, analysis_source) where analysis_source is 'ai' or 'mock'."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return MOCK_AI_RESULT, "mock"

    try:
        from pydantic_ai import Agent

        agent = Agent(
            "anthropic:claude-sonnet-4-6",
            output_type=TaiwanStockAIAnalysis,
            system_prompt=_SYSTEM_PROMPT,
        )
        prompt = _build_prompt(
            symbol, company_name, market_type,
            current_price, price_change_percent, chart_data, news,
        )
        result = await agent.run(prompt)
        analysis: TaiwanStockAIAnalysis = result.output
        return {
            "summary": analysis.summary,
            "trend": analysis.trend,
            "confidence": analysis.confidence,
            "risks": analysis.risks,
            "catalysts": analysis.catalysts,
            "recommendation": analysis.recommendation,
        }, "ai"

    except Exception:
        return MOCK_AI_RESULT, "mock"
