"""Discord 交易複盤 bot — 你在群組貼交易圖,它用 Claude(能看圖)自動複盤。

複盤邏輯 = 使用者的策略鐵則(多空同一套:1h 超買超賣 + 1m 實體破 EMA12;
15m EMA12 是目標參考,不是訊號篩選條件;背離只是注意不是扳機)。
若能從圖辨識幣種,另抓 Binance 真實 K 線佐證。

需要環境變數:
  DISCORD_BOT_TOKEN  — Discord 開發者頁面拿的 bot token
  ANTHROPIC_API_KEY  — 從 backend/.env 自動載入(用 Claude 看圖)
可選:
  BOT_AI_MODEL       — 預設 claude-sonnet-5
  BOT_CHANNEL_ID     — 只在此頻道回覆(不設=所有看得到的頻道)

跑:
  set DISCORD_BOT_TOKEN=你的token
  .venv/Scripts/python.exe backend/scripts/discord_replay_bot.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

import discord
from anthropic import Anthropic

import trade_journal   # 同目錄;bot 以 script 執行時 sys.path[0]=backend/scripts
import notion_journal  # Notion 後端(設了 NOTION_TOKEN+NOTION_DB_ID 才啟用)

# 從 backend/.env 載入 ANTHROPIC_API_KEY(不覆蓋既有 OS 環境變數)
_ENV = Path(__file__).resolve().parents[1] / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)\s*$", line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MODEL = os.getenv("BOT_AI_MODEL", "claude-sonnet-5")
JOURNAL_MODEL = os.getenv("JOURNAL_AI_MODEL", "claude-haiku-4-5-20251001")  # !log 解析用便宜模型
CHANNEL_ID = os.getenv("BOT_CHANNEL_ID")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")
USE_NOTION = bool(NOTION_TOKEN and NOTION_DB_ID)   # 兩個都設才走 Notion,否則本機 SQLite
ai = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── 訊號自動推播設定 ──
SIGNAL_CHANNEL_ID = int(os.getenv("SIGNAL_CHANNEL_ID", "1523771234230337657"))
# minQ=0:只用 1h RSI 75/25 跳觀察名單;15m EMA12/資費/OI 只作參考與排序。
SCAN_URL = os.getenv("SCAN_URL", "https://ai-stock-rosy-eight.vercel.app/api/crypto-scan?minVol=15&top=150&minQ=0")
SIGNAL_SIDE = os.getenv("SIGNAL_SIDE", "both")        # both / short / long
# 推播門檻:star=只推★放量觸發(預設) / trigger=★+◆觸發(含無量) / all=再加👀觀察
SIGNAL_LEVEL = os.getenv("SIGNAL_LEVEL", "star").lower()
COOLDOWN_MIN = int(os.getenv("SIGNAL_COOLDOWN_MIN", "30"))
_setup_alert: dict[str, float] = {}                   # sym -> 上次「👀超買超賣觀察」推播時間
_trig_alert: dict[str, float] = {}                    # sym -> 上次「1m EMA12 觸發觀察」推播時間

SYSTEM = """你是加密永續交易複盤助手。使用者鐵則:設定看1hr RSI-14超買≥75/超賣≤25(鐵門檻,沒到不做);多空鏡像=超買做空/超賣做多;資費只作順風/逆風參考不是跳訊號門檻;觸發=1分一大根整根實體收破EMA12(非收針,均值回歸不強求放量);目標=拉回15m EMA12(目標參考,不是篩選條件);背離只是注意不是扳機;逆勢/搶跑是死因;出場=吃反轉那根就走或保本續抱。

【重要·別誤判】1h RSI 超買/超賣門檻是「掃描器」在出訊號前就驗證過的。使用者常常只貼 1m 圖。**只給 1m 圖、看不到 1h,絕不能因此說「無法確認門檻」或暗示搶跑**;若使用者說「根據訊號/信號」進場,就當 1h 門檻已滿足。系統會在你回覆後附上該幣「真實 1h RSI」供對照——看不到 1h 時語氣中性,只評執行面(觸發那根合不合格、出場),不要無中生有挑毛病。這單若賺且執行合格,就明講它對。

若給了多張圖=同一單的不同時間框架:大週期判設定、小週期判觸發,綜合一個結論,不要每張圖各講一段。

看圖後用繁中輸出**極精簡**複盤。**第一行一定是「幣種:<代號>」**(從圖上讀,如 CHIP),接著最多 5 行:
方向/結果:(做多或做空、賺或賠)
進場:(觸發合不合格?有沒有一大根實體破1m EMA12)
趨勢:(順勢還逆勢)
問題:(最關鍵一個;沒有就寫「執行合格,無明顯錯誤」)
教訓:(一句)
不要客套、不要逐項列數字、結尾不用免責聲明。"""

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


def _sniff_media_type(raw: bytes) -> str:
    """從圖檔 magic bytes 判真實格式(Discord 的 content_type 常標錯)。"""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:4] == b"GIF8":
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _rsi14(closes: list[float]) -> list[float]:
    """Wilder RSI-14 序列(暖機後)。closes 至少 15 根。"""
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


def fetch_klines_note(text: str) -> str:
    """從複盤文字認出幣種,附上真實 1h RSI-14 + 資費,替 bot 補上它看不到的 1h 佐證。"""
    m = re.search(r"幣種[:：]\s*([A-Za-z0-9]{2,12})", text) or \
        re.search(r"\b([A-Z0-9]{2,12})\s*/?\s*USDT\b", text)
    if not m:
        return ""
    sym = m.group(1).upper().replace("USDT", "") + "USDT"
    note = f"\n\n📊 {sym}"
    try:  # 1h RSI(bot 看不到的門檻佐證)
        req = urllib.request.Request(
            f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&limit=120",
            headers={"User-Agent": "Mozilla/5.0"})
        kl = json.load(urllib.request.urlopen(req, timeout=8))
        rsis = _rsi14([float(c[4]) for c in kl])
        if rsis:
            cur = rsis[-1]
            last6 = rsis[-6:]
            hi, lo = max(last6), min(last6)
            gate = "超買✓門檻符合" if hi >= 75 else "超賣✓門檻符合" if lo <= 25 else "未達75/25門檻"
            note += f" 1h RSI 現在{cur:.0f}(近6根 {lo:.0f}~{hi:.0f},{gate})"
    except Exception:
        pass
    try:  # 資費
        req = urllib.request.Request(
            f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}",
            headers={"User-Agent": "Mozilla/5.0"})
        d = json.load(urllib.request.urlopen(req, timeout=8))
        note += f" · 資費 {float(d.get('lastFundingRate', 0)) * 100:+.4f}%"
    except Exception:
        pass
    return note if note.strip() != f"📊 {sym}" else ""


def _row_num(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


_COL_SHORT = 0xEF4444   # 做空=紅
_COL_LONG = 0x10B981    # 做多=綠


def _fmt_price(price: float) -> str:
    if price >= 1:
        return f"{price:.3f}"
    return f"{price:.6g}"


def build_signal_embed(row: dict[str, Any]) -> tuple["discord.Embed", bool]:
    """把一列掃描結果做成 Discord embed(彩色側條卡片,比純文字好讀)。

    回傳 (embed, is_short)。紅=做空、綠=做多;標題 emoji 帶狀態(👀觀察 / ◆◇ 訊號)。
    """
    tag = str(row.get("tag", ""))
    sym = str(row.get("sym", "?")).replace("USDT", "")
    rsi = round(_row_num(row, "rsi"))
    is_short = "做空" in tag or rsi >= 75
    triggered = bool(row.get("triggered"))
    tier = str(row.get("tier") or "◆")
    dist = _row_num(row, "dist_e12")
    ext_z = _row_num(row, "ext_z")
    fr_pct = round(_row_num(row, "fr_pct"))
    oi_state = str(row.get("oi_state", "中性"))
    oi_chg = _row_num(row, "oi_chg")
    quality = round(_row_num(row, "quality"))
    price = _row_num(row, "price")

    dir_word = "做空" if is_short else "做多"
    color = _COL_SHORT if is_short else _COL_LONG
    arrow = "↓" if is_short else "↑"
    break_word = "跌破" if is_short else "突破"
    oi_icon = "🔥" if oi_state == "堆積" else "⚠️" if oi_state == "消退" else ""

    if triggered:
        emoji = "★" if tier == "★" else "◆"
        vol_word = "放量" if tier == "★" else "無量"
        title = f"{emoji} {sym} · {dir_word}訊號 · {vol_word}"
        body_x = _row_num(row, "trig_body")
        vol_x = _row_num(row, "trig_vol")
        desc = (f"⚡ **1m 整根實體{break_word} EMA12 + 守住**\n"
                f"實體 `{body_x:.1f}x` · 量 `{vol_x:.1f}x`")
    else:
        title = f"👀 {sym} · {dir_word}觀察"
        gate = "超買 ≥75" if is_short else "超賣 ≤25"
        desc = f"1h RSI **{rsi}**（{gate}）· 等 1m EMA12 {break_word} + 守住"

    e = discord.Embed(title=title, description=desc, color=color)
    e.add_field(name="🎯 距15m EMA12目標", value=f"**{arrow} {abs(dist):.1f}%**", inline=True)
    e.add_field(name="1h RSI", value=f"`{rsi}`", inline=True)
    e.add_field(name="偏離z", value=f"`{ext_z:+.1f}`", inline=True)
    e.add_field(name="資費分位", value=f"`{fr_pct}%`", inline=True)
    e.add_field(name=f"OI {oi_icon}".strip(), value=f"`{oi_chg:+.1f}%`", inline=True)
    e.add_field(name="品質(排序)", value=f"`{quality}`", inline=True)
    e.set_footer(text=f"價 {_fmt_price(price)}　·　觀察輔助,非投資建議")
    return e, is_short


async def signal_loop():
    """每分鐘打掃描 API,發現新的 ★ 觸發就推到訊號頻道(同幣冷卻,不洗版)。
    不用 Anthropic token(只讀 Binance 免費資料)。"""
    await bot.wait_until_ready()
    ch = bot.get_channel(SIGNAL_CHANNEL_ID)
    if ch is None:
        print(f"⚠ 找不到訊號頻道 {SIGNAL_CHANNEL_ID}(bot 沒進那個群/沒權限?),訊號推播略過", flush=True)
        return
    level_txt = {"star": "只推★放量觸發", "trigger": "★+◆觸發(含無量)",
                 "all": "★+◆觸發+👀觀察"}.get(SIGNAL_LEVEL, SIGNAL_LEVEL)
    print(f"🟢 訊號推播啟動 → #{getattr(ch, 'name', SIGNAL_CHANNEL_ID)}"
          f"(每60s掃、{level_txt}、同幣冷卻{COOLDOWN_MIN}分)", flush=True)
    while not bot.is_closed():
        try:
            req = urllib.request.Request(SCAN_URL, headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            rows = data.get("rows", [])   # 每列都已過 1h RSI 75/25 鐵門檻
            now = time.time()
            for r in rows:
                if not isinstance(r, dict):
                    continue
                embed, is_short = build_signal_embed(r)
                if SIGNAL_SIDE == "short" and not is_short:
                    continue
                if SIGNAL_SIDE == "long" and is_short:
                    continue
                # 推播門檻:預設只推 ★(放量觸發),靜音 ◆無量與 👀觀察
                triggered = bool(r.get("triggered"))
                is_star = triggered and r.get("tier") == "★"
                if SIGNAL_LEVEL == "star" and not is_star:
                    continue
                if SIGNAL_LEVEL == "trigger" and not triggered:
                    continue
                sym = str(r.get("sym", "?"))
                if triggered:
                    # ★/◆ 1m 整根實體收破 EMA12 = 觸發觀察(較強)
                    if now - _trig_alert.get(sym, 0) < COOLDOWN_MIN * 60:
                        continue
                    _trig_alert[sym] = now
                    _setup_alert[sym] = now   # 觸發也算一次設定,避免緊接著又推觀察
                else:
                    # 👀 只是 1h 超買/超賣設定,還沒 1m EMA12 收破 → 提醒去盯 1m
                    if now - _setup_alert.get(sym, 0) < COOLDOWN_MIN * 60:
                        continue
                    _setup_alert[sym] = now
                await ch.send(embed=embed)
        except Exception as e:  # noqa: BLE001 網路波動不中斷
            print(f"訊號掃描失敗:{e}", flush=True)
        await asyncio.sleep(60)


@bot.event
async def on_ready():
    trade_journal.init_db()
    jbackend = "Notion" if USE_NOTION else f"SQLite({trade_journal.DB_PATH.name})"
    print(f"✓ Bot 上線:{bot.user}  模型={MODEL}  日誌後端={jbackend}", flush=True)
    if not getattr(bot, "_signal_started", False):
        bot._signal_started = True  # type: ignore[attr-defined]
        bot.loop.create_task(signal_loop())


async def handle_log(msg: discord.Message, text: str) -> None:
    """!log <白話> → Claude 解析成結構化欄位存進交易日誌。"""
    if not text:
        await msg.reply(
            "用法:`!log <白話描述>`\n"
            "例:`!log 空TAC 有等觸發 rsi87 距離21% 停損3% 20倍 賠1R 停損後有回目標 吃反轉前被清`\n"
            "關鍵字盡量帶:方向 / 有沒有等觸發 / 賺賠幾R / **賠單:停損後有沒有回目標** / 停損% / 槓桿\n"
            "看統計:`!週報`")
        return
    try:
        async with msg.channel.typing():
            resp = ai.messages.create(
                model=JOURNAL_MODEL, max_tokens=400,
                system=trade_journal.EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": text}],
            )
            raw = "".join(getattr(b, "text", "") for b in resp.content
                          if getattr(b, "type", None) == "text").strip()
            if raw.startswith("```"):                       # 去掉可能的程式碼圍欄
                raw = raw.strip("`")
                raw = raw[4:].strip() if raw.lower().startswith("json") else raw.strip()
            data = json.loads(raw)
            row = trade_journal.coerce(data)
            if USE_NOTION:
                notion_journal.create_trade(NOTION_TOKEN, NOTION_DB_ID, row)
                await msg.reply(trade_journal.confirm_line(row, 0).replace("已記 #0", "已記入 Notion"))
            else:
                tid = trade_journal.insert_trade(row, text)
                await msg.reply(trade_journal.confirm_line(row, tid))
    except json.JSONDecodeError:
        await msg.reply("⚠️ 沒解析成功,換個講法再試,把方向/賺賠幾R/有沒有等觸發/停損後有無回目標講清楚。")
    except Exception as e:  # noqa: BLE001
        await msg.reply(f"記錄失敗:{e}")


@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return
    if CHANNEL_ID and str(msg.channel.id) != str(CHANNEL_ID):
        return

    # ── 文字指令:交易日誌 ──
    cmd = (msg.content or "").strip()
    if cmd.startswith("!log"):
        await handle_log(msg, cmd[4:].strip())
        return
    if cmd in ("!週報", "!週報表", "!stats", "!report", "!報表"):
        try:
            if USE_NOTION:
                report = trade_journal.build_report(notion_journal.query_trades(NOTION_TOKEN, NOTION_DB_ID))
            else:
                report = trade_journal.weekly_report()
        except Exception as e:  # noqa: BLE001
            report = f"讀取日誌失敗:{e}"
        await msg.reply(report)
        return

    imgs = [a for a in msg.attachments if (a.content_type or "").startswith("image")][:6]  # 一次最多 6 張
    if not imgs:
        return
    try:
        async with msg.channel.typing():
            # 讀所有圖 → 多個 image 區塊(多時間框架綜合判讀)
            content: list = []
            for idx, a in enumerate(imgs):
                raw = await a.read()
                media_type = _sniff_media_type(raw)  # 從位元組判真實格式,不信 Discord 標的
                b64 = base64.standard_b64encode(raw).decode()
                if len(imgs) > 1:
                    content.append({"type": "text", "text": f"[圖{idx + 1}/{len(imgs)}]"})
                content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
            hint = "這單複盤,精簡" if len(imgs) == 1 else \
                f"這是同一單的 {len(imgs)} 個時間框架,綜合判讀後精簡複盤"
            content.append({"type": "text", "text": (msg.content or hint)})
            kwargs = dict(
                model=MODEL, max_tokens=1200, system=SYSTEM,
                messages=[{"role": "user", "content": content}],
            )
            if "opus" in MODEL or "sonnet-5" in MODEL:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024}  # 思考預算下限,省錢
            try:
                resp = ai.messages.create(**kwargs)
            except Exception:
                kwargs.pop("thinking", None)  # 該模型不支援 thinking 參數就拿掉重試
                resp = ai.messages.create(**kwargs)
            # Claude 可能先回 thinking 區塊,取所有 text 區塊(不能假設 content[0])
            answer = "".join(getattr(b, "text", "") for b in resp.content
                             if getattr(b, "type", None) == "text").strip()
            if not answer:
                answer = "（模型未回傳文字內容,請再試一次)"
            text = answer + fetch_klines_note(answer)
    except Exception as e:  # noqa: BLE001
        text = f"複盤失敗:{e}"
    # Discord 單則 2000 字上限 → 分段
    first = True
    for i in range(0, len(text), 1900):
        chunk = text[i:i + 1900]
        if first:
            await msg.reply(chunk); first = False
        else:
            await msg.channel.send(chunk)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("缺 DISCORD_BOT_TOKEN。先 set DISCORD_BOT_TOKEN=你的token 再跑。")
    bot.run(TOKEN)
