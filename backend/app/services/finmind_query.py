"""Generic FinMind dataset query proxy for the in-app FinMind playground.

The FinMind token stays server-side (never sent to the browser). Datasets are
allow-listed so the endpoint is a curated explorer, not an open proxy. Follows
FinMind's IP-ban policy: 402 = quota exceeded (back off, do not hammer), 403 =
IP banned (~30 min), 400/401 = token problem (do NOT retry). We never retry here
— a single request per call — so this path can never trigger a ban by looping.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

FINMIND_DATA_URL = "https://api.finmindtrade.com/api/v4/data"

# Curated, grouped allow-list. label = zh display; paid = backer/sponsor only.
DATASET_GROUPS: dict[str, list[dict[str, Any]]] = {
    "技術面": [
        {"name": "TaiwanStockPrice", "label": "個股日K (還原前)", "paid": False},
        {"name": "TaiwanStockPriceAdj", "label": "個股還原日K", "paid": False},
        {"name": "TaiwanStockPER", "label": "PER / PBR / 殖利率", "paid": False},
        {"name": "TaiwanStockKBar", "label": "分K資料", "paid": True},
    ],
    "籌碼面": [
        {"name": "TaiwanStockInstitutionalInvestorsBuySell", "label": "三大法人買賣超", "paid": False},
        {"name": "TaiwanStockMarginPurchaseShortSale", "label": "融資融券", "paid": False},
        {"name": "TaiwanStockShareholding", "label": "外資持股比例", "paid": False},
        {"name": "TaiwanStockSecuritiesLending", "label": "借券", "paid": False},
        {"name": "TaiwanStockHoldingSharesPer", "label": "股權分散表", "paid": True},
        {"name": "TaiwanStockTradingDailyReportSecIdAgg", "label": "券商分點彙總", "paid": True},
    ],
    "基本面": [
        {"name": "TaiwanStockMonthRevenue", "label": "月營收", "paid": False},
        {"name": "TaiwanStockFinancialStatements", "label": "綜合損益表", "paid": False},
        {"name": "TaiwanStockBalanceSheet", "label": "資產負債表", "paid": False},
        {"name": "TaiwanStockCashFlowsStatement", "label": "現金流量表", "paid": False},
        {"name": "TaiwanStockDividend", "label": "股利政策", "paid": False},
        {"name": "TaiwanStockDividendResult", "label": "除權息結果", "paid": False},
        {"name": "TaiwanStockMarketValue", "label": "市值", "paid": True},
    ],
    "衍生性 / 期貨": [
        {"name": "TaiwanFuturesDaily", "label": "期貨日成交", "paid": False},
        {"name": "TaiwanOptionDaily", "label": "選擇權日成交", "paid": False},
        {"name": "TaiwanFuturesInstitutionalInvestors", "label": "三大法人期貨未平倉", "paid": False},
        {"name": "TaiwanOptionInstitutionalInvestors", "label": "三大法人選擇權", "paid": False},
    ],
    "其他": [
        {"name": "TaiwanStockInfo", "label": "台股總覽", "paid": False},
        {"name": "TaiwanStockDelisting", "label": "下市公司", "paid": False},
        {"name": "TaiwanStockSplitPrice", "label": "分割參考價", "paid": False},
        {"name": "TaiwanStockNews", "label": "個股新聞", "paid": True},
        {"name": "TaiwanStockGovernmentBankBuySell", "label": "八大行庫買賣", "paid": False},
    ],
}

ALLOWED_DATASETS: frozenset[str] = frozenset(
    item["name"] for group in DATASET_GROUPS.values() for item in group
)


async def query_finmind(
    dataset: str,
    *,
    data_id: str = "",
    start_date: str = "",
    end_date: str = "",
    row_limit: int = 500,
) -> dict[str, Any]:
    """One FinMind /data request. Returns a structured envelope; never raises and
    never retries (loop-free → cannot trigger an IP ban)."""
    if dataset not in ALLOWED_DATASETS:
        return {"dataset": dataset, "status": "not_allowed", "msg": "dataset 不在允許清單", "rows": [], "columns": [], "count": 0}

    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    if not token:
        return {"dataset": dataset, "status": "no_token", "msg": "FINMIND_API_KEY 未設定", "rows": [], "columns": [], "count": 0}

    params: dict[str, str] = {"dataset": dataset, "token": token}
    if data_id:
        params["data_id"] = data_id.strip()
    if start_date:
        params["start_date"] = start_date.strip()
    if end_date:
        params["end_date"] = end_date.strip()

    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = await client.get(FINMIND_DATA_URL, params=params)
    except Exception as exc:
        return {"dataset": dataset, "status": "network_error", "msg": str(exc)[:200], "rows": [], "columns": [], "count": 0}

    # FinMind status semantics (see BanIPPolicy): 402 quota, 403 banned, 400/401 token.
    if resp.status_code == 402:
        return {"dataset": dataset, "status": "rate_limited", "msg": "已達免費層流量上限（每小時約 600 次），請稍後再試", "rows": [], "columns": [], "count": 0}
    if resp.status_code == 403:
        return {"dataset": dataset, "status": "ip_banned", "msg": "IP 被暫時封鎖（約 30 分鐘自動解除），勿重複重試", "rows": [], "columns": [], "count": 0}
    if resp.status_code in (400, 401):
        detail = ""
        try:
            detail = str((resp.json() or {}).get("msg") or "").strip()
        except ValueError:
            detail = ""
        low = detail.lower()
        if "level" in low:  # paid dataset queried with a free/insufficient token
            return {"dataset": dataset, "status": "needs_paid_plan", "msg": f"此資料集需更高的 FinMind 方案：{detail}", "rows": [], "columns": [], "count": 0}
        return {"dataset": dataset, "status": "param_error", "msg": detail or "參數或 token 問題（請勿重試，先檢查設定）", "rows": [], "columns": [], "count": 0}

    try:
        payload = resp.json()
    except ValueError:
        return {"dataset": dataset, "status": "bad_response", "msg": "回應非 JSON", "rows": [], "columns": [], "count": 0}

    rows = payload.get("data") or []
    if payload.get("status") != 200 and not rows:
        msg = str(payload.get("msg") or "no data")
        # A paid dataset on a free token comes back here — surface it plainly.
        return {"dataset": dataset, "status": "empty_or_unauthorized", "msg": msg[:200], "rows": [], "columns": [], "count": 0}

    columns = list(rows[0].keys()) if rows else []
    return {
        "dataset": dataset,
        "status": "ok",
        "msg": "",
        "total": len(rows),
        "count": min(len(rows), row_limit),
        "columns": columns,
        "rows": rows[:row_limit],
    }
