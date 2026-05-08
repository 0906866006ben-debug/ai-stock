"""
Taiwan stock chip/institutional analysis.

Analyzes institutional flows: foreign investors, 投信, dealers.
Includes margin financing, short interest, major shareholders.

Uses FinMind API when available, falls back to realistic mock data.
"""
import os
import httpx
from datetime import date, timedelta

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

# Mock institutional data
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
    """Generate realistic mock chip/institutional data."""
    if symbol in _MOCK_CHIP_DATA:
        return _MOCK_CHIP_DATA[symbol].copy()

    # Generic mock for unknown symbols
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


async def get_tw_chip_analysis(symbol: str) -> tuple[dict, bool]:
    """
    Fetch Taiwan stock chip/institutional analysis data.

    Returns: (chip_data_dict, is_mock)

    chip_data_dict keys:
      company_name, foreign_5d_net, foreign_10d_net, foreign_20d_net,
      trust_5d_net, trust_10d_net, dealer_5d_net, dealer_10d_net,
      margin_balance, margin_balance_change,
      short_interest, short_interest_change,
      foreign_accumulation_trend, trust_accumulation_trend, dealer_trend,
      shareholder_concentration, major_shareholders_count
    """
    token = os.getenv("FINMIND_API_KEY")
    if not token:
        return _mock_chip_data(symbol), True

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to fetch institutional data
            resp = await client.get(
                FINMIND_BASE,
                params={
                    "dataset": "TaiwanStockInstitutional",
                    "data_id": symbol,
                    "token": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

            if payload.get("status") != 200 or not payload.get("data"):
                return _mock_chip_data(symbol), True

            # Parse institutional data
            latest_data = payload["data"][-1] if isinstance(payload["data"], list) else payload["data"]

            chip_data = {
                "company_name": symbol,
                "foreign_5d_net": int(latest_data.get("foreign_5d", 0)) if latest_data.get("foreign_5d") else 0,
                "foreign_10d_net": int(latest_data.get("foreign_10d", 0)) if latest_data.get("foreign_10d") else 0,
                "foreign_20d_net": int(latest_data.get("foreign_20d", 0)) if latest_data.get("foreign_20d") else 0,
                "trust_5d_net": int(latest_data.get("trust_5d", 0)) if latest_data.get("trust_5d") else 0,
                "trust_10d_net": int(latest_data.get("trust_10d", 0)) if latest_data.get("trust_10d") else 0,
                "dealer_5d_net": int(latest_data.get("dealer_5d", 0)) if latest_data.get("dealer_5d") else 0,
                "dealer_10d_net": int(latest_data.get("dealer_10d", 0)) if latest_data.get("dealer_10d") else 0,
                "margin_balance": float(latest_data.get("margin_balance", 0)) if latest_data.get("margin_balance") else 0,
                "margin_balance_change": float(latest_data.get("margin_change", 0)) if latest_data.get("margin_change") else 0,
                "short_interest": float(latest_data.get("short_interest", 0)) if latest_data.get("short_interest") else 0,
                "short_interest_change": float(latest_data.get("short_change", 0)) if latest_data.get("short_change") else 0,
                "foreign_accumulation_trend": _infer_trend(latest_data.get("foreign_5d", 0)),
                "trust_accumulation_trend": _infer_trend(latest_data.get("trust_5d", 0)),
                "dealer_trend": _infer_trend(latest_data.get("dealer_5d", 0)),
                "shareholder_concentration": latest_data.get("concentration", "moderate"),
                "major_shareholders_count": int(latest_data.get("major_count", 5)) if latest_data.get("major_count") else 5,
            }

            return chip_data, False

    except Exception:
        return _mock_chip_data(symbol), True


def _infer_trend(net_value: int | float) -> str:
    """Infer accumulation/distribution trend from net buying value."""
    if net_value > 1000000:
        return "accumulating"
    elif net_value < -1000000:
        return "distributing"
    else:
        return "neutral"
