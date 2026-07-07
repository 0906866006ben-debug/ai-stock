"""抓某幣「當下」的訊號條件(1h RSI、距15m EMA12、資費、OI)——全走 Binance 免費 API,零 Claude。

給交易日誌 bot 用:下單時自動把訊號快照補進紀錄,使用者不用手打。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

FAPI = "https://fapi.binance.com"


def _get(path: str) -> Any:
    req = urllib.request.Request(FAPI + path, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=10))


def rsi14(closes: list[float]) -> list[float]:
    """Wilder RSI-14 序列。"""
    n = 14
    if len(closes) < n + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    out = []
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        rs = ag / al if al > 0 else 999.0
        out.append(100 - 100 / (1 + rs))
    return out


def ema_last(vals: list[float], n: int) -> float:
    k = 2 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def snapshot(sym: str) -> dict[str, Any]:
    """回傳該幣當下訊號條件;任何一項抓不到就給 None,永不 raise。"""
    sym = sym.upper().replace("USDT", "") + "USDT"
    snap: dict[str, Any] = {"sym": sym.replace("USDT", "")}

    try:  # 1h RSI
        kl = _get(f"/fapi/v1/klines?symbol={sym}&interval=1h&limit=120")
        rsis = rsi14([float(c[4]) for c in kl])
        if rsis:
            last6 = rsis[-6:]
            snap["rsi_now"] = round(rsis[-1], 1)
            snap["rsi_hi6"] = round(max(last6), 1)
            snap["rsi_lo6"] = round(min(last6), 1)
    except Exception:
        pass

    try:  # 15m EMA12 距離
        k15 = _get(f"/fapi/v1/klines?symbol={sym}&interval=15m&limit=120")
        closes15 = [float(c[4]) for c in k15]
        price = closes15[-1]
        e12 = ema_last(closes15, 12)
        snap["price"] = price
        snap["dist_ema12"] = round((price / e12 - 1) * 100, 2)
    except Exception:
        pass

    try:  # 資費
        d = _get(f"/fapi/v1/premiumIndex?symbol={sym}")
        snap["funding_pct"] = round(float(d.get("lastFundingRate", 0)) * 100, 4)
    except Exception:
        pass

    try:  # OI 近3根變化
        oi = _get(f"/futures/data/openInterestHist?symbol={sym}&period=1h&limit=6")
        if isinstance(oi, list) and len(oi) >= 4:
            a = float(oi[-4]["sumOpenInterest"])
            b = float(oi[-1]["sumOpenInterest"])
            if a > 0:
                chg = (b / a - 1) * 100
                snap["oi_chg"] = round(chg, 1)
                snap["oi_state"] = "堆積" if chg >= 3 else "消退" if chg <= -3 else "中性"
    except Exception:
        pass

    return snap


def gate_text(snap: dict[str, Any], direction: str | None) -> str:
    """一句話說門檻符不符(用近6根最高/最低對 75/25)。"""
    hi, lo = snap.get("rsi_hi6"), snap.get("rsi_lo6")
    if direction == "short" and hi is not None:
        return "超買✓門檻符合" if hi >= 75 else f"近6根最高僅{hi:.0f},未達75"
    if direction == "long" and lo is not None:
        return "超賣✓門檻符合" if lo <= 25 else f"近6根最低僅{lo:.0f},未達25"
    return ""
