"""交易日誌 bot(獨立,零 Claude token)——在 Discord「交易日誌」頻道記做單。

你打:  !單 空 CHIP 進0.0381 tp0.0352 sl0.0402 20倍
它做:  正則解析 → 去 Binance 抓「訊號當時條件」(1h RSI、距15m EMA12、資費、OI)
        → 連同 進場/TP/SL/停損距離 一起寫進 Notion → 回一張確認卡片。
        全程不呼叫 Claude,所以常開 24/7 也不花 token。

結果(賺賠幾R、A/B型)之後你自己在手機 Notion 那列手動補。

環境變數(建議都放 backend/.env,bot 會自動讀):
  TRADELOG_BOT_TOKEN  — 這支 bot 自己的 Discord token(跟複盤 bot 不同支)
  NOTION_TOKEN, NOTION_DB_ID — 跟複盤 bot 共用同一個 Notion 資料庫
可選:
  TRADELOG_CHANNEL_ID — 只在這個頻道回應(不設=所有看得到的頻道)
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from pathlib import Path

import discord

import crypto_market
import notion_journal

# 讀 backend/.env,並「覆蓋」OS 既有值(.env 為準)——避免 OS 裡的殭屍舊金鑰
# (CLAUDE.md 已記載此陷阱:曾被已撤銷的 AIza 殭屍 GEMINI_API_KEY 蓋掉 .env 的 AQ 新金鑰)
_ENV = Path(__file__).resolve().parents[1] / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)\s*$", line)
        if m:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")

TOKEN = os.getenv("TRADELOG_BOT_TOKEN")
CHANNEL_ID = os.getenv("TRADELOG_CHANNEL_ID")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")
# 看圖用免費 Gemini(不是 Claude,不花錢);只有附圖時才呼叫
GEMINI_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
VISION_MODEL = os.getenv("JOURNAL_VISION_MODEL", "gemini-2.5-flash")

_COL_SHORT, _COL_LONG = 0xEF4444, 0x10B981
_HELP = (
    "**記一單(純文字)**:`!單 空 CHIP 進0.0381 tp0.0352 sl0.0402 20倍`\n"
    "**記一單(附圖讀價)**:打 `!單`(可只寫方向+幣)並**附一張倉位框截圖**,"
    "我用免費 Gemini 讀出 進場/TP/SL(不花 Claude 錢)。\n"
    "兩種都會自動補上當時 1h RSI / 距15m EMA12 / 資費 / OI 存進 Notion。\n"
    "結果(幾R、A/B型)之後在手機 Notion 那列手動補。看統計:`!週報`"
)

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


def _num(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def parse_order(text: str) -> dict | None:
    """把 `!單 ...` 白話解析成 row dict(不含快照)。缺方向或幣種回 None。"""
    direction = None
    if re.search(r"做空|放空|\b空\b|short", text, re.IGNORECASE) or text.strip().startswith("空"):
        direction = "short"
    elif re.search(r"做多|\b多\b|long", text, re.IGNORECASE) or text.strip().startswith("多"):
        direction = "long"
    # 幣種:第一個不是關鍵字的英數 token
    sym = None
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9]{1,11}", text):
        base = re.match(r"[A-Za-z]+", tok).group(0).lower()
        if base in ("tp", "sl", "short", "long", "x"):
            continue
        sym = tok.upper().replace("USDT", "")
        break
    entry = _num(r"(?:進場|進|entry)\s*([0-9]*\.?[0-9]+)", text)
    tp = _num(r"tp\s*([0-9]*\.?[0-9]+)", text)
    sl = _num(r"sl\s*([0-9]*\.?[0-9]+)", text)
    lev = _num(r"([0-9]+)\s*(?:倍|[xX])", text)
    # 一律回 dict(附圖時 sym/direction 可由 Gemini 補);缺什麼由呼叫端驗
    return {"sym": sym, "direction": direction,
            "entry_price": entry, "tp_price": tp, "sl_price": sl, "leverage": lev}


def _recompute_stop(row: dict) -> None:
    e, s = row.get("entry_price"), row.get("sl_price")
    if e and s and e > 0:
        row["stop_dist_pct"] = round(abs(e - s) / e * 100, 2)


def _sniff_media_type(raw: bytes) -> str:
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


_VISION_PROMPT = (
    "這是一張加密貨幣交易截圖,通常帶 TradingView 的多單/空單倉位工具(方框)。"
    "讀出這筆交易:sym(幣種代號,去USDT大寫)、direction(short=空/紅框往下、long=多/綠框往上)、"
    "entry_price(進場價)、tp_price(停利/目標那條)、sl_price(停損那條)。"
    '只輸出 JSON:{"sym":..,"direction":"short|long","entry_price":num,"tp_price":num,"sl_price":num}。'
    "看不到的欄位給 null;價格用純數字(去掉逗號)。"
)


def gemini_read_position(img_b64: str, mime: str) -> dict:
    """用免費 Gemini 視覺讀倉位框 → dict(sym/direction/entry/tp/sl)。失敗回 {}。"""
    if not GEMINI_KEY:
        return {}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{VISION_MODEL}:generateContent?key={GEMINI_KEY}")
    body = {
        "contents": [{"parts": [{"text": _VISION_PROMPT},
                                 {"inline_data": {"mime_type": mime, "data": img_b64}}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    resp = json.load(urllib.request.urlopen(req, timeout=30))
    txt = resp["candidates"][0]["content"]["parts"][0]["text"]
    v = json.loads(txt)
    out: dict = {}
    if v.get("sym"):
        out["sym"] = str(v["sym"]).upper().replace("USDT", "")
    if v.get("direction") in ("short", "long"):
        out["direction"] = v["direction"]
    for k in ("entry_price", "tp_price", "sl_price"):
        try:
            if v.get(k) is not None:
                out[k] = float(v[k])
        except (TypeError, ValueError):
            pass
    return out


def build_confirm_embed(row: dict, snap: dict, used_vision: bool = False) -> discord.Embed:
    short = row["direction"] == "short"
    color = _COL_SHORT if short else _COL_LONG
    e = discord.Embed(title=f"📓 已記錄 {row['sym']} {'🔻做空' if short else '🔺做多'}", color=color)
    plan = []
    if row.get("entry_price") is not None:
        plan.append(f"進 `{row['entry_price']:g}`")
    if row.get("tp_price") is not None:
        plan.append(f"TP `{row['tp_price']:g}`")
    if row.get("sl_price") is not None:
        plan.append(f"SL `{row['sl_price']:g}`")
    if row.get("leverage") is not None:
        plan.append(f"`{row['leverage']:g}x`")
    if row.get("stop_dist_pct") is not None:
        plan.append(f"停損 `{row['stop_dist_pct']:g}%`")
    e.description = "　·　".join(plan) if plan else "(未填進出場價)"

    gate = crypto_market.gate_text(snap, row["direction"])
    rsi_now, rsi_hi = snap.get("rsi_now"), snap.get("rsi_hi6")
    if rsi_now is not None:
        e.add_field(name="訊號1h RSI", value=f"現在 `{rsi_now:g}` / 近6高 `{rsi_hi:g}`\n{gate}", inline=True)
    if snap.get("dist_ema12") is not None:
        e.add_field(name="距15m EMA12", value=f"`{snap['dist_ema12']:+g}%`", inline=True)
    if snap.get("funding_pct") is not None:
        e.add_field(name="資費", value=f"`{snap['funding_pct']:+g}%`", inline=True)
    if snap.get("oi_state"):
        icon = "🔥" if snap["oi_state"] == "堆積" else "⚠️" if snap["oi_state"] == "消退" else ""
        e.add_field(name=f"OI {icon}".strip(), value=f"`{snap.get('oi_chg', 0):+g}%` {snap['oi_state']}", inline=True)
    src = "🔎 進出場價由圖片辨識(Gemini) · " if used_vision else ""
    e.set_footer(text=src + "結果R / 賺賠 / A-B型 → 到手機 Notion 那列手動補")
    return e


@bot.event
async def on_ready():
    nz = "OK" if (NOTION_TOKEN and NOTION_DB_ID) else "未設定(!單 會失敗)"
    print(f"✓ 交易日誌 bot 上線:{bot.user}  Notion={nz}", flush=True)


@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return
    if CHANNEL_ID and str(msg.channel.id) != str(CHANNEL_ID):
        return
    cmd = (msg.content or "").strip()

    if cmd in ("!週報", "!stats", "!報表"):
        try:
            import trade_journal
            report = trade_journal.build_report(notion_journal.query_trades(NOTION_TOKEN, NOTION_DB_ID))
        except Exception as e:  # noqa: BLE001
            report = f"讀取失敗:{e}"
        await msg.reply(report)
        return

    if cmd.startswith("!單") or cmd.lower().startswith("!order"):
        body = re.sub(r"^!單|^!order", "", cmd, flags=re.IGNORECASE).strip()
        imgs = [a for a in msg.attachments if (a.content_type or "").startswith("image")][:1]
        if not body and not imgs:
            await msg.reply(_HELP)
            return
        if not (NOTION_TOKEN and NOTION_DB_ID):
            await msg.reply("⚠️ 還沒設定 NOTION_TOKEN / NOTION_DB_ID,無法寫入。")
            return
        try:
            async with msg.channel.typing():
                row = parse_order(body)          # 純文字先填(免費)
                used_vision = False
                if imgs:
                    if not GEMINI_KEY:
                        await msg.reply("⚠️ 附圖讀價需要 GEMINI_API_KEY(放 backend/.env)。這次先用文字。")
                    else:
                        raw = await imgs[0].read()
                        v = gemini_read_position(base64.standard_b64encode(raw).decode(),
                                                 _sniff_media_type(raw))  # 免費 Gemini 看圖
                        for k in ("sym", "direction", "entry_price", "tp_price", "sl_price"):
                            if not row.get(k) and v.get(k) is not None:   # 文字優先,圖補缺
                                row[k] = v[k]
                        used_vision = bool(v)
                _recompute_stop(row)
                if not row.get("sym") or not row.get("direction"):
                    await msg.reply("⚠️ 沒讀到幣種或方向。附清楚的倉位框截圖,或文字補,例:`!單 空 CHIP` 再附圖讀價。")
                    return
                snap = crypto_market.snapshot(row["sym"])            # 抓訊號當時條件(Binance 免費)
                row.update({k: snap[k] for k in ("rsi_now", "rsi_hi6", "dist_ema12",
                            "funding_pct", "oi_state", "oi_chg") if k in snap})
                row["rsi_1h"] = snap.get("rsi_now")                  # 對應 Notion「1h RSI」欄
                notion_journal.create_trade(NOTION_TOKEN, NOTION_DB_ID, row)
                await msg.reply(embed=build_confirm_embed(row, snap, used_vision))
        except Exception as e:  # noqa: BLE001
            await msg.reply(f"記錄失敗:{e}")
        return


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("缺 TRADELOG_BOT_TOKEN。到 Discord 開第二個 bot 拿 token,放進 backend/.env。")
    bot.run(TOKEN)
