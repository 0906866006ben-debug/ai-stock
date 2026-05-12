"""Unit tests for technical indicator math."""
import pytest
from backend.app.services.tw_indicators import (
    sma, ema, rsi, macd, build_indicators, parse_indicator_query,
)


# ── SMA ──────────────────────────────────────────────────────────────────────

def test_sma_warmup_returns_none():
    result = sma([1, 2, 3, 4, 5], 3)
    assert result[0] is None
    assert result[1] is None
    assert result[2] == pytest.approx(2.0)  # (1+2+3)/3
    assert result[3] == pytest.approx(3.0)  # (2+3+4)/3
    assert result[4] == pytest.approx(4.0)  # (3+4+5)/3


def test_sma_period_one_returns_input():
    assert sma([10.0, 20.0, 30.0], 1) == [10.0, 20.0, 30.0]


def test_sma_short_input_all_none():
    assert sma([1, 2], 5) == [None, None]


def test_sma_zero_period_safe():
    assert sma([1, 2, 3], 0) == [None, None, None]


# ── EMA ──────────────────────────────────────────────────────────────────────

def test_ema_seeds_with_sma():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = ema(values, 3)
    assert result[0] is None
    assert result[1] is None
    assert result[2] == pytest.approx(2.0)  # SMA seed
    # Multiplier = 2/(3+1) = 0.5; next = (4 - 2)*0.5 + 2 = 3.0
    assert result[3] == pytest.approx(3.0)
    # next = (5 - 3)*0.5 + 3 = 4.0
    assert result[4] == pytest.approx(4.0)


def test_ema_short_input_all_none():
    assert ema([1, 2], 5) == [None, None]


# ── RSI ──────────────────────────────────────────────────────────────────────

def test_rsi_constant_series_no_loss_returns_100():
    # Perfectly rising series: avg_loss = 0 → RSI = 100
    values = [float(i) for i in range(1, 20)]
    result = rsi(values, 14)
    assert result[14] == 100.0


def test_rsi_warmup_is_none():
    values = [float(i) for i in range(1, 20)]
    result = rsi(values, 14)
    for i in range(14):
        assert result[i] is None


def test_rsi_falling_series_below_50():
    values = [float(i) for i in range(20, 1, -1)]  # 20, 19, ..., 2
    result = rsi(values, 14)
    assert result[14] == 0.0  # all losses → RSI = 0


def test_rsi_short_input_all_none():
    assert rsi([1, 2, 3], 14) == [None, None, None]


# ── MACD ─────────────────────────────────────────────────────────────────────

def test_macd_returns_three_aligned_arrays():
    values = [float(i) for i in range(1, 50)]
    result = macd(values, fast=12, slow=26, signal_period=9)
    assert set(result.keys()) == {"macd", "signal", "histogram"}
    assert len(result["macd"]) == len(values)
    assert len(result["signal"]) == len(values)
    assert len(result["histogram"]) == len(values)


def test_macd_first_25_indices_are_none_for_macd_line():
    values = [float(i) for i in range(1, 50)]
    result = macd(values, fast=12, slow=26, signal_period=9)
    # macd_line is None until both ema_fast (idx 11+) and ema_slow (idx 25+) exist
    for i in range(25):
        assert result["macd"][i] is None
    assert result["macd"][25] is not None


def test_macd_histogram_equals_macd_minus_signal():
    values = [float(i) * 1.1 + (i % 3) for i in range(1, 60)]
    result = macd(values)
    for m, s, h in zip(result["macd"], result["signal"], result["histogram"]):
        if m is None or s is None:
            assert h is None
        else:
            assert h == pytest.approx(m - s)


# ── build_indicators ─────────────────────────────────────────────────────────

def _candle(close: float, vol: int = 1000) -> dict:
    return {
        "time": "2026-01-01",
        "open": close - 1, "high": close + 1, "low": close - 2,
        "close": close, "volume": vol,
    }


def test_build_indicators_default_keys():
    candles = [_candle(float(i)) for i in range(1, 70)]
    result = build_indicators(candles)
    assert "ma5" in result
    assert "ma20" in result
    assert "ma60" in result
    assert "rsi" in result
    assert "macd" in result
    assert "volume" in result
    assert len(result["ma5"]) == 69
    assert len(result["volume"]) == 69


def test_build_indicators_subset():
    candles = [_candle(float(i)) for i in range(1, 30)]
    result = build_indicators(candles, requested={"ma5", "volume"})
    assert set(result.keys()) == {"ma5", "volume"}


# ── parse_indicator_query ────────────────────────────────────────────────────

def test_parse_query_expands_ma():
    result = parse_indicator_query("ma,rsi")
    assert {"ma5", "ma20", "ma60", "ma120", "ma240", "rsi"}.issubset(result)


def test_parse_query_all_returns_full_set():
    result = parse_indicator_query("all")
    assert {"ma5", "ma20", "ma60", "rsi", "macd", "volume"}.issubset(result)


def test_parse_query_empty_returns_none():
    assert parse_indicator_query(None) is None
    assert parse_indicator_query("") is None


def test_parse_query_filters_unknown():
    assert parse_indicator_query("garbage,rsi") == {"rsi"}
