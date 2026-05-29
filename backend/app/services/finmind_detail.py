import os
import asyncio
import httpx
from datetime import date, timedelta

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

# Known ETF prefixes/patterns in Taiwan
_ETF_PREFIXES = ("00", "0050", "0056")


def detect_is_etf(symbol: str) -> bool:
    return symbol.startswith("00") or len(symbol) == 6


async def _fetch_dataset(dataset: str, data_id: str, start_date: str, token: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": dataset,
                    "data_id": data_id,
                    "start_date": start_date,
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        if payload.get("status") == 200:
            return payload.get("data", [])
    except Exception:
        pass
    return []


def _build_revenue_summary(data: list[dict]) -> dict:
    if not data:
        return {"status": "no_data", "available_months": 0}

    rows = sorted(data, key=lambda r: r.get("date", ""))
    latest = rows[-1]
    latest_rev = float(latest.get("revenue", 0) or 0)

    yoy_pct = None
    mom_pct = None

    if len(rows) >= 2:
        prev = rows[-2]
        prev_rev = float(prev.get("revenue", 0) or 0)
        if prev_rev:
            mom_pct = round((latest_rev - prev_rev) / prev_rev * 100, 2)

    if len(rows) >= 13:
        year_ago = rows[-13]
        ya_rev = float(year_ago.get("revenue", 0) or 0)
        if ya_rev:
            yoy_pct = round((latest_rev - ya_rev) / ya_rev * 100, 2)

    return {
        "latest_revenue": f"{latest_rev:,.0f}",
        "yoy_pct": yoy_pct,
        "mom_pct": mom_pct,
        "available_months": len(rows),
        "status": "ok",
    }


def _build_valuation_summary(data: list[dict]) -> dict:
    if not data:
        return {"status": "no_data"}

    rows = sorted(data, key=lambda r: r.get("date", ""))
    latest = rows[-1]

    per_raw = latest.get("PER") or latest.get("per")
    pbr_raw = latest.get("PBR") or latest.get("pbr")
    div_raw = latest.get("dividend_yield") or latest.get("DividendYield")

    per = float(per_raw) if per_raw else None
    pbr = float(pbr_raw) if pbr_raw else None
    div_yield = float(div_raw) if div_raw else None

    status = "no_data"
    if per is not None and per > 0:
        if per < 12:
            status = "cheap"
        elif per < 20:
            status = "fair"
        else:
            status = "expensive"

    return {
        "per": per,
        "pbr": pbr,
        "dividend_yield": div_yield,
        "status": status,
    }


def _build_institutional_summary(data: list[dict]) -> dict:
    if not data:
        return {"status": "no_data", "direction": "unknown"}

    foreign = [r for r in data if r.get("name") in ("Foreign_Investor", "Foreign_Dealer_Self")]
    trust = [r for r in data if r.get("name") == "Investment_Trust"]
    dealer = [r for r in data if r.get("name") in ("Dealer_self", "Dealer")]

    def net_n(rows: list[dict], n: int) -> int | None:
        recent = sorted(rows, key=lambda r: r.get("date", ""))[-n:]
        if not recent:
            return None
        total = 0
        for r in recent:
            buy = int(r.get("buy", 0) or 0)
            sell = int(r.get("sell", 0) or 0)
            total += buy - sell
        return total

    f5 = net_n(foreign, 5)
    f10 = net_n(foreign, 10)
    t5 = net_n(trust, 5)
    t10 = net_n(trust, 10)
    d5 = net_n(dealer, 5)

    direction = "unknown"
    if f5 is not None:
        if f5 > 0:
            direction = "net_buy"
        elif f5 < 0:
            direction = "net_sell"
        else:
            direction = "neutral"

    return {
        "foreign_net_5d": f5,
        "foreign_net_10d": f10,
        "trust_net_5d": t5,
        "trust_net_10d": t10,
        "dealer_net_5d": d5,
        "direction": direction,
        "status": "ok",
    }


def _build_chip_risk_summary(margin_data: list[dict], short_data: list[dict]) -> dict:
    # Both margin and short come from TaiwanStockMarginPurchaseShortSale
    # Fields: MarginPurchaseTodayBalance, ShortSaleTodayBalance
    margin_balance = None
    short_balance = None

    if margin_data:
        latest_m = sorted(margin_data, key=lambda r: r.get("date", ""))[-1]
        raw = latest_m.get("MarginPurchaseTodayBalance")
        margin_balance = int(raw) if raw is not None else None

    if short_data:
        latest_s = sorted(short_data, key=lambda r: r.get("date", ""))[-1]
        raw = latest_s.get("ShortSaleTodayBalance")
        short_balance = int(raw) if raw is not None else None

    # Derive risk level from margin/short ratio
    risk_level = "unknown"
    chip_direction = "unknown"
    if margin_balance is not None and short_balance is not None:
        if short_balance > margin_balance * 0.3:
            risk_level = "high"
            chip_direction = "bearish"
        elif short_balance > margin_balance * 0.1:
            risk_level = "medium"
            chip_direction = "neutral"
        else:
            risk_level = "low"
            chip_direction = "bullish"

    status = "ok" if (margin_data or short_data) else "no_data"

    return {
        "margin_balance": margin_balance,
        "short_balance": short_balance,
        "chip_direction": chip_direction,
        "risk_level": risk_level,
        "status": status,
    }


async def get_tw_detail(symbol: str) -> dict:
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_detail()

    end = date.today()
    start_14m = (end - timedelta(days=425)).strftime("%Y-%m-%d")
    start_30d = (end - timedelta(days=30)).strftime("%Y-%m-%d")
    start_2y = (end - timedelta(days=760)).strftime("%Y-%m-%d")

    revenue_task = asyncio.create_task(
        _fetch_dataset("TaiwanStockMonthRevenue", symbol, start_14m, token)
    )
    per_task = asyncio.create_task(
        _fetch_dataset("TaiwanStockPER", symbol, start_30d, token)
    )
    inst_task = asyncio.create_task(
        _fetch_dataset("TaiwanStockInstitutionalInvestorsBuySell", symbol, start_30d, token)
    )
    margin_task = asyncio.create_task(
        _fetch_dataset("TaiwanStockMarginPurchaseShortSale", symbol, start_30d, token)
    )
    cashflow_task = asyncio.create_task(
        _fetch_dataset("TaiwanStockCashFlowsStatement", symbol, start_2y, token)
    )

    revenue_data, per_data, inst_data, margin_data, cashflow_data = await asyncio.gather(
        revenue_task, per_task, inst_task, margin_task, cashflow_task,
        return_exceptions=True,
    )

    def safe(result, default):
        return result if isinstance(result, list) else default

    return {
        "revenue_summary": _build_revenue_summary(safe(revenue_data, [])),
        "valuation_summary": _build_valuation_summary(safe(per_data, [])),
        "institutional_summary": _build_institutional_summary(safe(inst_data, [])),
        "chip_risk_summary": _build_chip_risk_summary(
            safe(margin_data, []), safe(margin_data, [])
        ),
        "cashflow_summary": _build_cashflow_summary(safe(cashflow_data, [])),
    }


def _mock_detail() -> dict:
    return {
        "revenue_summary": {"status": "no_data", "available_months": 0},
        "valuation_summary": {"status": "no_data"},
        "institutional_summary": {"status": "no_data", "direction": "unknown"},
        "chip_risk_summary": {"status": "no_data", "chip_direction": "unknown", "risk_level": "unknown"},
        "cashflow_summary": {"status": "no_data"},
    }


def _build_cashflow_summary(rows: list) -> dict:
    """Latest-quarter cash-flow snapshot from TaiwanStockCashFlowsStatement (long
    format: date/type/value). Free dataset. Values in TWD."""
    if not rows:
        return {"status": "no_data"}
    by_period: dict[str, dict[str, float]] = {}
    for row in rows:
        period = str(row.get("date") or "")[:10]
        type_code = str(row.get("type") or "")
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        by_period.setdefault(period, {})[type_code] = value
    if not by_period:
        return {"status": "no_data"}

    def pick(period: dict[str, float], *codes: str):
        for code in codes:
            if code in period:
                return period[code]
        return None

    periods = sorted(by_period)
    latest = by_period[periods[-1]]
    operating = pick(latest, "CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities")
    investing = pick(latest, "CashProvidedByInvestingActivities")
    financing = pick(latest, "CashFlowsProvidedFromFinancingActivities")
    capex = pick(latest, "PropertyAndPlantAndEquipment")
    free_cf = operating - abs(capex) if (operating is not None and capex is not None) else None

    trend = "unknown"
    if len(periods) >= 2:
        prior = by_period[periods[-2]]
        prior_op = pick(prior, "CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities")
        if operating is not None and prior_op is not None:
            trend = "improving" if operating > prior_op else ("declining" if operating < prior_op else "stable")

    return {
        "status": "ok",
        "period": periods[-1],
        "operating_cash_flow": operating,
        "investing_cash_flow": investing,
        "financing_cash_flow": financing,
        "free_cash_flow": free_cf,
        "operating_cf_positive": (operating is not None and operating > 0),
        "operating_cf_trend": trend,
    }
