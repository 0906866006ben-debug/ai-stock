"""Telegram bot integration: SQLite watchlist + webhook handler."""
import os
import sqlite3
import asyncio
import httpx
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "telegram_watchlist.db"
TELEGRAM_API = "https://api.telegram.org"


# ── Database ──────────────────────────────────────────────────────────────────

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                chat_id TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, stock_code)
            )
        """)
        conn.commit()


def db_add(chat_id: str, stock_code: str, stock_name: str | None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (chat_id, stock_code, stock_name) VALUES (?,?,?)",
            (chat_id, stock_code.upper(), stock_name),
        )
        conn.commit()


def db_remove(chat_id: str, stock_code: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM watchlist WHERE chat_id=? AND stock_code=?",
            (chat_id, stock_code.upper()),
        )
        conn.commit()


def db_list(chat_id: str) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT stock_code, stock_name FROM watchlist WHERE chat_id=? ORDER BY created_at",
            (chat_id,),
        ).fetchall()
    return [{"stock_code": r[0], "stock_name": r[1]} for r in rows]


# ── Sync from web UI ──────────────────────────────────────────────────────────

# Shared watchlist chat id for web-UI-initiated syncs (optional)
_WEB_CHAT_ID = os.getenv("TELEGRAM_WEB_CHAT_ID", "web_ui")


def sync_watchlist(action: str, stock_code: str, stock_name: str | None) -> dict:
    """Called by the web UI to keep a common watchlist in sync."""
    init_db()
    code = stock_code.strip().upper()
    if action == "add":
        db_add(_WEB_CHAT_ID, code, stock_name)
        return {"status": "ok", "message": f"已加入自選: {code}"}
    elif action == "remove":
        db_remove(_WEB_CHAT_ID, code)
        return {"status": "ok", "message": f"已移除自選: {code}"}
    return {"status": "error", "message": "action 必須為 add 或 remove"}


# ── Telegram messaging ────────────────────────────────────────────────────────

async def _send(chat_id: str, text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    except Exception:
        pass


def _chunk(text: str, size: int = 4096) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


async def send_chunks(chat_id: str, text: str) -> None:
    for chunk in _chunk(text):
        await _send(chat_id, chunk)
        await asyncio.sleep(0.3)


# ── Command handler ───────────────────────────────────────────────────────────

_HELP = (
    "📊 <b>股票助理指令</b>\n\n"
    "/add 2330 — 加入自選\n"
    "/remove 2330 — 移除自選\n"
    "/list — 查看自選清單\n"
    "/report — 分析所有自選\n"
    "/help — 顯示此說明"
)


async def handle_webhook(body: dict) -> None:
    """Process an incoming Telegram webhook update."""
    init_db()
    message = body.get("message") or body.get("edited_message")
    if not message:
        return

    chat_id = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()
    if not text or not chat_id:
        return

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("start", "help"):
        await send_chunks(chat_id, _HELP)

    elif cmd == "add":
        if not arg:
            await _send(chat_id, "用法：/add 股票代碼  例如：/add 2330")
            return
        code = arg.upper().split()[0]
        db_add(chat_id, code, None)
        await _send(chat_id, f"✅ 已加入自選：{code}")

    elif cmd == "remove":
        if not arg:
            await _send(chat_id, "用法：/remove 股票代碼")
            return
        code = arg.upper().split()[0]
        db_remove(chat_id, code)
        await _send(chat_id, f"🗑️ 已移除自選：{code}")

    elif cmd == "list":
        items = db_list(chat_id)
        if not items:
            await _send(chat_id, "📋 自選清單為空，使用 /add 新增")
            return
        lines = "\n".join(f"• {i['stock_code']}" + (f" {i['stock_name']}" if i['stock_name'] else "") for i in items)
        await send_chunks(chat_id, f"📋 <b>自選清單</b>\n{lines}")

    elif cmd == "report":
        items = db_list(chat_id)
        if not items:
            await _send(chat_id, "自選清單為空，無法產生報告。")
            return
        await _send(chat_id, f"⏳ 正在分析 {len(items)} 支股票，請稍候…")
        # Import here to avoid circular imports
        from .finmind_market import get_tw_market_data
        for item in items[:5]:  # limit to 5
            code = item["stock_code"]
            try:
                market, is_mock = await get_tw_market_data(code)
                price = market.get("current_price", "N/A")
                chg = market.get("price_change_percent", 0.0)
                sign = "+" if chg >= 0 else ""
                icon = "📈" if chg >= 0 else "📉"
                msg = f"{icon} <b>{code}</b>\n現價：{price}\n漲跌：{sign}{chg:.2f}%"
                if is_mock:
                    msg += "\n（模擬資料）"
                await send_chunks(chat_id, msg)
            except Exception:
                await _send(chat_id, f"❌ {code} 查詢失敗")
            await asyncio.sleep(1)

    else:
        await _send(chat_id, f"未知指令：{cmd}\n輸入 /help 查看說明")
