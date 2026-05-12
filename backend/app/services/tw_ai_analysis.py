import os

from ..models.schemas import TaiwanStockAIAnalysis
from .tw_technical_analysis import compute_all_indicators
from .gemini_diagnostics import (
    get_gemini_model_chain,
    is_gemini_enabled,
    log_gemini_diagnostics,
)

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
    """Compute technical indicators using pandas/numpy."""
    ind = compute_all_indicators(chart_data)
    closes = [r["close"] for r in chart_data]
    n = len(closes)
    current_price = closes[-1] if closes else 0

    ma5 = ind["ma"]["ma5"]
    ma20 = ind["ma"]["ma20"]

    return {
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ind["ma"]["ma60"],
        "rsi": ind["rsi"],
        "macd": ind["macd"],
        "price_5d_change": ind["price_changes"]["change_5d"],
        "price_20d_change": ind["price_changes"]["change_20d"],
        "price_60d_change": ind["price_changes"]["change_60d"],
        "avg_vol_20": ind["volume"]["avg_vol_20"],
        "latest_vol": ind["volume"]["latest_vol"],
        "vol_ratio": ind["volume"]["vol_ratio"],
        "above_ma5": (current_price > ma5) if ma5 is not None else None,
        "above_ma20": (current_price > ma20) if ma20 is not None else None,
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
    ma60_str = _fmt(ind["ma60"])
    rsi_str = _fmt(ind["rsi"], fmt=".2f")

    # MACD formatting
    macd_str = "N/A"
    if ind["macd"]:
        macd_str = f"線{ind['macd']['macd']:.4f} 信號{ind['macd']['signal']:.4f} 柱狀{ind['macd']['histogram']:.4f}"

    p5_str = _fmt(ind["price_5d_change"], suffix="%")
    p20_str = _fmt(ind["price_20d_change"], suffix="%")
    p60_str = _fmt(ind["price_60d_change"], suffix="%")

    def _above(flag) -> str:
        if flag is None:
            return "N/A"
        return "高於" if flag else "低於"

    vol_str = "N/A"
    if ind["latest_vol"] and ind["avg_vol_20"]:
        vol_str = f"{ind['latest_vol']:,}（20日均量 {ind['avg_vol_20']:,} 的 {ind.get('vol_ratio', 0):.1f} 倍）"

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
移動平均線：
  MA5：{ma5_str}（目前股價{_above(ind['above_ma5'])} MA5）
  MA20：{ma20_str}（目前股價{_above(ind['above_ma20'])} MA20）
  MA60：{ma60_str}
相對強度指數（RSI）：{rsi_str}
MACD（12,26,9）：{macd_str}
價格漲跌：
  5日：{p5_str}
  20日：{p20_str}
  60日：{p60_str}

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
    api_key = os.getenv("GEMINI_API_KEY")
    model_chain = get_gemini_model_chain()
    if not is_gemini_enabled():
        print("Gemini disabled by GEMINI_ENABLED=false; using fallback.")
        log_gemini_diagnostics(
            context="tw_quick_analysis",
            model=model_chain[0],
            attempted=False,
            fallback_used=True,
            fallback_models=model_chain[1:],
        )
        return MOCK_AI_RESULT, "mock"

    if not api_key:
        log_gemini_diagnostics(
            context="tw_quick_analysis",
            model=model_chain[0],
            attempted=False,
            fallback_used=True,
            fallback_models=model_chain[1:],
        )
        return MOCK_AI_RESULT, "mock"

    prompt = _build_prompt(
        symbol, company_name, market_type,
        current_price, price_change_percent, chart_data, news,
    )
    last_error = None

    for model_name in model_chain:
        try:
            from pydantic_ai import Agent

            log_gemini_diagnostics(
                context="tw_quick_analysis",
                model=model_name,
                attempted=True,
                fallback_models=model_chain[1:],
            )
            agent = Agent(
                model_name,
                output_type=TaiwanStockAIAnalysis,
                system_prompt=_SYSTEM_PROMPT,
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

        except Exception as e:
            last_error = e
            log_gemini_diagnostics(
                context="tw_quick_analysis",
                model=model_name,
                attempted=True,
                fallback_used=True,
                error=e,
                fallback_models=model_chain[1:],
            )
            print(f"TW quick AI analysis error for {model_name}: {e}; trying fallback if available")

    print(f"All Gemini models failed for TW quick analysis; using fallback. Last error: {last_error}")
    return MOCK_AI_RESULT, "mock"
