"""Resilient derivatives backfill ordered by strategy-universe frequency.

Rebuilds the engine's daily universe (prev-day quote volume >= 15M USD,
top 150 by absolute prev-day move — both directions, because the strategy
trades overbought shorts and oversold longs) over the dev period from cached
1d klines,
then backfills premium-index and open-interest history symbol by symbol in
descending universe-appearance order, so the most strategy-relevant symbols
gain coverage first. Resumable: the store only downloads missing ranges.
Temporary operational script; safe to delete after the backfill.
"""
import os
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "backend" / ".env")
except ImportError:
    pass

from backend.scripts.crypto_bt_data import BinanceFuturesClient, CryptoBacktestStore, utc_ms
from backend.scripts.altcoin_universe import is_eligible_altcoin_symbol

START_MS = utc_ms(datetime(2025, 10, 1, tzinfo=timezone.utc))
END_MS = utc_ms(datetime(2026, 6, 1, tzinfo=timezone.utc))
_db_override = os.getenv("CRYPTO_BACKTEST_DB", "").strip()
DB = Path(_db_override).expanduser() if _db_override else Path.home() / ".crypto_backtest" / "klines.db"
DAY_MS = 86_400_000
MIN_QUOTE_VOLUME = 15_000_000.0
TOP_N = 150
STEP_RETRIES = 12
RETRY_SLEEP_SEC = 20


def universe_frequency_order(store: CryptoBacktestStore) -> list[str]:
    rows = store.conn.execute(
        "SELECT open_ms, sym, o, c, qv FROM klines WHERE itv='1d' AND open_ms>=? AND open_ms<?",
        (START_MS - DAY_MS, END_MS),
    ).fetchall()
    by_day: dict[int, list[tuple[str, float, float, float]]] = {}
    for ms, sym, o, c, qv in rows:
        by_day.setdefault(ms, []).append((sym, o, c, qv))
    counter: Counter[str] = Counter()
    day = START_MS
    while day < END_MS:
        prev = by_day.get(day - DAY_MS, [])
        ranked = sorted(
            ((abs(c / o - 1.0), sym) for sym, o, c, qv in prev if qv >= MIN_QUOTE_VOLUME and o > 0),
            reverse=True,
        )[:TOP_N]
        counter.update(sym for _, sym in ranked)
        day += DAY_MS
    # Keep frequency order (most strategy-relevant first); data layer stays a
    # superset of every strategy-side universe definition.
    return [sym for sym, _ in counter.most_common() if is_eligible_altcoin_symbol(sym)]


def run_step(label: str, fn) -> bool:
    for attempt in range(1, STEP_RETRIES + 1):
        try:
            rows = fn()
            print(f"[ok] {label} rows now {len(rows):,}", flush=True)
            return True
        except Exception as exc:
            print(f"[retry {attempt}/{STEP_RETRIES}] {label}: {type(exc).__name__}: {exc}", flush=True)
            if attempt == STEP_RETRIES:
                traceback.print_exc()
                return False
            time.sleep(RETRY_SLEEP_SEC)
    return False


def main() -> int:
    shard = int(sys.argv[1]) if len(sys.argv) > 2 else 0
    of = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    client = BinanceFuturesClient(timeout=90, request_pause_sec=0.3)
    store = CryptoBacktestStore(DB)
    failed: list[str] = []
    try:
        symbols = universe_frequency_order(store)[shard::of]
        print(f"=== shard {shard}/{of}: {len(symbols)} symbols (frequency-ordered stripe) ===", flush=True)
        for i, sym in enumerate(symbols, 1):
            print(f"=== [{i}/{len(symbols)}] {sym} {time.strftime('%H:%M:%S')} ===", flush=True)
            ok_p = run_step(
                f"{sym} premium 5m",
                lambda s=sym: store.ensure_premium_index_klines(s, "5m", START_MS, END_MS, client),
            )
            ok_o = run_step(
                f"{sym} open interest 5m",
                lambda s=sym: store.ensure_open_interest(s, "5m", START_MS, END_MS, client),
            )
            if not (ok_p and ok_o):
                failed.append(sym)
    finally:
        store.close()
    if failed:
        print(f"=== done with {len(failed)} failed symbols: {failed[:30]} ===", flush=True)
        return 1
    print("=== backfill complete: all universe symbols ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
