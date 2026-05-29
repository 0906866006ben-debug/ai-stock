"""
Taiwan stock chip/institutional analysis.

Analyzes institutional flows: foreign investors, 投信, dealers.
Includes margin financing, short interest.

Uses FinMind API when available, falls back to realistic mock data.
Datasets used:
  TaiwanStockInstitutionalInvestors  — daily rows with name/buy/sell fields
  TaiwanStockMarginPurchaseSale      — margin balance
  TaiwanStockShortSale               — short sale balance
"""
import os
import asyncio
import httpx
from datetime import date, timedelta

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

_MOCK_CHIP_DATA = {
    "2330": {
        "company_name": "台積電",
        "foreign_5d_net": 2500000,
        "foreign_10d_net": 8500000,
        "foreign_20d_net": 15000000,
        "trust_5d_net": 1200000,
        "trust_10d_net": 3800000,
        "dealer_5d_net": -800000,
        "dealer_10d_net": -2500000,
        "margin_balance": 850,
        "margin_balance_change": -15,
        "short_interest": 120,
        "short_interest_change": 5,
        "foreign_accumulation_trend": "accumulating",
        "trust_accumulation_trend": "accumulating",
        "dealer_trend": "distributing",
        "shareholder_concentration": "moderate",
        "major_shareholders_count": 5,
    },
    "0050": {
        "company_name": "元大台灣50",
        "foreign_5d_net": 500000,
        "foreign_10d_net": 1500000,
        "foreign_20d_net": 3000000,
        "trust_5d_net": -300000,
        "trust_10d_net": -800000,
        "dealer_5d_net": 200000,
        "dealer_10d_net": 500000,
        "margin_balance": 450,
        "margin_balance_change": 10,
        "short_interest": 50,
        "short_interest_change": -5,
        "foreign_accumulation_trend": "neutral",
        "trust_accumulation_trend": "distributing",
        "dealer_trend": "neutral",
        "shareholder_concentration": "high",
        "major_shareholders_count": 3,
    },
}


def _mock_chip_data(symbol: str) -> dict:
    if symbol in _MOCK_CHIP_DATA:
        return _MOCK_CHIP_DATA[symbol].copy()
    return {
        "company_name": symbol,
        "foreign_5d_net": 500000,
        "foreign_10d_net": 1500000,
        "foreign_20d_net": 3000000,
        "trust_5d_net": 200000,
        "trust_10d_net": 500000,
        "dealer_5d_net": -100000,
        "dealer_10d_net": -300000,
        "margin_balance": 500,
        "margin_balance_change": 5,
        "short_interest": 50,
        "short_interest_change": 0,
        "foreign_accumulation_trend": "neutral",
        "trust_accumulation_trend": "neutral",
        "dealer_trend": "neutral",
        "shareholder_concentration": "moderate",
        "major_shareholders_count": 5,
    }


def _parse_payload(resp: httpx.Response) -> list[dict]:
    """Return data list from a FinMind response, or [] on any failure."""
    try:
        payload = resp.json()
        if payload.get("status") == 200 and isinstance(payload.get("data"), list):
            return payload["data"]
    except Exception:
        pass
    return []


def _rolling_net(rows: list[dict], n: int) -> int:
    """Sum (buy - sell) for the last n rows, sorted ascending by date."""
    recent = sorted(rows, key=lambda r: r.get("date", ""))[-n:]
    return sum(int(r.get("buy", 0) or 0) - int(r.get("sell", 0) or 0) for r in recent)


def _infer_trend(net_value: int | float) -> str:
    if net_value > 1_000_000:
        return "accumulating"
    if net_value < -1_000_000:
        return "distributing"
    return "neutral"


async def get_tw_chip_analysis(symbol: str) -> tuple[dict, bool]:
    """
    Fetch Taiwan stock chip/institutional analysis data.

    Returns (chip_data_dict, is_mock).
    """
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_chip_data(symbol), True

    start = (date.today() - timedelta(days=35)).strftime("%Y-%m-%d")
    params_base = {"data_id": symbol, "start_date": start, "token": token}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            inst_r, margin_r, share_r = await asyncio.gather(
                client.get(FINMIND_BASE, params={**params_base, "dataset": "TaiwanStockInstitutionalInvestorsBuySell"}),
                client.get(FINMIND_BASE, params={**params_base, "dataset": "TaiwanStockMarginPurchaseShortSale"}),
                client.get(FINMIND_BASE, params={**params_base, "dataset": "TaiwanStockShareholding"}),
            )

        inst_rows = _parse_payload(inst_r)
        margin_rows = _parse_payload(margin_r)
        share_rows = _parse_payload(share_r)
        short_rows = margin_rows  # same dataset contains both margin and short

        if not inst_rows:
            return _mock_chip_data(symbol), True

        # Split institutional rows by investor type
        foreign_rows = [r for r in inst_rows if r.get("name") in ("Foreign_Investor", "Foreign_Dealer_Self")]
        trust_rows   = [r for r in inst_rows if r.get("name") == "Investment_Trust"]
        dealer_rows  = [r for r in inst_rows if r.get("name") in ("Dealer_self", "Dealer", "Dealer_Hedging")]

        foreign_5d  = _rolling_net(foreign_rows, 5)
        foreign_10d = _rolling_net(foreign_rows, 10)
        foreign_20d = _rolling_net(foreign_rows, 20)
        trust_5d    = _rolling_net(trust_rows,   5)
        trust_10d   = _rolling_net(trust_rows,   10)
        dealer_5d   = _rolling_net(dealer_rows,  5)
        dealer_10d  = _rolling_net(dealer_rows,  10)

        # Margin + short balance from TaiwanStockMarginPurchaseShortSale
        # Fields: MarginPurchaseTodayBalance, ShortSaleTodayBalance
        margin_balance = 0
        margin_change  = 0
        short_interest = 0
        short_change   = 0
        if margin_rows:
            sorted_m = sorted(margin_rows, key=lambda r: r.get("date", ""))
            latest_m = sorted_m[-1]
            margin_balance = int(latest_m.get("MarginPurchaseTodayBalance") or 0)
            short_interest = int(latest_m.get("ShortSaleTodayBalance") or 0)
            if len(sorted_m) >= 2:
                prev_m = sorted_m[-2]
                margin_change = margin_balance - int(prev_m.get("MarginPurchaseTodayBalance") or 0)
                short_change  = short_interest - int(prev_m.get("ShortSaleTodayBalance") or 0)

        # Foreign holding ratio (絕對外資持股%) from TaiwanStockShareholding —
        # complements the net-flow numbers with the absolute ownership level.
        foreign_holding_ratio = None
        foreign_holding_ratio_change = None
        if share_rows:
            sorted_s = sorted(share_rows, key=lambda r: r.get("date", ""))
            def _ratio(row: dict) -> float | None:
                try:
                    return float(row.get("ForeignInvestmentSharesRatio"))
                except (TypeError, ValueError):
                    return None
            foreign_holding_ratio = _ratio(sorted_s[-1])
            if len(sorted_s) >= 2 and foreign_holding_ratio is not None:
                prev_ratio = _ratio(sorted_s[-2])
                if prev_ratio is not None:
                    foreign_holding_ratio_change = round(foreign_holding_ratio - prev_ratio, 4)

        chip_data = {
            "company_name": symbol,
            "foreign_holding_ratio": foreign_holding_ratio,
            "foreign_holding_ratio_change": foreign_holding_ratio_change,
            "foreign_5d_net": foreign_5d,
            "foreign_10d_net": foreign_10d,
            "foreign_20d_net": foreign_20d,
            "trust_5d_net": trust_5d,
            "trust_10d_net": trust_10d,
            "dealer_5d_net": dealer_5d,
            "dealer_10d_net": dealer_10d,
            "margin_balance": margin_balance,
            "margin_balance_change": margin_change,
            "short_interest": short_interest,
            "short_interest_change": short_change,
            "foreign_accumulation_trend": _infer_trend(foreign_5d),
            "trust_accumulation_trend": _infer_trend(trust_5d),
            "dealer_trend": _infer_trend(dealer_5d),
            "shareholder_concentration": "moderate",
            "major_shareholders_count": 5,
        }
        return chip_data, False

    except Exception:
        return _mock_chip_data(symbol), True
