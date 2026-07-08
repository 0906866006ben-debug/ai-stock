"""下單計畫計算器(dry-run 核心)——把一個訊號算成完整下單計畫。

策略參數(已與使用者確認):
  觸發=1m｜SL=進場前 N 根 15m 針尖(預設25)｜TP=15m EMA12
  風險=5u/單,部位=5u÷停損%,槓桿=min(20, 1/(2×停損))逐倉(確保爆倉在針尖外)
不下單、不碰 testnet——只算計畫給人看。
"""
from __future__ import annotations

import json
import math
import urllib.request
from typing import Any

FAPI = "https://fapi.binance.com"
RISK_USD = 5.0          # 每單風險(碰針尖賠這麼多 = -1R)
MAX_LEV = 20


def _get(path: str) -> Any:
    req = urllib.request.Request(FAPI + path, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def _ema_last(vals: list[float], n: int) -> float:
    k = 2 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def plan_trade(sym: str, direction: str, pin_bars: int = 25) -> dict[str, Any]:
    """direction: 'long'/'short'。回傳下單計畫 + 3/5/10 針尖 RR 對比。"""
    sym = sym.upper().replace("USDT", "") + "USDT"
    k15 = _get(f"/fapi/v1/klines?symbol={sym}&interval=15m&limit=60")
    closes = [float(c[4]) for c in k15]
    highs = [float(c[2]) for c in k15]
    lows = [float(c[3]) for c in k15]
    price = _get(f"/fapi/v1/premiumIndex?symbol={sym}")["markPrice"]
    entry = float(price)
    tp = _ema_last(closes, 12)                       # 15m EMA12 目標

    def pinbar(n: int) -> float:
        return min(lows[-n:]) if direction == "long" else max(highs[-n:])

    sl = pinbar(pin_bars)
    long = direction == "long"
    # 有效性:做多 TP(EMA12)要在進場上方、SL 在下方;做空相反。否則無回歸空間=跳過。
    valid = (tp > entry and sl < entry) if long else (tp < entry and sl > entry)
    stop_frac = abs(entry - sl) / entry
    tp_frac = (tp - entry) / entry if long else (entry - tp) / entry  # 帶號:負=方向不對
    rr = tp_frac / stop_frac if stop_frac > 0 else 0.0

    # 風險化部位:碰針尖賠 RISK_USD
    notional = RISK_USD / stop_frac if stop_frac > 0 else 0.0
    # 槓桿保守化:強平距離 ≈ 1/lev −維持保證金,要求 ≥ 3×停損距離(GRASS 教訓:
    # 舊公式 2× 沒算 MMR,強平比止損先到)。下單後另有實測強平價+自動補保證金雙保險。
    lev = max(1, min(MAX_LEV, math.floor(0.8 / (3 * stop_frac)))) if stop_frac > 0 else 1
    margin = notional / lev
    qty = notional / entry

    # 針尖窗口 RR 對比(停損%越大 RR 越低)
    rr_cmp = {}
    for n in (3, 5, 10, 25):
        s = pinbar(n)
        sf = abs(entry - s) / entry
        rr_cmp[n] = (round(tp_frac / sf, 2) if sf > 0 else 0.0, round(sf * 100, 2))

    return {
        "sym": sym, "direction": direction, "entry": entry, "tp": tp, "sl": sl, "valid": valid,
        "stop_pct": round(stop_frac * 100, 2), "tp_pct": round(tp_frac * 100, 2), "rr": round(rr, 2),
        "notional": round(notional, 2), "leverage": lev, "margin": round(margin, 2),
        "qty": qty, "risk_usd": RISK_USD, "rr_by_bars": rr_cmp,
        "side": "BUY" if long else "SELL", "close_side": "SELL" if long else "BUY",
    }


def format_plan(p: dict[str, Any]) -> str:
    arrow = "🔺做多" if p["direction"] == "long" else "🔻做空"
    g = lambda x: f"{x:g}"
    if not p["valid"]:
        return f"【{p['sym']} {arrow}】⛔ 跳過:價格已在 EMA12 {'上' if p['direction']=='long' else '下'}方,無回歸空間(TP方向不對)"
    return (
        f"【{p['sym']} {arrow}】\n"
        f"  進場 {g(p['entry'])}  TP {g(p['tp'])}(15m EMA12)  SL {g(p['sl'])}(15m針尖25)\n"
        f"  停損 {p['stop_pct']}%  獲利空間 {p['tp_pct']}%  → RR {p['rr']}\n"
        f"  部位 名目{p['notional']}u × {p['leverage']}x(保證金{p['margin']}u)  風險 {p['risk_usd']}u=-1R\n"
        f"  RR對比: 3根={p['rr_by_bars'][3]}  5根={p['rr_by_bars'][5]}  10根={p['rr_by_bars'][10]}"
    )


if __name__ == "__main__":
    import sys
    # 用法:auto_trader.py CHIP short   或   BTC long
    sym, d = sys.argv[1], sys.argv[2]
    print(format_plan(plan_trade(sym, d)))
