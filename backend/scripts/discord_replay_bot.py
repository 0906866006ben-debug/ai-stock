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

# 從 backend/.env 載入 ANTHROPIC_API_KEY(不覆蓋既有 OS 環境變數)
_ENV = Path(__file__).resolve().parents[1] / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)\s*$", line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MODEL = os.getenv("BOT_AI_MODEL", "claude-sonnet-5")
CHANNEL_ID = os.getenv("BOT_CHANNEL_ID")
ai = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── 訊號自動推播設定 ──
SIGNAL_CHANNEL_ID = int(os.getenv("SIGNAL_CHANNEL_ID", "1523771234230337657"))
# minQ=0:只用 1h RSI 75/25 跳觀察名單;15m EMA12/資費/OI 只作參考與排序。
SCAN_URL = os.getenv("SCAN_URL", "https://ai-stock-rosy-eight.vercel.app/api/crypto-scan?minVol=15&top=150&minQ=0")
SIGNAL_SIDE = os.getenv("SIGNAL_SIDE", "both")        # both / short / long
COOLDOWN_MIN = int(os.getenv("SIGNAL_COOLDOWN_MIN", "30"))
_setup_alert: dict[str, float] = {}                   # sym -> 上次「👀超買超賣觀察」推播時間
_trig_alert: dict[str, float] = {}                    # sym -> 上次「1m EMA12 觸發觀察」推播時間

SYSTEM = """你是加密永續交易複盤助手。使用者鐵則:設定看1hr RSI-14超買≥75/超賣≤25(鐵門檻,沒到不做);多空鏡像=超買做空/超賣做多;資費只作順風/逆風參考不是跳訊號門檻;觸發=1分一大根整根實體收破EMA12(非收針,均值回歸不強求放量);目標=拉回15m EMA12(目標參考,不是篩選條件);背離只是注意不是扳機;逆勢/搶跑是死因;出場=吃反轉那根就走或保本續抱。

若給了多張圖=同一單的不同時間框架:大週期(1h)判「設定/方向/超買超賣」、小週期(1m/15m)判「觸發那根合不合格」,綜合後給一個結論,不要每張圖各講一段。

看圖後用繁中輸出**極精簡**複盤,總共不超過 6 行,格式:
方向/結果:(做多或做空、賺或賠)
進場:(合不合格?有沒有一大根實體破1m EMA12,還是搶跑)
趨勢:(均線多頭還空頭、順勢還逆勢)
問題:(這單最關鍵的一個錯,一句話)
教訓:(一句)
不要分段標題、不要客套、不要逐項列數字。若圖資訊不足就一句帶過。結尾不用免責聲明。"""

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


def fetch_klines_note(text: str) -> str:
    """若複盤文字提到某 Binance 幣種,附一句即時參考(盡力,不強求)。"""
    m = re.search(r"\b([A-Z0-9]{2,12})\s*/?\s*USDT\b", text)
    if not m:
        return ""
    sym = m.group(1) + "USDT"
    try:
        req = urllib.request.Request(
            f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}",
            headers={"User-Agent": "Mozilla/5.0"})
        d = json.load(urllib.request.urlopen(req, timeout=8))
        fr = float(d.get("lastFundingRate", 0)) * 100
        return f"\n\n📊 {sym} 目前資費 {fr:+.4f}%(即時參考)"
    except Exception:
        return ""


def _row_num(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def _target_text(dist_pct: float) -> str:
    if dist_pct > 0:
        position = "現價在上方"
    elif dist_pct < 0:
        position = "現價在下方"
    else:
        position = "貼近"
    return f"15m EMA12距離{abs(dist_pct):.1f}%({position})"


def build_signal_message(row: dict[str, Any]) -> tuple[str, bool]:
    """Build Discord signal-channel copy aligned with the crypto scan contract.

    Returns the message and whether the row is short-side observation.
    """
    tag = str(row.get("tag", ""))
    sym = str(row.get("sym", "?"))
    rsi = round(_row_num(row, "rsi"))
    is_short = "做空" in tag or rsi >= 75
    triggered = bool(row.get("triggered"))
    side = "空向" if is_short else "多向"
    setup = f"1h RSI{rsi} {'超買≥75' if is_short else '超賣≤25'}"
    action = "跌破" if is_short else "突破"
    target = _target_text(_row_num(row, "dist_e12"))
    fr_pct = round(_row_num(row, "fr_pct"))
    oi_state = str(row.get("oi_state", "OI?"))
    quality = round(_row_num(row, "quality"))
    price = _row_num(row, "price")

    if triggered:
        tier = str(row.get("tier") or "◆")
        head = "🔻 1m EMA12跌破觀察" if is_short else "🔺 1m EMA12突破觀察"
        body_x = _row_num(row, "trig_body")
        vol_x = _row_num(row, "trig_vol")
        msg = (
            f"**{tier} {head}  {sym}**\n"
            f"設定:{setup} → {side}觀察\n"
            f"扳機:1m整根實體{action}EMA12+守住 · 實體{body_x:.1f}x/量{vol_x:.1f}x\n"
            f"目標參考:{target} · 資費分位{fr_pct}%/{oi_state}/品質{quality} · 價{price:g}"
        )
    else:
        head = "👀 超買觀察·空向" if is_short else "👀 超賣觀察·多向"
        msg = (
            f"**{head}  {sym}**\n"
            f"設定:{setup} → 先進觀察名單\n"
            f"等待:1m EMA12{action}+守住,尚未觸發\n"
            f"目標參考:{target} · 資費分位{fr_pct}%/{oi_state}/品質{quality} · 價{price:g}"
        )
    return msg, is_short


async def signal_loop():
    """每分鐘打掃描 API,發現新的 ★ 觸發就推到訊號頻道(同幣冷卻,不洗版)。
    不用 Anthropic token(只讀 Binance 免費資料)。"""
    await bot.wait_until_ready()
    ch = bot.get_channel(SIGNAL_CHANNEL_ID)
    if ch is None:
        print(f"⚠ 找不到訊號頻道 {SIGNAL_CHANNEL_ID}(bot 沒進那個群/沒權限?),訊號推播略過", flush=True)
        return
    print(f"🟢 訊號推播啟動 → #{getattr(ch, 'name', SIGNAL_CHANNEL_ID)}"
          f"(每60s掃、1h超買超賣觀察+1m EMA12觸發、同幣冷卻{COOLDOWN_MIN}分)", flush=True)
    while not bot.is_closed():
        try:
            req = urllib.request.Request(SCAN_URL, headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            rows = data.get("rows", [])   # 每列都已過 1h RSI 75/25 鐵門檻
            now = time.time()
            for r in rows:
                if not isinstance(r, dict):
                    continue
                msg, is_short = build_signal_message(r)
                if SIGNAL_SIDE == "short" and not is_short:
                    continue
                if SIGNAL_SIDE == "long" and is_short:
                    continue
                sym = str(r.get("sym", "?"))
                if r.get("triggered"):
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
                await ch.send(msg)
        except Exception as e:  # noqa: BLE001 網路波動不中斷
            print(f"訊號掃描失敗:{e}", flush=True)
        await asyncio.sleep(60)


@bot.event
async def on_ready():
    print(f"✓ Bot 上線:{bot.user}  模型={MODEL}", flush=True)
    if not getattr(bot, "_signal_started", False):
        bot._signal_started = True  # type: ignore[attr-defined]
        bot.loop.create_task(signal_loop())


@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return
    if CHANNEL_ID and str(msg.channel.id) != str(CHANNEL_ID):
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
