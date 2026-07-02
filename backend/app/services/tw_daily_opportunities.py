"""每日交易機會（Daily Opportunities）— 研究報告 v2 三桶規則的線上 MVP。

Strategy basis: Docs/research/tw_screening_strategy_full_v2_2026-07-02.md
  中線桶: 月營收 YoY 動能 × 外資/投信連買（雙確認）→ S/A/B/C 分級
  長線桶: 價值綜合（益本比/殖利率/PBR 百分位）+ 營收成長確認（F-Score 待接入）
  短線:   非獨立桶——僅作進場時點觀察訊號（營收創高公告窗、外資大額買超）

Data architecture (cloud-safe, no local DB):
  - TWSE STOCK_DAY_ALL  (free, all TWSE stocks, daily OHLCV/turnover)
  - TWSE BWIBBU_ALL     (free, all TWSE stocks, PER/PBR/dividend yield)
  - TWSE RWD T86        (free, all-market institutional net buy per day)
  - FinMind MonthRevenue (per-stock, ONLY for the shortlisted candidates,
    bounded ~<=160 calls/day, well within the free-tier rate limit)

Honesty contract:
  - All user-facing strings are verb-free condition descriptions (no 買/賣).
  - Output carries explicit notices: rules are research-derived but the
    simplified forward-return backtest has NOT been run/audited yet, and
    which filters of the report are not yet implemented in this MVP.
  - Whole result cached once per UTC day; T86 per-date cached permanently.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import httpx

from backend.app.services import file_cache
from backend.app.services.tw_market_heatmap import _stock_info_map

_CACHE_NS = "daily_opps"
_T86_NS = "t86_day"
_REV_NS = "opps_rev"

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

# ── Buyable checklist thresholds (report §4; some items MVP-deferred) ──
MIN_PRICE = 10.0
MIN_TURNOVER = 30_000_000  # 日成交值 3,000 萬
EXCLUDED_INDUSTRIES = {"金融保險業", "存託憑證", "金融業"}

MID_SHORTLIST = 100
LONG_SHORTLIST = 60


async def get_daily_opportunities() -> dict:
    today = date.today().strftime("%Y-%m-%d")
    cached = file_cache.load(_CACHE_NS, today)
    if isinstance(cached, dict):
        return cached

    async with httpx.AsyncClient(timeout=30.0) as client:
        quotes, valuation = await asyncio.gather(
            _twse_day_all(client), _twse_bwibbu(client)
        )
        if not quotes:
            return {"status": "no_data", "date": today, "detail": "TWSE 全市場行情不可用"}
        t86 = await _t86_recent_days(client, days=10)

        info_map = _stock_info_map()

        # ── 可買性篩查（報告 §4 的 MVP 子集）──
        buyable: dict[str, dict] = {}
        for sid, q in quotes.items():
            if q["close"] < MIN_PRICE or q["turnover"] < MIN_TURNOVER:
                continue
            info = info_map.get(sid) or {}
            industry = info.get("i") or ""
            name = q["name"] or info.get("n") or sid
            if industry in EXCLUDED_INDUSTRIES or name.endswith("KY") or "DR" in sid:
                continue
            if not sid.isdigit() or len(sid) != 4:  # 排除 ETF/權證/特別股
                continue
            v = valuation.get(sid) or {}
            buyable[sid] = {
                "name": name, "industry": industry, **q,
                "per": v.get("per"), "pbr": v.get("pbr"), "yield": v.get("yield"),
                "foreign_streak": _streak(t86.get(sid, {}).get("foreign", [])),
                "trust_streak": _streak(t86.get(sid, {}).get("trust", [])),
                "foreign_net_5d": sum((t86.get(sid, {}).get("foreign", []) or [])[:5]),
                "foreign_net_today": (t86.get(sid, {}).get("foreign") or [0])[0],
            }

        # ── 中線桶候選：法人連買預篩 → FinMind 營收確認 ──
        pre = [
            (sid, b) for sid, b in buyable.items()
            if b["foreign_streak"] >= 3 or b["trust_streak"] >= 3
        ]
        pre.sort(key=lambda x: (x[1]["foreign_streak"], x[1]["foreign_net_5d"]), reverse=True)
        mid_candidates = pre[:MID_SHORTLIST]

        token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
        rev_map = await _fetch_revenues(client, [sid for sid, _ in mid_candidates], token)

        mid_items = []
        for sid, b in mid_candidates:
            rev = rev_map.get(sid)
            if not rev:
                continue
            grade = _grade_mid(rev, b)
            if grade is None:
                continue
            mid_items.append(_item(sid, b, grade, _mid_basis(rev, b), {
                "revenue_yoy": rev["yoy"], "yoy_streak_months": rev["yoy_streak"],
                "revenue_14m_high": rev["new_high"], "revenue_month": rev["month"],
                "foreign_streak_days": b["foreign_streak"], "trust_streak_days": b["trust_streak"],
                "foreign_net_5d_shares": b["foreign_net_5d"],
            }))
        mid_items.sort(key=lambda x: ("SABC".index(x["grade"]), -(x["metrics"]["revenue_yoy"] or 0)))

        # ── 長線桶：價值綜合排名 + 營收成長確認 ──
        pool = [(sid, b) for sid, b in buyable.items()
                if (b.get("per") or 0) > 0 and (b.get("yield") or 0) > 0 and (b.get("pbr") or 0) > 0]
        ranked = _value_rank(pool)
        long_short = ranked[:LONG_SHORTLIST]
        need = [sid for sid, _, _ in long_short if sid not in rev_map]
        rev_map.update(await _fetch_revenues(client, need, token))

        long_items = []
        for sid, b, score in long_short:
            rev = rev_map.get(sid)
            if not rev or (rev["yoy"] is None) or rev["yoy"] <= 0:
                continue
            grade = "S" if (score >= 0.85 and rev["yoy"] >= 10) else ("A" if score >= 0.75 else "B")
            long_items.append(_item(sid, b, grade, _long_basis(b, rev, score), {
                "value_score": round(score, 3), "per": b["per"], "pbr": b["pbr"],
                "dividend_yield": b["yield"], "revenue_yoy": rev["yoy"],
            }))
        long_items.sort(key=lambda x: ("SABC".index(x["grade"]), -x["metrics"]["value_score"]))

        # ── 短線＝進場時點觀察訊號（依附於中線候選）──
        short_items = []
        for it in mid_items:
            sid = it["stock_id"]
            b = buyable[sid]
            rev = rev_map.get(sid) or {}
            triggers = []
            if rev.get("new_high") and _in_announcement_window(rev.get("month")):
                triggers.append("月營收創14個月新高且處於公告後漂移窗（約20個交易日）")
            approx_value = abs(b["foreign_net_today"]) * b["close"]
            if b["foreign_net_today"] > 0 and b["turnover"] and approx_value >= 0.05 * b["turnover"]:
                triggers.append("外資今日買超金額約占當日成交值 5% 以上")
            if triggers:
                short_items.append(_item(sid, b, it["grade"], "；".join(triggers), {
                    "from_bucket": "mid", "triggers": triggers,
                }))

    result = {
        "status": "ok",
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_total": len(quotes),
        "buyable_count": len(buyable),
        "buckets": {
            "short": short_items[:15],
            "mid": mid_items[:20],
            "long": long_items[:20],
        },
        "strategy_basis": "Docs/research/tw_screening_strategy_full_v2_2026-07-02.md",
        "notices": [
            "本清單為符合研究報告 v2 條件的候選觀察名單與其支持數據，非投資建議。",
            "回測驗證與稽核尚未完成——分級規則為文獻起點參數，未經我方資料驗證，不可視為已證實的獲利能力。",
            "MVP 覆蓋範圍：僅上市（TWSE）個股；市值門檻、MAX 樂透股濾網、IVOL 濾網、F-Score 尚未接入。",
            "本分析僅供參考，不構成投資建議。",
        ],
    }
    file_cache.save(_CACHE_NS, today, result)
    return result


# ────────────────────────── helpers ──────────────────────────

def _item(sid: str, b: dict, grade: str, basis: str, metrics: dict) -> dict:
    return {
        "stock_id": sid, "name": b["name"], "close": b["close"],
        "change_pct": b.get("change_pct"), "industry": b.get("industry") or "",
        "grade": grade, "basis": basis, "metrics": metrics,
    }


def _grade_mid(rev: dict, b: dict) -> str | None:
    yoy, streak = rev["yoy"], rev["yoy_streak"]
    if yoy is None:
        return None
    inst = max(b["foreign_streak"], b["trust_streak"])
    if yoy >= 30 and streak >= 3 and b["foreign_streak"] >= 5:
        return "S"
    if yoy >= 10 and streak >= 2 and inst >= 3:
        return "A"
    if yoy > 0 and inst >= 3:
        return "B"
    if yoy > 0 or b["foreign_streak"] >= 3:
        return "C"
    return None


def _mid_basis(rev: dict, b: dict) -> str:
    parts = [f"月營收 YoY {rev['yoy']:+.1f}%（{rev['month']}）"]
    if rev["yoy_streak"] >= 2:
        parts.append(f"YoY 連續 {rev['yoy_streak']} 個月為正")
    if rev["new_high"]:
        parts.append("營收為近14個月新高")
    if b["foreign_streak"] >= 3:
        parts.append(f"外資連續買超 {b['foreign_streak']} 日")
    if b["trust_streak"] >= 3:
        parts.append(f"投信連續買超 {b['trust_streak']} 日")
    return "；".join(parts)


def _long_basis(b: dict, rev: dict, score: float) -> str:
    return (
        f"價值綜合分位 {score:.0%}（PER {b['per']:.1f}、PBR {b['pbr']:.2f}、殖利率 {b['yield']:.2f}%）；"
        f"月營收 YoY {rev['yoy']:+.1f}% 為正"
    )


def _value_rank(pool: list) -> list:
    """Average percentile of earnings yield (1/PER), dividend yield, 1/PBR."""
    if not pool:
        return []
    def pct_ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        ranks = [0.0] * len(vals)
        for pos, i in enumerate(order):
            ranks[i] = pos / max(len(vals) - 1, 1)
        return ranks
    ey = pct_ranks([1.0 / b["per"] for _, b in pool])
    dy = pct_ranks([b["yield"] for _, b in pool])
    bp = pct_ranks([1.0 / b["pbr"] for _, b in pool])
    scored = [(sid, b, (ey[i] + dy[i] + bp[i]) / 3) for i, (sid, b) in enumerate(pool)]
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored


def _streak(nets: list) -> int:
    n = 0
    for v in nets:
        if v > 0:
            n += 1
        else:
            break
    return n


def _in_announcement_window(rev_month: str | None) -> bool:
    """月營收於次月10日前公告；公告後約一個月視為漂移觀察窗。"""
    if not rev_month:
        return False
    try:
        y, m = int(rev_month[:4]), int(rev_month[5:7])
    except ValueError:
        return False
    announce = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 10)
    return announce <= date.today() <= announce + timedelta(days=32)


# ────────────────────────── data fetchers ──────────────────────────

async def _twse_day_all(client: httpx.AsyncClient) -> dict[str, dict]:
    try:
        r = await client.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            headers={"accept": "application/json"},
        )
        r.raise_for_status()
        rows = r.json()
    except Exception:
        return {}
    out = {}
    for row in rows:
        try:
            sid = str(row.get("Code") or "").strip()
            close = float(row.get("ClosingPrice") or 0)
            change = float(row.get("Change") or 0)
            turnover = float(row.get("TradeValue") or 0)
        except (TypeError, ValueError):
            continue
        prev = close - change
        if not sid or close <= 0:
            continue
        out[sid] = {
            "name": str(row.get("Name") or "").strip(), "close": close,
            "turnover": turnover,
            "change_pct": round(change / prev * 100, 2) if prev > 0 else None,
        }
    return out


async def _twse_bwibbu(client: httpx.AsyncClient) -> dict[str, dict]:
    try:
        r = await client.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
            headers={"accept": "application/json"},
        )
        r.raise_for_status()
        rows = r.json()
    except Exception:
        return {}
    out = {}
    for row in rows:
        sid = str(row.get("Code") or "").strip()
        def num(key):
            try:
                v = float(row.get(key) or 0)
                return v if v > 0 else None
            except (TypeError, ValueError):
                return None
        if sid:
            out[sid] = {"per": num("PEratio"), "pbr": num("PBratio"), "yield": num("DividendYield")}
    return out


async def _t86_recent_days(client: httpx.AsyncClient, days: int = 10) -> dict[str, dict]:
    """Last N trading days of institutional net-buy, most-recent-first.
    Each trading date's table is cached permanently (it never changes)."""
    per_day: list[dict[str, tuple[int, int]]] = []
    d = date.today()
    scanned = 0
    while len(per_day) < days and scanned < 25:
        key = d.strftime("%Y%m%d")
        table = file_cache.load(_T86_NS, key)
        if table is None:
            table = await _t86_one_day(client, key)
            # cache even empty ({}) so weekends/holidays are not re-fetched,
            # except today (data may appear after market close)
            if table or d != date.today():
                file_cache.save(_T86_NS, key, table or {})
        if table:
            per_day.append(table)
        d -= timedelta(days=1)
        scanned += 1

    merged: dict[str, dict] = {}
    for day_table in per_day:
        for sid, (f, t) in day_table.items():
            m = merged.setdefault(sid, {"foreign": [], "trust": []})
            m["foreign"].append(f)
            m["trust"].append(t)
    # 補零對齊：某日缺席（如處置停牌）視為 0
    for m in merged.values():
        while len(m["foreign"]) < len(per_day):
            m["foreign"].append(0)
            m["trust"].append(0)
    return merged


async def _t86_one_day(client: httpx.AsyncClient, yyyymmdd: str) -> dict[str, tuple[int, int]]:
    try:
        r = await client.get(
            "https://www.twse.com.tw/rwd/zh/fund/T86",
            params={"date": yyyymmdd, "selectType": "ALLBUT0999", "response": "json"},
        )
        r.raise_for_status()
        j = r.json()
    except Exception:
        return {}
    if j.get("stat") != "OK":
        return {}
    fields = j.get("fields", [])
    try:
        i_sid = fields.index("證券代號")
        i_foreign = next(i for i, f in enumerate(fields) if "外陸資買賣超股數" in f)
        i_trust = next(i for i, f in enumerate(fields) if f == "投信買賣超股數")
    except (ValueError, StopIteration):
        return {}
    out = {}
    for row in j.get("data", []):
        try:
            sid = str(row[i_sid]).strip()
            f = int(str(row[i_foreign]).replace(",", ""))
            t = int(str(row[i_trust]).replace(",", ""))
            out[sid] = (f, t)
        except (ValueError, IndexError, TypeError):
            continue
    return out


async def _fetch_revenues(client: httpx.AsyncClient, sids: list[str], token: str | None) -> dict[str, dict]:
    """14-month revenue per shortlisted stock via FinMind (bounded, cached/day)."""
    if not token or not sids:
        return {}
    today = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=430)).isoformat()
    sem = asyncio.Semaphore(8)
    out: dict[str, dict] = {}

    async def one(sid: str):
        cached = file_cache.load(_REV_NS, f"{sid}_{today}")
        if isinstance(cached, dict):
            out[sid] = cached
            return
        async with sem:
            try:
                r = await client.get(FINMIND_BASE, params={
                    "dataset": "TaiwanStockMonthRevenue", "data_id": sid,
                    "start_date": start, "token": token,
                })
                j = r.json()
            except Exception:
                return
        rows = j.get("data") or []
        if j.get("status") != 200 or len(rows) < 13:
            return
        rows.sort(key=lambda x: x.get("date", ""))
        revs = [float(x.get("revenue") or 0) for x in rows]
        yoy = round((revs[-1] / revs[-13] - 1) * 100, 2) if revs[-13] else None
        streak = 0
        for k in range(len(revs) - 1, 12, -1):
            if revs[k - 12] and revs[k] > revs[k - 12]:
                streak += 1
            else:
                break
        rec = {
            "yoy": yoy, "yoy_streak": streak,
            "new_high": revs[-1] >= max(revs),
            "month": str(rows[-1].get("date", ""))[:7],
        }
        out[sid] = rec
        file_cache.save(_REV_NS, f"{sid}_{today}", rec)

    await asyncio.gather(*(one(s) for s in sids))
    return out
