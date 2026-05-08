"""
Tests for technical analysis agent and extended indicators.
"""
import pytest
from backend.app.services.tw_technical_extended import (
    kd_indicator, bollinger_bands, atr, support_resistance,
    trend_direction, breakout_detection, compute_extended_indicators
)
from backend.app.agents.technical_agent import analyze_technical
from backend.app.models.schemas import TechnicalAnalysis


# Sample candle data for testing
def _generate_sample_candles(days: int = 100, trend: str = "up") -> list[dict]:
    """Generate realistic OHLCV candles."""
    candles = []
    base_price = 2300.0

    for i in range(days):
        if trend == "up":
            daily_change = (i % 20) * 0.3 / 100  # Gradual uptrend
        elif trend == "down":
            daily_change = -(i % 20) * 0.3 / 100  # Downtrend
        else:
            daily_change = (i % 20 - 10) * 0.1 / 100  # Sideways

        open_price = base_price
        close_price = base_price * (1 + daily_change)
        high_price = max(open_price, close_price) * 1.01
        low_price = min(open_price, close_price) * 0.99

        candles.append({
            "time": f"2025-01-{(i % 28) + 1:02d}",
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": 5000000 + i * 10000,
        })
        base_price = close_price

    return candles


def test_kd_indicator_basic():
    """Test KD indicator computation."""
    candles = _generate_sample_candles(50)
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]

    result = kd_indicator(highs, lows, closes, period=9)

    assert "%K" in result
    assert "%D" in result
    assert len(result["%K"]) == 50
    assert len(result["%D"]) == 50
    # First values should be None (warmup)
    assert result["%K"][0] is None


def test_bollinger_bands_basic():
    """Test Bollinger Bands computation."""
    candles = _generate_sample_candles(50)
    closes = [float(c["close"]) for c in candles]

    result = bollinger_bands(closes, period=20)

    assert "upper" in result
    assert "middle" in result
    assert "lower" in result
    assert len(result["upper"]) == 50
    # Upper band should be greater than middle
    for i in range(20, 50):
        if result["upper"][i] is not None and result["middle"][i] is not None:
            assert result["upper"][i] > result["middle"][i]


def test_atr_computation():
    """Test ATR (Average True Range) computation."""
    candles = _generate_sample_candles(50)
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]

    result = atr(highs, lows, closes, period=14)

    assert len(result) == 50
    # ATR should be None before period
    assert result[10] is None
    # ATR should be computed after period
    assert result[14] is not None
    # ATR should be positive
    assert result[14] > 0


def test_support_resistance():
    """Test support/resistance level detection."""
    candles = _generate_sample_candles(50)
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    result = support_resistance(highs, lows)

    assert "support" in result
    assert "resistance" in result
    assert isinstance(result["support"], list)
    assert isinstance(result["resistance"], list)


def test_trend_direction():
    """Test trend direction detection."""
    # Uptrend
    up_candles = _generate_sample_candles(50, trend="up")
    up_highs = [float(c["high"]) for c in up_candles]
    up_lows = [float(c["low"]) for c in up_candles]
    assert trend_direction(up_highs, up_lows) == "uptrend"

    # Downtrend
    down_candles = _generate_sample_candles(50, trend="down")
    down_highs = [float(c["high"]) for c in down_candles]
    down_lows = [float(c["low"]) for c in down_candles]
    assert trend_direction(down_highs, down_lows) == "downtrend"

    # Sideways
    side_candles = _generate_sample_candles(50, trend="sideways")
    side_highs = [float(c["high"]) for c in side_candles]
    side_lows = [float(c["low"]) for c in side_candles]
    trend = trend_direction(side_highs, side_lows)
    assert trend in ["uptrend", "downtrend", "sideways"]


def test_breakout_detection():
    """Test breakout detection."""
    closes = [2300.0, 2305.0, 2310.0, 2315.0, 2320.0]  # Upward
    resistance = 2310.0

    # Test breakout above resistance
    result = breakout_detection(closes, resistance, 2290.0)
    assert "breakout_direction" in result
    # Last close is above resistance
    assert result["above_resistance"] is True


def test_compute_extended_indicators():
    """Test comprehensive extended indicators computation."""
    candles = _generate_sample_candles(100)

    result = compute_extended_indicators(candles)

    # Check all keys present
    assert "ma120" in result
    assert "ma240" in result
    assert "kd" in result
    assert "bollinger_bands" in result
    assert "atr" in result
    assert "support" in result
    assert "resistance" in result
    assert "trend" in result
    assert "breakout" in result

    # Check structure
    assert len(result["ma120"]) == 100
    assert "%K" in result["kd"]
    assert "%D" in result["kd"]
    assert "upper" in result["bollinger_bands"]
    assert "middle" in result["bollinger_bands"]
    assert "lower" in result["bollinger_bands"]


@pytest.mark.asyncio
async def test_technical_analysis_mock():
    """Test technical analysis with mock (no API key)."""
    candles = _generate_sample_candles(100)

    result = await analyze_technical("2330", "台積電", candles)

    assert isinstance(result, TechnicalAnalysis)
    assert result.summary is not None
    assert result.trend in ["uptrend", "downtrend", "sideways"]
    assert isinstance(result.momentum, dict)
    assert "rsi" in result.momentum
    assert isinstance(result.volatility, dict)
    assert isinstance(result.key_levels, dict)
    assert isinstance(result.risks, list)
    assert isinstance(result.opportunities, list)
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_technical_analysis_empty_candles():
    """Test technical analysis with empty candles."""
    result = await analyze_technical("2330", "台積電", [])

    assert isinstance(result, TechnicalAnalysis)
    assert result.is_mock is True


@pytest.mark.asyncio
async def test_technical_analysis_etf():
    """Test technical analysis for ETF."""
    candles = _generate_sample_candles(100)

    result = await analyze_technical("0050", "元大台灣50", candles)

    assert isinstance(result, TechnicalAnalysis)
    assert result.trend is not None


def test_technical_analysis_schema():
    """Test TechnicalAnalysis schema validation."""
    analysis = TechnicalAnalysis(
        summary="技術面分析總結",
        trend="uptrend",
        momentum={"rsi": 65, "rsi_signal": "正常", "macd_signal": "正向"},
        volatility={"atr": 15.5, "bb_position": "upper", "volatility_level": "normal"},
        key_levels={"support": [2280], "resistance": [2320], "breakout_potential": "none"},
        risks=["超買風險"],
        opportunities=["支撐反彈"],
        confidence=0.75,
        is_mock=False,
    )

    assert analysis.summary == "技術面分析總結"
    assert analysis.trend == "uptrend"
    assert analysis.confidence == 0.75
    assert len(analysis.risks) == 1
