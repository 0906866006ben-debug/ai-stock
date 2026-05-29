"""Pure CAN SLIM feature extraction layer."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backend.app.services.backtest.historical_data_store import HistoricalDataStore


class CanslimFeatures(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of_date: str

    month_revenue_yoy: list[float] | None = None
    quarterly_eps_yoy: float | None = None
    quarterly_eps_yoy_series: list[float] | None = None
    eps_cagr_3y: float | None = None
    roe_ttm: float | None = None
    op_margin_last4: list[float] | None = None
    pe_ttm: float | None = None
    ttm_eps: float | None = None
    latest_fy_eps: float | None = None
    annual_eps_last3: list[float] | None = None
    shares_outstanding: float | None = None

    close: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    ma120: float | None = None
    ma120_slope: float | None = None
    high_252d: float | None = None
    pct_from_52w_high: float | None = None
    rs_60d_pct: float | None = None
    rs_252d_pct: float | None = None

    at_limit_up: bool | None = None
    at_limit_down: bool | None = None
    avg_volume_20: float | None = None
    avg_volume_50: float | None = None
    avg_turnover_20: float | None = None
    up_down_volume_ratio_10: float | None = None
    volume_ratio_recent_vs_prior_20: float | None = None
    latest_volume: float | None = None
    is_20d_high: bool | None = None
    box_high_20: float | None = None
    box_low_20: float | None = None
    box_high_prior_20: float | None = None
    box_low_prior_20: float | None = None

    foreign_net_5: list[float] | None = None
    trust_net_5: list[float] | None = None
    dealer_net_5: list[float] | None = None

    day_trade_ratio: None = None
    chip_concentration: None = None
    event_window_active: bool | None = None

    missing_fields: list[str] = Field(default_factory=list)
    data_warnings: list[str] = Field(default_factory=list)


def build_features(
    symbol: str,
    as_of_date: str,
    store: HistoricalDataStore,
    *,
    universe_returns_60d: dict[str, float] | None = None,
    universe_returns_252d: dict[str, float] | None = None,
    fin_metrics: dict | None = None,
    detail: dict | None = None,
    eps_filing_date: str | None = None,
    event_window_active: bool | None = None,
) -> CanslimFeatures:
    """Build raw CAN SLIM features without applying any rule thresholds."""
    missing: list[str] = []
    warnings = [
        "day_trade_ratio unavailable in data layer",
        "chip_concentration unavailable in data layer",
    ]

    bars = store.get_ohlcv_as_of(symbol, as_of_date, 252)
    features: dict[str, Any] = {
        "symbol": symbol,
        "as_of_date": as_of_date,
        "day_trade_ratio": None,
        "chip_concentration": None,
        "event_window_active": event_window_active,
    }
    if event_window_active is None:
        missing.append("event_window_active")
    features.update(_ohlcv_features(bars, missing))
    features.update(_growth_features(fin_metrics, detail, eps_filing_date, as_of_date, missing))
    features.update(_institutional_features(detail, as_of_date, missing))

    if universe_returns_60d is None:
        features["rs_60d_pct"] = None
        missing.append("rs_60d_pct")
    else:
        features["rs_60d_pct"] = _rank_percentile(symbol, universe_returns_60d)
        if features["rs_60d_pct"] is None:
            missing.append("rs_60d_pct")

    if universe_returns_252d is None:
        features["rs_252d_pct"] = None
        missing.append("rs_252d_pct")
    else:
        features["rs_252d_pct"] = _rank_percentile(symbol, universe_returns_252d)
        if features["rs_252d_pct"] is None:
            missing.append("rs_252d_pct")

    features["missing_fields"] = _dedupe(missing)
    features["data_warnings"] = warnings
    return CanslimFeatures(**features)


def _ohlcv_features(bars: pd.DataFrame, missing: list[str]) -> dict[str, Any]:
    out = {
        "close": None,
        "ma20": None,
        "ma60": None,
        "ma120": None,
        "ma120_slope": None,
        "high_252d": None,
        "pct_from_52w_high": None,
        "at_limit_up": None,
        "at_limit_down": None,
        "avg_volume_20": None,
        "avg_volume_50": None,
        "avg_turnover_20": None,
        "up_down_volume_ratio_10": None,
        "volume_ratio_recent_vs_prior_20": None,
        "latest_volume": None,
        "is_20d_high": None,
        "box_high_20": None,
        "box_low_20": None,
        "box_high_prior_20": None,
        "box_low_prior_20": None,
    }
    if bars.empty:
        missing.extend(out)
        return out

    close = pd.to_numeric(bars["close"], errors="coerce")
    high = pd.to_numeric(bars["high"], errors="coerce")
    low = pd.to_numeric(bars["low"], errors="coerce")
    volume = pd.to_numeric(bars["volume"], errors="coerce")
    turnover = pd.to_numeric(bars["turnover"], errors="coerce") if "turnover" in bars else pd.Series(dtype=float)

    out["close"] = _clean_float(close.iloc[-1])
    # TW ±10% daily price limit (漲跌停). A limit-up LOCK (closed at the high near +10%)
    # means you cannot fill a market buy — a chase risk, not a buy opportunity; a
    # limit-down lock means exit liquidity is gone. Detected from OHLCV only.
    if len(close.dropna()) >= 2:
        prev_c = _clean_float(close.iloc[-2])
        cur_c = out["close"]
        if prev_c and prev_c > 0 and cur_c is not None:
            ret = cur_c / prev_c - 1.0
            hi = _clean_float(high.iloc[-1])
            lo = _clean_float(low.iloc[-1])
            out["at_limit_up"] = bool(ret >= 0.095 and hi is not None and cur_c >= hi)
            out["at_limit_down"] = bool(ret <= -0.095 and lo is not None and cur_c <= lo)
    _ma(out, missing, "ma20", close, 20)
    _ma(out, missing, "ma60", close, 60)
    _ma(out, missing, "ma120", close, 120)

    if len(close.dropna()) >= 120:
        previous = close.iloc[-20] if len(close) >= 140 else close.iloc[0]
        current = out["ma120"]
        out["ma120_slope"] = _safe_ratio(float(current) - float(previous), float(previous)) if current is not None else None
    else:
        missing.append("ma120_slope")

    if len(high.dropna()) >= 252:
        high_252d = _clean_float(high.tail(252).max())
        out["high_252d"] = high_252d
        out["pct_from_52w_high"] = _safe_ratio(float(out["close"]), high_252d) - 1 if out["close"] is not None and high_252d else None
    else:
        missing.extend(["high_252d", "pct_from_52w_high"])

    if len(volume.dropna()) >= 20:
        out["avg_volume_20"] = _clean_float(volume.tail(20).mean())
    else:
        missing.append("avg_volume_20")

    if len(volume.dropna()) >= 50:
        out["avg_volume_50"] = _clean_float(volume.tail(50).mean())
    else:
        missing.append("avg_volume_50")

    out["latest_volume"] = _clean_float(volume.iloc[-1])
    if out["latest_volume"] is None:
        missing.append("latest_volume")

    if len(turnover.dropna()) >= 20:
        out["avg_turnover_20"] = _clean_float(turnover.tail(20).mean())
    else:
        missing.append("avg_turnover_20")

    if len(bars) >= 10:
        recent = bars.tail(10).copy()
        recent_close = pd.to_numeric(recent["close"], errors="coerce")
        recent_volume = pd.to_numeric(recent["volume"], errors="coerce")
        diff = recent_close.diff()
        up_volume = recent_volume[diff > 0]
        down_volume = recent_volume[diff < 0]
        if not up_volume.empty and not down_volume.empty and float(down_volume.mean()) != 0:
            out["up_down_volume_ratio_10"] = _clean_float(float(up_volume.mean()) / float(down_volume.mean()))
        else:
            missing.append("up_down_volume_ratio_10")
    else:
        missing.append("up_down_volume_ratio_10")

    if len(volume.dropna()) >= 20:
        recent_mean = _clean_float(volume.tail(10).mean())
        prior_mean = _clean_float(volume.iloc[-20:-10].mean())
        out["volume_ratio_recent_vs_prior_20"] = (
            _safe_ratio(float(recent_mean), float(prior_mean))
            if recent_mean is not None and prior_mean is not None
            else None
        )
        if out["volume_ratio_recent_vs_prior_20"] is None:
            missing.append("volume_ratio_recent_vs_prior_20")
    else:
        missing.append("volume_ratio_recent_vs_prior_20")

    if len(high.dropna()) >= 20 and len(low.dropna()) >= 20:
        out["box_high_20"] = _clean_float(high.tail(20).max())
        out["box_low_20"] = _clean_float(low.tail(20).min())
        out["is_20d_high"] = out["close"] >= out["box_high_20"] * 0.999 if out["close"] is not None else None
        if out["is_20d_high"] is None:
            missing.append("is_20d_high")
    else:
        missing.extend(["box_high_20", "box_low_20"])
        missing.append("is_20d_high")

    if len(high.dropna()) >= 21 and len(low.dropna()) >= 21:
        out["box_high_prior_20"] = _clean_float(high.iloc[-21:-1].max())
        out["box_low_prior_20"] = _clean_float(low.iloc[-21:-1].min())
    else:
        missing.extend(["box_high_prior_20", "box_low_prior_20"])
    return out


def _growth_features(
    fin_metrics: dict | None,
    detail: dict | None,
    eps_filing_date: str | None,
    as_of_date: str,
    missing: list[str],
) -> dict[str, Any]:
    out = {
        "month_revenue_yoy": None,
        "quarterly_eps_yoy": None,
        "quarterly_eps_yoy_series": None,
        "eps_cagr_3y": None,
        "roe_ttm": None,
        "op_margin_last4": None,
        "pe_ttm": None,
        "ttm_eps": None,
        "latest_fy_eps": None,
        "annual_eps_last3": None,
        "shares_outstanding": None,
    }
    revenue_yoy = _extract_month_revenue_yoy(detail)
    if revenue_yoy is None:
        missing.append("month_revenue_yoy")
    else:
        out["month_revenue_yoy"] = revenue_yoy

    if fin_metrics is None:
        missing.extend(["quarterly_eps_yoy", "eps_cagr_3y", "roe_ttm", "op_margin_last4", "pe_ttm"])
        return out

    if eps_filing_date and _parse_date(eps_filing_date) < _parse_date(as_of_date):
        # quarterly_eps_yoy is a GROWTH RATE that legitimately exceeds 1.0 (>100%
        # growth — exactly what CANSLIM hunts). It must arrive as a fraction from every
        # source (PIT/live adapters normalize at emission), so do NOT apply the
        # magnitude heuristic here: _normalize_ratio(1.5) would corrupt 150% -> 1.5%.
        out["quarterly_eps_yoy"] = _clean_float(_first_present(fin_metrics, "quarterly_eps_yoy", "eps_yoy"))
        if out["quarterly_eps_yoy"] is None:
            missing.append("quarterly_eps_yoy")
        # Quarterly EPS YoY series (fractions) for earnings-acceleration detection (C).
        series = _first_present(fin_metrics, "quarterly_eps_yoy_series")
        if isinstance(series, (list, tuple)):
            cleaned = [_clean_float(v) for v in series]
            cleaned = [v for v in cleaned if v is not None]
            out["quarterly_eps_yoy_series"] = cleaned or None
        if out["quarterly_eps_yoy_series"] is None:
            missing.append("quarterly_eps_yoy_series")
    else:
        missing.append("quarterly_eps_yoy")

    annual_eps = _first_present(fin_metrics, "annual_eps", "annual_eps_last3", "eps_last3")
    out["eps_cagr_3y"] = _eps_cagr_3y(annual_eps)
    if out["eps_cagr_3y"] is None:
        missing.append("eps_cagr_3y")

    # Keep the last-3 annual EPS series itself (not just the endpoint CAGR) so the A
    # pillar can check year-by-year stability, not only first-vs-last growth.
    if annual_eps is not None:
        cleaned_annual = [_clean_float(value) for value in list(annual_eps)[-3:]]
        cleaned_annual = [value for value in cleaned_annual if value is not None]
        out["annual_eps_last3"] = cleaned_annual or None
    if out["annual_eps_last3"] is None:
        missing.append("annual_eps_last3")

    # A-pillar trend guard inputs (report: TTM EPS vs last full fiscal year).
    out["ttm_eps"] = _clean_float(_first_present(fin_metrics, "ttm_eps"))
    latest_fy = _first_present(fin_metrics, "latest_fy_eps")
    if latest_fy is None and annual_eps:
        latest_fy = list(annual_eps)[-1]
    out["latest_fy_eps"] = _clean_float(latest_fy)

    # roe/margins keep the magnitude heuristic: as fractions they are bounded ~<=1, so
    # a value >1 unambiguously means percent units (live source) -> /100 is safe. (This
    # is NOT true for growth-rate fields above, which routinely exceed 1.0.)
    out["roe_ttm"] = _normalize_ratio(_first_present(fin_metrics, "roe_ttm", "roe"))
    if out["roe_ttm"] is None:
        missing.append("roe_ttm")

    margins = _first_present(fin_metrics, "op_margin_last4", "operating_margin_last4", "operating_margins")
    if margins is None:
        single_margin = _normalize_ratio(_first_present(fin_metrics, "operating_margin", "op_margin"))
        out["op_margin_last4"] = [single_margin] if single_margin is not None else None
    else:
        out["op_margin_last4"] = [_normalize_ratio(value) for value in list(margins)[-4:]]
    if not out["op_margin_last4"] or any(value is None for value in out["op_margin_last4"]):
        out["op_margin_last4"] = None
        missing.append("op_margin_last4")

    out["pe_ttm"] = _clean_float(_first_present(fin_metrics, "pe_ttm", "pe_ratio"))
    if out["pe_ttm"] is None:
        missing.append("pe_ttm")

    # Supply-side (S): common shares outstanding (a raw count, not a ratio) for the
    # cross-sectional float-size percentile. No magnitude heuristic.
    out["shares_outstanding"] = _clean_float(_first_present(fin_metrics, "shares_outstanding"))
    if out["shares_outstanding"] is None:
        missing.append("shares_outstanding")
    return out


def _institutional_features(detail: dict | None, as_of_date: str, missing: list[str]) -> dict[str, Any]:
    out = {"foreign_net_5": None, "trust_net_5": None, "dealer_net_5": None}
    if detail is None:
        missing.extend(out)
        return out

    for output_key, possible_keys in {
        "foreign_net_5": ("foreign_net_5", "foreign_net_5d", "foreign"),
        "trust_net_5": ("trust_net_5", "investment_trust_net_5", "investment_trust_net_5d", "trust"),
        "dealer_net_5": ("dealer_net_5", "proprietary_net_5", "dealer_net_5d", "dealer"),
    }.items():
        value = _first_present(detail, *possible_keys)
        series = _series_before_or_on_lagged_date(value, as_of_date)
        if series is None:
            missing.append(output_key)
        else:
            out[output_key] = series[-5:]
    return out


def _extract_month_revenue_yoy(detail: dict | None) -> list[float] | None:
    if detail is None:
        return None
    value = _first_present(detail, "month_revenue_yoy", "monthly_revenue_yoy", "revenue_yoy_series")
    if value is None and isinstance(detail.get("revenue_summary"), dict):
        value = _first_present(detail["revenue_summary"], "month_revenue_yoy", "monthly_revenue_yoy", "revenue_yoy_series")
    if value is None:
        rows = _first_present(detail, "monthly_revenue", "revenue_rows")
        if isinstance(rows, list):
            extracted = [
                _clean_float(_first_present(row, "revenue_yoy", "month_revenue_yoy", "YoY", "yoy"))
                for row in rows
                if isinstance(row, dict)
            ]
            value = [item for item in extracted if item is not None]
    if value is None:
        return None
    # month_revenue_yoy is a GROWTH RATE (a strong month can exceed +100% = 1.0).
    # Every setter of this field emits a fraction (assemble_pit_inputs computes it as
    # (cur-prior)/prior), so do NOT magnitude-guess: _normalize_ratio(1.5) would turn
    # +150% revenue into +1.5% and fail a hyper-grower.
    if isinstance(value, (int, float)):
        cleaned_scalar = _clean_float(value)
        return [cleaned_scalar] if cleaned_scalar is not None else None
    series = [_clean_float(item) for item in list(value)]
    cleaned = [item for item in series if item is not None]
    return cleaned if cleaned else None


def _rank_percentile(symbol: str, returns: dict[str, float]) -> float | None:
    if symbol not in returns or not returns:
        return None
    ranked = sorted((str(key), float(value)) for key, value in returns.items())
    symbol_return = float(returns[symbol])
    below_or_equal = sum(1 for _key, value in ranked if value <= symbol_return)
    if len(ranked) == 1:
        return 1.0
    return (below_or_equal - 1) / (len(ranked) - 1)


def _series_before_or_on_lagged_date(value: Any, as_of_date: str) -> list[float] | None:
    if value is None:
        return None
    lagged_date = _parse_date(as_of_date) - timedelta(days=1)
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict) and "series" in value:
        value = value["series"]
    if not isinstance(value, list):
        return None

    rows = []
    plain_values = []
    for item in value:
        if isinstance(item, dict):
            item_date = _first_present(item, "date", "Date")
            item_value = _first_present(item, "value", "net", "net_buy", "buy_sell", "amount")
            if item_date and _parse_date(str(item_date)) <= lagged_date and item_value is not None:
                rows.append((str(item_date), float(item_value)))
        elif item is not None:
            plain_values.append(float(item))
    if rows:
        return [value for _date, value in sorted(rows, key=lambda row: row[0])[-5:]]
    return plain_values[-5:] if plain_values else None


def _ma(out: dict[str, Any], missing: list[str], key: str, close: pd.Series, bars: int) -> None:
    if len(close.dropna()) >= bars:
        out[key] = _clean_float(close.tail(bars).mean())
    else:
        missing.append(key)


def _eps_cagr_3y(values: Any) -> float | None:
    if values is None:
        return None
    series = [float(value) for value in list(values)[-3:] if value is not None]
    if len(series) < 3 or series[0] <= 0 or series[-1] <= 0:
        return None
    return (series[-1] / series[0]) ** (1 / 2) - 1


def _normalize_ratio(value: Any) -> float | None:
    cleaned = _clean_float(value)
    if cleaned is None:
        return None
    if abs(cleaned) > 1:
        return cleaned / 100.0
    return cleaned


def _first_present(mapping: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _clean_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
