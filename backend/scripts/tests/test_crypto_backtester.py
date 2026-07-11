from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from backend.scripts.crypto_bt_data import CryptoBacktestStore, FundingRate, Kline, build_daily_universe, utc_ms
from backend.scripts.crypto_backtester import (
    PlannedTrade,
    StrategyParams,
    find_signal_events_for_symbol,
    rsi_1h_at,
    simulate_exit,
    validate_oos_allowed,
)


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return utc_ms(datetime(year, month, day, hour, minute, tzinfo=timezone.utc))


def _bar(sym: str, itv: str, open_ms: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> Kline:
    return Kline(sym=sym, itv=itv, open_ms=open_ms, o=o, h=h, l=l, c=c, v=v, qv=v * c)


def _short_signal_fixture() -> tuple[list[Kline], list[Kline], int]:
    sym = "TESTUSDT"
    signal_hour = _ms(2026, 4, 2, 1)
    hourly: list[Kline] = []
    start_hour = signal_hour - 24 * 60 * 60 * 1000
    close = 72.0
    for idx in range(24):
        open_ms = start_hour + idx * 60 * 60 * 1000
        close += 5.0
        hourly.append(_bar(sym, "1h", open_ms, close - 0.8, close + 0.4, close - 1.1, close, 10_000.0))

    one_minute: list[Kline] = []
    start_1m = signal_hour
    price = 190.0
    for idx in range(31):
        open_ms = start_1m + idx * 60_000
        one_minute.append(_bar(sym, "1m", open_ms, price, price + 0.15, price - 0.15, price + 0.03, 100.0))
        price += 0.03

    break_open = start_1m + 31 * 60_000
    one_minute.append(_bar(sym, "1m", break_open, 192.0, 192.2, 183.0, 184.0, 220.0))
    confirm_open = start_1m + 32 * 60_000
    one_minute.append(_bar(sym, "1m", confirm_open, 184.0, 184.4, 182.8, 183.3, 120.0))
    for idx in range(33, 45):
        open_ms = start_1m + idx * 60_000
        one_minute.append(_bar(sym, "1m", open_ms, 183.2, 184.0, 182.5, 183.0, 100.0))
    return one_minute, hourly, confirm_open


def test_sqlite_store_upserts_and_loads_klines() -> None:
    store = CryptoBacktestStore(":memory:")
    try:
        row = _bar("BTCUSDT", "1m", _ms(2026, 4, 1), 100.0, 101.0, 99.0, 100.5)
        assert store.upsert_klines([row]) == 1
        loaded = store.load_klines("BTCUSDT", "1m", row.open_ms, row.open_ms + 60_000)
        assert loaded == [row]
    finally:
        store.close()


def test_zero_lookahead_future_mutation_does_not_change_current_signals() -> None:
    one_minute, hourly, confirm_open = _short_signal_fixture()
    params = StrategyParams(rsi_hi=75.0, rsi_lo=25.0)
    cutoff_close = confirm_open + 60_000
    before = [
        (e.symbol, e.direction, e.tier, e.break_ms, e.confirm_ms)
        for e in find_signal_events_for_symbol("TESTUSDT", one_minute, hourly, params)
        if e.confirm_ms <= cutoff_close
    ]

    mutated = list(one_minute)
    for idx in range(35, len(mutated)):
        bar = mutated[idx]
        mutated[idx] = replace(bar, o=777.0 + idx, h=888.0 + idx, l=555.0 - idx, c=666.0 + idx, v=9999.0)
    after = [
        (e.symbol, e.direction, e.tier, e.break_ms, e.confirm_ms)
        for e in find_signal_events_for_symbol("TESTUSDT", mutated, hourly, params)
        if e.confirm_ms <= cutoff_close
    ]

    assert before
    assert after == before


def test_double_touch_exits_sl_and_marks_ambiguous() -> None:
    params = StrategyParams(taker_fee_rate=0.0, slippage_rate=0.0)
    entry_ts = _ms(2026, 4, 1, 0, 1)
    planned = PlannedTrade(
        symbol="TESTUSDT",
        direction="long",
        tier="*",
        grade="C",
        entry_ts=entry_ts,
        entry_px=100.0,
        sl=95.0,
        tp=105.0,
        stop_pct=5.0,
        tp_pct=5.0,
        rr_planned=1.0,
        notional=100.0,
        risk_usd=5.0,
        fr_pct=None,
        rv_ratio=None,
        breadth=None,
    )
    bars = [_bar("TESTUSDT", "1m", entry_ts, 100.0, 106.0, 94.0, 101.0)]

    result = simulate_exit(planned, bars, funding_rates=[], params=params)

    assert result.exit_reason == "SL"
    assert result.ambiguous == 1
    assert result.exit_px == pytest.approx(95.0)
    assert result.r == pytest.approx(-1.0)


def test_oos_default_rejects_june_2026_or_later() -> None:
    with pytest.raises(ValueError, match="OOS"):
        validate_oos_allowed(_ms(2026, 6, 1), _ms(2026, 6, 8), allow_oos=False)


def test_strict_higher_timeframe_policy_ignores_partial_hour_close() -> None:
    start = _ms(2026, 4, 1)
    hourly = [
        _bar("TESTUSDT", "1h", start + idx * 3_600_000, 100 + idx, 102 + idx, 99 + idx, 101 + idx)
        for idx in range(16)
    ]
    decision_ts = hourly[-1].close_ms + 30 * 60_000

    closed = rsi_1h_at(hourly, decision_ts, current_close=50.0, policy="closed_only")
    partial = rsi_1h_at(hourly, decision_ts, current_close=50.0, policy="partial_live_mirror")

    assert closed == pytest.approx(100.0)
    assert partial is not None
    assert partial < closed


def test_universe_excludes_incomplete_symbol_without_fabricating_rows() -> None:
    store = CryptoBacktestStore(":memory:")
    start = _ms(2026, 5, 2)
    end = _ms(2026, 5, 3)
    findings: list[str] = []
    try:
        btc_rows = [
            _bar("BTCUSDT", "1d", start - 86_400_000, 100, 110, 90, 105, 1_000_000),
            _bar("BTCUSDT", "1d", start, 105, 112, 100, 108, 1_000_000),
            _bar("BTCUSDT", "1d", end, 108, 115, 102, 110, 1_000_000),
        ]
        store.upsert_klines(btc_rows)

        universe = build_daily_universe(
            store,
            client=None,
            start_ms=start,
            end_ms=end,
            min_quote_volume=0,
            top_n=10,
            symbols=["BTCUSDT", "MISSINGUSDT"],
            findings=findings,
        )
    finally:
        store.close()

    assert all(members == ["BTCUSDT"] for members in universe.values())
    assert any("MISSINGUSDT: excluded" in finding for finding in findings)


def test_funding_coverage_accepts_exchange_millisecond_jitter() -> None:
    store = CryptoBacktestStore(":memory:")
    step = 8 * 3_600_000
    start = _ms(2026, 5, 1)
    try:
        store.upsert_funding(
            [
                FundingRate(sym="BTCUSDT", ts=start + offset * step + jitter, rate=0.0001)
                for offset, jitter in ((0, 3), (1, 1), (2, 8))
            ]
        )

        missing = store._missing_funding_ranges("BTCUSDT", start, start + 2 * step)
    finally:
        store.close()

    assert missing == []
