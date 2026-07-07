"""Notion 交易日誌後端 — 把每一單寫進 Notion 資料庫,手機隨時翻;查回來給 A/B 型診斷。

一次性建庫(token 只留在你電腦):
  set NOTION_TOKEN=你的integration token
  .venv/Scripts/python.exe backend/scripts/notion_journal.py "<你分享給 integration 的 Notion 頁面網址>"
  → 會在那頁底下建好欄位正確的資料庫,印出 NOTION_DB_ID,把它也貼進啟動檔。

執行期(bot 會用):
  NOTION_TOKEN + NOTION_DB_ID 兩個都設好 → !log 寫 Notion、!週報 讀 Notion。
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Notion 資料庫欄位定義(建庫用)
DB_PROPERTIES = {
    "名稱": {"title": {}},
    "幣種": {"rich_text": {}},
    "方向": {"select": {"options": [{"name": "做空", "color": "red"}, {"name": "做多", "color": "green"}]}},
    "等觸發": {"select": {"options": [{"name": "等觸發", "color": "green"}, {"name": "搶跑", "color": "red"}]}},
    "1h RSI": {"number": {}},
    "RSI近6高": {"number": {}},
    "距15mEMA12%": {"number": {}},
    "資費%": {"number": {}},
    "OI狀態": {"select": {"options": [{"name": "堆積", "color": "green"}, {"name": "消退", "color": "red"}, {"name": "中性", "color": "gray"}]}},
    "進場價": {"number": {}},
    "TP價": {"number": {}},
    "SL價": {"number": {}},
    "停損距離%": {"number": {}},
    "槓桿": {"number": {}},
    "結果R": {"number": {}},
    "賺賠": {"select": {"options": [{"name": "賺", "color": "green"}, {"name": "賠", "color": "red"}]}},
    "分型": {"select": {"options": [{"name": "A型", "color": "yellow"}, {"name": "B型", "color": "gray"}]}},
    "出場原因": {"rich_text": {}},
}

# 這些是後來加的欄位;對既有資料庫做 add_missing_columns 時補上
_ADDED_COLUMNS = ("RSI近6高", "資費%", "OI狀態", "進場價", "TP價", "SL價")


def _api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"Notion API {e.code}: {detail[:300]}") from None


# ── 一次性:從頁面 URL 建資料庫 ──
def _page_id_from_url(url: str) -> str:
    ids = re.findall(r"[0-9a-fA-F]{32}", url.replace("-", ""))
    if not ids:
        raise SystemExit("網址裡找不到 Notion 頁面 ID,確認你貼的是那個頁面的完整網址。")
    h = ids[-1].lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def create_database(token: str, page_url: str, title: str = "交易日誌") -> str:
    parent = _page_id_from_url(page_url)
    body = {
        "parent": {"type": "page_id", "page_id": parent},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": DB_PROPERTIES,
    }
    return _api("POST", "/databases", token, body)["id"]


# ── 寫入 ──
def _props_from_row(row: dict[str, Any]) -> dict:
    sym = row.get("sym") or "?"
    d = row.get("direction")
    dmark = "🔻空" if d == "short" else "🔺多" if d == "long" else ""
    r = row.get("result_r")
    resw = f"{r:+g}R" if r is not None else ""
    title = " ".join(x for x in (sym, dmark, resw) if x)
    p: dict[str, Any] = {
        "名稱": {"title": [{"text": {"content": title or sym}}]},
        "幣種": {"rich_text": [{"text": {"content": sym}}]},
    }
    if d in ("short", "long"):
        p["方向"] = {"select": {"name": "做空" if d == "short" else "做多"}}
    wt = row.get("waited_trigger")
    if wt is not None:
        p["等觸發"] = {"select": {"name": "等觸發" if wt else "搶跑"}}
    for col, key in (("1h RSI", "rsi_1h"), ("RSI近6高", "rsi_hi6"), ("距15mEMA12%", "dist_ema12"),
                     ("資費%", "funding_pct"), ("進場價", "entry_price"), ("TP價", "tp_price"),
                     ("SL價", "sl_price"), ("停損距離%", "stop_dist_pct"),
                     ("槓桿", "leverage"), ("結果R", "result_r")):
        v = row.get(key)
        if v is not None:
            p[col] = {"number": v}
    ois = row.get("oi_state")
    if ois in ("堆積", "消退", "中性"):
        p["OI狀態"] = {"select": {"name": ois}}
    w = row.get("win")
    if w is not None:
        p["賺賠"] = {"select": {"name": "賺" if w else "賠"}}
    ab = row.get("reverted_after_stop")
    if ab is not None:
        p["分型"] = {"select": {"name": "A型" if ab else "B型"}}
    er = row.get("exit_reason")
    if er:
        p["出場原因"] = {"rich_text": [{"text": {"content": str(er)[:200]}}]}
    return p


def create_trade(token: str, db_id: str, row: dict[str, Any]) -> str:
    body = {"parent": {"database_id": db_id}, "properties": _props_from_row(row)}
    return _api("POST", "/pages", token, body)["id"]


def add_missing_columns(token: str, db_id: str) -> list[str]:
    """幫既有資料庫補上 _ADDED_COLUMNS(已存在的會跳過)。回傳實際新增的欄位名。"""
    existing = _api("GET", f"/databases/{db_id}", token).get("properties", {})
    to_add = {c: DB_PROPERTIES[c] for c in _ADDED_COLUMNS if c not in existing}
    if to_add:
        _api("PATCH", f"/databases/{db_id}", token, {"properties": to_add})
    return list(to_add.keys())


# ── 查詢(回傳欄位對齊 trade_journal schema,給 build_report 用)──
def _num(prop: dict | None) -> float | None:
    return prop.get("number") if prop else None


def _sel(prop: dict | None) -> str | None:
    s = prop.get("select") if prop else None
    return s.get("name") if s else None


def _rt(prop: dict | None) -> str | None:
    arr = prop.get("rich_text") if prop else None
    return arr[0]["plain_text"] if arr else None


def query_trades(token: str, db_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        body: dict[str, Any] = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        d = _api("POST", f"/databases/{db_id}/query", token, body)
        for pg in d.get("results", []):
            pr = pg.get("properties", {})
            dword = _sel(pr.get("方向"))
            wt = _sel(pr.get("等觸發"))
            paid = _sel(pr.get("賺賠"))
            ab = _sel(pr.get("分型"))
            out.append({
                "sym": _rt(pr.get("幣種")),
                "direction": "short" if dword == "做空" else "long" if dword == "做多" else None,
                "waited_trigger": 1 if wt == "等觸發" else 0 if wt == "搶跑" else None,
                "rsi_1h": _num(pr.get("1h RSI")),
                "dist_ema12": _num(pr.get("距15mEMA12%")),
                "stop_dist_pct": _num(pr.get("停損距離%")),
                "leverage": _num(pr.get("槓桿")),
                "result_r": _num(pr.get("結果R")),
                "win": 1 if paid == "賺" else 0 if paid == "賠" else None,
                "reverted_after_stop": 1 if ab == "A型" else 0 if ab == "B型" else None,
            })
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")
    return out


def _load_token() -> str:
    tok = os.getenv("NOTION_TOKEN")
    if not tok:  # 退而求其次:讀 backend/.env
        env = Path(__file__).resolve().parents[1] / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                m = re.match(r"\s*NOTION_TOKEN\s*=\s*(.*)\s*$", line)
                if m:
                    tok = m.group(1).strip().strip('"').strip("'")
    if not tok:
        raise SystemExit("缺 NOTION_TOKEN。先 set NOTION_TOKEN=你的token 再跑。")
    return tok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('用法:\n  建庫:notion_journal.py "<Notion 頁面網址>"\n  補欄位:notion_journal.py --migrate')
    token = _load_token()
    if sys.argv[1] == "--migrate":
        db_id = os.getenv("NOTION_DB_ID")
        if not db_id:  # 從 backend/.env 讀
            env = Path(__file__).resolve().parents[1] / ".env"
            if env.exists():
                for line in env.read_text(encoding="utf-8").splitlines():
                    m = re.match(r"\s*NOTION_DB_ID\s*=\s*(.*)\s*$", line)
                    if m:
                        db_id = m.group(1).strip().strip('"').strip("'")
        if not db_id:
            raise SystemExit("缺 NOTION_DB_ID(env 或 backend/.env)。")
        added = add_missing_columns(token, db_id)
        print(f"✓ 補欄位完成,新增:{added or '(無,已是最新)'}")
    else:
        db_id = create_database(token, sys.argv[1])
        print("✓ 資料庫已建立。把下面這行加進 .env / 啟動檔:")
        print(f"    NOTION_DB_ID={db_id}")
