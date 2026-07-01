#!/usr/bin/env python
"""Hands-off OHLCV freshness loop for the canonical store.

yfinance hard-throttles under bulk requests, so a single pass only updates a few
hundred stocks. This loops: find the stocks still behind the freshest trading day,
re-fetch ONLY those (so each pass shrinks the stale set instead of wasting the
throttle budget on already-fresh stocks), sleep to let the throttle reset, repeat.

Writes the canonical backend/historical_data.db. Safe to run alongside the backend
(WAL) and alongside the PIT download (different DB file).

    .venv\\Scripts\\python.exe refresh_ohlcv_loop.py [--passes 16] [--sleep-min 45]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import time
from pathlib import Path

os.environ.setdefault("YFINANCE_ONLY_MODE", "1")  # never spend FinMind quota here

from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH
from backend.scripts.download_history import download_all, incremental_days_by_symbol

DB = str(DEFAULT_DB_PATH)
INDICES = ("TAIEX", "TPEX")


def _stale() -> tuple[str, list[str]]:
    """(target_date, stocks whose latest bar is older than the freshest stock)."""
    conn = sqlite3.connect(DB)
    try:
        target = conn.execute(
            "SELECT MAX(date) FROM ohlcv WHERE stock_id NOT IN ('TAIEX','TPEX')"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT stock_id, MAX(date) FROM ohlcv WHERE stock_id NOT IN ('TAIEX','TPEX') GROUP BY stock_id"
        ).fetchall()
    finally:
        conn.close()
    stale = [str(s) for s, d in rows if s and d and str(d) < str(target)]
    return str(target), stale


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=16)
    ap.add_argument("--sleep-min", type=float, default=45.0, help="Minutes between passes (yfinance throttle reset)")
    args = ap.parse_args()

    store = HistoricalDataStore(DB)
    prev_stale = None
    for p in range(1, args.passes + 1):
        target, stale = _stale()
        print(f"[pass {p}/{args.passes}] target={target} stale={len(stale)}", flush=True)
        if not stale:
            print("All stocks at the freshest trading day — done.", flush=True)
            return 0
        days_by = incremental_days_by_symbol(store, stale, min_days=18, buffer_days=7, max_days=60)
        wrote = asyncio.run(download_all(stocks=stale, days=40, store=store, rate_limit_sec=0.8, days_by_symbol=days_by))
        _, stale_after = _stale()
        print(f"[pass {p}] wrote {wrote} rows; stale {len(stale)} -> {len(stale_after)}", flush=True)
        if not stale_after:
            print("All stocks fresh — done.", flush=True)
            return 0
        # Stop early if a pass made no progress twice in a row (throttle fully stuck / genuinely-absent tail).
        if prev_stale is not None and len(stale_after) >= prev_stale:
            print("[note] no net progress this pass (throttle or genuinely-delisted tail).", flush=True)
        prev_stale = len(stale_after)
        if p < args.passes:
            print(f"[pass {p}] sleeping {args.sleep_min:.0f} min for throttle reset...", flush=True)
            time.sleep(args.sleep_min * 60.0)
    print("Reached max passes.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
