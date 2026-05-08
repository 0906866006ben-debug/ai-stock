"""Taiwan ETF holdings + sector weights.

Curated coverage for the most-traded Taiwan ETFs. Issuer scrapers are
stubbed — fall back to curated mock data so the UI is always stable.
"""
from __future__ import annotations

# Curated mock holdings reflecting publicly-known recent compositions.
# These are quarterly-stable, low-maintenance baseline values; intended as
# fallback when issuer fetches fail.
_CURATED: dict[str, dict] = {
    "0050": {
        "fund_name": "元大台灣50",
        "total_constituents": 50,
        "last_updated": "2026-04-30",
        "holdings": [
            {"stock_code": "2330", "company_name": "台積電", "weight_pct": 53.0, "shares": None},
            {"stock_code": "2317", "company_name": "鴻海",   "weight_pct":  4.5, "shares": None},
            {"stock_code": "2454", "company_name": "聯發科", "weight_pct":  3.8, "shares": None},
            {"stock_code": "2308", "company_name": "台達電", "weight_pct":  2.6, "shares": None},
            {"stock_code": "2382", "company_name": "廣達",   "weight_pct":  2.4, "shares": None},
            {"stock_code": "2891", "company_name": "中信金", "weight_pct":  1.6, "shares": None},
            {"stock_code": "2412", "company_name": "中華電", "weight_pct":  1.5, "shares": None},
            {"stock_code": "2882", "company_name": "國泰金", "weight_pct":  1.4, "shares": None},
            {"stock_code": "2881", "company_name": "富邦金", "weight_pct":  1.3, "shares": None},
            {"stock_code": "3711", "company_name": "日月光投控", "weight_pct": 1.2, "shares": None},
        ],
        "sector_weights": [
            {"sector": "半導體",   "weight_pct": 65.0},
            {"sector": "電子零組件", "weight_pct": 9.0},
            {"sector": "金融",     "weight_pct": 8.5},
            {"sector": "電腦週邊",  "weight_pct": 5.5},
            {"sector": "電信",     "weight_pct": 2.0},
            {"sector": "其他",     "weight_pct": 10.0},
        ],
    },
    "0056": {
        "fund_name": "元大高股息",
        "total_constituents": 50,
        "last_updated": "2026-04-30",
        "holdings": [
            {"stock_code": "2382", "company_name": "廣達",     "weight_pct": 5.0, "shares": None},
            {"stock_code": "3231", "company_name": "緯創",     "weight_pct": 4.8, "shares": None},
            {"stock_code": "2376", "company_name": "技嘉",     "weight_pct": 4.5, "shares": None},
            {"stock_code": "2356", "company_name": "英業達",   "weight_pct": 4.3, "shares": None},
            {"stock_code": "2324", "company_name": "仁寶",     "weight_pct": 3.8, "shares": None},
            {"stock_code": "2347", "company_name": "聯強",     "weight_pct": 3.5, "shares": None},
            {"stock_code": "2385", "company_name": "群光",     "weight_pct": 3.2, "shares": None},
            {"stock_code": "3034", "company_name": "聯詠",     "weight_pct": 3.0, "shares": None},
            {"stock_code": "2603", "company_name": "長榮",     "weight_pct": 2.8, "shares": None},
            {"stock_code": "2002", "company_name": "中鋼",     "weight_pct": 2.5, "shares": None},
        ],
        "sector_weights": [
            {"sector": "電腦週邊",  "weight_pct": 35.0},
            {"sector": "半導體",   "weight_pct": 18.0},
            {"sector": "電子零組件", "weight_pct": 13.0},
            {"sector": "鋼鐵",     "weight_pct":  8.0},
            {"sector": "航運",     "weight_pct":  6.0},
            {"sector": "其他",     "weight_pct": 20.0},
        ],
    },
    "00878": {
        "fund_name": "國泰永續高股息",
        "total_constituents": 30,
        "last_updated": "2026-04-30",
        "holdings": [
            {"stock_code": "2330", "company_name": "台積電",   "weight_pct": 7.5, "shares": None},
            {"stock_code": "2317", "company_name": "鴻海",     "weight_pct": 5.5, "shares": None},
            {"stock_code": "2412", "company_name": "中華電",   "weight_pct": 5.2, "shares": None},
            {"stock_code": "2308", "company_name": "台達電",   "weight_pct": 4.8, "shares": None},
            {"stock_code": "2382", "company_name": "廣達",     "weight_pct": 4.5, "shares": None},
            {"stock_code": "2454", "company_name": "聯發科",   "weight_pct": 4.0, "shares": None},
            {"stock_code": "2891", "company_name": "中信金",   "weight_pct": 3.8, "shares": None},
            {"stock_code": "2882", "company_name": "國泰金",   "weight_pct": 3.5, "shares": None},
            {"stock_code": "1216", "company_name": "統一",     "weight_pct": 3.2, "shares": None},
            {"stock_code": "2881", "company_name": "富邦金",   "weight_pct": 3.0, "shares": None},
        ],
        "sector_weights": [
            {"sector": "半導體",   "weight_pct": 22.0},
            {"sector": "金融",     "weight_pct": 19.0},
            {"sector": "電子零組件", "weight_pct": 15.0},
            {"sector": "電腦週邊",  "weight_pct": 12.0},
            {"sector": "電信",     "weight_pct":  7.0},
            {"sector": "食品",     "weight_pct":  5.0},
            {"sector": "其他",     "weight_pct": 20.0},
        ],
    },
    "00919": {
        "fund_name": "群益台灣精選高息",
        "total_constituents": 30,
        "last_updated": "2026-04-30",
        "holdings": [
            {"stock_code": "2382", "company_name": "廣達",     "weight_pct": 8.5, "shares": None},
            {"stock_code": "3231", "company_name": "緯創",     "weight_pct": 7.0, "shares": None},
            {"stock_code": "2356", "company_name": "英業達",   "weight_pct": 6.0, "shares": None},
            {"stock_code": "2376", "company_name": "技嘉",     "weight_pct": 5.5, "shares": None},
            {"stock_code": "2324", "company_name": "仁寶",     "weight_pct": 5.0, "shares": None},
            {"stock_code": "3702", "company_name": "大聯大",   "weight_pct": 4.5, "shares": None},
            {"stock_code": "2347", "company_name": "聯強",     "weight_pct": 4.0, "shares": None},
            {"stock_code": "2385", "company_name": "群光",     "weight_pct": 3.5, "shares": None},
            {"stock_code": "2603", "company_name": "長榮",     "weight_pct": 3.2, "shares": None},
            {"stock_code": "1101", "company_name": "台泥",     "weight_pct": 3.0, "shares": None},
        ],
        "sector_weights": [
            {"sector": "電腦週邊",  "weight_pct": 42.0},
            {"sector": "電子通路",  "weight_pct": 12.0},
            {"sector": "半導體",   "weight_pct": 10.0},
            {"sector": "航運",     "weight_pct":  6.0},
            {"sector": "水泥",     "weight_pct":  5.0},
            {"sector": "其他",     "weight_pct": 25.0},
        ],
    },
}


SUPPORTED_ETFS = set(_CURATED.keys())


def is_supported_etf(symbol: str) -> bool:
    return symbol in SUPPORTED_ETFS


def get_etf_holdings(symbol: str) -> dict:
    """Return holdings + sector breakdown for a TW ETF.

    Currently uses curated data only; future work can add live issuer
    fetchers. Returns stable empty fields for unsupported codes.
    """
    if symbol in _CURATED:
        data = _CURATED[symbol]
        return {
            "symbol": symbol,
            "fund_name": data["fund_name"],
            "total_constituents": data["total_constituents"],
            "last_updated": data["last_updated"],
            "holdings": list(data["holdings"]),
            "sector_weights": list(data["sector_weights"]),
            "status": "mock",
        }

    return {
        "symbol": symbol,
        "fund_name": None,
        "total_constituents": None,
        "last_updated": None,
        "holdings": [],
        "sector_weights": [],
        "status": "unsupported",
    }
