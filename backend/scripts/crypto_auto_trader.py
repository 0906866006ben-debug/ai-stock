"""加密自動交易(Binance 測試網 paper trading)——訊號→風險化下單→掛TP/SL→平倉自動記 Notion。

策略(已與使用者鎖定):
  觸發 = 掃描器 ★(1m 整根收破 EMA12+守住)｜方向 = 1h RSI 75/25
  進場 = 市價｜SL = 25根15m 擺動針尖｜TP = 15m EMA12｜貼EMA12無空間跳過
  部位 = 風險 5u/單(部位=5u÷停損%)、槓桿自動 ≤20x、逐倉｜不設RR/偏離門檻(全收)
  平倉 → 自動寫 Notion(R = 已實現盈虧 ÷ 總風險;加倉後為 10u)

環境變數(backend/.env):
  TESTNET_API_KEY / TESTNET_API_SECRET  測試網金鑰
  NOTION_TOKEN / NOTION_DB_ID           記錄用
可選:
  AUTOTRADE_DRYRUN=1   只印計畫不下單(預設 1,驗證用;改 0 才真下單)
  AUTOTRADE_STAR_ONLY=1 只做★放量觸發(預設 1;改 0 才會連◆也做)
  AUTOTRADE_WEBHOOK=... Discord webhook(推播開/平倉;不設就只印 console)
  AUTOTRADE_MAX_OPEN=8  同時最多持倉數
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

import auto_trader
import binance_testnet as tn
import notion_journal

# 讀 .env(覆蓋 OS 殭屍值)
_ENV = Path(__file__).resolve().parents[1] / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)\s*$", line)
        if m:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")

DRYRUN = os.getenv("AUTOTRADE_DRYRUN", "1") == "1"
STAR_ONLY = os.getenv("AUTOTRADE_STAR_ONLY", "1") == "1"
WEBHOOK = os.getenv("AUTOTRADE_WEBHOOK")
MAX_OPEN = int(os.getenv("AUTOTRADE_MAX_OPEN", "8"))
SCAN_URL = os.getenv("AUTOTRADE_SCAN_URL",
                     "https://ai-stock-rosy-eight.vercel.app/api/crypto-scan?minVol=15&top=150&minQ=0")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
# 自動交易記到專屬資料庫(AUTOTRADE_NOTION_DB_ID),與手動日誌(NOTION_DB_ID)分開,統計不混
NOTION_DB_ID = os.getenv("AUTOTRADE_NOTION_DB_ID") or os.getenv("NOTION_DB_ID")
RISK = auto_trader.RISK_USD
MIN_STOP_PCT = float(os.getenv("AUTOTRADE_MIN_STOP", "0.3"))    # 停損太緊(針尖貼進場)會秒掃+部位爆大,跳過
MAX_NOTIONAL = float(os.getenv("AUTOTRADE_MAX_NOTIONAL", "1000"))  # 單筆名目上限,防一單過大
POLL_SEC = 60
# 冷卻只防「同一個觸發事件」被前後兩次輪詢重複吃到(觸發在名單上僅存活~1分鐘);
# 沒持倉+新訊號就該做,不用死等 30 分(GWEI 漏單教訓)。
COOLDOWN_SEC = int(os.getenv("AUTOTRADE_COOLDOWN_MIN", "5")) * 60
MAX_ADDS = int(os.getenv("AUTOTRADE_MAX_ADDS", "1"))   # 持倉中同向新★最多加倉次數(每段獨立5u風險)
LIQ_BUFFER_MULT = float(os.getenv("AUTOTRADE_LIQ_BUFFER_MULT", "1.5"))
LIQ_MARGIN_RETRIES = int(os.getenv("AUTOTRADE_LIQ_MARGIN_RETRIES", "3"))
STATE_FILE = Path(__file__).resolve().parents[1] / "auto_trades_state.json"
COOLDOWN_FILE = Path(__file__).resolve().parents[1] / "auto_trades_cooldown.json"


def load_cooldown() -> dict:
    if COOLDOWN_FILE.exists():
        try:
            return json.loads(COOLDOWN_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_cooldown(cd: dict) -> None:
    try:
        COOLDOWN_FILE.write_text(json.dumps(cd), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def prune_cooldown(cd: dict, now: float | None = None) -> None:
    """保留近期觸發事件即可;舊格式的 sym-only 冷卻也順手清掉。"""
    t = now or time.time()
    for key, ts in list(cd.items()):
        try:
            age = t - float(ts)
        except (TypeError, ValueError):
            age = COOLDOWN_SEC + 1
        if ":" not in key or age > max(COOLDOWN_SEC * 6, 3600):
            cd.pop(key, None)


def signal_event_key(row: dict, direction: str) -> str:
    """同一根 1m 觸發使用同一 key;新觸發即使同幣也不被舊冷卻擋住。"""
    sym = str(row.get("sym", "?"))
    trigger_ms = row.get("trigger_ms") or row.get("confirm_ms")
    if trigger_ms:
        event = str(trigger_ms)
    else:
        # 舊 API fallback:只用目前分鐘防同一輪重複;新版 API 會提供 trigger_ms。
        event = str(int(time.time() // 60))
    return f"{sym}:{direction}:{event}"


def cooldown_active(cooldown: dict, key: str, now: float | None = None) -> bool:
    try:
        return (now or time.time()) - float(cooldown.get(key, 0)) < COOLDOWN_SEC
    except (TypeError, ValueError):
        return False


def mark_cooldown(cooldown: dict, key: str, now: float | None = None) -> None:
    t = now or time.time()
    prune_cooldown(cooldown, t)
    cooldown[key] = t
    save_cooldown(cooldown)


def notify(msg: str) -> None:
    print(msg, flush=True)
    if WEBHOOK:
        try:
            data = json.dumps({"content": msg[:1900]}).encode()
            req = urllib.request.Request(WEBHOOK, data=data,
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": "Mozilla/5.0"})  # Discord 擋預設 Python UA
            urllib.request.urlopen(req, timeout=8)
        except Exception:  # noqa: BLE001
            pass


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_state(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_signals() -> list[dict]:
    """回傳觸發中的訊號(★,或 STAR_ONLY=0 時含◆)。502/504 等暫時性錯誤退避重試,失敗回空。"""
    for attempt in range(3):
        try:
            req = urllib.request.Request(SCAN_URL, headers={"User-Agent": "Mozilla/5.0"})
            rows = json.loads(urllib.request.urlopen(req, timeout=25).read()).get("rows", [])
            break
        except Exception:  # noqa: BLE001 Vercel 偶發 502 Bad Gateway/超時
            if attempt == 2:
                return []          # 這輪放棄,下一輪再掃(訊號會再出現,不致漏單)
            time.sleep(5 * (attempt + 1))
    out = []
    for r in rows:
        if not r.get("triggered"):
            continue
        if STAR_ONLY and r.get("tier") != "★":
            continue
        out.append(r)
    return out


def ensure_liq_buffer(sym: str, stop_frac: float, notional_hint: float) -> dict | None:
    """成交後用交易所實際持倉重驗強平距離;太近就補逐倉保證金再重抓。"""
    pos = tn.position(sym)
    if not pos:
        return None
    for _ in range(max(1, LIQ_MARGIN_RETRIES)):
        entry_real = float(pos["entryPrice"])
        liq = float(pos.get("liquidationPrice") or 0)
        if liq <= 0:
            return pos
        liq_dist = abs(entry_real - liq) / entry_real
        if liq_dist >= stop_frac * LIQ_BUFFER_MULT:
            return pos
        extra = max(notional_hint * stop_frac, RISK)
        try:
            tn.add_margin(sym, extra)
            notify(f"🛡 {sym} 強平{liq_dist*100:.1f}%太近(SL{stop_frac*100:.1f}%),已補保證金 {extra:.2f}u")
            time.sleep(0.7)
            pos = tn.position(sym) or pos
        except Exception as e:  # noqa: BLE001
            notify(f"⚠️ {sym} 補保證金失敗:{e}(強平{liq:g} 可能太近)")
            return pos
    return pos


def try_open(row: dict, state: dict, cooldown: dict) -> None:
    sym = row["sym"]
    direction = "short" if "做空" in row["tag"] else "long"
    event_key = signal_event_key(row, direction)
    now = time.time()
    if cooldown_active(cooldown, event_key, now):
        return
    adding = False
    if sym in state:                           # 持倉中又來訊號 → 同向可加倉,反向忽略
        t = state[sym]
        if t["direction"] != direction:
            notify(f"↔️ {sym} 持倉中出現反向新訊號,不翻倉、不加倉,交給原 SL/TP")
            mark_cooldown(cooldown, event_key, now)
            return
        if t.get("adds", 0) >= MAX_ADDS:
            mark_cooldown(cooldown, event_key, now)
            return
        if row.get("tier") != "★":             # 加倉只吃更強的 ★,◆只提示不加
            mark_cooldown(cooldown, event_key, now)
            return
        adding = True
    if not adding and len([k for k in state]) >= MAX_OPEN:
        return
    if not tn.has_symbol(sym):
        return  # 測試網沒這個幣
    if not DRYRUN and not adding:
        try:                                   # 交易所已有持倉(state 遺失/手動單)→ 絕不疊倉
            if tn.position(sym) is not None:
                print(f"  {sym} 交易所已有持倉但不在 state,跳過(避免疊倉)", flush=True)
                return
        except Exception:  # noqa: BLE001
            return                             # 查不到就這輪先不下,安全優先

    try:
        p = auto_trader.plan_trade(sym, direction)
    except Exception as e:  # noqa: BLE001
        print(f"  {sym} 計畫失敗:{e}", flush=True)
        return
    if not p["valid"]:
        return
    if p["stop_pct"] < MIN_STOP_PCT:
        print(f"  {sym} 停損 {p['stop_pct']}% 太緊(<{MIN_STOP_PCT}%,針尖貼進場會秒掃),跳過", flush=True)
        return
    if p["notional"] > MAX_NOTIONAL:
        print(f"  {sym} 名目 {p['notional']}u > 上限 {MAX_NOTIONAL}u,跳過", flush=True)
        return
    minnot = tn.filters(sym).get("minNotional", 0)
    if p["notional"] < max(minnot, 0):
        print(f"  {sym} 名目 {p['notional']}u < 最小 {minnot}u,跳過", flush=True)
        return
    if tn.round_qty(sym, p["qty"]) <= 0:       # 數量捨入後歸零(高價幣+大步進),下單必炸
        print(f"  {sym} 數量捨入後為 0,跳過", flush=True)
        return

    # ── 下單前精算強平價:用檔位表(MMR/cum)逐級降槓桿,直到 強平距離 ≥ 2×停損 ──
    long = direction == "long"
    stop_frac = p["stop_pct"] / 100
    lp = 0.0
    try:
        br = tn.bracket_for(sym, p["notional"])
        mmr, cum = float(br["maintMarginRatio"]), float(br["cum"])
        lev = min(p["leverage"], int(br.get("initialLeverage", p["leverage"])))
        while lev > 1:
            lp = tn.liq_price(p["entry"], p["qty"], p["notional"] / lev, mmr, cum, long)
            if abs(p["entry"] - lp) / p["entry"] >= 2 * stop_frac:
                break
            lev -= 1
        p["leverage"], p["margin"] = lev, round(p["notional"] / lev, 2)
    except Exception as e:  # noqa: BLE001 檔位表拿不到就用保守公式的槓桿
        print(f"  {sym} 強平精算失敗(用保守槓桿):{str(e)[:60]}", flush=True)

    head = "🔺做多" if direction == "long" else "🔻做空"
    tier = row.get("tier") or "◆"
    verb = "➕加倉" if adding else "🟢下單"
    line = (f"{'[乾跑]' if DRYRUN else verb} {tier} {sym} {head}｜進{p['entry']:g} TP{p['tp']:g} SL{p['sl']:g}"
            f"｜停損{p['stop_pct']}% 肉{p['tp_pct']}% RR{p['rr']}"
            f"｜名目{p['notional']}u×{p['leverage']}x 保證金{p['margin']}u"
            f"{f'｜強平{lp:g}' if lp else ''}")
    if DRYRUN:
        notify(line)
        mark_cooldown(cooldown, event_key)     # 乾跑也只冷卻同一觸發事件
        return

    try:
        if not adding:                          # 加倉沿用原槓桿/逐倉設定,只補數量
            tn.set_isolated(sym)
            tn.set_leverage(sym, p["leverage"])
        tn.market_entry(sym, p["side"], p["qty"])   # 只下市價進場;SL/TP 由盯盤市價平(測試網條件單受限)
    except Exception as e:  # noqa: BLE001
        notify(f"⚠️ {sym} {'加倉' if adding else '下單'}失敗:{e}")
        return

    # 成交後:①用「實際成交價」重錨 TP/SL(主網計畫價≠測試網成交價,不重錨會系統性偏移)
    # ②強平價實測(GRASS 教訓):強平必須比 SL 遠至少 50%,不夠就補逐倉保證金推遠
    entry_real, tp_real, sl_real = p["entry"], p["tp"], p["sl"]
    try:
        time.sleep(1)
        pos = ensure_liq_buffer(sym, stop_frac, p["notional"])
        if pos:
            entry_real = float(pos["entryPrice"])
            tp_frac = p["tp_pct"] / 100
            if long:
                tp_real, sl_real = entry_real * (1 + tp_frac), entry_real * (1 - stop_frac)
            else:
                tp_real, sl_real = entry_real * (1 - tp_frac), entry_real * (1 + stop_frac)
    except Exception:  # noqa: BLE001
        pass

    if adding:
        t = state[sym]
        t["adds"] = t.get("adds", 0) + 1
        t["risk"] = t.get("risk", RISK) + RISK          # 每段獨立 5u 風險,R=總損益÷總風險
        t["tp"], t["sl"] = tp_real, sl_real              # SL/TP 更新成最新訊號的實際成交結構
        t["stop_pct"] = p["stop_pct"]
        t["entry"] = entry_real                          # 交易所回的加權均價
        t.setdefault("segments", []).append({
            "entry": entry_real, "tp": tp_real, "sl": sl_real, "stop_pct": p["stop_pct"],
            "risk": RISK, "qty": p["qty"], "trigger_key": event_key, "opened_ms": int(time.time() * 1000),
        })
    else:
        state[sym] = {
            "direction": direction, "entry": entry_real, "tp": tp_real, "sl": sl_real,
            "stop_pct": p["stop_pct"], "open_ms": int(time.time() * 1000),
            "adds": 0, "risk": RISK,
            "segments": [{
                "entry": entry_real, "tp": tp_real, "sl": sl_real, "stop_pct": p["stop_pct"],
                "risk": RISK, "qty": p["qty"], "trigger_key": event_key, "opened_ms": int(time.time() * 1000),
            }],
        }
    save_state(state)
    mark_cooldown(cooldown, event_key)                   # 只防同一觸發事件被重複吃到
    notify(line)


def _record_close(sym: str, t: dict, state: dict, cooldown: dict, reason: str) -> None:
    try:
        pnl = tn.realized_pnl(sym, t["open_ms"] - 2000)
    except Exception:  # noqa: BLE001
        pnl = 0.0
    r = round(pnl / t.get("risk", RISK), 2)     # 有加倉時 R=總損益÷總風險(5u×段數)
    win = 1 if pnl > 0 else 0
    entry, tp = t["entry"], t["tp"]
    row = {
        "sym": sym.replace("USDT", ""), "direction": t["direction"], "entry_price": entry, "tp_price": tp,
        "sl_price": t["sl"], "stop_dist_pct": t["stop_pct"],
        "dist_ema12": round((entry / tp - 1) * 100, 2) if tp else None,
        "result_r": r, "win": win,
    }
    try:
        notion_journal.create_trade(NOTION_TOKEN, NOTION_DB_ID, row)
    except Exception as e:  # noqa: BLE001
        print(f"  {sym} 寫 Notion 失敗:{e}", flush=True)
    try:
        refresh = getattr(notion_journal, "refresh_stats_description", None)
        if callable(refresh):
            refresh(NOTION_TOKEN, NOTION_DB_ID)
    except Exception as e:  # noqa: BLE001
        print(f"  {sym} 更新 Notion 統計失敗:{e}", flush=True)
    notify(f"📓 平倉 {sym}（{reason}）｜{'✅賺' if win else '❌賠'} {r:+g}R（{pnl:+.2f}u）→ 已記 Notion")
    prune_cooldown(cooldown)
    save_cooldown(cooldown)                    # 只保留觸發事件冷卻;平倉不建立幣種死冷卻
    del state[sym]
    save_state(state)


def manage_positions(state: dict, cooldown: dict) -> None:
    """盯每個持倉:價格碰到 SL/TP 就市價平倉並記錄。"""
    for sym in list(state.keys()):
        t = state[sym]
        try:
            pos = tn.position(sym)
        except Exception:  # noqa: BLE001
            continue
        if pos is None:                       # 已被外部平掉 → 直接記錄
            _record_close(sym, t, state, cooldown, "外部平倉")
            continue
        try:
            price = tn.mark_price(sym)
        except Exception:  # noqa: BLE001
            continue
        long = t["direction"] == "long"
        hit_tp = price >= t["tp"] if long else price <= t["tp"]
        hit_sl = price <= t["sl"] if long else price >= t["sl"]
        if hit_tp or hit_sl:
            amt = abs(float(pos["positionAmt"]))
            close_side = "SELL" if long else "BUY"
            try:
                tn.market_entry(sym, close_side, amt)
            except Exception as e:  # noqa: BLE001
                notify(f"⚠️ {sym} 平倉失敗:{e}")
                continue
            time.sleep(1)
            _record_close(sym, t, state, cooldown, "TP" if hit_tp else "SL")


def main() -> None:
    if not (tn.KEY and tn.SECRET):
        raise SystemExit("缺 TESTNET_API_KEY / TESTNET_API_SECRET(放 backend/.env)")
    bal = tn.usdt_balance()
    mode = "乾跑(不下單)" if DRYRUN else "實單(測試網)"
    lvl = "只★放量" if STAR_ONLY else "★◆都做"
    notify(f"🤖 自動交易啟動｜模式={mode}｜{lvl}｜風險{RISK}u/單｜餘額{bal:.0f}u｜同時最多{MAX_OPEN}倉")
    state = load_state()
    cooldown: dict[str, float] = load_cooldown()
    last_scan = 0.0
    last_err = ""                                              # 同錯誤去重,不洗版
    while True:
        try:
            manage_positions(state, cooldown)                 # 每 15s 盯盤平倉
            if time.time() - last_scan >= POLL_SEC:            # 每 60s 掃新訊號
                last_scan = time.time()
                for row in fetch_signals():
                    try_open(row, state, cooldown)
            last_err = ""
        except Exception as e:  # noqa: BLE001
            msg = str(e)[:120]
            if msg != last_err:                                # 同一種錯只印一次
                print(f"迴圈錯誤(重試中):{msg}", flush=True)
                last_err = msg
        time.sleep(15)


if __name__ == "__main__":
    main()
