"""Point-in-time market regime feature builder.

The distribution-day and follow-through-day fields are informational for now.
They can later augment R-5, but Phase F only computes them and never blocks on
market regime or missing index data.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from backend.app.services.screener_market_loader import load_taiex_history_with_source
from backend.app.services.sector_service import list_ai_tech_codes
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.types import MarketFeatures


def build_market_features(
    as_of_date: str,
    *,
    index_bundle: Mapping[str, Any] | None = None,
    store: Any = None,
    universe: Sequence[str] | None = None,
) -> MarketFeatures:
    """Build point-in-time MarketFeatures from injected or existing market data."""
    params = load_params()
    missing: list[str] = []
    warnings: list[str] = []
    bundle = dict(index_bundle or {})
    store_taiex = _index_from_store(store, as_of_date, ("TAIEX", "^TWII", "Y9999"))
    store_tpex = _index_from_store(store, as_of_date, ("TPEX", "^TWOII", "OTC"))
    store_sox = _index_from_store(store, as_of_date, ("^SOX", "SOX", "SOXX"))
    store_nasdaq = _index_from_store(store, as_of_date, ("^IXIC", "IXIC", "NASDAQ", "^NDX"))
    if index_bundle is None and store_taiex is None:
        loaded = _load_default_taiex()
        if loaded is not None:
            bundle["taiex"] = loaded
        else:
            warnings.append("TAIEX market loader unavailable")

    features: dict[str, Any] = {}
    taiex_frame = bundle.get("taiex")
    if taiex_frame is None:
        taiex_frame = store_taiex
    tpex_frame = bundle.get("tpex")
    if tpex_frame is None:
        tpex_frame = store_tpex
    features.update(_index_features(taiex_frame, as_of_date, "taiex", params, missing, warnings))
    features.update(_index_features(tpex_frame, as_of_date, "tpex", params, missing, warnings))
    features.update(_external_features(bundle, as_of_date, params, missing, warnings, store_sox=store_sox, store_nasdaq=store_nasdaq))
    features.update(_taiex_ex_tsmc_features(bundle, as_of_date, params, missing, warnings))
    features["breadth_above_ma60_pct"] = _breadth_above_ma60_pct(
        as_of_date,
        store=store,
        universe=universe,
        params=params,
        missing=missing,
        warnings=warnings,
    )

    taiex = _frame_as_of(taiex_frame, as_of_date)
    if taiex is None:
        features["distribution_day_count"] = None
        features["follow_through_day"] = None
        missing.extend(["distribution_day_count", "follow_through_day"])
    else:
        features["distribution_day_count"] = _distribution_day_count(taiex)
        features["follow_through_day"] = _follow_through_day(taiex)

    return MarketFeatures(
        **features,
        missing_fields=_dedupe(missing),
        data_warnings=_dedupe(warnings),
    )


def _index_features(
    frame: Any,
    as_of_date: str,
    prefix: str,
    params: Mapping[str, Any],
    missing: list[str],
    warnings: list[str],
) -> dict[str, float | None]:
    rule_id = "M-1" if prefix == "taiex" else "M-2"
    rule = params["market"]["rules"][rule_id]
    ma_days = int(rule["thresholds"]["ma_days"])
    slope_lookback = int(rule["thresholds"]["slope_lookback_bars"])
    out = {f"{prefix}_close": None, f"{prefix}_ma150": None, f"{prefix}_ma150_slope": None}
    bars = _frame_as_of(frame, as_of_date)
    if bars is None:
        missing.extend(out)
        warnings.append(f"{prefix.upper()} index data missing")
        return out

    close = pd.to_numeric(bars["close"], errors="coerce").dropna()
    if len(close) < ma_days:
        missing.extend([f"{prefix}_ma150", f"{prefix}_ma150_slope"])
        warnings.append(f"{prefix.upper()} insufficient bars for MA{ma_days}")
        out[f"{prefix}_close"] = _clean_float(close.iloc[-1]) if not close.empty else None
        if out[f"{prefix}_close"] is None:
            missing.append(f"{prefix}_close")
        return out

    ma = close.tail(ma_days).mean()
    prior_window = close.iloc[-ma_days - slope_lookback : -slope_lookback] if len(close) >= ma_days + slope_lookback else close.iloc[:ma_days]
    prior_ma = prior_window.mean()
    out[f"{prefix}_close"] = _clean_float(close.iloc[-1])
    out[f"{prefix}_ma150"] = _clean_float(ma)
    out[f"{prefix}_ma150_slope"] = _safe_ratio(float(ma) - float(prior_ma), float(prior_ma))
    return out


def _external_features(
    bundle: Mapping[str, Any],
    as_of_date: str,
    params: Mapping[str, Any],
    missing: list[str],
    warnings: list[str],
    *,
    store_sox: Any = None,
    store_nasdaq: Any = None,
) -> dict[str, bool | None]:
    ma_days = int(params["market"]["rules"]["M-4"]["thresholds"]["external_ma_days"])
    sox_frame = bundle.get("sox") if bundle.get("sox") is not None else store_sox
    nasdaq_frame = bundle.get("nasdaq") if bundle.get("nasdaq") is not None else store_nasdaq
    out = {
        "sox_above_ma60": _above_ma(sox_frame, as_of_date, ma_days),
        "nasdaq_above_ma60": _above_ma(nasdaq_frame, as_of_date, ma_days),
    }
    for key, value in out.items():
        if value is None:
            missing.append(key)
            warnings.append(f"{key} input missing or insufficient")
    return out


def _taiex_ex_tsmc_features(
    bundle: Mapping[str, Any],
    as_of_date: str,
    params: Mapping[str, Any],
    missing: list[str],
    warnings: list[str],
) -> dict[str, float | None]:
    out = {"taiex_ex_tsmc_close": None, "taiex_ex_tsmc_ma150": None, "taiex_ex_tsmc_ma150_slope": None}
    if "2330_weight" not in bundle or bundle.get("taiex_ex_tsmc") is None:
        missing.extend(out)
        warnings.append("ex-TSMC proxy unavailable; using full TAIEX")
        return out

    proxy = _index_features(bundle.get("taiex_ex_tsmc"), as_of_date, "taiex", params, missing, warnings)
    return {
        "taiex_ex_tsmc_close": proxy["taiex_close"],
        "taiex_ex_tsmc_ma150": proxy["taiex_ma150"],
        "taiex_ex_tsmc_ma150_slope": proxy["taiex_ma150_slope"],
    }


def _breadth_above_ma60_pct(
    as_of_date: str,
    *,
    store: Any,
    universe: Sequence[str] | None,
    params: Mapping[str, Any],
    missing: list[str],
    warnings: list[str],
) -> float | None:
    if store is None:
        missing.append("breadth_above_ma60_pct")
        warnings.append("historical store missing; breadth unavailable")
        return None

    codes = list(universe) if universe is not None else sorted(list_ai_tech_codes())
    ma_days = int(params["market"]["rules"]["M-3"]["thresholds"]["ma_days"])
    checked = 0
    above = 0
    for code in codes:
        bars = store.get_ohlcv_as_of(str(code), as_of_date, ma_days)
        if bars is None or bars.empty or len(bars) < ma_days or "close" not in bars:
            continue
        close = pd.to_numeric(bars["close"], errors="coerce").dropna()
        if len(close) < ma_days:
            continue
        checked += 1
        if float(close.iloc[-1]) > float(close.tail(ma_days).mean()):
            above += 1

    if checked == 0:
        missing.append("breadth_above_ma60_pct")
        warnings.append("breadth universe data missing")
        return None
    return above / checked


def _index_from_store(store: Any, as_of_date: str, candidates: Sequence[str]) -> pd.DataFrame | None:
    if store is None:
        return None
    for symbol in candidates:
        try:
            bars = store.get_ohlcv_as_of(symbol, as_of_date, 220)
        except Exception:
            continue
        if bars is not None and not bars.empty:
            return bars
    return None


def _above_ma(frame: Any, as_of_date: str, ma_days: int) -> bool | None:
    bars = _frame_as_of(frame, as_of_date)
    if bars is None or len(bars) < ma_days:
        return None
    close = pd.to_numeric(bars["close"], errors="coerce").dropna()
    if len(close) < ma_days:
        return None
    return bool(float(close.iloc[-1]) > float(close.tail(ma_days).mean()))


def _distribution_day_count(bars: pd.DataFrame) -> int | None:
    if len(bars) < 2 or "volume" not in bars:
        return None
    recent = bars.tail(25).copy()
    close = pd.to_numeric(recent["close"], errors="coerce")
    volume = pd.to_numeric(recent["volume"], errors="coerce")
    down = close.pct_change() <= -0.002
    higher_volume = volume > volume.shift(1)
    return int((down & higher_volume).sum())


def _follow_through_day(bars: pd.DataFrame) -> bool | None:
    if len(bars) < 5 or "volume" not in bars:
        return None
    recent = bars.tail(25).copy()
    close = pd.to_numeric(recent["close"], errors="coerce")
    volume = pd.to_numeric(recent["volume"], errors="coerce")
    low_idx = int(close.idxmin())
    after_low = recent.loc[low_idx:].copy()
    if len(after_low) < 4:
        return False
    close_after = pd.to_numeric(after_low["close"], errors="coerce")
    volume_after = pd.to_numeric(after_low["volume"], errors="coerce")
    rally = close_after.pct_change() >= 0.015
    rising_volume = volume_after > volume_after.shift(1)
    return bool((rally & rising_volume).any())


def _frame_as_of(frame: Any, as_of_date: str) -> pd.DataFrame | None:
    if frame is None:
        return None
    df = pd.DataFrame(frame).copy()
    if df.empty or "date" not in df or "close" not in df:
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    cutoff = pd.to_datetime(as_of_date)
    df = df[df["date"].notna() & (df["date"] <= cutoff)].sort_values("date").reset_index(drop=True)
    return df if not df.empty else None


def _load_default_taiex() -> pd.DataFrame | None:
    try:
        result = asyncio.run(load_taiex_history_with_source(days=260))
    except RuntimeError:
        return None
    except Exception:
        return None
    return result.dataframe if result.available else None


def _clean_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
