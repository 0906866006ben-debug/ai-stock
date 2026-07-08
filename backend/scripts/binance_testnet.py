"""Binance 期貨測試網 client(paper trading)——簽章、下單、查持倉、精度處理。

假錢環境(testnet.binancefuture.com),金鑰放 backend/.env:
  TESTNET_API_KEY / TESTNET_API_SECRET

只做「工具層」:下市價單、掛 TP/SL、設槓桿/逐倉、查持倉、算數量精度。
策略決策(何時下、下多大)由上層 auto_trader 負責。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://testnet.binancefuture.com"

# 讀 .env(覆蓋 OS,避免殭屍值)
_ENV = Path(__file__).resolve().parents[1] / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)\s*$", line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))

KEY = os.getenv("TESTNET_API_KEY", "")
SECRET = os.getenv("TESTNET_API_SECRET", "")


def _public(path: str, params: dict | None = None) -> Any:
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def _signed(method: str, path: str, params: dict | None = None) -> Any:
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 5000
    q = urllib.parse.urlencode(p)
    sig = hmac.new(SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE}{path}?{q}&signature={sig}"
    req = urllib.request.Request(url, method=method, headers={"X-MBX-APIKEY": KEY})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"測試網 {e.code}: {e.read().decode(errors='replace')[:300]}") from None


# ── 精度(每個 symbol 的數量步進 / 價格跳動 / 最小名目)──
_FILTERS: dict[str, dict] = {}


def _load_filters() -> None:
    if _FILTERS:
        return
    for s in _public("/fapi/v1/exchangeInfo")["symbols"]:
        f = {x["filterType"]: x for x in s["filters"]}
        _FILTERS[s["symbol"]] = {
            "qtyStep": float(f["LOT_SIZE"]["stepSize"]),
            "minQty": float(f["LOT_SIZE"]["minQty"]),
            "tick": float(f["PRICE_FILTER"]["tickSize"]),
            "minNotional": float(f.get("MIN_NOTIONAL", {}).get("notional", 0) or 0),
        }


def _step_round(v: float, step: float) -> float:
    return math.floor(v / step) * step if step else v


def _dec(step: float) -> int:
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def round_qty(sym: str, qty: float) -> float:
    _load_filters()
    st = _FILTERS[sym]["qtyStep"]
    return round(_step_round(qty, st), _dec(st))


def round_price(sym: str, price: float) -> float:
    _load_filters()
    tk = _FILTERS[sym]["tick"]
    return round(_step_round(price, tk), _dec(tk))


def filters(sym: str) -> dict:
    _load_filters()
    return _FILTERS.get(sym, {})


def has_symbol(sym: str) -> bool:
    _load_filters()
    return sym in _FILTERS


# ── 行情 / 帳戶 / 持倉 ──
def mark_price(sym: str) -> float:
    return float(_public("/fapi/v1/premiumIndex", {"symbol": sym})["markPrice"])


def usdt_balance() -> float:
    for b in _signed("GET", "/fapi/v2/balance"):
        if b["asset"] == "USDT":
            return float(b["availableBalance"])
    return 0.0


def position(sym: str) -> dict | None:
    """回傳該 symbol 目前持倉(有部位才回),否則 None。"""
    for p in _signed("GET", "/fapi/v2/positionRisk", {"symbol": sym}):
        if abs(float(p["positionAmt"])) > 0:
            return p
    return None


def open_orders(sym: str) -> list:
    return _signed("GET", "/fapi/v1/openOrders", {"symbol": sym})


def realized_pnl(sym: str, since_ms: int) -> float:
    """自 since_ms 起,該 symbol 的淨已實現損益 = 已實現盈虧 − 手續費 ± 資金費。
    (只算 REALIZED_PNL 會系統性高估 R:停損小→名目大→taker 費占比大。)"""
    inc = _signed("GET", "/fapi/v1/income",
                  {"symbol": sym, "startTime": since_ms, "limit": 500})
    keep = ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE")
    return sum(float(x["income"]) for x in inc if x.get("incomeType") in keep)


def cancel_all(sym: str) -> None:
    try:
        _signed("DELETE", "/fapi/v1/allOpenOrders", {"symbol": sym})
    except RuntimeError:
        pass


def add_margin(sym: str, amount: float) -> None:
    """逐倉補保證金(把強平價推遠)。type=1 增加。"""
    _signed("POST", "/fapi/v1/positionMargin",
            {"symbol": sym, "amount": round(amount, 2), "type": 1})


_BRACKETS: dict[str, list] = {}


def leverage_bracket(sym: str) -> list[dict]:
    """該幣的槓桿檔位表(名目分層的 MMR/cum),下單前精算強平用。有快取。"""
    if sym not in _BRACKETS:
        d = _signed("GET", "/fapi/v1/leverageBracket", {"symbol": sym})
        if isinstance(d, list):
            d = d[0]
        _BRACKETS[sym] = d["brackets"]
    return _BRACKETS[sym]


def bracket_for(sym: str, notional: float) -> dict:
    for b in leverage_bracket(sym):
        if notional <= float(b["notionalCap"]):
            return b
    return leverage_bracket(sym)[-1]


def liq_price(entry: float, qty: float, margin: float, mmr: float, cum: float, long: bool) -> float:
    """逐倉強平價(官方公式,單向持倉)。"""
    if long:
        return (qty * entry - margin - cum) / (qty * (1 - mmr))
    return (qty * entry + margin + cum) / (qty * (1 + mmr))


# ── 下單前設定 ──
def set_leverage(sym: str, lev: int) -> None:
    _signed("POST", "/fapi/v1/leverage", {"symbol": sym, "leverage": lev})


def set_isolated(sym: str) -> None:
    try:
        _signed("POST", "/fapi/v1/marginType", {"symbol": sym, "marginType": "ISOLATED"})
    except RuntimeError as e:
        if "-4046" not in str(e):   # -4046 = 已經是該模式,忽略
            raise


# ── 下單 ──
def market_entry(sym: str, side: str, qty: float) -> dict:
    """side=BUY(做多)/SELL(做空)。"""
    return _signed("POST", "/fapi/v1/order",
                   {"symbol": sym, "side": side, "type": "MARKET", "quantity": round_qty(sym, qty)})


def stop_market(sym: str, close_side: str, stop_price: float) -> dict:
    """整倉停損(STOP_MARKET, closePosition)。close_side=平倉方向(多單平=SELL)。"""
    return _signed("POST", "/fapi/v1/order",
                   {"symbol": sym, "side": close_side, "type": "STOP_MARKET",
                    "stopPrice": round_price(sym, stop_price), "closePosition": "true"})


def take_profit_market(sym: str, close_side: str, stop_price: float) -> dict:
    """整倉停利(TAKE_PROFIT_MARKET, closePosition)。"""
    return _signed("POST", "/fapi/v1/order",
                   {"symbol": sym, "side": close_side, "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": round_price(sym, stop_price), "closePosition": "true"})


if __name__ == "__main__":
    print("餘額 USDT:", usdt_balance())
    for s in ("BTCUSDT", "AKEUSDT"):
        if has_symbol(s):
            print(f"{s}: 標記價 {mark_price(s)}  精度 {filters(s)}")
