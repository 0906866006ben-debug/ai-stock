"""Discord 交易複盤 bot — 你在群組貼交易圖,它用 Claude(能看圖)自動複盤。

複盤邏輯 = 使用者的策略鐵則(多空同一套:超買超賣 + 放量實體破 EMA20 + 資費;
設定看15m、觸發看1m一大根放量實體破線、非收針;背離只是注意不是扳機;
出場目標要跟進場框架匹配)。若能從圖辨識幣種,另抓 Binance 真實 K 線佐證。

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

import base64
import json
import os
import re
import urllib.request
from pathlib import Path

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

SYSTEM = """你是使用者的加密永續交易「複盤助手」。使用者的策略鐵則(據此評判每一單):
- 多空同一套鏡像:超買/超賣 + 放量突破/跌破 EMA20 + 資費(人群擁擠方向:做空要資費正=多單擠,做多要資費負=空單擠)。
- 觸發定義(可以做單的那一刻):1分K「一大根」(實體明顯大於近20根均實體)+ 放量(量明顯大於均量)+ 「實體」收破 EMA20(收盤在K棒下/上部,不是下影線刺破又收回的「收針」)。
- 設定看較大週期(15m)的超買超賣+資費+擁擠;觸發看1分放量實體破 EMA20。
- MACD/RSI 背離只是「注意」訊號,不是進場扳機。強勢趨勢裡背離常會再延伸一大段(超買可以更超買),憑背離逆勢進場是常見死因。
- 出場目標要跟「進場的時間框架」匹配:用1m/15m訊號進場,就別把停利放到1h級距離(=貪心,常在到達前先被掃損)。

任務:分析使用者貼的這張交易截圖,輸出繁體中文複盤,結構:
1. 【我看到什麼】幣種、方向、進場/停損/目標/風報比/結果(盡量從圖上的持倉工具與數字讀出來)。
2. 【趨勢背景】均線排列(EMA20/50/100/200)是多頭還空頭、價格在均線上或下。
3. 【成敗真正原因】對照上面鐵則,這單為什麼賺/賠;特別指出「進場那根 K 是否真的符合『一大根放量實體破 EMA20』」還是搶跑(憑背離/憑感覺)。
4. 【哪條鐵則沒守好 / 守得好】。
5. 【一句話教訓】。
語氣直白、專業、保守、不迎合。若圖上資訊不足就明說。結尾一行:本複盤為觀察分析,非投資建議。"""

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


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


@bot.event
async def on_ready():
    print(f"✓ Bot 上線:{bot.user}  模型={MODEL}", flush=True)


@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return
    if CHANNEL_ID and str(msg.channel.id) != str(CHANNEL_ID):
        return
    imgs = [a for a in msg.attachments if (a.content_type or "").startswith("image")]
    if not imgs:
        return
    a = imgs[0]
    _ok = ("image/png", "image/jpeg", "image/gif", "image/webp")
    media_type = a.content_type if a.content_type in _ok else "image/png"
    try:
        async with msg.channel.typing():
            raw = await a.read()
            b64 = base64.standard_b64encode(raw).decode()
            resp = ai.messages.create(
                model=MODEL, max_tokens=1400, system=SYSTEM,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": (msg.content or "這單複盤")},
                ]}])
            text = resp.content[0].text + fetch_klines_note(resp.content[0].text)
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
