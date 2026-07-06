"""加密永續「超買/超賣 × 價格異常 × 資費定位」即時掃描器。

用途:輔助觀察/進場,**非策略、不宣稱 edge、無回測背書**。只把符合條件的
幣即時排出來,判斷與風控由使用者自負。資料源 Binance USDT 永續(免費、無金鑰)。

訊號邏輯(對齊使用者手法:超買後翻頭 + 資費看人群多空):
  做空觀察 = RSI 高(超買) + 近期急漲(價格異常) + 資費為正(人群壓多) + 已跌破 EMA12(翻頭)
  做多觀察 = RSI 低(超賣) + 近期急跌 + 資費為負(人群壓空) + 已站上 EMA12(翻頭)
  價格異常 = 15m 報酬 / 成交量相對自身近期分布的離群程度(z-score)

Run:  .venv/Scripts/python.exe backend/scripts/crypto_anomaly_scanner.py
      .venv/Scripts/python.exe backend/scripts/crypto_anomaly_scanner.py --tf 5m --top 30 --min-vol 30
"""
from __future__ import annotations

import argparse
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

import numpy as np

BASE = "https://fapi.binance.com"


def _get(path: str, params: dict | None = None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def rsi(closes: np.ndarray, n: int = 14) -> float:
    if len(closes) < n + 1:
        return float("nan")
    d = np.diff(closes)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = up[-n:].mean()
    ad = dn[-n:].mean()
    if ad == 0:
        return 100.0
    rs = au / ad
    return 100 - 100 / (1 + rs)


def ema(closes: np.ndarray, span: int) -> np.ndarray:
    a = 2 / (span + 1)
    out = np.empty_like(closes)
    out[0] = closes[0]
    for i in range(1, len(closes)):
        out[i] = a * closes[i] + (1 - a) * out[i - 1]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="15m", help="K 線週期 (1m/5m/15m/1h)")
    ap.add_argument("--top", type=int, default=40, help="先按流動性+異常取前 N 檔細掃")
    ap.add_argument("--min-vol", type=float, default=20.0, help="24h 成交額下限(百萬美元)")
    ap.add_argument("--rsi-hi", type=float, default=70.0)
    ap.add_argument("--rsi-lo", type=float, default=30.0)
    args = ap.parse_args()

    print(f"抓全市場 ticker + 資費 … (tf={args.tf})", flush=True)
    tickers = {t["symbol"]: t for t in _get("/fapi/v1/ticker/24hr")}
    prem = {p["symbol"]: p for p in _get("/fapi/v1/premiumIndex")}

    # 池:USDT 永續、24h 成交額達標、排除槓桿代幣
    pool = []
    for sym, t in tickers.items():
        if not sym.endswith("USDT"):
            continue
        qv = float(t.get("quoteVolume", 0)) / 1e6  # 百萬美元
        if qv < args.min_vol:
            continue
        chg = abs(float(t.get("priceChangePercent", 0)))
        pool.append((sym, qv, chg))
    # 先按「24h 漲跌幅絕對值」(價格異常代理)排,取前 N 細掃
    pool.sort(key=lambda x: x[2], reverse=True)
    shortlist = [s for s, _, _ in pool[: max(args.top, 20)]]
    print(f"池 {len(pool)} 檔 → 細掃前 {len(shortlist)} 檔異常者", flush=True)

    rows = []
    for sym in shortlist:
        try:
            k = _get("/fapi/v1/klines", {"symbol": sym, "interval": args.tf, "limit": 100})
        except Exception:
            continue
        closes = np.array([float(c[4]) for c in k])
        vols = np.array([float(c[5]) for c in k])
        if len(closes) < 30:
            continue
        r = rsi(closes)
        e12 = ema(closes, 12)[-1]
        e26 = ema(closes, 26)[-1]
        price = closes[-1]
        # 近期報酬 z-score(價格異常):最後一根相對過去分布
        rets = np.diff(closes) / closes[:-1]
        ret_z = (rets[-1] - rets[:-1].mean()) / (rets[:-1].std() + 1e-9)
        vol_z = (vols[-1] - vols[:-1].mean()) / (vols[:-1].std() + 1e-9)
        fr = float(prem.get(sym, {}).get("lastFundingRate", 0) or 0)
        dist_e12 = price / e12 - 1
        broke_below = closes[-2] >= ema(closes, 12)[-2] and price < e12   # 剛跌破 EMA12
        broke_above = closes[-2] <= ema(closes, 12)[-2] and price > e12   # 剛站上 EMA12

        tag, strength = "", 0.0
        if r >= args.rsi_hi and fr > 0:
            tag = "🔻做空觀察(超買+資費正)"
            strength = (r - 50) + fr * 5000 + max(ret_z, 0) * 5 + (8 if price < e12 else 0)
            if broke_below:
                tag += " ★剛跌破EMA12"
        elif r <= args.rsi_lo and fr < 0:
            tag = "🔺做多觀察(超賣+資費負)"
            strength = (50 - r) + (-fr) * 5000 + max(-ret_z, 0) * 5 + (8 if price > e12 else 0)
            if broke_above:
                tag += " ★剛站上EMA12"
        elif abs(ret_z) >= 3 or vol_z >= 4:
            tag = "⚡純價格/量能異常(觀察)"
            strength = abs(ret_z) + vol_z
        if not tag:
            continue
        rows.append({
            "sym": sym, "price": price, "rsi": r, "fr": fr * 100, "dist_e12": dist_e12 * 100,
            "ret_z": ret_z, "vol_z": vol_z, "chg24": float(tickers[sym]["priceChangePercent"]),
            "tag": tag, "strength": strength,
        })

    rows.sort(key=lambda x: x["strength"], reverse=True)
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    print(f"\n=== 加密異常掃描 {now}  (tf={args.tf}, RSI 超買≥{args.rsi_hi}/超賣≤{args.rsi_lo}) ===")
    print(f"{'幣種':<16}{'價格':>12}{'RSI':>6}{'資費%':>8}{'離EMA12%':>9}{'ret_z':>7}{'24h%':>8}  訊號")
    for r in rows[:25]:
        print(f"{r['sym']:<16}{r['price']:>12.6g}{r['rsi']:>6.0f}{r['fr']:>8.3f}"
              f"{r['dist_e12']:>9.1f}{r['ret_z']:>7.1f}{r['chg24']:>8.1f}  {r['tag']}")
    if not rows:
        print("目前無符合條件者。")
    print("\n⚠ 本掃描為觀察輔助,非投資建議、無回測背書;做空噴出幣有軋空尾部風險,務必控槓桿與停損。")


if __name__ == "__main__":
    main()
