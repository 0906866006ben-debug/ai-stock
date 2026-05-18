from __future__ import annotations

import pandas as pd

from backend.screeners.multi_factor_surge.config import CONFIG, clamp_score
from backend.screeners.multi_factor_surge.schemas import ModuleScore


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _kd(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    period = int(CONFIG["technical"]["kd_period"])
    low_min = df["low"].rolling(period, min_periods=period).min()
    high_max = df["high"].rolling(period, min_periods=period).max()
    rsv = ((df["close"] - low_min) / (high_max - low_min).replace(0, pd.NA) * 100).fillna(50)
    k = rsv.ewm(alpha=1 / int(CONFIG["technical"]["kd_smooth_k"]), adjust=False).mean()
    d = k.ewm(alpha=1 / int(CONFIG["technical"]["kd_smooth_d"]), adjust=False).mean()
    return k, d


def kd_high_saturation_days(df: pd.DataFrame) -> int:
    k, _ = _kd(df)
    threshold = float(CONFIG["technical"]["kd_high_threshold"])
    count = 0
    for value in reversed(k.tolist()):
        if value > threshold:
            count += 1
        else:
            break
    return count


def macd_golden_cross_above_zero(df: pd.DataFrame) -> bool:
    close = df["close"]
    dif = _ema(close, int(CONFIG["technical"]["macd_fast"])) - _ema(close, int(CONFIG["technical"]["macd_slow"]))
    dea = _ema(dif, int(CONFIG["technical"]["macd_signal"]))
    if len(df) < 2:
        return False
    return bool(dif.iloc[-2] <= dea.iloc[-2] and dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-1] > 0 and dea.iloc[-1] > 0)


def bollinger_state(df: pd.DataFrame) -> tuple[str, bool, bool]:
    period = int(CONFIG["technical"]["bb_period"])
    close = df["close"]
    ma = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    upper = ma + std * float(CONFIG["technical"]["bb_std"])
    lower = ma - std * float(CONFIG["technical"]["bb_std"])
    width = ((upper - lower) / ma).fillna(0)
    squeeze = bool(width.iloc[-6:-1].min() < float(CONFIG["technical"]["bb_squeeze_width_pct"])) if len(width) >= 6 else False
    expand = bool(width.iloc[-1] > width.iloc[-2] * float(CONFIG["technical"]["bb_expand_width_ratio"])) if len(width) >= 2 and width.iloc[-2] else False
    breakout = bool(close.iloc[-1] > upper.iloc[-1]) if pd.notna(upper.iloc[-1]) else False
    if squeeze and expand and breakout:
        return "squeeze_then_expand", True, True
    if breakout:
        return "breakout", False, True
    if squeeze:
        return "squeeze", True, False
    return "neutral", False, False


def obv_above_ma10(df: pd.DataFrame) -> tuple[bool, bool]:
    direction = df["close"].diff().fillna(0).apply(lambda v: 1 if v > 0 else -1 if v < 0 else 0)
    obv = (direction * df["volume"]).cumsum()
    ma = obv.rolling(int(CONFIG["technical"]["obv_ma_period"]), min_periods=1).mean()
    above = bool(obv.iloc[-1] > ma.iloc[-1])
    crossed = bool(len(obv) >= 2 and obv.iloc[-2] <= ma.iloc[-2] and obv.iloc[-1] > ma.iloc[-1])
    return above, crossed


def score_technicals(df: pd.DataFrame) -> tuple[ModuleScore, dict[str, object]]:
    k, d = _kd(df)
    kd_days = kd_high_saturation_days(df)
    macd_cross = macd_golden_cross_above_zero(df)
    bb_state, bb_squeeze_expand, bb_breakout = bollinger_state(df)
    obv_above, obv_cross = obv_above_ma10(df)
    metrics = {
        "kd_high_saturation_days": kd_days,
        "kd_k": round(float(k.iloc[-1]), 2),
        "kd_d": round(float(d.iloc[-1]), 2),
        "macd_state": "golden_cross_above_zero" if macd_cross else "neutral",
        "bb_state": bb_state,
        "obv_vs_ma10": "above" if obv_above else "below",
        "obv_cross_above_ma10": obv_cross,
    }
    score = 45
    reasons: list[str] = []
    if kd_days >= int(CONFIG["technical"]["kd_high_saturation_days"]):
        score += 18
        reasons.append(f"KD 高檔鈍化 {kd_days} 日")
    if macd_cross:
        score += 18
        reasons.append("MACD 零軸上黃金交叉")
    if bb_squeeze_expand:
        score += 20
        reasons.append("布林收斂後張口突破")
    elif bb_breakout:
        score += 10
        reasons.append("布林上緣突破")
    if obv_above:
        score += 8
        reasons.append("OBV 位於 MA10 之上")
    if obv_cross:
        score += 8
        reasons.append("OBV 向上穿越 MA10")
    return ModuleScore(score=clamp_score(score), reasons=reasons), metrics
