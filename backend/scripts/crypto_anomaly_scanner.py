"""加密永續「1h 超買/超賣 x 1m EMA12 觸發 x 15m EMA12 目標」即時掃描器。

用途:輔助觀察/進場,**非策略、不宣稱 edge、無回測背書**。只把符合條件的
幣即時排出來,判斷與風控由使用者自負。資料源 Binance USDT 永續(免費、無金鑰)。

訊號邏輯(對齊 Next `/api/crypto-scan`):
  做空觀察 = 1h RSI >= 75
  做多觀察 = 1h RSI <= 25
  觸發 = 1m 一大根實體收破 EMA12 + 下一根守住;放量升級為 ★,無量為 ◆
  15m EMA12 = 目標參考,不是觀察名單的篩選條件

Run:  .venv/Scripts/python.exe backend/scripts/crypto_anomaly_scanner.py
      .venv/Scripts/python.exe backend/scripts/crypto_anomaly_scanner.py --top 30 --min-vol 30
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

import numpy as np

BASE = "https://fapi.binance.com"


def _telegram(text: str) -> None:
    """推播到 Telegram(複用 repo 的 TELEGRAM_BOT_TOKEN + chat id)。失敗靜默。"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("CHAT_ID") or os.getenv("TELEGRAM_WEB_CHAT_ID")
    if not token or not chat:
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass


def _get(path: str, params: dict[str, Any] | None = None, timeout: int = 12) -> Any:
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def rsi_series(closes: np.ndarray, n: int = 14) -> np.ndarray:
    out = np.full(len(closes), np.nan, dtype=float)
    if len(closes) <= n:
        return out
    diff = np.diff(closes[: n + 1])
    gain = np.where(diff > 0, diff, 0.0).sum() / n
    loss = np.where(diff < 0, -diff, 0.0).sum() / n
    out[n] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    for idx in range(n + 1, len(closes)):
        delta = closes[idx] - closes[idx - 1]
        gain = (gain * (n - 1) + (delta if delta > 0 else 0.0)) / n
        loss = (loss * (n - 1) + (-delta if delta < 0 else 0.0)) / n
        out[idx] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def ema_last(closes: np.ndarray, span: int) -> float:
    alpha = 2 / (span + 1)
    ema = float(closes[0])
    for close in closes[1:]:
        ema = alpha * float(close) + (1 - alpha) * ema
    return ema


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _mean(values: np.ndarray) -> float:
    return float(values.mean()) if len(values) else 0.0


def _std(values: np.ndarray) -> float:
    return float(values.std()) or 1e-9


def big_break(klines: list[list[Any]], direction: int, vol_mult: float, body_mult: float) -> dict[str, float | bool]:
    if len(klines) < 26:
        return {"hit": False, "loud": False, "body": 0.0, "vol": 0.0, "held": False}
    opens = np.array([float(c[1]) for c in klines], dtype=float)
    highs = np.array([float(c[2]) for c in klines], dtype=float)
    lows = np.array([float(c[3]) for c in klines], dtype=float)
    closes = np.array([float(c[4]) for c in klines], dtype=float)
    vols = np.array([float(c[5]) for c in klines], dtype=float)
    idx = len(closes) - 2
    e12_prev = ema_last(closes[:idx], 12)
    e12_break = ema_last(closes[: idx + 1], 12)
    e12_confirm = ema_last(closes, 12)
    open_, high, low, close, volume = opens[idx], highs[idx], lows[idx], closes[idx], vols[idx]
    prev_close = closes[idx - 1]
    body = abs(close - open_)
    candle_range = max(high - low, 1e-12)
    body_mul = body / (float(np.mean(np.abs(closes[idx - 20:idx] - opens[idx - 20:idx]))) or 1e-12)
    vol_mul = volume / (_mean(vols[idx - 20:idx]) or 1e-12)
    big = body_mul >= body_mult
    loud = vol_mul >= vol_mult
    close_pos = (close - low) / candle_range
    if direction < 0:
        broke = big and prev_close >= e12_prev and close < e12_break and close < open_ and close_pos <= 0.4
        held = closes[-1] < e12_confirm
    else:
        broke = big and prev_close <= e12_prev and close > e12_break and close > open_ and close_pos >= 0.6
        held = closes[-1] > e12_confirm
    return {"hit": bool(broke and held), "loud": bool(loud), "body": float(body_mul), "vol": float(vol_mul), "held": bool(held)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h", help="設定框架,預設 1h")
    ap.add_argument("--trig-tf", default="1m", help="觸發框架,預設 1m")
    ap.add_argument("--top", type=int, default=150, help="先按 24h 異常取前 N 檔細掃")
    ap.add_argument("--min-vol", type=float, default=15.0, help="24h 成交額下限(百萬美元)")
    ap.add_argument("--min-q", type=float, default=0.0, help="品質分下限")
    ap.add_argument("--rsi-hi", type=float, default=75.0)
    ap.add_argument("--rsi-lo", type=float, default=25.0)
    ap.add_argument("--vol-mult", type=float, default=1.5, help="1m 放量倍數")
    ap.add_argument("--body-mult", type=float, default=1.5, help="1m 實體倍數")
    ap.add_argument("--json", action="store_true", help="輸出 JSON(貼進 Artifact 看板用)")
    ap.add_argument("--watch", type=int, default=0, metavar="SEC",
                    help="盯盤模式:每 SEC 秒重掃一次(0=只掃一次)")
    ap.add_argument("--telegram", action="store_true",
                    help="有新訊號(★剛翻頭)時推播 Telegram(需 TELEGRAM_BOT_TOKEN + CHAT_ID)")
    ap.add_argument("--alert-tag", default="★", help="只有 tag 含此字串才推播(預設只推剛翻頭的 ★)")
    args = ap.parse_args()

    if args.watch > 0:
        _watch_loop(args)
        return
    rows, now = scan_once(args, verbose=not args.json)
    _output(args, rows, now)


def scan_once(args: argparse.Namespace, verbose: bool = False) -> tuple[list[dict[str, Any]], str]:
    if verbose:
        print(f"抓全市場 ticker + 資費 ... (tf={args.tf}, trig={args.trig_tf})", flush=True)
    tickers_raw = _get("/fapi/v1/ticker/24hr")
    prem_raw = _get("/fapi/v1/premiumIndex")
    tickers = {t["symbol"]: t for t in tickers_raw}
    funding = {p["symbol"]: float(p.get("lastFundingRate", 0) or 0) for p in prem_raw}

    pool: list[str] = []
    chg_map: dict[str, float] = {}
    for sym, ticker in tickers.items():
        if not sym.endswith("USDT"):
            continue
        if float(ticker.get("quoteVolume", 0) or 0) / 1e6 < args.min_vol:
            continue
        chg_map[sym] = float(ticker.get("priceChangePercent", 0) or 0)
        pool.append(sym)
    fr_vals = sorted(funding.get(sym, 0.0) for sym in pool)
    shortlist = sorted(pool, key=lambda sym: abs(chg_map[sym]), reverse=True)[: max(args.top, 20)]
    if verbose:
        print(f"池 {len(pool)} 檔 -> 細掃前 {len(shortlist)} 檔異常者", flush=True)

    rows: list[dict[str, Any]] = []
    for sym in shortlist:
        try:
            k = _get("/fapi/v1/klines", {"symbol": sym, "interval": args.tf, "limit": 120})
        except Exception:
            continue
        if len(k) < 40:
            continue
        closes = np.array([float(c[4]) for c in k], dtype=float)
        rsi = float(rsi_series(closes)[-1])

        direction = 0
        tag = ""
        if rsi >= args.rsi_hi:
            direction = -1
            tag = "🔻做空觀察(1h超買≥75·待1m EMA12跌破)"
        elif rsi <= args.rsi_lo:
            direction = 1
            tag = "🔺做多觀察(1h超賣≤25·待1m EMA12突破)"
        if not tag:
            continue

        try:
            k15 = _get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "limit": 120})
        except Exception:
            continue
        if len(k15) < 20:
            continue
        closes15 = np.array([float(c[4]) for c in k15], dtype=float)
        vols15 = np.array([float(c[5]) for c in k15], dtype=float)
        price = float(closes15[-1])
        fr = funding.get(sym, 0.0)
        fr_pct = bisect.bisect_left(fr_vals, fr) / len(fr_vals) if fr_vals else 0.5
        e12 = ema_last(closes15, 12)
        dist_e12 = (price / e12 - 1) * 100
        recent = closes15[-30:]
        recent_diff = np.diff(recent)
        ext_z = (price - e12) / ((_std(recent_diff) * np.sqrt(20)) or 1e-9)
        vpast = vols15[-21:-1]
        vol_z = (float(vols15[-1]) - _mean(vpast)) / _std(vpast)
        oi_chg = 0.0
        try:
            oi_hist = _get("/futures/data/openInterestHist", {"symbol": sym, "period": args.tf, "limit": 12})
            if len(oi_hist) >= 4:
                a = float(oi_hist[-4].get("sumOpenInterest", 0) or 0)
                b = float(oi_hist[-1].get("sumOpenInterest", 0) or 0)
                if a > 0:
                    oi_chg = (b / a - 1) * 100
        except Exception:
            pass

        oi_state = "堆積" if oi_chg >= 3 else "消退" if oi_chg <= -3 else "中性"
        ext_extreme = abs(ext_z) >= 3
        rsi_quality = _clamp((rsi - args.rsi_hi) / (100 - args.rsi_hi)) * 45 if direction < 0 else _clamp((args.rsi_lo - rsi) / args.rsi_lo) * 45
        funding_aligned = (direction < 0 and fr > 0) or (direction > 0 and fr < 0)
        quality = rsi_quality
        quality += _clamp(abs(ext_z) / 3) * 20
        quality += 15 if funding_aligned else 0
        quality += 10 if oi_chg >= 3 else -5 if oi_chg <= -3 else 0
        quality += 8 if ext_extreme else 0
        quality = max(0.0, min(100.0, quality))
        tag += " 資費順風" if funding_aligned else " 資費逆風"
        if quality < args.min_q:
            continue
        if oi_state == "堆積":
            tag += " 🔥OI堆積"
        elif oi_state == "消退":
            tag += " ⚠️OI消退"
        if ext_extreme:
            tag += " 極端偏離"

        triggered = False
        tier = ""
        trig_body = 0.0
        trig_vol = 0.0
        try:
            k1 = _get("/fapi/v1/klines", {"symbol": sym, "interval": args.trig_tf, "limit": 40})
            trig = big_break(k1, direction, args.vol_mult, args.body_mult)
            trig_body = round(float(trig["body"]), 1)
            trig_vol = round(float(trig["vol"]), 1)
            if trig["hit"]:
                triggered = True
                tier = "★" if trig["loud"] else "◆"
                dir_txt = "🔻做空" if direction < 0 else "🔺做多"
                brk = "整根實體跌破" if direction < 0 else "整根實體突破"
                tag = f"{dir_txt} {tier}{args.trig_tf}{brk}EMA12+守住{'+放量' if trig['loud'] else '(無量)'}"
        except Exception:
            pass

        rows.append({
            "sym": sym,
            "price": price,
            "rsi": rsi,
            "fr": fr * 100,
            "fr_pct": round(fr_pct * 100),
            "dist_e12": dist_e12,
            "ext_z": ext_z,
            "ret_z": ext_z,
            "vol_z": vol_z,
            "oi_chg": oi_chg,
            "oi_state": oi_state,
            "ext_extreme": ext_extreme,
            "diverg": False,
            "chg24": chg_map[sym],
            "tag": tag,
            "quality": round(quality),
            "strength": round(quality),
            "triggered": triggered,
            "tier": tier,
            "trig_body": trig_body,
            "trig_vol": trig_vol,
        })

    rows.sort(key=lambda row: (bool(row["triggered"]), row["quality"]), reverse=True)
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    return rows, now


def _round_json(value: Any) -> Any:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, np.floating):
        return round(float(value), 6)
    if isinstance(value, dict):
        return {key: _round_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_json(item) for item in value]
    return value


def _output(args: argparse.Namespace, rows: list[dict[str, Any]], now: str) -> None:
    if args.json:
        payload = {
            "status": "ok",
            "scan_mode": "rsi_setup_v2",
            "generated_at": now,
            "tf": args.tf,
            "trig_tf": args.trig_tf,
            "min_quality": args.min_q,
            "rows": _round_json(rows),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return
    print(f"\n=== 加密異常掃描 {now}  (tf={args.tf}, RSI 超買≥{args.rsi_hi}/超賣≤{args.rsi_lo}) ===")
    print(f"{'幣種':<16}{'價格':>12}{'RSI':>6}{'資費%':>8}{'分位':>6}{'偏離z':>8}{'品質':>6}  訊號")
    for row in rows[:25]:
        print(f"{row['sym']:<16}{row['price']:>12.6g}{row['rsi']:>6.0f}{row['fr']:>8.3f}"
              f"{row['fr_pct']:>6.0f}{row['ext_z']:>8.1f}{row['quality']:>6.0f}  {row['tag']}")
    if not rows:
        print("目前無符合條件者。")
    print("\n⚠ 本掃描為觀察輔助,非投資建議、無回測背書;做空噴出幣有軋空尾部風險,務必控槓桿與停損。")


def _watch_loop(args: argparse.Namespace) -> None:
    """盯盤模式:每 args.watch 秒重掃;有新的符合 --alert-tag 的訊號才印/推播(去重)。"""
    print(f"🟢 盯盤啟動:每 {args.watch}s 重掃 tf={args.tf};"
          f"{'Telegram 推播開' if args.telegram else '僅本機輸出'}。Ctrl+C 停止。", flush=True)
    seen: dict[str, float] = {}  # sym -> 上次推播時間,避免重複洗版
    while True:
        try:
            rows, now = scan_once(args, verbose=False)
        except Exception as exc:  # noqa: BLE001 網路波動不中斷
            print(f"[{now if 'now' in dir() else ''}] 掃描失敗:{exc},稍後重試", flush=True)
            time.sleep(args.watch)
            continue
        hits = [row for row in rows if args.alert_tag in row["tag"]]
        line = " | ".join(f"{row['sym'].replace('USDT','')} {row['tag'].split('(')[0]} RSI{row['rsi']:.0f}" for row in hits[:6])
        print(f"[{now}] 命中 {len(hits)} / 掃出 {len(rows)}  {line}", flush=True)
        if args.telegram:
            fresh = [row for row in hits if time.time() - seen.get(row["sym"], 0) >= args.watch]
            for row in fresh:
                seen[row["sym"]] = time.time()
                msg = (f"📡 <b>{row['sym'].replace('USDT','')}</b> {row['tag']}\n"
                       f"價 {row['price']:.6g} · RSI {row['rsi']:.0f} · 資費 {row['fr']:+.3f}% · "
                       f"離EMA12 {row['dist_e12']:+.1f}% · 24h {row['chg24']:+.1f}%\n⚠ 控槓桿+停損,非建議")
                _telegram(msg)
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
