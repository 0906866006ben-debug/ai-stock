"""
Technical Analysis Agent

Analyzes Taiwan stock technical indicators using PydanticAI.
Generates Traditional Chinese narrative explaining:
- Trend direction and strength
- Momentum signals (RSI, MACD, KD)
- Volatility and Bollinger Bands
- Support/resistance levels
- Breakout potential
- Key technical risks and opportunities
"""
import os
from pydantic_ai import Agent
from backend.app.models.schemas import TechnicalAnalysis
from backend.app.services.tw_technical_extended import compute_extended_indicators
from backend.app.services.tw_indicators import rsi, macd

_SYSTEM_PROMPT = (
    "你是一位專業的台灣股票技術分析師。"
    "根據提供的技術指標，以繁體中文撰寫結構化的技術面分析。"
    "必須分析："
    "1. 趨勢方向（上升、下降、盤整）及強度"
    "2. 動能指標（RSI、MACD、KD 訊號）"
    "3. 波動性（ATR、布林通道位置）"
    "4. 關鍵技術位置（支撐、壓力、突破潛力）"
    "5. 技術風險與交易機會"
    "分析內容必須基於提供的指標，不得捏造。"
    "若指標不完整，請說明限制。"
    "本分析僅供參考，不構成投資建議。"
)


async def analyze_technical(
    symbol: str, company_name: str, candles: list[dict]
) -> TechnicalAnalysis:
    """
    Perform technical analysis on a Taiwan stock.

    Args:
        symbol: Stock symbol (e.g., "2330")
        company_name: Company name (e.g., "台積電")
        candles: List of OHLCV candles

    Returns:
        TechnicalAnalysis with structured output + narrative
    """
    # Compute extended indicators
    indicators = compute_extended_indicators(candles)

    # Build prompt with indicator data
    indicators_text = _format_indicators_for_prompt(candles, indicators)
    user_prompt = f"""
請分析以下台灣股票的技術面：

股票代碼：{symbol}
公司名稱：{company_name}

=== 技術指標 ===
{indicators_text}

請提供：
1. 趨勢方向（上升/下降/盤整）和強度評估
2. 動能訊號（RSI、MACD、KD 位置和意義）
3. 波動性水準和布林通道位置解讀
4. 關鍵技術位置（支撐/壓力）和突破可能性
5. 技術面風險清單
6. 交易機會清單
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return _mock_technical_analysis(symbol, company_name, candles, indicators)

        agent = Agent(
            "google-gla:gemini-2.5-flash",
            output_type=TechnicalAnalysis,
            system_prompt=_SYSTEM_PROMPT,
        )
        result = await agent.run(user_prompt)
        analysis = result.output
        analysis.is_mock = False
        return analysis

    except Exception:
        return _mock_technical_analysis(symbol, company_name, candles, indicators)


def _format_indicators_for_prompt(candles: list[dict], indicators: dict) -> str:
    """Format indicators dict into readable text for AI prompt."""
    if not candles:
        return "無數據"

    lines = []

    # Latest price
    latest = candles[-1]
    lines.append(f"最新收盤價：{latest['close']:.2f}")
    lines.append(f"日期範圍：{candles[0]['time']} 至 {candles[-1]['time']}")
    lines.append("")

    # Trend
    trend = indicators.get("trend", "sideways")
    lines.append(f"趨勢方向：{_trend_zh(trend)}")

    # Moving averages
    if indicators.get("ma120") and indicators["ma120"][-1] is not None:
        lines.append(f"MA120：{indicators['ma120'][-1]:.2f}")
    if indicators.get("ma240") and indicators["ma240"][-1] is not None:
        lines.append(f"MA240：{indicators['ma240'][-1]:.2f}")

    lines.append("")

    # RSI
    if candles:
        closes = [float(c["close"]) for c in candles]
        rsi_vals = rsi(closes, 14)
        if rsi_vals[-1] is not None:
            rsi_val = rsi_vals[-1]
            lines.append(f"RSI(14)：{rsi_val:.2f}")
            if rsi_val > 70:
                lines.append("  訊號：超買")
            elif rsi_val < 30:
                lines.append("  訊號：超賣")

    # MACD
    if candles:
        closes = [float(c["close"]) for c in candles]
        macd_result = macd(closes)
        if macd_result["macd"][-1] is not None:
            macd_val = macd_result["macd"][-1]
            signal_val = macd_result["signal"][-1]
            lines.append(f"MACD：{macd_val:.4f}")
            lines.append(f"信號線：{signal_val:.4f}")
            if macd_val > signal_val:
                lines.append("  訊號：正向")
            else:
                lines.append("  訊號：負向")

    # KD
    kd = indicators.get("kd", {})
    if kd.get("%K") and kd["%K"][-1] is not None:
        lines.append(f"KD K值：{kd['%K'][-1]:.2f}")
        if kd.get("%D") and kd["%D"][-1] is not None:
            lines.append(f"KD D值：{kd['%D'][-1]:.2f}")

    lines.append("")

    # Bollinger Bands
    bb = indicators.get("bollinger_bands", {})
    if bb.get("upper") and bb["upper"][-1] is not None:
        lines.append(f"布林通道上軌：{bb['upper'][-1]:.2f}")
        lines.append(f"布林通道中軌：{bb['middle'][-1]:.2f}")
        lines.append(f"布林通道下軌：{bb['lower'][-1]:.2f}")

    # ATR
    if indicators.get("atr") and indicators["atr"][-1] is not None:
        lines.append(f"ATR(14)：{indicators['atr'][-1]:.2f}")

    lines.append("")

    # Support and Resistance
    support = indicators.get("support", [])
    resistance = indicators.get("resistance", [])
    if support:
        lines.append(f"支撐位：{', '.join(f'{x:.2f}' for x in support)}")
    if resistance:
        lines.append(f"壓力位：{', '.join(f'{x:.2f}' for x in resistance)}")

    # Breakout
    breakout = indicators.get("breakout", {})
    if breakout.get("breakout_direction") != "none":
        lines.append(f"突破方向：{_breakout_zh(breakout.get('breakout_direction'))}")

    return "\n".join(lines)


def _trend_zh(trend: str) -> str:
    """Convert trend to Chinese."""
    mapping = {"uptrend": "上升趨勢", "downtrend": "下降趨勢", "sideways": "盤整"}
    return mapping.get(trend, "不確定")


def _breakout_zh(direction: str) -> str:
    """Convert breakout direction to Chinese."""
    mapping = {"upside": "向上突破", "downside": "向下跌破", "none": "無"}
    return mapping.get(direction, "無")


def _mock_technical_analysis(
    symbol: str, company_name: str, candles: list[dict], indicators: dict
) -> TechnicalAnalysis:
    """Generate mock technical analysis when API unavailable."""

    trend = indicators.get("trend", "sideways")
    trend_zh = _trend_zh(trend)

    # Determine momentum signals
    if candles:
        closes = [float(c["close"]) for c in candles]
        rsi_vals = rsi(closes, 14)
        rsi_val = rsi_vals[-1] if rsi_vals[-1] is not None else 50.0
        macd_result = macd(closes)
        macd_val = macd_result["macd"][-1] if macd_result["macd"][-1] is not None else 0.0

        rsi_signal = "超買" if rsi_val > 70 else ("超賣" if rsi_val < 30 else "正常")
        macd_signal = "正向" if macd_val > 0 else "負向"
    else:
        rsi_signal = "正常"
        macd_signal = "中立"

    # Support and resistance
    support = indicators.get("support", [])
    resistance = indicators.get("resistance", [])
    support_str = f"{support[0]:.0f}" if support else "N/A"
    resistance_str = f"{resistance[0]:.0f}" if resistance else "N/A"

    return TechnicalAnalysis(
        summary=f"技術面總體評估：{company_name}目前處於{trend_zh}，動能訊號{macd_signal}，RSI 處於{rsi_signal}區間。",
        trend=trend,
        momentum={
            "rsi": rsi_vals[-1] if candles and rsi_vals[-1] is not None else 50.0,
            "rsi_signal": rsi_signal,
            "macd_signal": macd_signal,
            "trend_confirmation": "confirmed" if trend != "sideways" else "weak",
        },
        volatility={
            "atr": indicators.get("atr", [None])[-1] if indicators.get("atr") else 10.0,
            "bb_position": "middle",
            "volatility_level": "normal",
        },
        key_levels={
            "support": [float(x) for x in support],
            "resistance": [float(x) for x in resistance],
            "breakout_potential": indicators.get("breakout", {}).get("breakout_direction", "none"),
        },
        risks=[
            f"RSI {rsi_signal}" if rsi_signal in ["超買", "超賣"] else "無極端訊號",
            f"動能 {macd_signal}" if macd_signal == "負向" else "動能正常",
            ("波動率升高" if indicators.get("atr") and indicators["atr"][-1] and indicators["atr"][-1] > 15 else "波動率正常"),
        ],
        opportunities=[
            "支撐反彈" if trend == "uptrend" else "壓力回檔",
            "KD 訊號" if indicators.get("kd", {}).get("%K") else "待觀察",
            "突破機會" if indicators.get("breakout", {}).get("breakout_direction") != "none" else "無明確突破",
        ],
        confidence=0.6,
        is_mock=True,
    )
