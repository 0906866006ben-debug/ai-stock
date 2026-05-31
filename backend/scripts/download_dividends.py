"""Backfill TaiwanStockDividendResult (除權息結果, free) for every stock in the OHLCV store,
warming the per-symbol cache used by dividend-adjusted (還原) prices.

Robust to the FinMind free-tier rolling-hour limit, like download_fundamentals:
  - Status-aware fetch DISTINGUISHES a genuine empty (HTTP 200, data=[]) from a rate-limit /
    error (status != 200). Genuine empties are CACHED as [] so they are skipped next pass;
    rate-limited symbols are NOT cached, so a later pass retries them.
  - --auto-resume: on hitting the limit (many consecutive failures), sleep ~61 min for the
    rolling window to reset, then resume; repeat until a pass completes without stopping.

Never logs the FinMind token (httpx logging silenced).

    python -m backend.scripts.download_dividends --rate-limit 1.0 --auto-resume
"""
from __future__ import annotations

import argparse
import logging
import os
import time

import httpx

from backend.scripts._env import load_backend_env
from backend.app.services import file_cache
from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"
_START_DATE = "2008-01-01"   # cover well before any backtest window


def _fetch_dividends(client: httpx.Client, symbol: str, token: str) -> tuple[list[dict], bool]:
    """Return (rows, ok). ok=False means rate-limit/error (status != 200 or exception) — the
    caller must NOT cache it (retry later). ok=True is a genuine response (possibly empty)."""
    try:
        resp = client.get(FINMIND_BASE, params={
            "dataset": "TaiwanStockDividendResult", "data_id": symbol,
            "start_date": _START_DATE, "token": token,
        })
    except Exception:
        return [], False
    if resp.status_code != 200:
        return [], False
    try:
        rows = resp.json().get("data") or []
    except Exception:
        return [], False
    return ([r for r in rows if isinstance(r, dict)], True)


def _one_pass(stocks: list[str], token: str, rate_limit: float, force: bool, max_consecutive_failures: int) -> tuple[dict, bool]:
    fetched = skipped = empty = failed = 0
    consecutive = 0
    stopped_early = False
    with httpx.Client(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for i, symbol in enumerate(stocks, 1):
            if (not force) and isinstance(file_cache.load("dividend_result", symbol), list):
                skipped += 1
                continue
            rows, ok = _fetch_dividends(client, str(symbol), token)
            if not ok:
                failed += 1
                consecutive += 1
                if consecutive >= max_consecutive_failures:
                    logger.warning("Stopped after %d consecutive failures — FinMind limit likely hit.", consecutive)
                    stopped_early = True
                    break
                time.sleep(max(0.0, rate_limit * 3))
                continue
            consecutive = 0
            file_cache.save("dividend_result", str(symbol), rows)   # cache genuine result (incl. empty)
            if rows:
                fetched += 1
            else:
                empty += 1
            if i % 100 == 0:
                logger.info("(%d/%d) fetched=%d skipped=%d empty=%d failed=%d", i, len(stocks), fetched, skipped, empty, failed)
            time.sleep(max(0.0, rate_limit))
    return {"fetched": fetched, "skipped": skipped, "empty": empty, "failed": failed}, stopped_early


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--rate-limit", type=float, default=1.0, help="Sleep seconds between symbols")
    parser.add_argument("--stocks", nargs="*", help="Override universe with explicit codes")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if already cached")
    parser.add_argument("--max-consecutive-failures", type=int, default=25)
    parser.add_argument("--auto-resume", action="store_true", help="Sleep ~61 min on rate limit and resume; repeat until a clean pass")
    parser.add_argument("--max-passes", type=int, default=48)
    parser.add_argument("--resume-wait-minutes", type=float, default=61.0)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # never log request URLs (leak FinMind token)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_backend_env()

    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    if not token:
        logger.error("FINMIND_API_KEY not set — cannot fetch dividends.")
        return 2

    stocks = args.stocks or HistoricalDataStore(args.db).list_stocks()
    logger.info("Backfilling dividends for %d symbols -> cache (auto_resume=%s)", len(stocks), args.auto_resume)

    for p in range(1, args.max_passes + 1):
        counts, stopped_early = _one_pass(stocks, token, args.rate_limit, args.force, args.max_consecutive_failures)
        logger.info("Pass %d: %s stopped_early=%s", p, counts, stopped_early)
        args.force = False   # subsequent passes only retry uncached (rate-limited) symbols
        if not stopped_early:
            logger.info("Done — a full pass completed without hitting the rate limit.")
            break
        if not args.auto_resume:
            logger.info("Rate limit hit; re-run later to resume (cached symbols are skipped).")
            break
        logger.info("Rate limit reached; sleeping %.0f min before resuming...", args.resume_wait_minutes)
        time.sleep(args.resume_wait_minutes * 60.0)

    logger.info("Backfill finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
