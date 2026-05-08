"""Pure technical-indicator math over OHLCV series.

All functions return arrays aligned with the input length, using None for
warm-up periods that don't have enough history yet.
"""
from __future__ import annotations


def sma(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        return [None] * len(values)
    out: list[float | None] = []
    rolling = 0.0
    for i, v in enumerate(values):
        rolling += v
        if i >= period:
            rolling -= values[i - period]
        if i + 1 < period:
            out.append(None)
        else:
            out.append(rolling / period)
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    if period <= 0 or len(values) < period:
        return [None] * len(values)
    out: list[float | None] = [None] * len(values)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    multiplier = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        prev = (values[i] - prev) * multiplier + prev
        out[i] = prev
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        change = values[i] - values[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = abs(min(change, 0.0))

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period

    def _rsi_value(g: float, l: float) -> float:
        if l == 0:
            return 100.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[period] = _rsi_value(avg_gain, avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i] = _rsi_value(avg_gain, avg_loss)

    return out


def macd(
    values: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> dict[str, list[float | None]]:
    n = len(values)
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)

    macd_line: list[float | None] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow)
    ]

    # EMA of the (non-None tail of) macd_line, then re-align
    valid_start = next((i for i, v in enumerate(macd_line) if v is not None), n)
    tail = [v for v in macd_line[valid_start:] if v is not None]
    signal_tail = ema(tail, signal_period) if tail else []

    signal_line: list[float | None] = [None] * n
    for i, v in enumerate(signal_tail):
        signal_line[valid_start + i] = v

    histogram: list[float | None] = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, signal_line)
    ]

    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


# ── Convenience: build indicator bundle from candles ─────────────────────────

INDICATOR_KEYS = {"ma5", "ma20", "ma60", "rsi", "macd", "volume"}


def build_indicators(candles: list[dict], requested: set[str] | None = None) -> dict:
    """Compute requested indicators from a candle list.

    Each candle is a dict with `open`, `high`, `low`, `close`, `volume`, `time`.
    Returns a dict keyed by indicator name. Unknown keys are ignored.
    """
    keys = requested or INDICATOR_KEYS
    closes = [float(c.get("close", 0.0)) for c in candles]
    out: dict = {}

    if "ma5" in keys:
        out["ma5"] = sma(closes, 5)
    if "ma20" in keys:
        out["ma20"] = sma(closes, 20)
    if "ma60" in keys:
        out["ma60"] = sma(closes, 60)
    if "rsi" in keys:
        out["rsi"] = rsi(closes, 14)
    if "macd" in keys:
        out["macd"] = macd(closes)
    if "volume" in keys:
        out["volume"] = [int(c.get("volume", 0)) for c in candles]

    return out


def parse_indicator_query(raw: str | None) -> set[str] | None:
    """Parse a comma-separated indicator list from the query string.

    Accepts: "ma,rsi,macd,volume" → expands "ma" to ma5/ma20/ma60.
    Returns None if no indicators are requested (caller skips computation).
    """
    if not raw:
        return None
    parts = {p.strip().lower() for p in raw.split(",") if p.strip()}
    if "ma" in parts:
        parts.discard("ma")
        parts.update({"ma5", "ma20", "ma60"})
    if "all" in parts:
        return set(INDICATOR_KEYS)
    return parts & INDICATOR_KEYS or None
