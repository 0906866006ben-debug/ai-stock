"""每日交易機會（Daily Opportunities）— 單一長線價值選股桶的線上 MVP。

中線桶已於 2026-07-04 退役（樣本外 T+60≈0，Docs/backtest/experiments_ledger.md
Iteration 1b）；系統收斂為長線桶為唯一選股桶 + 短線時點疊加。

Strategy basis: Docs/research/tw_screening_strategy_full_v2_2026-07-02.md
  長線桶: 價值綜合（益本比/殖利率/PBR 百分位）+ 營收成長為正確認 → S/A/B 分級。
          選股力經 dev+OOS 對齊回測（experiments_ledger Iteration 1b/2）：金融排除後
          OOS A T+250 約 +2.6%（輕微高估）。
  短線:   非獨立桶——長線候選中出現進場時點訊號（營收創高公告窗、外資大額買超）

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
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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
# FinMind TaiwanStockInfo industry labels (verified 2026-07-04): the sector is
# "金融保險" (NOT "金融保險業") — the old label never matched, silently leaking
# banks/FHCs into the value pool where their structurally low PBR ranks them
# artificially cheap. Exclude financials + DRs (aligned with the backtest universe).
EXCLUDED_INDUSTRIES = {"金融保險", "金融業", "存託憑證"}

LONG_SHORTLIST = 60

# 中線桶（CANSLIM 領導股）快照：本機正典資料庫計算、隨 repo 部署（雲端無正典 DB）。
# 訊號=experiments_ledger Iteration 4；該回測 FAIL（T+60 excu +1.4% 未達 +2% 門檻、
# 逐事件輸 TAIEX）→ 本桶僅為「條件觀察名單」，端點必須攜帶誠實標註。
_LEADER_SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "leader_snapshot.json"


def _load_leader_snapshot() -> dict | None:
    try:
        return json.loads(_LEADER_SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


async def _merge_ai_picks(core: dict) -> dict:
    """疊加 AI 每日精選（自帶當日快取；失敗→誠實 unavailable，不影響量化桶）。"""
    from backend.app.services.tw_ai_daily_picks import get_ai_daily_picks
    out = dict(core)
    try:
        picks = await get_ai_daily_picks(core)
    except Exception:  # noqa: BLE001
        picks = None
    out["ai_picks"] = picks if picks else {"status": "unavailable"}
    return out


async def get_daily_opportunities() -> dict:
    today = date.today().strftime("%Y-%m-%d")
    cached = file_cache.load(_CACHE_NS, today)
    if isinstance(cached, dict):
        return await _merge_ai_picks(cached)

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

        token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")

        # ── 長線桶（唯一選股桶）：價值綜合排名 + 營收成長確認 ──
        pool = [(sid, b) for sid, b in buyable.items()
                if (b.get("per") or 0) > 0 and (b.get("yield") or 0) > 0 and (b.get("pbr") or 0) > 0]
        ranked = _value_rank(pool)
        long_short = ranked[:LONG_SHORTLIST]
        rev_map = await _fetch_revenues(client, [sid for sid, _, _ in long_short], token)

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

        # ── 短線＝進場時點觀察訊號（依附於長線候選，非獨立桶）──
        short_items = []
        for it in long_items:
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
                    "from_bucket": "long", "triggers": triggers,
                }))

        # ── 中線桶（CANSLIM 領導股，快照制；未達驗證門檻的觀察名單）──
        mid_items = []
        mid_meta: dict = {}
        snap = _load_leader_snapshot()
        if snap and snap.get("items"):
            stale_days = (date.today() - date.fromisoformat(snap["as_of"])).days
            mid_meta = {
                "as_of": snap["as_of"],
                "regime_on": snap.get("regime_on"),
                "stale": stale_days > 7,
            }
            for it in snap["items"]:
                sid = it["stock_id"]
                live = buyable.get(sid) or {}
                info = info_map.get(sid) or {}
                mid_items.append({
                    "stock_id": sid,
                    "name": live.get("name") or info.get("n") or sid,
                    "close": live.get("close") or it["close"],
                    "change_pct": live.get("change_pct"),
                    "industry": live.get("industry") or info.get("i") or "",
                    "grade": it["grade"],
                    "radar": bool(it.get("radar")),
                    "basis": it["basis"] + f"（快照 {snap['as_of']}）",
                    "metrics": it["metrics"],
                })

    result = {
        "status": "ok",
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_total": len(quotes),
        "buyable_count": len(buyable),
        "buckets": {
            "long": long_items[:20],
            "mid": mid_items[:20],
            "short": short_items[:15],
        },
        "mid_meta": mid_meta,
        "strategy_basis": "Docs/research/tw_screening_strategy_full_v2_2026-07-02.md；驗證：Docs/backtest/experiments_ledger.md Iteration 1b/2",
        "notices": [
            "本清單為長線價值選股（價值綜合分位 × 營收成長為正）符合條件的候選觀察名單與支持數據，非投資建議。",
            "選股力已回測（vs 可買池中位、次日開盤進場、扣 0.585% 成本）：開發期 2012-21 長線 A 級 T+250 約 +4.4%、80% 正年度；樣本外 2022-26 約 +2.6%、60% 正年度（5 年中 3 年）。",
            "已稽核無前視／資料洩漏，但下市樣本覆蓋不全與未還原除息使數字為「輕微高估」，且近年（2025-26）走弱、樣本偏小——不可視為已證實的獲利能力。",
            "短線區為長線候選中出現的進場時點觀察訊號（營收創高公告窗、外資大額買超），非獨立策略。",
            "中線桶（CANSLIM 領導股：貼近 252 日高點 × 月營收加速 × 帶量 × 大盤在 100 日線上）為條件觀察名單："
            "回測（2012-21，n=5,561）T+60 選股力中位 +1.4% 未達事前註冊門檻 +2%（10/10 年為正但量薄），"
            "且逐事件對市值加權大盤為負——未達驗證門檻、非已驗證選股力，分級 S/A/B 亦未經分級別驗證。",
            "中線桶以本機資料快照計算（見各項『快照』日期），非即時；快照過舊時請以其日期判讀。",
            "MVP 覆蓋範圍：僅上市（TWSE）個股，已排除金融保險與存託憑證。",
            "本分析僅供參考，不構成投資建議。",
        ],
    }
    file_cache.save(_CACHE_NS, today, result)
    return await _merge_ai_picks(result)


# ────────────────────────── helpers ──────────────────────────

def _item(sid: str, b: dict, grade: str, basis: str, metrics: dict) -> dict:
    return {
        "stock_id": sid, "name": b["name"], "close": b["close"],
        "change_pct": b.get("change_pct"), "industry": b.get("industry") or "",
        "grade": grade, "basis": basis, "metrics": metrics,
    }


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
