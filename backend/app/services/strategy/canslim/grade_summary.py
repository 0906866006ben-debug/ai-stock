"""Readable A/B-grade summary for the universe-scan cards.

Consolidates the deterministic CANSLIM screening evidence (pillar verdicts,
scores, invalidation conditions, durability) into three short, plain-language
sections so the scan cards are scannable:

    why_grade        — which pillars carry / cap the grade
    key_risks        — risk pillars + structural invalidation conditions
    durability_note  — composite durability score + its strongest / weakest parts

Two backends, identical output shape:
  * `build_deterministic_summary` — pure template over the structured fields
    (zero cost, instant, no fabrication). Always the fallback.
  * `summarize_with_gemini` — natural-language polish via the project's existing
    PydanticAI + Gemini path (same pattern as news_pillar). Used only when
    GEMINI_API_KEY is present; on any error it falls back to the template.

Guardrails (CANSLIM redesign): structured output only, NEVER buy/sell/hold/target/
stop language (scrubbed via screening_language), and the model may ONLY restate the
evidence it is given — it must not invent facts or numbers.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from backend.app.services.strategy.canslim.screening_language import (
    clean_user_facing_text,
    contains_forbidden_action_language,
)

PILLAR_NAMES = {
    "C": "當季獲利",
    "A": "年度獲利品質",
    "N": "創新高/題材",
    "S": "供需量能",
    "L": "領先強度",
    "I": "法人支持",
    "M": "大盤環境",
}

DURABILITY_COMPONENT_NAMES = {
    "op_margin_stability": "營益率穩定",
    "roe_quality": "ROE 品質",
    "roe_trend": "ROE 趨勢",
    "multiyear_consistency": "多年成長一致",
    "multi_year_consistency": "多年成長一致",
    "earnings_purity": "本業獲利純度",
    "inst_continuity": "法人連續性",
    "institutional_flow": "法人連續性",
    "cfo_quality": "現金流品質",
    "partial_fscore": "Piotroski 分數",
    "f_score_partial": "Piotroski 分數",
}


class GradeSummary(BaseModel):
    """Three short verb-free sections explaining a scan card's grade."""
    model_config = ConfigDict(frozen=True)

    why_grade: str = ""
    key_risks: str = ""
    durability_note: str = ""
    source: str = "template"  # "gemini" | "template"


def _scrub(text: str) -> str:
    """Verb-free guard: drop forbidden action language, keep it observational."""
    cleaned = clean_user_facing_text(text or "")
    if contains_forbidden_action_language(cleaned):
        # Strip to a neutral note rather than emit an imperative.
        return ""
    return cleaned


def build_deterministic_summary(card: Mapping[str, Any]) -> GradeSummary:
    """Compose a readable summary purely from the structured screening fields."""
    grade = str(card.get("grade") or "—")
    pillars: dict[str, str] = dict(card.get("pillars") or {})
    passed = [PILLAR_NAMES[p] for p in ("C", "A", "N", "S", "L", "I", "M")
              if pillars.get(p) == "Pass"]
    failed = [PILLAR_NAMES[p] for p in ("C", "A", "N", "S", "L", "I", "M")
              if pillars.get(p) == "Fail"]
    weak = [PILLAR_NAMES[p] for p in ("C", "A", "N", "S", "L", "I", "M")
            if pillars.get(p) == "Weak"]
    signal = card.get("signal")

    # why_grade
    parts: list[str] = [f"{grade} 級"]
    if signal is not None:
        parts[0] += f"(訊號 {signal}/100)"
    if passed:
        parts.append("通過支柱:" + "、".join(passed))
    if weak:
        parts.append("偏弱:" + "、".join(weak))
    if failed:
        parts.append("未過:" + "、".join(failed))
    # earnings-cap note (the growth-screen gate)
    if pillars.get("C") == "Fail" and pillars.get("A") == "Fail":
        parts.append("當季與年度獲利皆未達標,分級因此受限。")
    why_grade = "；".join(parts) + "。"

    # key_risks
    risk_bits: list[str] = []
    risk_score = card.get("risk")
    structure = card.get("structure_status")
    if structure and structure != "intact":
        status_map = {"weakening": "結構轉弱", "invalidated": "結構失效", "profit_watch": "延伸/獲利了結觀察區"}
        risk_bits.append(status_map.get(str(structure), str(structure)))
    for sig in list(card.get("invalidation") or [])[:4]:
        s = _scrub(str(sig))
        if s:
            risk_bits.append(s)
    if risk_score is not None and risk_score >= 35 and not risk_bits:
        risk_bits.append(f"風險分數偏高({risk_score}/100)")
    key_risks = "；".join(dict.fromkeys(risk_bits)) + ("。" if risk_bits else "")
    if not key_risks:
        key_risks = "目前未偵測到明顯的結構失效條件。"

    # durability_note
    dur = card.get("durability_score")
    comps: dict[str, float] = dict(card.get("durability_components") or {})
    if dur is None and not comps:
        durability_note = "耐久度資料不足。"
    else:
        named = [(DURABILITY_COMPONENT_NAMES.get(k, k), v) for k, v in comps.items()
                 if isinstance(v, (int, float))]
        named.sort(key=lambda kv: kv[1], reverse=True)
        strong = [n for n, v in named[:2] if v >= 0.6]
        weakest = [n for n, v in named[-2:] if v < 0.5]
        bits = []
        if dur is not None:
            bits.append(f"耐久度 {round(float(dur))}/100")
        if strong:
            bits.append("強:" + "、".join(strong))
        if weakest:
            bits.append("弱:" + "、".join(weakest))
        durability_note = "｜".join(bits) + "。"

    return GradeSummary(
        why_grade=_scrub(why_grade) or why_grade,
        key_risks=key_risks,
        durability_note=durability_note,
        source="template",
    )


_GEMINI_SYSTEM_PROMPT = (
    "你是一個台股 CANSLIM 篩選結果的『說明助理』。你會收到一檔股票的結構化篩選證據"
    "(分級、各支柱通過/偏弱/未過狀態、訊號/風險分數、失效條件、耐久度分數與元件)。"
    "請用繁體中文,把它整理成三段簡短、客觀、好讀的說明:\n"
    "1) why_grade:為什麼是這個分級(哪些支柱加分、哪些拖累)。\n"
    "2) key_risks:關鍵風險與失效條件(用觀察語氣)。\n"
    "3) durability_note:耐久度品質(分數與最強/最弱元件)。\n"
    "嚴格規則:只能根據提供的證據陳述,絕對不可捏造任何數字或事實;"
    "絕對不可出現買/賣/持有/進場/出場/目標價/停損/停利等任何操作指令或建議;"
    "這不是投資建議,只是把篩選結果講得更白話。"
)


async def summarize_with_gemini(card: Mapping[str, Any]) -> GradeSummary | None:
    """Natural-language summary via Gemini (PydanticAI). None when unavailable."""
    try:
        from backend.app.services.gemini_diagnostics import (
            get_gemini_model, is_gemini_enabled, to_pydantic_ai_model_id,
        )
    except Exception:
        return None
    if not os.getenv("GEMINI_API_KEY") or not is_gemini_enabled():
        return None
    try:
        from pydantic_ai import Agent
    except Exception:
        return None
    try:
        agent = Agent(
            to_pydantic_ai_model_id(get_gemini_model()),
            output_type=GradeSummary,
            system_prompt=_GEMINI_SYSTEM_PROMPT,
        )
        result = await agent.run(json.dumps(dict(card), ensure_ascii=False, default=str))
        out = result.output
    except Exception:
        return None
    # Verb-free + anti-empty guard; fall back to template fields if scrubbed away.
    why = _scrub(out.why_grade)
    risks = _scrub(out.key_risks)
    dur = _scrub(out.durability_note)
    if not (why or risks or dur):
        return None
    return GradeSummary(why_grade=why, key_risks=risks, durability_note=dur, source="gemini")


async def summarize_grade(card: Mapping[str, Any]) -> GradeSummary:
    """Gemini when available, else deterministic template. Always returns verb-free."""
    ai = await summarize_with_gemini(card)
    if ai is not None:
        # Backfill any section the model left blank with the template version.
        tmpl = build_deterministic_summary(card)
        return GradeSummary(
            why_grade=ai.why_grade or tmpl.why_grade,
            key_risks=ai.key_risks or tmpl.key_risks,
            durability_note=ai.durability_note or tmpl.durability_note,
            source="gemini",
        )
    return build_deterministic_summary(card)


async def summarize_batch(
    cards: list[Mapping[str, Any]],
    *,
    concurrency: int = 5,
) -> dict[str, GradeSummary]:
    """Summarize many cards with bounded concurrency. Keyed by card['stock_id']."""
    out: dict[str, GradeSummary] = {}
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(card: Mapping[str, Any]) -> None:
        sid = str(card.get("stock_id") or "")
        if not sid:
            return
        async with sem:
            try:
                out[sid] = await summarize_grade(card)
            except Exception:
                out[sid] = build_deterministic_summary(card)

    await asyncio.gather(*(one(c) for c in cards))
    return out
