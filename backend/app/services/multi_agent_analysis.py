from __future__ import annotations

import json
import os
import re
from datetime import date, timezone, datetime
from typing import Any

from backend.app.models.schemas import (
    AgentAnalysisResponse,
    AgentEvidencePack,
    AgentKeyValue,
    AgentStage,
    ClaudeFinalReview,
    GeminiStructuredInsight,
    MultiAgentAnalysis,
)
from backend.app.services.finmind_detail import get_tw_detail
from backend.app.services.finmind_market import get_tw_price_history_with_source
from backend.app.services.gemini_diagnostics import (
    ai_key_available,
    get_gemini_model_chain,
    is_gemini_enabled,
    to_pydantic_ai_model_id,
)
from backend.app.services.tw_macro import get_macro_summary
from backend.app.services.yahoo_news import get_tw_stock_news

PIPELINE_VERSION = "finmind-gemini-claude-v1"

GEMINI_SYSTEM_PROMPT = (
    "你是資料整理 agent。只能整理使用者提供的 evidence_packs，不得新增未提供的事實。"
    "請用繁體中文輸出固定 schema：key_points、conflicts、missing_data、coverage_notes。"
    "不得輸出買賣建議、目標價或價格預測。若資料缺漏，放入 missing_data。"
)

CLAUDE_SYSTEM_PROMPT = (
    "你是最後審閱 agent。只能依據提供的 FinMind evidence 和 Gemini structured insight 做結論。"
    "輸出必須是 JSON，符合欄位 status、confidence、conclusion、supporting_evidence、"
    "key_risks、conflicting_signals、data_limitations、manual_review_required。"
    "status 只能是 Strong、Neutral、Weak、Insufficient_Data；confidence 只能是 High、Medium、Low。"
    "不得輸出買進、賣出、持有、目標價、價位預測或保證性語句。"
)

_FORBIDDEN_ADVICE_PATTERNS = [
    r"\bBUY\b",
    r"\bSELL\b",
    r"\bHOLD\b",
    "買進",
    "賣出",
    "持有",
    "目標價",
    "停損",
    "停利",
]


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _fmt_num(value: Any, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _safe_text(value) or "N/A"
    if abs(number) >= 1000:
        return f"{number:,.0f}{suffix}"
    return f"{number:.2f}{suffix}"


def _scrub_user_facing_text(text: str) -> str:
    cleaned = _safe_text(text)
    replacements = {
        "買進": "偏正向觀察",
        "賣出": "偏負向觀察",
        "持有": "中性觀察",
        "目標價": "估值假設",
        "停損": "風險控管",
        "停利": "風險控管",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"\bBUY\b", "positive observation", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSELL\b", "negative observation", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bHOLD\b", "neutral observation", cleaned, flags=re.IGNORECASE)
    return cleaned


def _pack_has_data(pack: AgentEvidencePack) -> bool:
    return pack.status in {"available", "partial"}


def _latest_candle_date(candles: list[dict]) -> str | None:
    if not candles:
        return None
    return _safe_text(candles[-1].get("time") or candles[-1].get("date")) or None


def _price_pack(candles: list[dict], warnings: list[str], is_mock: bool) -> AgentEvidencePack:
    if not candles:
        return AgentEvidencePack(
            id="price",
            label="價格量能",
            source="Backend",
            status="missing",
            summary="價格資料不足，無法整理近期趨勢。",
            warnings=warnings or ["price_history_missing"],
        )

    latest = candles[-1]
    prev = candles[-2] if len(candles) >= 2 else latest
    close = float(latest.get("close") or 0)
    prev_close = float(prev.get("close") or close or 1)
    change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0.0
    volumes = [float(row.get("volume") or 0) for row in candles[-20:]]
    avg_vol_20 = sum(volumes) / len(volumes) if volumes else None
    latest_vol = float(latest.get("volume") or 0)
    vol_ratio = latest_vol / avg_vol_20 if avg_vol_20 else None
    status = "partial" if is_mock else "available"

    return AgentEvidencePack(
        id="price",
        label="價格量能",
        source="Backend" if is_mock else "FinMind",
        status=status,
        latest_date=_latest_candle_date(candles),
        summary=(
            f"最新收盤 {_fmt_num(close)}，單日變動 {_fmt_num(change_pct, '%')}；"
            f"近 20 日量比 {_fmt_num(vol_ratio, 'x')}。"
        ),
        key_values=[
            AgentKeyValue(label="最新收盤", value=_fmt_num(close)),
            AgentKeyValue(label="單日漲跌幅", value=_fmt_num(change_pct, "%")),
            AgentKeyValue(label="近20日量比", value=_fmt_num(vol_ratio, "x")),
        ],
        warnings=warnings,
    )


def _revenue_pack(detail: dict) -> AgentEvidencePack:
    rev = detail.get("revenue_summary") or {}
    status = "available" if rev.get("status") == "ok" else "missing"
    summary = "月營收資料不足。"
    if status == "available":
        summary = (
            f"最新月營收 {rev.get('latest_revenue') or 'N/A'}，"
            f"年增 {_fmt_num(rev.get('yoy_pct'), '%')}，月增 {_fmt_num(rev.get('mom_pct'), '%')}。"
        )
    return AgentEvidencePack(
        id="revenue",
        label="月營收",
        source="FinMind",
        status=status,
        summary=summary,
        key_values=[
            AgentKeyValue(label="月營收年增率", value=_fmt_num(rev.get("yoy_pct"), "%")),
            AgentKeyValue(label="月營收月增率", value=_fmt_num(rev.get("mom_pct"), "%")),
            AgentKeyValue(label="可用月份", value=str(rev.get("available_months") or 0)),
        ],
        warnings=[] if status == "available" else ["revenue_missing"],
    )


def _valuation_pack(detail: dict) -> AgentEvidencePack:
    val = detail.get("valuation_summary") or {}
    has_data = val.get("per") is not None or val.get("pbr") is not None
    status = "available" if has_data else "missing"
    summary = "估值資料不足。"
    if has_data:
        summary = (
            f"PER {_fmt_num(val.get('per'))}，PBR {_fmt_num(val.get('pbr'))}，"
            f"股息殖利率 {_fmt_num(val.get('dividend_yield'), '%')}；"
            f"估值狀態 {val.get('status') or 'unknown'}。"
        )
    return AgentEvidencePack(
        id="valuation",
        label="估值",
        source="FinMind",
        status=status,
        summary=summary,
        key_values=[
            AgentKeyValue(label="PER", value=_fmt_num(val.get("per"))),
            AgentKeyValue(label="PBR", value=_fmt_num(val.get("pbr"))),
            AgentKeyValue(label="股息殖利率", value=_fmt_num(val.get("dividend_yield"), "%")),
        ],
        warnings=[] if has_data else ["valuation_missing"],
    )


def _chip_pack(detail: dict) -> AgentEvidencePack:
    inst = detail.get("institutional_summary") or {}
    chip = detail.get("chip_risk_summary") or {}
    has_inst = inst.get("status") == "ok"
    has_chip = chip.get("status") == "ok"
    status = "available" if has_inst or has_chip else "missing"
    summary = "籌碼資料不足。"
    if status == "available":
        summary = (
            f"外資 5 日淨額 {_fmt_num(inst.get('foreign_net_5d'))}，"
            f"投信 5 日淨額 {_fmt_num(inst.get('trust_net_5d'))}，"
            f"籌碼風險 {chip.get('risk_level') or 'unknown'}。"
        )
    return AgentEvidencePack(
        id="chip",
        label="籌碼",
        source="FinMind",
        status=status,
        summary=summary,
        key_values=[
            AgentKeyValue(label="外資5日", value=_fmt_num(inst.get("foreign_net_5d"))),
            AgentKeyValue(label="投信5日", value=_fmt_num(inst.get("trust_net_5d"))),
            AgentKeyValue(label="籌碼風險", value=_safe_text(chip.get("risk_level")) or "unknown"),
        ],
        warnings=[] if status == "available" else ["chip_missing"],
    )


def _cashflow_pack(detail: dict) -> AgentEvidencePack:
    cf = detail.get("cashflow_summary") or {}
    status = "available" if cf.get("status") == "ok" else "missing"
    summary = "現金流資料不足。"
    if status == "available":
        summary = (
            f"最近期營業現金流 {_fmt_num(cf.get('operating_cash_flow'))}，"
            f"自由現金流 {_fmt_num(cf.get('free_cash_flow'))}，"
            f"趨勢 {cf.get('operating_cf_trend') or 'unknown'}。"
        )
    return AgentEvidencePack(
        id="cashflow",
        label="現金流",
        source="FinMind",
        status=status,
        latest_date=cf.get("period"),
        summary=summary,
        key_values=[
            AgentKeyValue(label="營業現金流", value=_fmt_num(cf.get("operating_cash_flow"))),
            AgentKeyValue(label="自由現金流", value=_fmt_num(cf.get("free_cash_flow"))),
            AgentKeyValue(label="OCF趨勢", value=_safe_text(cf.get("operating_cf_trend")) or "unknown"),
        ],
        warnings=[] if status == "available" else ["cashflow_missing"],
    )


def _news_pack(news: list[dict]) -> AgentEvidencePack:
    valid = [item for item in news if item.get("title")]
    if not valid:
        return AgentEvidencePack(
            id="news",
            label="新聞",
            source="Yahoo",
            status="missing",
            summary="近期新聞資料不足。",
            warnings=["news_missing"],
        )
    titles = [str(item.get("title")) for item in valid[:3]]
    latest_date = _safe_text(valid[0].get("published_at") or valid[0].get("date")) or None
    return AgentEvidencePack(
        id="news",
        label="新聞",
        source="Yahoo",
        status="available",
        latest_date=latest_date,
        summary="；".join(titles),
        key_values=[
            AgentKeyValue(label=f"新聞{i + 1}", value=title)
            for i, title in enumerate(titles)
        ],
        warnings=[],
    )


def _macro_pack(macro: dict) -> AgentEvidencePack:
    if not macro or macro.get("status") == "no_data":
        return AgentEvidencePack(
            id="macro",
            label="總經",
            source="Backend",
            status="missing",
            summary="總經資料不足。",
            warnings=["macro_missing"],
        )
    summary = (
        f"美元台幣 {_fmt_num(macro.get('usd_twd'))}，"
        f"NASDAQ {_fmt_num(macro.get('nasdaq'))}，"
        f"外資期貨方向 {macro.get('fut_foreign_direction') or 'unknown'}。"
    )
    return AgentEvidencePack(
        id="macro",
        label="總經",
        source="Backend",
        status="available",
        summary=summary,
        key_values=[
            AgentKeyValue(label="USD/TWD", value=_fmt_num(macro.get("usd_twd"))),
            AgentKeyValue(label="NASDAQ", value=_fmt_num(macro.get("nasdaq"))),
            AgentKeyValue(label="外資期貨方向", value=_safe_text(macro.get("fut_foreign_direction")) or "unknown"),
        ],
        warnings=[],
    )


async def build_finmind_evidence(symbol: str) -> tuple[list[AgentEvidencePack], list[str], bool]:
    price_result = await get_tw_price_history_with_source(symbol, 260)
    detail = await get_tw_detail(symbol)
    news = await get_tw_stock_news(symbol)
    macro = await get_macro_summary()

    price_warnings = list(price_result.source_info.data_warnings or [])
    packs = [
        _price_pack(price_result.candles, price_warnings, price_result.source_info.is_mock_data),
        _revenue_pack(detail),
        _valuation_pack(detail),
        _chip_pack(detail),
        _cashflow_pack(detail),
        _news_pack(news or []),
        _macro_pack(macro or {}),
    ]
    warnings = []
    for pack in packs:
        warnings.extend(pack.warnings)
    warnings = list(dict.fromkeys(warnings))
    is_mock = bool(price_result.source_info.is_mock_data)
    return packs, warnings, is_mock


def build_gemini_fallback(evidence_packs: list[AgentEvidencePack]) -> GeminiStructuredInsight:
    available = [pack for pack in evidence_packs if _pack_has_data(pack)]
    missing = [pack.label for pack in evidence_packs if pack.status == "missing"]
    key_points = [pack.summary for pack in available[:5] if pack.summary]
    conflicts: list[str] = []

    chip = next((pack for pack in evidence_packs if pack.id == "chip"), None)
    price = next((pack for pack in evidence_packs if pack.id == "price"), None)
    if chip and chip.status == "available" and "net_sell" in chip.summary and price and price.status == "available":
        conflicts.append("價格資料可用，但籌碼摘要出現偏負向訊號，需人工比對。")

    if not key_points:
        key_points = ["目前可用資料不足，僅能產生資料完整性檢查。"]

    return GeminiStructuredInsight(
        key_points=[_scrub_user_facing_text(item) for item in key_points],
        conflicts=conflicts,
        missing_data=missing,
        coverage_notes=[
            f"可用資料包 {len(available)}/{len(evidence_packs)}；缺漏：{', '.join(missing) if missing else '無明顯缺漏'}。"
        ],
    )


async def run_gemini_structurer(
    *,
    symbol: str,
    evidence_packs: list[AgentEvidencePack],
    question: str | None = None,
) -> tuple[GeminiStructuredInsight, str]:
    model_chain = get_gemini_model_chain()
    if not ai_key_available() or not is_gemini_enabled():
        return build_gemini_fallback(evidence_packs), "fallback"

    payload = {
        "symbol": symbol,
        "question": question,
        "evidence_packs": [pack.model_dump(mode="json") for pack in evidence_packs],
    }
    prompt = json.dumps(payload, ensure_ascii=False)

    for model_name in model_chain:
        try:
            from pydantic_ai import Agent

            agent = Agent(
                to_pydantic_ai_model_id(model_name),
                output_type=GeminiStructuredInsight,
                system_prompt=GEMINI_SYSTEM_PROMPT,
            )
            result = await agent.run(prompt)
            insight = result.output
            return GeminiStructuredInsight(
                key_points=[_scrub_user_facing_text(item) for item in insight.key_points],
                conflicts=[_scrub_user_facing_text(item) for item in insight.conflicts],
                missing_data=[_scrub_user_facing_text(item) for item in insight.missing_data],
                coverage_notes=[_scrub_user_facing_text(item) for item in insight.coverage_notes],
            ), "completed"
        except Exception:
            continue
    return build_gemini_fallback(evidence_packs), "fallback"


def build_claude_fallback(
    evidence_packs: list[AgentEvidencePack],
    gemini: GeminiStructuredInsight,
) -> ClaudeFinalReview:
    available_count = sum(1 for pack in evidence_packs if _pack_has_data(pack))
    missing_count = len(evidence_packs) - available_count
    if available_count <= 2:
        status = "Insufficient_Data"
        confidence = "Low"
    elif gemini.conflicts:
        status = "Neutral"
        confidence = "Medium"
    elif missing_count <= 2:
        status = "Neutral"
        confidence = "Medium"
    else:
        status = "Insufficient_Data"
        confidence = "Low"

    conclusion = (
        "後端已完成資料彙整，但 Claude API 未啟用或呼叫失敗；"
        "以下為 deterministic fallback 結論，適合用來檢查資料缺口。"
    )
    return ClaudeFinalReview(
        status=status,
        confidence=confidence,
        conclusion=_scrub_user_facing_text(conclusion),
        supporting_evidence=[_scrub_user_facing_text(item) for item in gemini.key_points[:5]],
        key_risks=["AI 最終審閱未使用 Claude API。"] + [_scrub_user_facing_text(item) for item in gemini.conflicts],
        conflicting_signals=[_scrub_user_facing_text(item) for item in gemini.conflicts],
        data_limitations=[_scrub_user_facing_text(item) for item in gemini.missing_data],
        manual_review_required=["若要消耗 Claude token 產生正式結論，請確認 ANTHROPIC_API_KEY 已設定。"],
    )


def _parse_json_object(text: str) -> dict | None:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(s[start : end + 1])
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _sanitize_review(review: ClaudeFinalReview) -> ClaudeFinalReview:
    return ClaudeFinalReview(
        status=review.status,
        confidence=review.confidence,
        conclusion=_scrub_user_facing_text(review.conclusion),
        supporting_evidence=[_scrub_user_facing_text(item) for item in review.supporting_evidence],
        key_risks=[_scrub_user_facing_text(item) for item in review.key_risks],
        conflicting_signals=[_scrub_user_facing_text(item) for item in review.conflicting_signals],
        data_limitations=[_scrub_user_facing_text(item) for item in review.data_limitations],
        manual_review_required=[_scrub_user_facing_text(item) for item in review.manual_review_required],
    )


async def run_claude_finalizer(
    *,
    symbol: str,
    evidence_packs: list[AgentEvidencePack],
    gemini: GeminiStructuredInsight,
    question: str | None = None,
) -> tuple[ClaudeFinalReview, str]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return build_claude_fallback(evidence_packs, gemini), "fallback"
    try:
        from anthropic import AsyncAnthropic
    except Exception:
        return build_claude_fallback(evidence_packs, gemini), "fallback"

    model = os.getenv("ANTHROPIC_MODEL") or os.getenv("ANTHROPIC_FAST_MODEL") or "claude-haiku-4-5-20251001"
    payload = {
        "symbol": symbol,
        "question": question,
        "evidence_packs": [pack.model_dump(mode="json") for pack in evidence_packs],
        "gemini_structured": gemini.model_dump(mode="json"),
    }
    try:
        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=model,
            max_tokens=1200,
            system=CLAUDE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        text = "".join(getattr(block, "text", "") for block in resp.content if getattr(block, "type", "") == "text")
        data = _parse_json_object(text)
        if not isinstance(data, dict):
            return build_claude_fallback(evidence_packs, gemini), "fallback"
        return _sanitize_review(ClaudeFinalReview(**data)), "completed"
    except Exception:
        return build_claude_fallback(evidence_packs, gemini), "fallback"


def _agent_stages(gemini_status: str, claude_status: str, finmind_status: str) -> list[AgentStage]:
    return [
        AgentStage(name="FinMind Agent", role="收集價格、營收、估值、籌碼、現金流與新聞資料。", status=finmind_status),
        AgentStage(name="Gemini Agent", role="整理大量資料，找出重點、衝突與缺口。", status=gemini_status),
        AgentStage(name="Claude Agent", role="依固定格式產生最終審閱結論。", status=claude_status),
    ]


def _has_forbidden_advice(response: AgentAnalysisResponse) -> bool:
    text = json.dumps(response.model_dump(mode="json"), ensure_ascii=False)
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _FORBIDDEN_ADVICE_PATTERNS)


async def run_multi_agent_analysis(
    symbol: str,
    *,
    question: str | None = None,
) -> AgentAnalysisResponse:
    evidence_packs, warnings, is_mock = await build_finmind_evidence(symbol)
    finmind_status = "fallback" if is_mock else "completed"
    if not any(_pack_has_data(pack) for pack in evidence_packs):
        finmind_status = "fallback"

    gemini, gemini_status = await run_gemini_structurer(
        symbol=symbol,
        evidence_packs=evidence_packs,
        question=question,
    )
    claude, claude_status = await run_claude_finalizer(
        symbol=symbol,
        evidence_packs=evidence_packs,
        gemini=gemini,
        question=question,
    )
    response = AgentAnalysisResponse(
        symbol=symbol,
        analysis_date=datetime.now(timezone.utc).date().isoformat(),
        is_mock=is_mock,
        data_warnings=warnings,
        analysis=MultiAgentAnalysis(
            pipeline_version=PIPELINE_VERSION,
            agents=_agent_stages(gemini_status, claude_status, finmind_status),
            evidence_packs=evidence_packs,
            gemini_structured=gemini,
            claude_final=claude,
        ),
    )
    if _has_forbidden_advice(response):
        response.analysis.claude_final.manual_review_required.append(
            "系統偵測到輸出可能含有交易動詞，已標記需人工審閱。"
        )
    return response
