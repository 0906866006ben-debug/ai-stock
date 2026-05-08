import asyncio

from .fmp_client import fmp_get


def _fmt_large(val: float | None) -> str | None:
    if val is None:
        return None
    val = float(val)
    if abs(val) >= 1e12:
        return f"${val / 1e12:.2f}T"
    if abs(val) >= 1e9:
        return f"${val / 1e9:.2f}B"
    if abs(val) >= 1e6:
        return f"${val / 1e6:.2f}M"
    return f"${val:,.0f}"


def _fmt_pct(val: float | None) -> str | None:
    if val is None:
        return None
    return f"{float(val) * 100:.1f}%"


async def _enrich_peer(symbol: str) -> dict:
    metrics, ratios = await asyncio.gather(
        fmp_get("key-metrics", {"symbol": symbol, "limit": 1}),
        fmp_get("ratios", {"symbol": symbol, "limit": 1}),
        return_exceptions=True,
    )

    result: dict = {}

    if isinstance(metrics, list) and metrics:
        m = metrics[0]
        if mc := m.get("marketCap"):
            result["market_cap_fmt"] = _fmt_large(float(mc))
        if ev_eb := m.get("evToEBITDA"):
            result["ev_ebitda"] = f"{float(ev_eb):.1f}x"

    if isinstance(ratios, list) and ratios:
        r = ratios[0]
        if v := r.get("priceEarningsRatio"):
            result["pe_ratio"] = f"{float(v):.1f}"
        if v := r.get("grossProfitMargin"):
            result["gross_margin"] = _fmt_pct(float(v))
        if v := r.get("netProfitMargin"):
            result["net_margin"] = _fmt_pct(float(v))
        if v := r.get("returnOnEquity"):
            result["roe"] = _fmt_pct(float(v))

    return result


async def get_competitors(symbol: str) -> dict:
    """Return peer companies with side-by-side financial metrics."""
    peers_raw = await fmp_get("stock-peers", {"symbol": symbol})

    if not isinstance(peers_raw, list) or not peers_raw:
        return {"symbol": symbol, "peers": []}

    top_peers = peers_raw[:5]

    enriched = await asyncio.gather(
        *[_enrich_peer(p["symbol"]) for p in top_peers],
        return_exceptions=True,
    )

    peers = []
    for peer_info, detail in zip(top_peers, enriched):
        if isinstance(detail, Exception):
            detail = {}
        peers.append({
            "symbol": peer_info.get("symbol"),
            "company_name": peer_info.get("companyName"),
            "price": peer_info.get("price"),
            "market_cap": _fmt_large(peer_info.get("mktCap")),
            **{k: v for k, v in detail.items()},
        })

    return {"symbol": symbol, "peers": peers}
