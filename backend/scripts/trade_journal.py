"""交易日誌 — 累積每一單的結構化紀錄,找出「一直吃止損」是 A 型還 B 型。

用法(在 Discord bot 裡):
  !log 空 TAC 有等觸發 rsi87 距離21% 停損3% 20倍 賠一個R 停損後有回目標 吃到反轉才走
  → bot 用 Claude 把白話解析成結構化欄位,存進 backend/trade_journal.db
  !週報 → 算 勝率 / 等觸發vs搶跑勝率 / A型vsB型 / 平均停損 / 期望值,並給誠實結論

診斷核心(被停損後價格有沒有還是回到目標):
  A 型(reverted_after_stop=1):停損後才修正 → 設定對,是停損太窄/搶跑/槓桿太高(修機械面)
  B 型(reverted_after_stop=0):停損後續噴/續跌 → 選錯行情,非均值回歸(修選股面/加 regime)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "trade_journal.db"

# 給 Claude 的抽取指示:把使用者白話 → 嚴格 JSON
EXTRACT_SYSTEM = """你是交易日誌解析器。使用者用白話描述一筆已平倉的加密永續交易,你要抽成 JSON。
只輸出 JSON 物件,不要任何解釋、不要 markdown 圍欄。欄位:
- sym: 幣種代號(去掉 USDT,大寫;不確定給 null)
- direction: "short"(做空/空)或 "long"(做多/多);不確定 null
- waited_trigger: 有等到 1m 整根實體收破+守住才進=true;搶跑/沒等訊號=false;沒提 null
- rsi_1h: 進場時 1h RSI 數字;沒提 null
- dist_ema12: 進場時距 15m EMA12 的百分比數字(只要數值,做空給正、做多給負或依語意);沒提 null
- stop_dist_pct: 停損距離百分比數值;沒提 null
- leverage: 槓桿倍數數值;沒提 null
- result_r: 損益的 R 倍數(賺為正、賠為負;"賠一個R"=-1,"賺兩個R"=2);沒提但有講賺賠就用 +1/-1;完全沒提 null
- win: true=這單賺、false=賠;由 result_r 或文字判斷;不確定 null
- reverted_after_stop: 只在「賠錢單」有意義。停損後價格有回到原目標(15m EMA12)=true(A型);沒回、繼續往不利方向=false(B型);賺錢單或沒提 null
- exit_reason: 出場原因短語(如 "吃反轉那根"、"保本停損"、"爆倉");沒提 null
範例輸入:「空 TAC 有等觸發 rsi87 距離21% 停損3% 20倍 賠一個R 停損後有回目標 吃到反轉前就被清」
範例輸出:{"sym":"TAC","direction":"short","waited_trigger":true,"rsi_1h":87,"dist_ema12":21,"stop_dist_pct":3,"leverage":20,"result_r":-1,"win":false,"reverted_after_stop":true,"exit_reason":"停損"}"""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  logged_at TEXT NOT NULL,
  sym TEXT,
  direction TEXT,
  waited_trigger INTEGER,
  rsi_1h REAL,
  dist_ema12 REAL,
  stop_dist_pct REAL,
  leverage REAL,
  result_r REAL,
  win INTEGER,
  reverted_after_stop INTEGER,
  exit_reason TEXT,
  raw TEXT
);
"""

_NUM_FIELDS = ("rsi_1h", "dist_ema12", "stop_dist_pct", "leverage", "result_r")
_BOOL_FIELDS = ("waited_trigger", "win", "reverted_after_stop")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as c:
        c.execute(_SCHEMA)


def _to_bool_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return 1 if v else 0
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "是", "有"):
        return 1
    if s in ("false", "0", "no", "否", "沒", "沒有"):
        return 0
    return None


def _to_num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def coerce(data: dict[str, Any]) -> dict[str, Any]:
    """把 Claude 回的原始 dict 清成可入庫的型別;win 缺就由 result_r 正負補。"""
    row: dict[str, Any] = {}
    row["sym"] = (str(data["sym"]).upper().replace("USDT", "") if data.get("sym") else None)
    d = data.get("direction")
    row["direction"] = d if d in ("short", "long") else None
    for f in _NUM_FIELDS:
        row[f] = _to_num(data.get(f))
    for f in _BOOL_FIELDS:
        row[f] = _to_bool_int(data.get(f))
    if row["win"] is None and row["result_r"] is not None:
        row["win"] = 1 if row["result_r"] > 0 else 0
    row["exit_reason"] = (str(data["exit_reason"]) if data.get("exit_reason") else None)
    return row


def insert_trade(row: dict[str, Any], raw: str) -> int:
    init_db()
    cols = ["sym", "direction", "waited_trigger", "rsi_1h", "dist_ema12",
            "stop_dist_pct", "leverage", "result_r", "win", "reverted_after_stop", "exit_reason"]
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            f"INSERT INTO trades (logged_at, {', '.join(cols)}, raw) "
            f"VALUES (datetime('now','localtime'), {', '.join('?' for _ in cols)}, ?)",
            [row.get(k) for k in cols] + [raw],
        )
        return cur.lastrowid or 0


def confirm_line(row: dict[str, Any], trade_id: int) -> str:
    """入庫後回一行人看得懂的確認。"""
    d = "🔻空" if row.get("direction") == "short" else "🔺多" if row.get("direction") == "long" else "?"
    r = row.get("result_r")
    res = f"{r:+g}R" if r is not None else ("賺" if row.get("win") == 1 else "賠" if row.get("win") == 0 else "?")
    wt = "等觸發" if row.get("waited_trigger") == 1 else "搶跑" if row.get("waited_trigger") == 0 else "?觸發"
    ab = ""
    if row.get("win") == 0:
        ab = " · A型(停損後有回)" if row.get("reverted_after_stop") == 1 else \
             " · B型(沒回頭)" if row.get("reverted_after_stop") == 0 else " · A/B未填"
    return f"✅ 已記 #{trade_id}:{row.get('sym') or '?'} {d} {res} · {wt}{ab}"


def _pct(a: int, b: int) -> str:
    return f"{100*a/b:.0f}%" if b else "—"


def fetch_all_trades() -> list[dict[str, Any]]:
    init_db()
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM trades")]


def weekly_report() -> str:
    """SQLite 後端:抓全部交易 → 出報告。"""
    return build_report(fetch_all_trades())


def build_report(ts: list[dict[str, Any]]) -> str:
    """把一串交易(dict,欄位同 schema)算成誠實結論。SQLite / Notion 共用。"""
    n = len(ts)
    if n == 0:
        return "📓 交易日誌還是空的。平一單就打 `!log <描述>` 記一筆。"

    wins = [t for t in ts if t["win"] == 1]
    losses = [t for t in ts if t["win"] == 0]
    waited = [t for t in ts if t["waited_trigger"] == 1]
    jumped = [t for t in ts if t["waited_trigger"] == 0]
    waited_w = [t for t in waited if t["win"] == 1]
    jumped_w = [t for t in jumped if t["win"] == 1]
    a_type = [t for t in losses if t["reverted_after_stop"] == 1]
    b_type = [t for t in losses if t["reverted_after_stop"] == 0]

    rs = [t["result_r"] for t in ts if t["result_r"] is not None]
    expectancy = f"{sum(rs)/len(rs):+.2f}R" if rs else "—(缺R)"
    stops = [t["stop_dist_pct"] for t in ts if t["stop_dist_pct"] is not None]
    levs = [t["leverage"] for t in ts if t["leverage"] is not None]
    avg_stop = f"{sum(stops)/len(stops):.1f}%" if stops else "—"
    avg_lev = f"{sum(levs)/len(levs):.0f}x" if levs else "—"

    lines = [
        "```",
        f"交易日誌週報   共 {n} 單   勝率 {_pct(len(wins), n)}   期望值 {expectancy}",
        "─" * 40,
        f"等觸發   {len(waited):>2} 單  勝率 {_pct(len(waited_w), len(waited))}",
        f"搶跑     {len(jumped):>2} 單  勝率 {_pct(len(jumped_w), len(jumped))}",
        f"平均停損 {avg_stop}   平均槓桿 {avg_lev}",
        f"賠錢單分型:A型(停損後有回)={len(a_type)}  B型(沒回頭)={len(b_type)}",
        "```",
    ]

    # ── 誠實結論 ──
    verdict: list[str] = []
    if n < 10:
        verdict.append(f"⚠️ 樣本只有 {n} 單,還不夠下結論——先別急著改規則,可能只是運氣。目標先累到 15–20 單。")
    if len(waited) >= 3 and len(jumped) >= 3:
        wr_w = len(waited_w) / len(waited)
        wr_j = len(jumped_w) / len(jumped)
        if wr_w - wr_j >= 0.2:
            verdict.append("🎯 **搶跑明顯拉低勝率** → 沒等 1m 整根收破+守住就別進,這是最便宜的修正。")
    if len(losses) >= 4:
        if len(a_type) > len(b_type) * 2:
            verdict.append("🔧 賠單多是 **A 型(停損後才修正)** → 設定沒錯,是**停損太窄/槓桿太高**把你洗掉。降槓桿、把停損放到結構外,而不是改篩選。")
        elif len(b_type) > len(a_type) * 2:
            verdict.append("🚫 賠單多是 **B 型(停損後沒回頭)** → 你在**強趨勢裡逆勢接**,這不是均值回歸行情。需要 regime 過濾,少碰噴出中的幣。")
        else:
            verdict.append("🤔 A/B 型各半 → 機械面和選股面都有份,先從『等觸發+降槓桿』這種零成本的機械修正開始。")
    if not verdict:
        verdict.append("資料還太少或欄位缺太多(R、A/B 型沒填),多記幾單、把賠單的『停損後有沒有回目標』補上,結論才算得準。")

    return "\n".join(lines) + "\n" + "\n".join(verdict)
