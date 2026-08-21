"""Data access layer for the crypto mean-reversion backtester.

The layer is intentionally boring: Binance public endpoints feed a SQLite
cache, and the simulator consumes only cached, timestamped bars/funding rows.
Network calls are isolated here so the simulation core can stay deterministic.
"""
from __future__ import annotations

import bisect
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

FAPI_BASE = "https://fapi.binance.com"

MINUTE_MS = 60_000
INTERVAL_MS: dict[str, int] = {
    "1m": MINUTE_MS,
    "15m": 15 * MINUTE_MS,
    "1h": 60 * MINUTE_MS,
    "1d": 24 * 60 * MINUTE_MS,
}


@dataclass(frozen=True)
class Kline:
    sym: str
    itv: str
    open_ms: int
    o: float
    h: float
    l: float
    c: float
    v: float
    qv: float

    @property
    def close_ms(self) -> int:
        return self.open_ms + INTERVAL_MS[self.itv]

    @classmethod
    def from_binance(cls, sym: str, itv: str, row: list[Any]) -> "Kline":
        return cls(
            sym=sym,
            itv=itv,
            open_ms=int(row[0]),
            o=float(row[1]),
            h=float(row[2]),
            l=float(row[3]),
            c=float(row[4]),
            v=float(row[5]),
            qv=float(row[7]) if len(row) > 7 else 0.0,
        )


@dataclass(frozen=True)
class FundingRate:
    sym: str
    ts: int
    rate: float


def utc_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def ms_to_utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def iso_utc(ms: int) -> str:
    return ms_to_utc(ms).isoformat(timespec="seconds").replace("+00:00", "Z")


def floor_ms(ms: int, interval: str) -> int:
    step = INTERVAL_MS[interval]
    return ms - (ms % step)


def iter_days(start_ms: int, end_ms: int) -> Iterable[int]:
    day = floor_ms(start_ms, "1d")
    while day < end_ms:
        yield day
        day += INTERVAL_MS["1d"]


def merge_windows(windows: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted((s, e) for s, e in windows if e > s)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def percentile_rank(values: list[float], value: float) -> float:
    if not values:
        return 50.0
    ordered = sorted(values)
    return 100.0 * bisect.bisect_left(ordered, value) / len(ordered)


def rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gain = 0.0
    loss = 0.0
    for idx in range(1, period + 1):
        delta = closes[idx] - closes[idx - 1]
        if delta > 0:
            gain += delta
        else:
            loss -= delta
    gain /= period
    loss /= period
    out[period] = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    for idx in range(period + 1, len(closes)):
        delta = closes[idx] - closes[idx - 1]
        gain = (gain * (period - 1) + (delta if delta > 0 else 0.0)) / period
        loss = (loss * (period - 1) + (-delta if delta < 0 else 0.0)) / period
        out[idx] = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    return out


def rsi_last(closes: list[float], period: int = 14) -> float | None:
    values = rsi_series(closes, period)
    return values[-1] if values else None


class BinanceFuturesClient:
    def __init__(
        self,
        base_url: str = FAPI_BASE,
        timeout: int = 20,
        request_pause_sec: float = 0.3,
        max_retries: int = 6,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.request_pause_sec = request_pause_sec
        self.max_retries = max_retries

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = ""
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            query = "?" + urllib.parse.urlencode(clean)
        url = self.base_url + path + query
        last_error = ""
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = resp.read()
                if self.request_pause_sec > 0:
                    time.sleep(self.request_pause_sec)
                return json.loads(payload)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode(errors="replace")[:300]
                last_error = f"HTTP {exc.code}: {body}"
                if exc.code in (418, 429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    retry_after = float(exc.headers.get("Retry-After", 0) or 0)
                    wait = retry_after or min(30.0, 1.5 * (attempt + 1))
                    time.sleep(wait)
                    continue
                raise RuntimeError(last_error) from None
            except urllib.error.URLError as exc:
                last_error = f"URL error: {exc}"
                if attempt < self.max_retries - 1:
                    time.sleep(min(30.0, 1.5 * (attempt + 1)))
                    continue
                raise RuntimeError(last_error) from None
        raise RuntimeError(last_error or f"request failed: {url}")

    def usdt_perp_symbols(self) -> list[str]:
        info = self.get_json("/fapi/v1/exchangeInfo")
        symbols: list[str] = []
        for item in info.get("symbols", []):
            if item.get("quoteAsset") != "USDT":
                continue
            if item.get("contractType") != "PERPETUAL":
                continue
            if item.get("status") not in (None, "TRADING"):   # 已下市/暫停交易不進宇宙
                continue
            sym = str(item.get("symbol") or "")
            if sym.endswith("USDT"):
                symbols.append(sym)
        return sorted(set(symbols))


class CryptoBacktestStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path) if str(db_path) != ":memory:" else Path(":memory:")
        if str(db_path) == ":memory:":
            self.conn = sqlite3.connect(":memory:", timeout=30)
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.db_path, timeout=30)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS klines (
                sym TEXT NOT NULL,
                itv TEXT NOT NULL,
                open_ms INTEGER NOT NULL,
                o REAL NOT NULL,
                h REAL NOT NULL,
                l REAL NOT NULL,
                c REAL NOT NULL,
                v REAL NOT NULL,
                qv REAL NOT NULL,
                PRIMARY KEY (sym, itv, open_ms)
            );
            CREATE TABLE IF NOT EXISTS funding (
                sym TEXT NOT NULL,
                ts INTEGER NOT NULL,
                rate REAL NOT NULL,
                PRIMARY KEY (sym, ts)
            );
            CREATE INDEX IF NOT EXISTS idx_klines_lookup ON klines(sym, itv, open_ms);
            CREATE INDEX IF NOT EXISTS idx_funding_lookup ON funding(sym, ts);
            """
        )
        self.conn.commit()

    def upsert_klines(self, rows: Iterable[Kline]) -> int:
        data = [
            (r.sym, r.itv, r.open_ms, r.o, r.h, r.l, r.c, r.v, r.qv)
            for r in rows
        ]
        if not data:
            return 0
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO klines(sym, itv, open_ms, o, h, l, c, v, qv)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            data,
        )
        self.conn.commit()
        return len(data)

    def upsert_funding(self, rows: Iterable[FundingRate]) -> int:
        data = [(r.sym, r.ts, r.rate) for r in rows]
        if not data:
            return 0
        self.conn.executemany(
            "INSERT OR REPLACE INTO funding(sym, ts, rate) VALUES (?, ?, ?)",
            data,
        )
        self.conn.commit()
        return len(data)

    def load_klines(self, sym: str, itv: str, start_ms: int, end_ms: int) -> list[Kline]:
        cur = self.conn.execute(
            """
            SELECT sym, itv, open_ms, o, h, l, c, v, qv
            FROM klines
            WHERE sym = ? AND itv = ? AND open_ms >= ? AND open_ms < ?
            ORDER BY open_ms
            """,
            (sym, itv, start_ms, end_ms),
        )
        return [Kline(*row) for row in cur.fetchall()]

    def load_funding(self, sym: str, start_ms: int, end_ms: int) -> list[FundingRate]:
        cur = self.conn.execute(
            """
            SELECT sym, ts, rate
            FROM funding
            WHERE sym = ? AND ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            (sym, start_ms, end_ms),
        )
        return [FundingRate(*row) for row in cur.fetchall()]

    def latest_funding_rate(self, sym: str, ts_ms: int) -> float | None:
        cur = self.conn.execute(
            """
            SELECT rate
            FROM funding
            WHERE sym = ? AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (sym, ts_ms),
        )
        row = cur.fetchone()
        return float(row[0]) if row else None

    def recent_funding_rates(self, sym: str, ts_ms: int, n: int = 3) -> list[float]:
        """最近 n 期資費(最新在前),供符號/翻轉判定(群組大神的「觀察轉正轉負」)。"""
        cur = self.conn.execute(
            "SELECT rate FROM funding WHERE sym = ? AND ts <= ? ORDER BY ts DESC LIMIT ?",
            (sym, ts_ms, n),
        )
        return [float(r[0]) for r in cur.fetchall()]

    def cached_symbols(self) -> list[str]:
        cur = self.conn.execute("SELECT DISTINCT sym FROM klines ORDER BY sym")
        return [str(row[0]) for row in cur.fetchall()]

    def _missing_kline_ranges(self, sym: str, itv: str, start_ms: int, end_ms: int) -> list[tuple[int, int]]:
        step = INTERVAL_MS[itv]
        start = floor_ms(start_ms, itv)
        if start < start_ms:
            start += step
        end = floor_ms(end_ms + step - 1, itv)
        if end <= start:
            return []
        existing = {
            int(row[0])
            for row in self.conn.execute(
                """
                SELECT open_ms FROM klines
                WHERE sym = ? AND itv = ? AND open_ms >= ? AND open_ms < ?
                """,
                (sym, itv, start, end),
            )
        }
        missing: list[tuple[int, int]] = []
        gap_start: int | None = None
        ts = start
        while ts < end:
            if ts not in existing:
                if gap_start is None:
                    gap_start = ts
            elif gap_start is not None:
                missing.append((gap_start, ts))
                gap_start = None
            ts += step
        if gap_start is not None:
            missing.append((gap_start, end))
        return missing

    def ensure_klines(
        self,
        sym: str,
        itv: str,
        start_ms: int,
        end_ms: int,
        client: BinanceFuturesClient | None,
    ) -> list[Kline]:
        missing = self._missing_kline_ranges(sym, itv, start_ms, end_ms)
        if missing and client is None:
            raise RuntimeError(f"missing cached klines for {sym} {itv} {missing[:3]}")
        for start, end in missing:
            self._download_klines(sym, itv, start, end, client)
        return self.load_klines(sym, itv, start_ms, end_ms)

    def _download_klines(
        self,
        sym: str,
        itv: str,
        start_ms: int,
        end_ms: int,
        client: BinanceFuturesClient | None,
    ) -> None:
        if client is None:
            raise RuntimeError("client is required for downloads")
        step = INTERVAL_MS[itv]
        cursor = start_ms
        while cursor < end_ms:
            try:
                raw = client.get_json(
                    "/fapi/v1/klines",
                    {
                        "symbol": sym,
                        "interval": itv,
                        "startTime": cursor,
                        "endTime": end_ms - 1,
                        "limit": 1000,
                    },
                )
            except RuntimeError as exc:
                # 已下市/暫停交易的幣(-1121/-1122)= 該幣無數據,跳過不炸全局
                if "-1122" in str(exc) or "-1121" in str(exc):
                    print(f"  [data] {sym} 不可交易(已下市/暫停),跳過", flush=True)
                    return
                raise
            if not raw:
                break
            rows = [Kline.from_binance(sym, itv, item) for item in raw]
            self.upsert_klines(rows)
            last_open = rows[-1].open_ms
            next_cursor = last_open + step
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(rows) < 1000:
                break

    def ensure_funding(
        self,
        sym: str,
        start_ms: int,
        end_ms: int,
        client: BinanceFuturesClient | None,
    ) -> list[FundingRate]:
        missing = self._missing_funding_ranges(sym, start_ms, end_ms)
        if missing and client is None:
            raise RuntimeError(f"missing cached funding for {sym} {missing[:3]}")
        for start, end in missing:
            self._download_funding(sym, start, end, client)
        return self.load_funding(sym, start_ms, end_ms)

    def _missing_funding_ranges(self, sym: str, start_ms: int, end_ms: int) -> list[tuple[int, int]]:
        step = 8 * INTERVAL_MS["1h"]
        start = (start_ms // step) * step
        end = ((end_ms + step - 1) // step) * step
        existing = {
            (int(row[0]) // step) * step
            for row in self.conn.execute(
                "SELECT ts FROM funding WHERE sym = ? AND ts >= ? AND ts <= ?",
                (sym, start, end + 60_000),
            )
        }
        missing: list[tuple[int, int]] = []
        gap_start: int | None = None
        ts = start
        while ts <= end:
            if ts not in existing:
                if gap_start is None:
                    gap_start = ts
            elif gap_start is not None:
                missing.append((gap_start, ts))
                gap_start = None
            ts += step
        if gap_start is not None:
            missing.append((gap_start, end))
        return missing

    def _download_funding(
        self,
        sym: str,
        start_ms: int,
        end_ms: int,
        client: BinanceFuturesClient | None,
    ) -> None:
        if client is None:
            raise RuntimeError("client is required for downloads")
        cursor = start_ms
        while cursor <= end_ms:
            raw = client.get_json(
                "/fapi/v1/fundingRate",
                {
                    "symbol": sym,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
            if not raw:
                break
            rows = [
                FundingRate(sym=sym, ts=int(item["fundingTime"]), rate=float(item["fundingRate"]))
                for item in raw
            ]
            self.upsert_funding(rows)
            next_cursor = rows[-1].ts + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(rows) < 1000:
                break


def scan_hourly_event_windows(
    klines_1h: list[Kline],
    start_ms: int,
    end_ms: int,
    rsi_hi: float = 75.0,
    rsi_lo: float = 25.0,
    pad_hours: int = 12,
) -> list[tuple[int, int]]:
    """Find coarse event windows from 1h bars.

    The coarse scan is allowed to be conservative because it only decides which
    1m/15m data to download. The simulator still recomputes signals from
    point-in-time 1m data.
    """
    if len(klines_1h) < 20:
        return []
    windows: list[tuple[int, int]] = []
    closes = [k.c for k in klines_1h]
    pad = pad_hours * INTERVAL_MS["1h"]
    for idx, bar in enumerate(klines_1h):
        if bar.open_ms < start_ms or bar.open_ms >= end_ms:
            continue
        before = closes[:idx]
        if len(before) < 14:
            continue
        high_rsi = rsi_last(before + [bar.h])
        low_rsi = rsi_last(before + [bar.l])
        short_candidate = high_rsi is not None and high_rsi >= rsi_hi
        long_candidate = low_rsi is not None and low_rsi <= rsi_lo
        if short_candidate or long_candidate:
            windows.append((bar.open_ms - pad, bar.open_ms + INTERVAL_MS["1h"] + pad))
    return merge_windows(windows)


def build_daily_universe(
    store: CryptoBacktestStore,
    client: BinanceFuturesClient | None,
    start_ms: int,
    end_ms: int,
    min_quote_volume: float = 15_000_000.0,
    top_n: int = 150,
    symbols: list[str] | None = None,
    findings: list[str] | None = None,
) -> dict[int, list[str]]:
    """Build the previous-UTC-day universe for each UTC day in the run."""
    source_symbols = symbols
    if source_symbols is None:
        if client is None:
            source_symbols = store.cached_symbols()
        else:
            source_symbols = client.usdt_perp_symbols()
    source_symbols = sorted(set(source_symbols or []))
    if not source_symbols:
        raise RuntimeError("no symbols available for universe construction")

    daily_start = floor_ms(start_ms, "1d") - INTERVAL_MS["1d"]
    daily_end = floor_ms(end_ms + INTERVAL_MS["1d"], "1d")
    covered_symbols: list[str] = []
    for sym in source_symbols:
        try:
            store.ensure_klines(sym, "1d", daily_start, daily_end, client)
        except Exception as exc:  # noqa: BLE001
            if findings is not None:
                findings.append(f"{sym}: excluded from universe due to incomplete 1d coverage ({str(exc)[:120]})")
            continue
        covered_symbols.append(sym)
    source_symbols = covered_symbols
    if not source_symbols:
        raise RuntimeError("no symbols have complete daily coverage for universe construction")

    by_day: dict[int, list[str]] = {}
    for day in iter_days(start_ms, end_ms):
        prev_day = day - INTERVAL_MS["1d"]
        ranked: list[tuple[float, str]] = []
        for sym in source_symbols:
            rows = store.load_klines(sym, "1d", prev_day, prev_day + INTERVAL_MS["1d"])
            if not rows:
                continue
            row = rows[0]
            if row.qv < min_quote_volume or row.o <= 0:
                continue
            pct = (row.c / row.o - 1.0) * 100.0
            ranked.append((abs(pct), sym))
        ranked.sort(reverse=True)
        by_day[day] = [sym for _, sym in ranked[:top_n]]
    return by_day


def universe_for_ts(universe_by_day: dict[int, list[str]], ts_ms: int) -> list[str]:
    return universe_by_day.get(floor_ms(ts_ms, "1d"), [])


def funding_percentile_at(
    store: CryptoBacktestStore,
    universe: list[str],
    sym: str,
    ts_ms: int,
) -> float | None:
    own = store.latest_funding_rate(sym, ts_ms)
    if own is None:
        return None
    vals = [
        rate
        for item in universe
        for rate in [store.latest_funding_rate(item, ts_ms)]
        if rate is not None
    ]
    if not vals:
        return None
    return percentile_rank(vals, own)
