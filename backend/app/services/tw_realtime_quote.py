"""台股盤中即時報價 — 證交所 MIS 官方接口（免費、合法）。

用途：小金庫/持倉現價。FinMind 日線是收盤後才發布（盤中只有前一交易日收盤），
此接口在盤中提供**當下成交價**，讓帳面損益能即時反映。

誠實資料契約：
  - 盤中有成交 → 回當下成交價；無成交/盤前 → 回昨收（欄位 y）作合理替代並標記。
  - 全部失敗 → 回空 dict，呼叫端自行退回 FinMind 日線（永不 crash、永不捏造）。
  - 不知上市/上櫃 → 同時試 tse_ 與 otc_ 前綴，取有回應者。
"""
from __future__ import annotations

import asyncio

import httpx

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/stock/index.jsp"}


def _to_float(v) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


async def get_tw_realtime_quotes(codes: list[str]) -> dict[str, dict]:
    """回 {code: {"price": float, "prev_close": float|None, "is_intraday": bool}}。

    price = 當下成交價（z），無成交則退回昨收（y）並 is_intraday=False。
    只回成功解析者；失敗的 code 直接缺席，呼叫端退回日線。
    """
    codes = [c.strip() for c in codes if c and c.strip().isdigit()]
    if not codes:
        return {}
    # 同時掛 tse_ 與 otc_，證交所會忽略不存在的 channel
    ex_ch = "|".join(f"tse_{c}.tw|otc_{c}.tw" for c in codes)
    out: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=_HEADERS) as client:
            resp = await client.get(MIS_URL, params={"ex_ch": ex_ch, "json": "1", "delay": "0"})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}
    for item in data.get("msgArray", []) or []:
        code = item.get("c")
        if not code or code in out:
            continue
        last = _to_float(item.get("z"))          # 當下成交價
        prev = _to_float(item.get("y"))          # 昨收
        # 盤中無成交時 z 常為 "-"；退回最佳買價 b / 最高 h / 開盤 o / 昨收
        if last is None:
            for k in ("o", "h", "l"):
                last = _to_float(item.get(k))
                if last:
                    break
        if last is None:
            last = prev
        if last is None:
            continue
        out[code] = {
            "price": last,
            "prev_close": prev,
            "is_intraday": _to_float(item.get("z")) is not None,
        }
    return out
