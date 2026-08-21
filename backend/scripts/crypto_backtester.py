"""Historical backtester for the crypto v2 mean-reversion strategy.

This script replays Binance USDT perpetual history. It is not connected to the
live bot and it never restarts or controls any bot process.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import re
import statistics
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.scripts.crypto_bt_data import (  # noqa: E402
    INTERVAL_MS,
    BinanceFuturesClient,
    CryptoBacktestStore,
    FundingRate,
    Kline,
    build_daily_universe,
    floor_ms,
    funding_percentile_at,
    iso_utc,
    merge_windows,
    rsi_last,
    scan_hourly_event_windows,
    universe_for_ts,
    utc_ms,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "backend" / "data" / "crypto_backtest" / "klines.db"
RUNS_DIR = ROOT / "backend" / "data" / "crypto_backtest" / "runs"
LEDGER_PATH = ROOT / "Docs" / "backtest" / "crypto_experiments_ledger.md"
OOS_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
OOS_START_MS = utc_ms(OOS_START)


@dataclass(frozen=True)
class StrategyParams:
    rsi_hi: float = 75.0
    rsi_lo: float = 25.0
    body_mult: float = 1.5
    vol_mult: float = 1.5
    pin_bars: int = 25
    tp_target: str = "ema12"
    min_stop: float = 1.0
    risk_usd: float = 5.0
    max_notional: float = 1000.0
    taker_fee_rate: float = 0.0005
    slippage_rate: float = 0.0005
    max_hold_hours: float = 48.0
    cooldown_minutes: int = 5
    squeeze_guard: bool = True
    tier_filter: str = "both"
    rr_min: float | None = None
    funding_sign: bool = False    # 空要資費>0、多要資費<0(大神步驟②弱版)
    funding_flip: bool = False    # 符號對齊且近2期內剛翻轉(大神「觀察轉正轉負」)
    rv_max: float | None = None
    higher_timeframe_policy: str = "closed_only"


@dataclass(frozen=True)
class SignalEvent:
    symbol: str
    direction: str
    tier: str
    break_ms: int
    confirm_ms: int
    rsi: float
    body_multiple: float
    volume_multiple: float


@dataclass(frozen=True)
class PlannedTrade:
    symbol: str
    direction: str
    tier: str
    grade: str
    entry_ts: int
    entry_px: float
    sl: float
    tp: float
    stop_pct: float
    tp_pct: float
    rr_planned: float
    notional: float
    risk_usd: float
    fr_pct: float | None
    rv_ratio: float | None
    breadth: int | None


@dataclass(frozen=True)
class TradeResult:
    symbol: str
    direction: str
    tier: str
    grade: str
    entry_ts: int
    entry_px: float
    sl: float
    tp: float
    stop_pct: float
    tp_pct: float
    rr_planned: float
    notional: float
    risk_usd: float
    exit_ts: int
    exit_px: float
    exit_reason: str
    gross_pnl: float
    fees: float
    funding_paid: float
    net_pnl: float
    r: float
    fr_pct: float | None
    rv_ratio: float | None
    breadth: int | None
    crossed_settlement: int
    ambiguous: int
    hold_minutes: int

    def to_row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "tier": self.tier,
            "grade": self.grade,
            "entry_ts": iso_utc(self.entry_ts),
            "entry_px": round(self.entry_px, 10),
            "sl": round(self.sl, 10),
            "tp": round(self.tp, 10),
            "stop_pct": round(self.stop_pct, 6),
            "tp_pct": round(self.tp_pct, 6),
            "rr_planned": round(self.rr_planned, 6),
            "notional": round(self.notional, 6),
            "risk_usd": round(self.risk_usd, 6),
            "exit_ts": iso_utc(self.exit_ts),
            "exit_px": round(self.exit_px, 10),
            "exit_reason": self.exit_reason,
            "gross_pnl": round(self.gross_pnl, 8),
            "fees": round(self.fees, 8),
            "funding_paid": round(self.funding_paid, 8),
            "net_pnl": round(self.net_pnl, 8),
            "r": round(self.r, 8),
            "fr_pct": None if self.fr_pct is None else round(self.fr_pct, 4),
            "rv_ratio": None if self.rv_ratio is None else round(self.rv_ratio, 6),
            "breadth": self.breadth,
            "crossed_settlement": self.crossed_settlement,
            "ambiguous": self.ambiguous,
            "hold_minutes": self.hold_minutes,
        }


VARIANTS: dict[str, dict[str, Any]] = {
    "baseline": {},
    "legacy_fidelity": {"higher_timeframe_policy": "partial_live_mirror"},
    "pin5": {"pin_bars": 5},
    "pin10": {"pin_bars": 10},
    "tp_ema20": {"tp_target": "ema20"},
    "rr_min_1_5": {"rr_min": 1.5},
    "no_squeeze": {"squeeze_guard": False},
    "star_only": {"tier_filter": "star"},
    "diamond_only": {"tier_filter": "diamond"},
    "funding_sign": {"funding_sign": True},
    "funding_flip": {"funding_flip": True},
    "regime_rv08": {"rv_max": 0.8},
}


def ema_last(values: list[float], span: int) -> float | None:
    if not values:
        return None
    alpha = 2.0 / (span + 1.0)
    ema = float(values[0])
    for value in values[1:]:
        ema = alpha * float(value) + (1.0 - alpha) * ema
    return ema


def parse_cli_date(raw: str, *, end_date: bool = False) -> int:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if end_date:
            dt += timedelta(days=1)
        return utc_ms(dt)
    text = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return utc_ms(dt.astimezone(timezone.utc))


def validate_oos_allowed(start_ms: int, end_ms: int, allow_oos: bool) -> None:
    if end_ms > OOS_START_MS and not allow_oos:
        raise ValueError(
            "OOS range requested. 2026-06-01 and later is sealed; rerun with --oos only after explicit approval."
        )


def params_for_variant(name: str, base: StrategyParams | None = None) -> StrategyParams:
    if name not in VARIANTS:
        raise ValueError(f"unknown variant: {name}")
    params = base or StrategyParams()
    return replace(params, **VARIANTS[name])


def partial_1h_rsi(klines_1h: list[Kline], ts_ms: int, current_close: float, period: int = 14) -> float | None:
    closes = [bar.c for bar in klines_1h if bar.close_ms <= ts_ms]
    if ts_ms % INTERVAL_MS["1h"] != 0:
        closes.append(current_close)
    if len(closes) <= period:
        return None
    return rsi_last(closes, period)


def rsi_1h_at(
    klines_1h: list[Kline],
    ts_ms: int,
    current_close: float,
    policy: str,
    period: int = 14,
) -> float | None:
    if policy == "partial_live_mirror":
        return partial_1h_rsi(klines_1h, ts_ms, current_close, period)
    if policy != "closed_only":
        raise ValueError(f"unknown higher-timeframe policy: {policy}")
    closes = [bar.c for bar in klines_1h if bar.close_ms <= ts_ms]
    if len(closes) <= period:
        return None
    return rsi_last(closes, period)


def big_break_at(
    klines_1m: list[Kline],
    confirm_idx: int,
    direction: str,
    params: StrategyParams,
) -> tuple[bool, bool, float, float]:
    break_idx = confirm_idx - 1
    if break_idx < 21:
        return False, False, 0.0, 0.0
    opens = [bar.o for bar in klines_1m]
    highs = [bar.h for bar in klines_1m]
    lows = [bar.l for bar in klines_1m]
    closes = [bar.c for bar in klines_1m]
    vols = [bar.v for bar in klines_1m]

    e12_prev = ema_last(closes[:break_idx], 12)
    e12_break = ema_last(closes[: break_idx + 1], 12)
    e12_confirm = ema_last(closes[: confirm_idx + 1], 12)
    if e12_prev is None or e12_break is None or e12_confirm is None:
        return False, False, 0.0, 0.0

    open_ = opens[break_idx]
    high = highs[break_idx]
    low = lows[break_idx]
    close = closes[break_idx]
    prev_close = closes[break_idx - 1]
    body = abs(close - open_)
    avg_body = statistics.fmean(abs(closes[i] - opens[i]) for i in range(break_idx - 20, break_idx)) or 1e-12
    avg_vol = statistics.fmean(vols[break_idx - 20:break_idx]) or 1e-12
    body_multiple = body / avg_body
    volume_multiple = vols[break_idx] / avg_vol
    candle_range = max(high - low, 1e-12)
    close_pos = (close - low) / candle_range
    big = body_multiple >= params.body_mult
    loud = volume_multiple >= params.vol_mult

    if direction == "short":
        broke = big and prev_close >= e12_prev and close < e12_break and close < open_ and close_pos <= 0.4
        held = closes[confirm_idx] < e12_confirm
    else:
        broke = big and prev_close <= e12_prev and close > e12_break and close > open_ and close_pos >= 0.6
        held = closes[confirm_idx] > e12_confirm
    return bool(broke and held), bool(loud), float(body_multiple), float(volume_multiple)


def find_signal_events_for_symbol(
    symbol: str,
    klines_1m: list[Kline],
    klines_1h: list[Kline],
    params: StrategyParams,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[SignalEvent]:
    events: list[SignalEvent] = []
    rows = sorted(klines_1m, key=lambda bar: bar.open_ms)
    hourly = sorted(klines_1h, key=lambda bar: bar.open_ms)
    for confirm_idx, confirm in enumerate(rows):
        confirm_ms = confirm.close_ms
        if start_ms is not None and confirm_ms < start_ms:
            continue
        if end_ms is not None and confirm_ms >= end_ms:
            continue
        rsi = rsi_1h_at(
            hourly,
            confirm_ms,
            confirm.c,
            params.higher_timeframe_policy,
        )
        if rsi is None:
            continue
        if rsi >= params.rsi_hi:
            direction = "short"
        elif rsi <= params.rsi_lo:
            direction = "long"
        else:
            continue
        hit, loud, body_multiple, volume_multiple = big_break_at(rows, confirm_idx, direction, params)
        if not hit:
            continue
        tier = "★" if loud else "◆"
        events.append(
            SignalEvent(
                symbol=symbol,
                direction=direction,
                tier=tier,
                break_ms=rows[confirm_idx - 1].open_ms,
                confirm_ms=confirm_ms,
                rsi=float(rsi),
                body_multiple=body_multiple,
                volume_multiple=volume_multiple,
            )
        )
    return events


def _entry_price(open_px: float, direction: str, params: StrategyParams) -> float:
    if direction == "long":
        return open_px * (1.0 + params.slippage_rate)
    return open_px * (1.0 - params.slippage_rate)


def _exit_price(raw_px: float, direction: str, params: StrategyParams) -> float:
    if direction == "long":
        return raw_px * (1.0 - params.slippage_rate)
    return raw_px * (1.0 + params.slippage_rate)


def _closed_15m_before(klines_15m: list[Kline], ts_ms: int) -> list[Kline]:
    return [bar for bar in klines_15m if bar.close_ms <= ts_ms]


def _tp_ema_with_partial(
    klines_15m: list[Kline],
    ts_ms: int,
    current_close: float,
    span: int,
) -> float | None:
    closes = [bar.c for bar in klines_15m if bar.close_ms <= ts_ms]
    if ts_ms % INTERVAL_MS["15m"] != 0:
        closes.append(current_close)
    if len(closes) < span:
        return None
    return ema_last(closes, span)


def grade_from_context(direction: str, fr_pct: float | None, rv_ratio: float | None) -> str:
    score = 0
    if fr_pct is not None:
        if direction == "short" and fr_pct >= 90.0:
            score += 1
        elif direction == "long" and fr_pct <= 10.0:
            score += 1
    if rv_ratio is not None and rv_ratio < 1.0:
        score += 1
    return {2: "S", 1: "B"}.get(score, "C")


def plan_trade(
    event: SignalEvent,
    klines_1m: list[Kline],
    klines_15m: list[Kline],
    params: StrategyParams,
    fr_pct: float | None,
    rv_ratio: float | None,
    breadth: int | None,
    fr_recent: list[float] | None = None,
) -> PlannedTrade | None:
    if params.tier_filter == "star" and event.tier != "★":
        return None
    if params.tier_filter == "diamond" and event.tier != "◆":
        return None
    if params.rv_max is not None and (rv_ratio is None or rv_ratio >= params.rv_max):
        return None
    if params.squeeze_guard and fr_pct is not None:
        if event.direction == "short" and fr_pct <= 10.0:
            return None
        if event.direction == "long" and fr_pct >= 90.0:
            return None
    if params.funding_sign or params.funding_flip:
        if not fr_recent:
            return None                                   # 沒資費資料就不進(此變體資費是門檻)
        now_rate = fr_recent[0]
        aligned = now_rate > 0 if event.direction == "short" else now_rate < 0
        if not aligned:
            return None
        if params.funding_flip:
            # 「剛翻轉」:前 1-2 期存在相反符號(空:先前 ≤0;多:先前 ≥0)
            prev = fr_recent[1:]
            flipped = any((r <= 0 if event.direction == "short" else r >= 0) for r in prev)
            if not (prev and flipped):
                return None

    rows_1m = {bar.open_ms: bar for bar in klines_1m}
    entry_bar = rows_1m.get(event.confirm_ms)
    confirm_bar = rows_1m.get(event.confirm_ms - INTERVAL_MS["1m"])
    if entry_bar is None or confirm_bar is None:
        return None
    entry_px = _entry_price(entry_bar.o, event.direction, params)

    closed_15m = _closed_15m_before(klines_15m, event.confirm_ms)
    if len(closed_15m) < max(params.pin_bars, 20):
        return None
    recent = closed_15m[-params.pin_bars :]
    if event.direction == "long":
        sl = min(bar.l for bar in recent)
    else:
        sl = max(bar.h for bar in recent)

    span = 20 if params.tp_target == "ema20" else 12
    tp = _tp_ema_with_partial(klines_15m, event.confirm_ms, confirm_bar.c, span)
    if tp is None:
        return None

    if event.direction == "long":
        if not (sl < entry_px and tp > entry_px):
            return None
        stop_pct = (entry_px - sl) / entry_px * 100.0
        tp_pct = (tp - entry_px) / entry_px * 100.0
    else:
        if not (sl > entry_px and tp < entry_px):
            return None
        stop_pct = (sl - entry_px) / entry_px * 100.0
        tp_pct = (entry_px - tp) / entry_px * 100.0
    if stop_pct < params.min_stop:
        return None
    rr = tp_pct / stop_pct if stop_pct > 0 else 0.0
    if params.rr_min is not None and rr < params.rr_min:
        return None

    notional = params.risk_usd / (stop_pct / 100.0)
    risk_usd = params.risk_usd
    if notional > params.max_notional:
        scale = params.max_notional / notional
        notional = params.max_notional
        risk_usd *= scale
    if notional <= 0 or risk_usd <= 0:
        return None
    grade = grade_from_context(event.direction, fr_pct, rv_ratio)
    return PlannedTrade(
        symbol=event.symbol,
        direction=event.direction,
        tier=event.tier,
        grade=grade,
        entry_ts=event.confirm_ms,
        entry_px=entry_px,
        sl=sl,
        tp=tp,
        stop_pct=stop_pct,
        tp_pct=tp_pct,
        rr_planned=rr,
        notional=notional,
        risk_usd=risk_usd,
        fr_pct=fr_pct,
        rv_ratio=rv_ratio,
        breadth=breadth,
    )


def _funding_cost(planned: PlannedTrade, exit_ts: int, funding_rates: list[FundingRate]) -> tuple[float, int]:
    paid = 0.0
    crossed = 0
    for item in funding_rates:
        if planned.entry_ts < item.ts <= exit_ts:
            crossed = 1
            if planned.direction == "long":
                paid += planned.notional * item.rate
            else:
                paid -= planned.notional * item.rate
    return paid, crossed


def simulate_exit(
    planned: PlannedTrade,
    bars_1m: list[Kline],
    funding_rates: list[FundingRate],
    params: StrategyParams,
) -> TradeResult:
    rows = [bar for bar in sorted(bars_1m, key=lambda item: item.open_ms) if bar.open_ms >= planned.entry_ts]
    if not rows:
        raise ValueError(f"no exit bars for {planned.symbol} after {iso_utc(planned.entry_ts)}")
    qty = planned.notional / planned.entry_px
    max_hold_ms = int(params.max_hold_hours * INTERVAL_MS["1h"])
    exit_raw = rows[-1].c
    exit_ts = rows[-1].close_ms
    exit_reason = "timeout"
    ambiguous = 0

    for bar in rows:
        if planned.direction == "long":
            hit_sl = bar.l <= planned.sl
            hit_tp = bar.h >= planned.tp
        else:
            hit_sl = bar.h >= planned.sl
            hit_tp = bar.l <= planned.tp
        if hit_sl:
            exit_raw = planned.sl
            exit_ts = bar.close_ms
            exit_reason = "SL"
            ambiguous = 1 if hit_tp else 0
            break
        if hit_tp:
            exit_raw = planned.tp
            exit_ts = bar.close_ms
            exit_reason = "TP"
            break
        if bar.close_ms - planned.entry_ts > max_hold_ms:
            exit_raw = bar.c
            exit_ts = bar.close_ms
            exit_reason = "timeout"
            break

    exit_px = _exit_price(exit_raw, planned.direction, params)
    if planned.direction == "long":
        gross_pnl = (exit_px - planned.entry_px) * qty
    else:
        gross_pnl = (planned.entry_px - exit_px) * qty
    exit_notional = abs(qty * exit_px)
    fees = planned.notional * params.taker_fee_rate + exit_notional * params.taker_fee_rate
    funding_paid, crossed = _funding_cost(planned, exit_ts, funding_rates)
    net_pnl = gross_pnl - fees - funding_paid
    r_value = net_pnl / planned.risk_usd if planned.risk_usd else 0.0
    hold_minutes = max(0, int(round((exit_ts - planned.entry_ts) / INTERVAL_MS["1m"])))
    return TradeResult(
        symbol=planned.symbol,
        direction=planned.direction,
        tier=planned.tier,
        grade=planned.grade,
        entry_ts=planned.entry_ts,
        entry_px=planned.entry_px,
        sl=planned.sl,
        tp=planned.tp,
        stop_pct=planned.stop_pct,
        tp_pct=planned.tp_pct,
        rr_planned=planned.rr_planned,
        notional=planned.notional,
        risk_usd=planned.risk_usd,
        exit_ts=exit_ts,
        exit_px=exit_px,
        exit_reason=exit_reason,
        gross_pnl=gross_pnl,
        fees=fees,
        funding_paid=funding_paid,
        net_pnl=net_pnl,
        r=r_value,
        fr_pct=planned.fr_pct,
        rv_ratio=planned.rv_ratio,
        breadth=planned.breadth,
        crossed_settlement=crossed,
        ambiguous=ambiguous,
        hold_minutes=hold_minutes,
    )


def rv_ratio_at(daily_btc: list[Kline], ts_ms: int) -> float | None:
    closed = [bar for bar in daily_btc if bar.close_ms <= ts_ms and bar.c > 0]
    if len(closed) < 31:
        return None
    closes = [bar.c for bar in closed[-31:]]
    rets = [math.log(closes[idx] / closes[idx - 1]) for idx in range(1, len(closes))]
    if len(rets) < 30:
        return None
    rv7 = statistics.pstdev(rets[-7:])
    rv30 = statistics.pstdev(rets[-30:])
    return rv7 / rv30 if rv30 > 0 else None


def breadth_at(
    hourly_by_symbol: dict[str, list[Kline]],
    universe: list[str],
    ts_ms: int,
    params: StrategyParams,
) -> int | None:
    count = 0
    seen = 0
    for sym in universe:
        rows = hourly_by_symbol.get(sym)
        if not rows:
            continue
        closes = [bar.c for bar in rows if bar.close_ms <= ts_ms]
        rsi = rsi_last(closes) if len(closes) > 14 else None
        if rsi is None:
            continue
        seen += 1
        if rsi >= params.rsi_hi or rsi <= params.rsi_lo:
            count += 1
    return count if seen else None


def _load_env() -> None:
    env = ROOT / "backend" / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)\s*$", line)
        if match:
            os.environ.setdefault(match.group(1), match.group(2).strip().strip('"').strip("'"))


def _metrics(trades: list[TradeResult], start_ms: int, end_ms: int, equity_base: float) -> dict[str, Any]:
    rs = [trade.r for trade in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    equity = equity_base + sum(t.net_pnl for t in trades)
    days = max((end_ms - start_ms) / INTERVAL_MS["1d"], 1.0)
    cagr = (equity / equity_base) ** (365.0 / days) - 1.0 if equity > 0 and equity_base > 0 else None

    curve = []
    acc = 0.0
    peak = 0.0
    max_dd = 0.0
    for trade in sorted(trades, key=lambda item: item.exit_ts):
        acc += trade.r
        peak = max(peak, acc)
        max_dd = min(max_dd, acc - peak)
        curve.append(acc)

    daily: dict[int, float] = {}
    for trade in trades:
        day = floor_ms(trade.exit_ts, "1d")
        daily[day] = daily.get(day, 0.0) + trade.net_pnl / equity_base
    daily_returns = list(daily.values())
    sharpe = None
    if len(daily_returns) > 1:
        stdev = statistics.pstdev(daily_returns)
        if stdev > 0:
            sharpe = statistics.fmean(daily_returns) / stdev * math.sqrt(365.0)

    period_minutes = max((end_ms - start_ms) / INTERVAL_MS["1m"], 1.0)
    exposure = sum(t.hold_minutes for t in trades) / period_minutes
    turnover = sum(t.notional for t in trades) / equity_base if equity_base > 0 else None
    return {
        "n": len(trades),
        "wins": len(wins),
        "win_rate": len(wins) / len(rs) if rs else None,
        "total_r": sum(rs),
        "avg_r": statistics.fmean(rs) if rs else None,
        "profit_factor": gross_win / abs(gross_loss) if gross_loss < 0 else None,
        "net_pnl": sum(t.net_pnl for t in trades),
        "fees": sum(t.fees for t in trades),
        "funding_paid": sum(t.funding_paid for t in trades),
        "cagr": cagr,
        "max_drawdown_r": abs(max_dd),
        "sharpe": sharpe,
        "avg_hold_min": statistics.fmean(t.hold_minutes for t in trades) if trades else None,
        "turnover": turnover,
        "exposure": exposure,
        "timeouts": sum(1 for t in trades if t.exit_reason == "timeout"),
        "ambiguous": sum(t.ambiguous for t in trades),
        "crossed_settlement": sum(t.crossed_settlement for t in trades),
        "equity_curve_r": curve,
    }


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value * 100.0:.{digits}f}%"


def _bucket_line(label: str, trades: list[TradeResult]) -> str:
    m = _metrics(trades, 0, INTERVAL_MS["1d"], 1000.0)
    pf = "inf" if m["profit_factor"] is None and m["n"] and m["total_r"] > 0 else _fmt_num(m["profit_factor"])
    return (
        f"{label:<12} n={m['n']:>4} win={_fmt_pct(m['win_rate'], 0):>5} "
        f"totalR={m['total_r']:>8.2f} avgR={_fmt_num(m['avg_r']):>6} PF={pf:>6}"
    )


def _group_report(title: str, trades: list[TradeResult], labels: list[str], key_fn) -> list[str]:
    lines = [f"\n## {title}"]
    for label in labels:
        bucket = [trade for trade in trades if key_fn(trade) == label]
        lines.append(_bucket_line(label, bucket))
    return lines


def _meat_bucket(trade: TradeResult) -> str:
    if trade.tp_pct < 1:
        return "<1%"
    if trade.tp_pct < 2:
        return "1-2%"
    return ">=2%"


def _stop_bucket(trade: TradeResult) -> str:
    if trade.stop_pct < 1:
        return "<1%"
    if trade.stop_pct < 2:
        return "1-2%"
    return ">=2%"


def _rv_bucket(trade: TradeResult) -> str:
    if trade.rv_ratio is None:
        return "(missing)"
    if trade.rv_ratio < 0.8:
        return "<0.8"
    if trade.rv_ratio <= 1.3:
        return "0.8-1.3"
    return ">1.3"


def _breadth_bucket(trade: TradeResult) -> str:
    if trade.breadth is None:
        return "(missing)"
    if trade.breadth < 50:
        return "<50"
    if trade.breadth < 100:
        return "50-99"
    return ">=100"


def _fr_bucket(trade: TradeResult) -> str:
    if trade.fr_pct is None:
        return "(missing)"
    if trade.fr_pct <= 10:
        return "<=10"
    if trade.fr_pct >= 90:
        return ">=90"
    return "10-90"


def build_report(
    trades: list[TradeResult],
    params: StrategyParams,
    start_ms: int,
    end_ms: int,
    variant: str,
    hypothesis: str,
    equity_base: float,
    cost_label: str | None = None,
    notes: list[str] | None = None,
) -> str:
    m = _metrics(trades, start_ms, end_ms, equity_base)
    lines = [
        "# Crypto Backtest Report",
        "",
        "## Overview",
        f"variant={variant}{f' cost={cost_label}' if cost_label else ''}",
        f"period={iso_utc(start_ms)} to {iso_utc(end_ms)}",
        f"hypothesis={hypothesis}",
        (
            f"trades={m['n']} win_rate={_fmt_pct(m['win_rate'])} totalR={m['total_r']:.2f} "
            f"avgR={_fmt_num(m['avg_r'])} PF={_fmt_num(m['profit_factor'])} netPnL={m['net_pnl']:.2f}"
        ),
        (
            f"CAGR={_fmt_pct(m['cagr'])} maxDD_R={_fmt_num(m['max_drawdown_r'])} "
            f"Sharpe={_fmt_num(m['sharpe'])} exposure={_fmt_pct(m['exposure'])} "
            f"turnover={_fmt_num(m['turnover'])}"
        ),
        (
            f"fees={m['fees']:.2f} funding_paid={m['funding_paid']:.2f} "
            f"timeouts={m['timeouts']} ambiguous={m['ambiguous']} crossed_settlement={m['crossed_settlement']}"
        ),
        "",
        "Data notes: OI history is unavailable beyond roughly 30 days, so grade uses funding percentile and BTC RV only.",
        "Universe note: backtest universe uses previous UTC daily quoteVolume and abs daily return; this approximates the live rolling 24h scanner.",
        "Breadth note: cross-sectional breadth uses last closed 1h RSI to avoid downloading all symbols' 1m partial bars.",
        f"Higher-timeframe policy: {params.higher_timeframe_policy}.",
    ]
    if notes:
        lines.extend(["", "## Notes", *[f"- {note}" for note in notes]])

    lines.extend(_group_report("Grade S/A/B/C", trades, ["S", "A", "B", "C"], lambda t: t.grade))

    lines.append("\n## Meat Buckets and Breakeven Win Rate")
    for label in ["<1%", "1-2%", ">=2%"]:
        bucket = [trade for trade in trades if _meat_bucket(trade) == label]
        reqs = [trade.stop_pct / (trade.stop_pct + trade.tp_pct) for trade in bucket if trade.stop_pct + trade.tp_pct > 0]
        line = _bucket_line(label, bucket)
        lines.append(f"{line} breakeven_win={_fmt_pct(statistics.fmean(reqs) if reqs else None, 0)}")

    lines.extend(_group_report("Stop Buckets", trades, ["<1%", "1-2%", ">=2%"], _stop_bucket))
    lines.extend(_group_report("Tier Star/Diamond", trades, ["★", "◆"], lambda t: t.tier))
    lines.extend(_group_report("RV Buckets", trades, ["<0.8", "0.8-1.3", ">1.3", "(missing)"], _rv_bucket))
    lines.extend(_group_report("Breadth Buckets", trades, ["<50", "50-99", ">=100", "(missing)"], _breadth_bucket))
    lines.extend(_group_report("Funding Buckets", trades, ["<=10", "10-90", ">=90", "(missing)"], _fr_bucket))

    curve_tail = ", ".join(f"{x:.2f}" for x in m["equity_curve_r"][-50:])
    lines.extend(
        [
            "\n## Equity Curve",
            f"cumulative_R_tail={curve_tail or '(empty)'}",
            "\n## Parameters",
            f"pin_bars={params.pin_bars} tp_target={params.tp_target} min_stop={params.min_stop}",
            f"fee_rate={params.taker_fee_rate} slippage_rate={params.slippage_rate} max_hold_hours={params.max_hold_hours}",
            f"squeeze_guard={params.squeeze_guard} tier_filter={params.tier_filter} rr_min={params.rr_min} rv_max={params.rv_max}",
            f"higher_timeframe_policy={params.higher_timeframe_policy}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_trades_csv(path: Path, trades: list[TradeResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [trade.to_row() for trade in trades]
    fieldnames = list(rows[0].keys()) if rows else list(TradeResult.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ensure_ledger() -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LEDGER_PATH.exists():
        return
    LEDGER_PATH.write_text(
        "# Crypto Experiments Ledger\n\n"
        "Discipline: dev period is 2025-10-01 to 2026-05-31. OOS starts on 2026-06-01 and is sealed unless --oos is explicitly approved. "
        "Each run must include a hypothesis and must not touch the Taiwan stock experiment ledger.\n\n"
        "| UTC time | variant | period | OOS | hypothesis | trades | total R | win rate | PF | report |\n"
        "|---|---|---|---|---|---:|---:|---:|---:|---|\n",
        encoding="utf-8",
    )


def append_ledger(
    run_dir: Path,
    trades: list[TradeResult],
    variant: str,
    start_ms: int,
    end_ms: int,
    hypothesis: str,
    allow_oos: bool,
    equity_base: float,
) -> None:
    ensure_ledger()
    m = _metrics(trades, start_ms, end_ms, equity_base)
    pf = "inf" if m["profit_factor"] is None and m["n"] and m["total_r"] > 0 else _fmt_num(m["profit_factor"])
    line = (
        f"| {datetime.now(timezone.utc).isoformat(timespec='seconds')} | {variant} | "
        f"{iso_utc(start_ms)} to {iso_utc(end_ms)} | {'yes' if allow_oos else 'no'} | "
        f"{hypothesis.replace('|', '/')} | {m['n']} | {m['total_r']:.2f} | "
        f"{_fmt_pct(m['win_rate'])} | {pf} | {run_dir.as_posix()} |\n"
    )
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _events_for_symbol(
    store: CryptoBacktestStore,
    client: BinanceFuturesClient | None,
    sym: str,
    hourly: list[Kline],
    windows: list[tuple[int, int]],
    params: StrategyParams,
    start_ms: int,
    end_ms: int,
) -> list[SignalEvent]:
    events: dict[int, SignalEvent] = {}
    for win_start, win_end in windows:
        klines_1m = store.ensure_klines(sym, "1m", win_start, win_end, client)
        local = find_signal_events_for_symbol(sym, klines_1m, hourly, params, start_ms, end_ms)
        for event in local:
            events[event.confirm_ms] = event
    return sorted(events.values(), key=lambda item: item.confirm_ms)


def _build_context(
    store: CryptoBacktestStore,
    hourly_by_symbol: dict[str, list[Kline]],
    daily_btc: list[Kline],
    universe_by_day: dict[int, list[str]],
    event: SignalEvent,
    params: StrategyParams,
) -> tuple[float | None, float | None, int | None, list[float]]:
    universe = universe_for_ts(universe_by_day, event.confirm_ms)
    fr_pct = funding_percentile_at(store, universe, event.symbol, event.confirm_ms) if universe else None
    rv = rv_ratio_at(daily_btc, event.confirm_ms)
    breadth = breadth_at(hourly_by_symbol, universe, event.confirm_ms, params) if universe else None
    fr_recent = store.recent_funding_rates(event.symbol, event.confirm_ms, 3)
    return fr_pct, rv, breadth, fr_recent


def run_backtest_once(
    *,
    store: CryptoBacktestStore,
    client: BinanceFuturesClient | None,
    start_ms: int,
    end_ms: int,
    params: StrategyParams,
    variant: str,
    symbols: list[str] | None,
    min_quote_volume: float,
    top_n: int,
) -> tuple[list[TradeResult], list[str]]:
    notes: list[str] = []
    universe_by_day = build_daily_universe(
        store,
        client,
        start_ms,
        end_ms,
        min_quote_volume=min_quote_volume,
        top_n=top_n,
        symbols=symbols,
        findings=notes,
    )
    all_symbols = sorted({sym for members in universe_by_day.values() for sym in members})
    if symbols:
        all_symbols = sorted(set(symbols))
        for day in list(universe_by_day):
            universe_by_day[day] = [sym for sym in universe_by_day[day] if sym in all_symbols] or all_symbols
    if not all_symbols:
        return [], ["No symbols passed the universe filter."]

    warmup_1h = start_ms - 3 * INTERVAL_MS["1d"]
    funding_start = start_ms - INTERVAL_MS["1d"]
    funding_end = end_ms + int(params.max_hold_hours * INTERVAL_MS["1h"])
    hourly_by_symbol: dict[str, list[Kline]] = {}
    windows_by_symbol: dict[str, list[tuple[int, int]]] = {}

    for idx, sym in enumerate(all_symbols, start=1):
        try:
            hourly = store.ensure_klines(sym, "1h", warmup_1h, end_ms, client)
            windows = scan_hourly_event_windows(hourly, start_ms, end_ms, params.rsi_hi, params.rsi_lo)
            store.ensure_funding(sym, funding_start, funding_end, client)
            hourly_by_symbol[sym] = hourly
            if windows:
                windows_by_symbol[sym] = windows
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{sym}: data load skipped ({str(exc)[:120]})")
        if idx % 25 == 0:
            print(f"loaded stage-1 data for {idx}/{len(all_symbols)} symbols", flush=True)

    daily_btc = store.ensure_klines("BTCUSDT", "1d", start_ms - 45 * INTERVAL_MS["1d"], end_ms, client)
    trades: list[TradeResult] = []
    for idx, sym in enumerate(sorted(windows_by_symbol), start=1):
        windows = merge_windows(windows_by_symbol[sym])
        try:
            events = _events_for_symbol(store, client, sym, hourly_by_symbol[sym], windows, params, start_ms, end_ms)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{sym}: stage-2 signal load skipped ({str(exc)[:120]})")
            continue
        if not events:
            continue
        next_allowed = 0
        open_until = 0
        for event in events:
            if event.confirm_ms < next_allowed or event.confirm_ms < open_until:
                continue
            try:
                fr_pct, rv, breadth, fr_recent = _build_context(
                    store, hourly_by_symbol, daily_btc, universe_by_day, event, params
                )
                context_start = event.confirm_ms - 12 * INTERVAL_MS["1h"]
                context_end = event.confirm_ms + 2 * INTERVAL_MS["1h"]
                klines_1m = store.ensure_klines(sym, "1m", context_start, context_end, client)
                klines_15m = store.ensure_klines(sym, "15m", context_start, context_end, client)
                planned = plan_trade(event, klines_1m, klines_15m, params, fr_pct, rv, breadth, fr_recent)
                next_allowed = event.confirm_ms + params.cooldown_minutes * INTERVAL_MS["1m"]
                if planned is None:
                    continue
                exit_end = planned.entry_ts + int(params.max_hold_hours * INTERVAL_MS["1h"]) + 2 * INTERVAL_MS["1m"]
                exit_bars = store.ensure_klines(sym, "1m", planned.entry_ts, exit_end, client)
                funding = store.ensure_funding(sym, planned.entry_ts, exit_end, client)
                result = simulate_exit(planned, exit_bars, funding, params)
            except Exception as exc:  # noqa: BLE001
                notes.append(
                    f"{sym}: event {iso_utc(event.confirm_ms)} skipped for incomplete replay data ({str(exc)[:120]})"
                )
                continue
            trades.append(result)
            open_until = result.exit_ts
        if idx % 10 == 0:
            print(f"simulated {idx}/{len(windows_by_symbol)} active symbols; trades={len(trades)}", flush=True)

    trades.sort(key=lambda item: item.entry_ts)
    return trades, notes


def _cost_scenarios(base: StrategyParams) -> list[tuple[str, StrategyParams]]:
    return [
        ("0pct", replace(base, taker_fee_rate=0.0, slippage_rate=0.0)),
        ("0.1pct", replace(base, taker_fee_rate=0.0005, slippage_rate=0.0005)),
        ("0.2pct", replace(base, taker_fee_rate=0.0010, slippage_rate=0.0010)),
    ]


def _write_cost_summary(path: Path, scenario_results: list[tuple[str, list[TradeResult]]], start_ms: int, end_ms: int, equity_base: float) -> None:
    lines = ["# Cost Sensitivity", "", "| fees+slip | trades | total R | win rate | PF | net PnL |", "|---|---:|---:|---:|---:|---:|"]
    for label, trades in scenario_results:
        m = _metrics(trades, start_ms, end_ms, equity_base)
        pf = "inf" if m["profit_factor"] is None and m["n"] and m["total_r"] > 0 else _fmt_num(m["profit_factor"])
        lines.append(f"| {label} | {m['n']} | {m['total_r']:.2f} | {_fmt_pct(m['win_rate'])} | {pf} | {m['net_pnl']:.2f} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def reconcile_with_notion(
    trades: list[TradeResult],
    start_ms: int,
    end_ms: int,
    out_csv: Path,
) -> str:
    _load_env()
    token = os.getenv("NOTION_TOKEN")
    db_id = os.getenv("AUTOTRADE_NOTION_DB_ID") or os.getenv("NOTION_DB_ID")
    if not token or not db_id:
        msg = "reconciliation skipped: missing NOTION_TOKEN or AUTOTRADE_NOTION_DB_ID/NOTION_DB_ID"
        out_csv.write_text("status,detail\nskipped,missing Notion env\n", encoding="utf-8")
        return msg
    try:
        from backend.scripts import notion_journal

        live_rows = notion_journal.query_trades(token, db_id)
    except Exception as exc:  # noqa: BLE001
        msg = f"reconciliation failed: {exc}"
        out_csv.write_text(f"status,detail\nfailed,{str(exc).replace(',', ';')}\n", encoding="utf-8")
        return msg

    def parse_opened(raw: Any) -> int | None:
        if not raw:
            return None
        try:
            text = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return utc_ms(dt.astimezone(timezone.utc))
        except ValueError:
            return None

    live = []
    for row in live_rows:
        opened = parse_opened(row.get("opened_at"))
        if opened is None or opened < start_ms or opened >= end_ms:
            continue
        sym = str(row.get("sym") or "").upper()
        if sym and not sym.endswith("USDT"):
            sym += "USDT"
        live.append({"sym": sym, "opened": opened, "direction": row.get("direction"), "row": row})

    unmatched_bt = set(range(len(trades)))
    rows: list[dict[str, Any]] = []
    matches = 0
    for item in live:
        best_idx = None
        best_delta = None
        for idx in list(unmatched_bt):
            trade = trades[idx]
            if trade.symbol != item["sym"]:
                continue
            delta = abs(trade.entry_ts - item["opened"])
            if delta <= 5 * INTERVAL_MS["1m"] and (best_delta is None or delta < best_delta):
                best_idx = idx
                best_delta = delta
        if best_idx is None:
            rows.append(
                {
                    "status": "live_only",
                    "live_symbol": item["sym"],
                    "live_entry_ts": iso_utc(item["opened"]),
                    "live_direction": item["direction"],
                    "bt_symbol": "",
                    "bt_entry_ts": "",
                    "delta_minutes": "",
                }
            )
        else:
            trade = trades[best_idx]
            unmatched_bt.remove(best_idx)
            matches += 1
            rows.append(
                {
                    "status": "matched",
                    "live_symbol": item["sym"],
                    "live_entry_ts": iso_utc(item["opened"]),
                    "live_direction": item["direction"],
                    "bt_symbol": trade.symbol,
                    "bt_entry_ts": iso_utc(trade.entry_ts),
                    "delta_minutes": round((trade.entry_ts - item["opened"]) / INTERVAL_MS["1m"], 2),
                }
            )
    for idx in sorted(unmatched_bt):
        trade = trades[idx]
        rows.append(
            {
                "status": "backtest_only",
                "live_symbol": "",
                "live_entry_ts": "",
                "live_direction": "",
                "bt_symbol": trade.symbol,
                "bt_entry_ts": iso_utc(trade.entry_ts),
                "delta_minutes": "",
            }
        )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = ["status", "live_symbol", "live_entry_ts", "live_direction", "bt_symbol", "bt_entry_ts", "delta_minutes"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    match_rate = matches / len(live) if live else 0.0
    verdict = "PASS" if not live or match_rate >= 0.70 else "FAIL"
    return f"reconciliation {verdict}: matched {matches}/{len(live)} live trades ({match_rate:.1%}); table={out_csv}"


def run_cli(args: argparse.Namespace) -> Path:
    start_ms = parse_cli_date(args.start)
    end_ms = parse_cli_date(args.end, end_date=True)
    validate_oos_allowed(start_ms, end_ms, args.oos)
    if not args.hypothesis:
        raise SystemExit("--hypothesis is required")
    base_params = params_for_variant(args.variant)
    if args.fee_rate is not None:
        base_params = replace(base_params, taker_fee_rate=args.fee_rate)
    if args.slippage_rate is not None:
        base_params = replace(base_params, slippage_rate=args.slippage_rate)
    if args.higher_timeframe_policy is not None:
        base_params = replace(base_params, higher_timeframe_policy=args.higher_timeframe_policy)
    symbols = None
    if args.symbols:
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
        symbols = [sym if sym.endswith("USDT") else f"{sym}USDT" for sym in symbols]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / f"{stamp}_{args.variant}"
    run_dir.mkdir(parents=True, exist_ok=True)
    store_notes: list[str] = []
    try:
        store = CryptoBacktestStore(args.db)
    except Exception as exc:  # noqa: BLE001
        requested = Path(args.db)
        if requested.resolve() != DEFAULT_DB.resolve():
            raise
        fallback = Path.home() / ".codex" / "memories" / "crypto_backtest" / "klines.db"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        print(f"WARNING: default SQLite cache failed at {requested}: {exc}; using {fallback}", flush=True)
        store = CryptoBacktestStore(fallback)
        store_notes.append(f"Default SQLite cache failed at {requested}; used fallback cache {fallback}.")
    client = None if args.offline else BinanceFuturesClient()
    try:
        if args.cost_sensitivity:
            scenario_results: list[tuple[str, list[TradeResult]]] = []
            scenario_notes: list[str] = []
            for label, params in _cost_scenarios(base_params):
                print(f"running cost scenario {label}", flush=True)
                trades, notes = run_backtest_once(
                    store=store,
                    client=client,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    params=params,
                    variant=args.variant,
                    symbols=symbols,
                    min_quote_volume=args.min_quote_volume,
                    top_n=args.top,
                )
                scenario_results.append((label, trades))
                notes = store_notes + notes
                scenario_notes.extend(f"{label}: {note}" for note in notes[:10])
                write_trades_csv(run_dir / f"trades_{label}.csv", trades)
                (run_dir / f"report_{label}.txt").write_text(
                    build_report(trades, params, start_ms, end_ms, args.variant, args.hypothesis, args.equity_base, label, notes),
                    encoding="utf-8",
                )
            base_label, base_trades = scenario_results[1]
            write_trades_csv(run_dir / "trades.csv", base_trades)
            _write_cost_summary(run_dir / "cost_sensitivity.txt", scenario_results, start_ms, end_ms, args.equity_base)
            (run_dir / "report.txt").write_text(
                (run_dir / f"report_{base_label}.txt").read_text(encoding="utf-8")
                + "\n"
                + (run_dir / "cost_sensitivity.txt").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            append_ledger(run_dir, base_trades, args.variant, start_ms, end_ms, args.hypothesis, args.oos, args.equity_base)
            if args.reconcile:
                msg = reconcile_with_notion(base_trades, start_ms, end_ms, run_dir / "reconciliation.csv")
                with (run_dir / "report.txt").open("a", encoding="utf-8") as fh:
                    fh.write(f"\n## Reconciliation\n{msg}\n")
        else:
            trades, notes = run_backtest_once(
                store=store,
                client=client,
                start_ms=start_ms,
                end_ms=end_ms,
                params=base_params,
                variant=args.variant,
                symbols=symbols,
                min_quote_volume=args.min_quote_volume,
                top_n=args.top,
            )
            notes = store_notes + notes
            write_trades_csv(run_dir / "trades.csv", trades)
            report = build_report(trades, base_params, start_ms, end_ms, args.variant, args.hypothesis, args.equity_base, None, notes)
            (run_dir / "report.txt").write_text(report, encoding="utf-8")
            append_ledger(run_dir, trades, args.variant, start_ms, end_ms, args.hypothesis, args.oos, args.equity_base)
            if args.reconcile:
                msg = reconcile_with_notion(trades, start_ms, end_ms, run_dir / "reconciliation.csv")
                with (run_dir / "report.txt").open("a", encoding="utf-8") as fh:
                    fh.write(f"\n## Reconciliation\n{msg}\n")
        return run_dir
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crypto historical mean-reversion backtester")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True, help="Inclusive UTC date when YYYY-MM-DD is used")
    parser.add_argument("--variant", default="baseline", choices=sorted(VARIANTS))
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--oos", action="store_true", help="Explicitly allow sealed OOS period from 2026-06-01")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--symbols", help="Comma-separated symbols for a constrained/debug run")
    parser.add_argument("--top", type=int, default=150)
    parser.add_argument("--min-quote-volume", type=float, default=15_000_000.0)
    parser.add_argument("--fee-rate", type=float)
    parser.add_argument("--slippage-rate", type=float)
    parser.add_argument(
        "--higher-timeframe-policy",
        choices=("closed_only", "partial_live_mirror"),
        help="Strict research uses closed_only; partial_live_mirror is legacy fidelity only.",
    )
    parser.add_argument("--equity-base", type=float, default=1000.0)
    parser.add_argument("--cost-sensitivity", action="store_true")
    parser.add_argument("--reconcile", action="store_true", help="Compare backtest entries with Notion v2 live records")
    parser.add_argument("--offline", action="store_true", help="Use only cached SQLite data; fail if data is missing")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run_dir = run_cli(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    print(f"run_dir={run_dir}")


if __name__ == "__main__":
    main()
