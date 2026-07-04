"""AI 每日精選（附理由）— 疊加在每日交易機會的量化桶之上。

架構（成本紀律）：量化桶先把全市場收斂成 ~40 檔候選（長線已驗證 + 中線觀察 +
短線時點），AI **每日僅 1 次呼叫**讀取候選的完整量化數據，精選 3-5 檔並給
資料紮根的理由。不掃全市場、不逐檔呼叫（374 秒慘案與成本鐵則）。

誠實契約：
  - AI 只能引用 prompt 內提供的數據，程式端再驗證 stock_id 必須存在於候選集
    （防幻覺）；理由字串 verb-free（不得出現買/賣/持有/目標價等指令詞）。
  - 僅快取成功回應（(date) 為鍵）；金鑰缺失或呼叫失敗 → 回 None，端點以
    status:"unavailable" 誠實呈現，永不 mock 混充。
"""
from __future__ import annotations

import os
from datetime import date

from pydantic import BaseModel
from pydantic_ai import Agent

from backend.app.agents.retry import run_with_backoff
from backend.app.services import file_cache
from backend.app.services.gemini_diagnostics import resolve_ai_model_id

_CACHE_NS = "ai_daily_picks"


class AIPick(BaseModel):
    stock_id: str
    name: str
    bucket: str  # long | mid | short
    reasons: list[str]  # 2-3 條，僅根據提供數據，verb-free
    risk_note: str
    watch_condition: str  # 此觀察不再成立的條件（數據化描述）


class AIDailyPicks(BaseModel):
    market_read: str  # 一句話盤面判讀（僅根據提供的候選結構與數據）
    picks: list[AIPick]


_SYSTEM_PROMPT = (
    "你是台灣股票研究助理。以下是今日通過量化篩選的候選股票與其完整數據。"
    "任務：從中精選 3-5 檔「數據面最突出」者，每檔給 2-3 條理由。"
    "鐵則：(1) 理由只能引用提供的數據，不得使用外部知識、不得捏造數字；"
    "(2) 全文為條件與數據描述，嚴禁出現 買/賣/持有/加碼/減碼/目標價/停損 等指令詞；"
    "(3) 長線桶為已回測驗證之選股力（一年期），中線桶為未達驗證門檻之觀察名單——"
    "精選時應反映此可信度差異；(4) risk_note 指出該檔數據中的弱點或需留意的結構；"
    "(5) watch_condition 描述何種數據變化會使此觀察不再成立。繁體中文。"
)


def _model_id() -> str:
    override = os.getenv("TW_AI_MODEL_UNIFIED")
    if override and override.strip():
        return override.strip()
    return resolve_ai_model_id()


def _key_available() -> bool:
    from backend.app.services.gemini_diagnostics import _provider_key_present
    return _provider_key_present(_model_id())


def _format_candidates(core: dict) -> tuple[str, set[str], dict]:
    buckets = core.get("buckets") or {}
    lines: list[str] = []
    valid: set[str] = set()
    name_map: dict[str, str] = {}
    label = {
        "long": "長線價值桶（已驗證：dev T+250 選股力 +4.4%／OOS +2.6%）",
        "mid": "中線桶 CANSLIM 領導股（未達驗證門檻的觀察名單）",
        "short": "進場時點觀察（依附長線候選）",
    }
    for key in ("long", "mid", "short"):
        items = buckets.get(key) or []
        if not items:
            continue
        lines.append(f"\n=== {label[key]} ===")
        for it in items:
            sid = it["stock_id"]
            valid.add(sid)
            name_map[sid] = it.get("name") or sid
            metrics = "、".join(f"{k}={v}" for k, v in (it.get("metrics") or {}).items() if v is not None)
            lines.append(f"- {sid} {it.get('name')}［{it.get('industry')}］級{it['grade']}："
                         f"{it.get('basis')}｛{metrics}｝")
    return "\n".join(lines), valid, name_map


async def get_ai_daily_picks(core: dict) -> dict | None:
    """回 dict（成功，含 cache）或 None（金鑰缺/失敗/無候選）。"""
    today = date.today().strftime("%Y-%m-%d")
    cached = file_cache.load(_CACHE_NS, today)
    if isinstance(cached, dict):
        return cached
    text, valid, name_map = _format_candidates(core)
    if not valid or not _key_available():
        return None
    prompt = f"今日候選清單（{core.get('date')}）：\n{text}\n\n請精選並輸出結構化結果。"
    try:
        agent = Agent(_model_id(), output_type=AIDailyPicks, system_prompt=_SYSTEM_PROMPT)
        result = await run_with_backoff(agent, prompt)
        out: AIDailyPicks = result.output
    except Exception as e:  # noqa: BLE001 — 失敗即誠實缺席，永不 mock
        print(f"AI daily picks error: {e}; omitting (no cache)")
        return None
    picks = []
    for p in out.picks[:5]:
        if p.stock_id not in valid:  # 防幻覺：候選集外的代號一律丟棄
            continue
        picks.append({
            "stock_id": p.stock_id,
            "name": name_map.get(p.stock_id, p.name),
            "bucket": p.bucket if p.bucket in {"long", "mid", "short"} else "long",
            "reasons": p.reasons[:3],
            "risk_note": p.risk_note,
            "watch_condition": p.watch_condition,
        })
    if not picks:
        return None
    payload = {
        "status": "ok",
        "date": today,
        "model": _model_id(),
        "market_read": out.market_read,
        "picks": picks,
        "notices": [
            "AI 精選為模型依據當日量化候選數據生成的觀察描述，僅供參考，不構成投資建議。",
            "精選範圍限於當日量化桶候選（非全市場逐檔 AI 分析）；理由僅引用當日數據。",
        ],
    }
    file_cache.save(_CACHE_NS, today, payload)
    return payload
