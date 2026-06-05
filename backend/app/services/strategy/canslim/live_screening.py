"""Live single-symbol CAN SLIM screening adapter.

This module wires local PIT stores and live source fallbacks into the existing
screening layer. It intentionally does not change CAN SLIM signal, score, rule,
grade, threshold, or gate logic.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
import os
import sqlite3

import pandas as pd

from backend.app.models.screener_schemas import CanslimFullResult, ScreeningResult
from backend.app.services.strategy.canslim.canslim_output import build_full_result
from backend.app.services.strategy.canslim.reviewer import review as review_canslim
from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore
from backend.app.services.finmind_detail import get_tw_detail
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pit_inputs import build_pit_inputs, universe_shares_as_of
from backend.app.services.strategy.canslim.durability import compute_durability
from backend.app.services.strategy.canslim.live_finmind_inputs import build_live_inputs
from backend.app.services.strategy.canslim.regime import build_market_features
from backend.app.services.strategy.canslim.screening import build_screening_result
from backend.app.services.strategy.canslim.types import MarketFeatures
from backend.app.services.tw_financial_metrics import fetch_real_metrics
from backend.app.services.strategy.canslim.news_pillar import NPillarAnalysis, analyze_n_pillar_sources_with_ai
from backend.app.services.yahoo_news import get_tw_stock_news_yahoo
from backend.app.services import file_cache


PILLARS = ("C", "A", "N", "S", "L", "I", "M")
PIT_TABLES = ("month_revenue", "institutional", "margin", "per", "financials")
_UNIVERSE_RETURNS_CACHE: dict[tuple[str, tuple[str, ...], str], tuple[dict[str, float], dict[str, float]]] = {}
_PIT_SYMBOLS_CACHE: dict[str, set[str]] = {}
_SCREENABLE_UNIVERSE_CACHE: dict[tuple[str, str], list[str]] = {}


async def screen_symbol(
    symbol: str,
    as_of_date: str | None = None,
    *,
    ohlcv_store: HistoricalDataStore | None = None,
    pit_store: PitFundamentalsStore | None = None,
) -> ScreeningResult:
    """Return a live/store-backed CAN SLIM ScreeningResult for one TW symbol.

    Missing stores, API keys, or source failures are reported through
    `is_mock`/`data_warnings`; the endpoint path should not crash because a live
    source is unavailable.
    """
    stock_id = str(symbol).strip()
    warnings: list[str] = []
    is_mock = False

    store = ohlcv_store or HistoricalDataStore()
    pit = pit_store or PitFundamentalsStore()
    resolved_date = str(as_of_date or _latest_as_of_date(store, stock_id, warnings))
    stale = _append_staleness_warning(resolved_date, warnings)
    universe = screenable_universe(pit, store)
    universe = _cap_live_universe(universe, include_symbol=stock_id, warnings=warnings)
    has_pit_coverage = _has_pit_coverage(pit, stock_id)
    if not has_pit_coverage:
        warnings.append(f"{stock_id} has no PIT fundamentals coverage; C/A/I pillars cannot be evaluated")

    detail, fin_metrics, eps_filing_date = _pit_inputs(stock_id, resolved_date, pit, warnings)
    live_fallback_used = False
    if _pit_inputs_are_sparse(detail, fin_metrics):
        # Try live FinMind (call + decode) before giving up — fills stocks not in the
        # PIT store (financials/traditional/shipping) without a backfill.
        live_detail, live_metrics, live_filing, live_warnings, live_is_mock = await _live_fundamental_fallback(stock_id, resolved_date)
        if (live_detail or live_metrics) and not live_is_mock:
            # Real live data → use it.
            detail = _merge_missing(detail, live_detail)
            fin_metrics = _merge_missing(fin_metrics, live_metrics)
            if not eps_filing_date:
                eps_filing_date = live_filing
            live_fallback_used = True
            warnings.extend(live_warnings)
        elif not has_pit_coverage:
            # No real fundamentals anywhere → genuinely Insufficient (not mock).
            detail = {}
            fin_metrics = {}
            eps_filing_date = None
            warnings.extend(live_warnings)
        else:
            # Covered but sparse and live gave only mock/nothing → keep partial, flag mock.
            warnings.extend(live_warnings)
            is_mock = is_mock or live_is_mock
    if live_fallback_used and stale:
        warnings.append("as-of mismatch: live fundamentals fallback blended with stale OHLCV/regime store data")

    universe_returns_60d, universe_returns_252d = universe_returns_for_as_of(
        resolved_date,
        store=store,
        universe=universe,
        include_symbol=stock_id,
    )
    if stock_id not in universe_returns_60d:
        warnings.append(f"{stock_id} lacks enough OHLCV history for 60-day relative strength")
    if stock_id not in universe_returns_252d:
        warnings.append(f"{stock_id} lacks enough OHLCV history for 252-day relative strength")

    market = _market_features(resolved_date, store, warnings, universe=universe)
    yahoo_news, tw_news, news_warnings, news_is_mock = await _news_inputs(stock_id, resolved_date)
    warnings.extend(news_warnings)
    is_mock = is_mock or news_is_mock
    n_analysis = await _n_pillar_for(stock_id, resolved_date, yahoo_news, tw_news)
    universe_shares = universe_shares_for_as_of(resolved_date, pit_store=pit, universe=universe, include_symbol=stock_id)

    try:
        result = build_screening_result(
            stock_id,
            resolved_date,
            store=store,
            market=market,
            fin_metrics=fin_metrics,
            detail=detail,
            universe_returns_60d=universe_returns_60d,
            universe_returns_252d=universe_returns_252d,
            event_window_active=False,
            eps_filing_date=eps_filing_date,
            yahoo_news=yahoo_news,
            tw_news_sentiment=tw_news,
            n_pillar_analysis=n_analysis,
            universe_shares=universe_shares,
        )
    except Exception as exc:
        warnings.append(f"CANSLIM screening fallback mock: {exc}")
        return _fallback_result(stock_id, resolved_date, warnings)

    durability = durability_metrics_for_symbol(stock_id, resolved_date, pit_store=pit)
    all_warnings = _dedupe([*warnings, *result.data_warnings])
    if durability.get("missing"):
        all_warnings = _dedupe([*all_warnings, f"durability missing: {', '.join(durability['missing'])}"])
    return result.model_copy(update={
        "is_mock": bool(is_mock),
        "data_warnings": all_warnings,
        "durability_score": durability.get("score"),
        "durability_components": durability.get("components") or {},
        "durability_metrics": durability if durability.get("score") is not None else None,
    })


async def screen_symbol_full(
    symbol: str,
    as_of_date: str | None = None,
    *,
    ohlcv_store: HistoricalDataStore | None = None,
    pit_store: PitFundamentalsStore | None = None,
) -> CanslimFullResult:
    """Consolidated CANSLIM output + deterministic reviewer for one TW symbol.

    Thin composition over the validated `screen_symbol`: it adds the presentation
    layer (`build_full_result`) and the quality reviewer. No signal/score/grade
    math changes.
    """
    result = await screen_symbol(symbol, as_of_date, ohlcv_store=ohlcv_store, pit_store=pit_store)
    full = build_full_result(result)
    return full.model_copy(update={"reviewer_result": review_canslim(full)})


def screenable_universe(pit_store: PitFundamentalsStore, ohlcv_store: HistoricalDataStore) -> list[str]:
    """RS reference universe: all OHLCV-covered symbols.

    RS percentile (T-1/L pillar) must be ranked against the broadest possible
    peer set. Using only PIT-covered symbols produces a biased, undersized
    universe during incremental fundamentals downloads and permanently excludes
    non-coverage stocks from proper ranking.

    Fundamental rules (C/A/I pillars) do their own PIT-coverage check internally
    via build_pit_inputs → they return None when data is absent, which lowers
    confidence but does NOT affect the RS universe size here.
    """
    cache_key = (_store_cache_key(ohlcv_store), "ohlcv_only")
    cached = _SCREENABLE_UNIVERSE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        ohlcv_symbols = sorted(str(symbol) for symbol in ohlcv_store.list_stocks())
    except Exception:
        ohlcv_symbols = []
    _SCREENABLE_UNIVERSE_CACHE[cache_key] = ohlcv_symbols
    return ohlcv_symbols


def _cap_live_universe(universe: list[str], *, include_symbol: str, warnings: list[str]) -> list[str]:
    """Bound live single-symbol work so the UI stays responsive."""
    try:
        max_symbols = int(os.getenv("AISTOCK_LIVE_SCREEN_UNIVERSE_MAX", "300"))
    except ValueError:
        max_symbols = 300
    symbols = _dedupe([str(include_symbol), *universe])
    if max_symbols <= 0 or len(symbols) <= max_symbols:
        return symbols
    capped = _stratified_symbol_sample(symbols, max_symbols, include_symbol=str(include_symbol))
    warnings.append(f"live screening RS universe sampled at {len(capped)} symbols for UI responsiveness")
    return capped


def _stratified_symbol_sample(symbols: list[str], max_symbols: int, *, include_symbol: str) -> list[str]:
    """Deterministically sample across the sorted universe instead of taking a code prefix."""
    ordered = sorted(_dedupe(symbols))
    if max_symbols <= 0 or len(ordered) <= max_symbols:
        return ordered

    target = max(1, max_symbols - 1)
    if target == 1:
        sampled = [ordered[0]]
    else:
        last = len(ordered) - 1
        sampled = [ordered[round(i * last / (target - 1))] for i in range(target)]
    capped = _dedupe([include_symbol, *sampled])
    if len(capped) > max_symbols:
        capped = capped[:max_symbols]
    return capped


def durability_metrics_for_symbol(
    symbol: str,
    as_of_date: str,
    *,
    pit_store: PitFundamentalsStore | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a frontend-friendly durability payload, or null-score on sparse data."""
    pit = pit_store or PitFundamentalsStore()
    model_params = params or load_params()
    try:
        financials = pit.get_financials_as_of(symbol, as_of_date, limit=20)
        balance_sheet = pit.get_balance_sheet_as_of(symbol, as_of_date, limit=8)
        cash_flow = pit.get_cash_flow_as_of(symbol, as_of_date, limit=12) if hasattr(pit, "get_cash_flow_as_of") else None
        detail, fin_metrics, _ = build_pit_inputs(symbol, as_of_date, pit)
        result = compute_durability(
            fin_metrics=fin_metrics,
            detail=detail,
            financials=financials,
            balance_sheet=balance_sheet,
            cash_flow=cash_flow,
            params=model_params,
        )
    except Exception:
        return {
            "score": None,
            "components": {},
            "confidence": 0,
            "change_yoy": None,
            "trend": None,
            "missing": ["durability_unavailable"],
        }
    if not result.components:
        return {
            "score": None,
            "components": {},
            "confidence": 0,
            "change_yoy": None,
            "trend": None,
            "missing": result.missing,
        }
    component_count = len(result.components)
    expected_count = component_count + len(result.missing)
    confidence = int(round(100 * component_count / expected_count)) if expected_count else 0
    return {
        "score": float(result.score),
        "components": {key: float(value) for key, value in result.components.items()},
        "confidence": confidence,
        "change_yoy": None,
        "trend": None,
        "missing": list(result.missing),
        "f_score_partial": result.fscore,
    }


def universe_returns_for_as_of(
    as_of_date: str,
    *,
    store: HistoricalDataStore,
    universe: list[str],
    include_symbol: str,
) -> tuple[dict[str, float], dict[str, float]]:
    symbols = _dedupe([*universe, str(include_symbol)])
    cache_key = (str(as_of_date), tuple(symbols), _store_cache_key(store))
    if cache_key not in _UNIVERSE_RETURNS_CACHE:
        _UNIVERSE_RETURNS_CACHE[cache_key] = (
            _compute_universe_returns(store, symbols, as_of_date, 60),
            _compute_universe_returns(store, symbols, as_of_date, 252),
        )
    return _UNIVERSE_RETURNS_CACHE[cache_key]


_UNIVERSE_SHARES_CACHE: dict[tuple[str, tuple[str, ...]], dict[str, float]] = {}


def universe_shares_for_as_of(
    as_of_date: str,
    *,
    pit_store: PitFundamentalsStore,
    universe: list[str],
    include_symbol: str,
) -> dict[str, float]:
    """Cached cross-sectional shares-outstanding map for the S float percentile."""
    symbols = _dedupe([*universe, str(include_symbol)])
    cache_key = (str(as_of_date), tuple(symbols))
    if cache_key not in _UNIVERSE_SHARES_CACHE:
        _UNIVERSE_SHARES_CACHE[cache_key] = universe_shares_as_of(pit_store, symbols, as_of_date)
    return _UNIVERSE_SHARES_CACHE[cache_key]


def clear_universe_returns_cache() -> None:
    _UNIVERSE_RETURNS_CACHE.clear()
    _UNIVERSE_SHARES_CACHE.clear()
    _PIT_SYMBOLS_CACHE.clear()
    _SCREENABLE_UNIVERSE_CACHE.clear()


def _adjusted_rs_enabled() -> bool:
    """Dividend-adjusted relative strength. OFF by default so validated CANSLIM
    grades are unchanged until the dividend cache is backfilled and the result is
    re-validated against the backtest. Enable with AISTOCK_ADJUSTED_RS=1."""
    return os.getenv("AISTOCK_ADJUSTED_RS", "").strip().lower() in {"1", "true", "yes", "on"}


def _compute_universe_returns(
    store: HistoricalDataStore,
    symbols: list[str],
    as_of_date: str,
    lookback_bars: int,
) -> dict[str, float]:
    adjusted = _adjusted_rs_enabled()
    out: dict[str, float] = {}
    for symbol in symbols:
        try:
            bars = store.get_ohlcv_as_of(symbol, as_of_date, lookback_bars)
        except Exception:
            continue
        value = _return_from_bars(bars, lookback_bars)
        if value is None:
            continue
        if adjusted:
            value = _dividend_adjusted_return(str(symbol), bars, value)
        out[str(symbol)] = value
    return out


def _dividend_adjusted_return(symbol: str, bars: Any, raw_return: float) -> float:
    """Back-adjust a raw window return by the dividend ratios that fell inside it
    (cache-only; no-op when the symbol's dividends are not backfilled)."""
    try:
        from backend.app.services.tw_adjusted_prices import dividend_window_factor
        dates = bars["date"].tolist()
        if not dates:
            return raw_return
        factor = dividend_window_factor(symbol, str(dates[0]), str(dates[-1]))
        if factor and factor != 1.0:
            return (1.0 + raw_return) / factor - 1.0
    except Exception:
        pass
    return raw_return


def _return_from_bars(bars: Any, lookback_bars: int) -> float | None:
    if bars is None or "close" not in bars or len(bars) < lookback_bars:
        return None
    close = pd.to_numeric(bars["close"], errors="coerce").dropna()
    # Tolerate a few missing/NaN bars inside the window — a single bad bar must NOT
    # void the whole relative-strength computation (this previously excluded ~44%
    # of the universe). Require enough valid points to still span the lookback.
    if len(close) < max(2, int(lookback_bars * 0.7)):
        return None
    start = float(close.iloc[0])
    end = float(close.iloc[-1])
    if start <= 0:
        return None
    return end / start - 1.0


def _pit_symbols(pit_store: PitFundamentalsStore) -> set[str]:
    cache_key = str(getattr(pit_store, "db_path", id(pit_store)))
    cached = _PIT_SYMBOLS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    symbols: set[str] = set()
    for table in PIT_TABLES:
        try:
            with pit_store._connect() as conn:
                rows = conn.execute(f"SELECT DISTINCT stock_id FROM {table}").fetchall()
        except (sqlite3.Error, AttributeError):
            continue
        symbols.update(str(row[0]) for row in rows if row[0])
    _PIT_SYMBOLS_CACHE[cache_key] = symbols
    return symbols


def _has_pit_coverage(pit_store: PitFundamentalsStore, stock_id: str) -> bool:
    for table in PIT_TABLES:
        try:
            with pit_store._connect() as conn:
                row = conn.execute(f"SELECT 1 FROM {table} WHERE stock_id = ? LIMIT 1", (str(stock_id),)).fetchone()
        except (sqlite3.Error, AttributeError):
            continue
        if row is not None:
            return True
    return False


def _store_cache_key(store: HistoricalDataStore) -> str:
    db_path = getattr(store, "db_path", None)
    if db_path is not None:
        return str(db_path)
    return str(id(store))


def _latest_as_of_date(store: HistoricalDataStore, symbol: str, warnings: list[str]) -> str:
    try:
        latest = store.get_latest_date(symbol)
    except Exception as exc:
        warnings.append(f"OHLCV latest-date lookup failed: {exc}")
        latest = None
    if latest:
        return str(latest)
    warnings.append("OHLCV store has no latest trading date for symbol; using today's date")
    return date.today().isoformat()


def _append_staleness_warning(as_of_date: str, warnings: list[str]) -> bool:
    try:
        parsed = datetime.strptime(str(as_of_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        warnings.append(f"data stale check unavailable: invalid as_of_date {as_of_date}")
        return False
    today = date.today()
    gap = max(0, (today - parsed).days)
    cfg = load_params().get("screening", {}).get("staleness", {})
    max_calendar_days = int(cfg.get("max_calendar_days", 10))
    if gap > max_calendar_days:
        warnings.append(
            f"DATA STALE: latest as_of {parsed.isoformat()} is {gap} calendar days behind today; "
            "screening reflects stale market state"
        )
        return True
    return False


def _pit_inputs(
    symbol: str,
    as_of_date: str,
    pit_store: PitFundamentalsStore,
    warnings: list[str],
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    try:
        return build_pit_inputs(symbol, as_of_date, pit_store)
    except Exception as exc:
        warnings.append(f"PIT fundamentals unavailable: {exc}")
        return {}, {}, None


def _pit_inputs_are_sparse(detail: dict[str, Any], fin_metrics: dict[str, Any]) -> bool:
    return not detail or not fin_metrics


async def _live_fundamental_fallback(symbol: str, as_of_date: str) -> tuple[dict[str, Any], dict[str, Any], str | None, list[str], bool]:
    """Live, on-demand fundamentals for stocks not in the PIT store.

    Primary path: real FinMind datasets decoded into the full observe shape via
    `build_live_inputs` (rich: revenue/EPS/CAGR/ROE/margins/institutional series).
    Falls back to the older summary-based path only if the live FinMind call
    yields nothing. Returns (detail, fin_metrics, eps_filing_date, warnings, is_mock).
    """
    warnings: list[str] = []

    try:
        ld, lm, lf = await build_live_inputs(symbol, as_of_date)
        if ld or lm:
            warnings.append("live FinMind fundamentals (on-demand call+decode, cached daily)")
            return ld, lm, lf, warnings, False
    except Exception as exc:
        warnings.append(f"live FinMind fundamentals unavailable: {exc}")

    # Legacy summary fallback (sparse) when the rich FinMind path returned nothing.
    is_mock = False
    detail: dict[str, Any] = {}
    fin_metrics: dict[str, Any] = {}
    try:
        live_detail = await get_tw_detail(symbol)
        if live_detail:
            detail, detail_warnings = _detail_to_canslim_detail(live_detail)
            warnings.extend(detail_warnings)
            fin_metrics.update(_detail_to_canslim_metrics(live_detail))
    except Exception as exc:
        warnings.append(f"live detail fallback unavailable: {exc}")
        is_mock = True

    try:
        metrics = await fetch_real_metrics(symbol)
        if metrics:
            metric_inputs, metric_warnings = _metrics_to_canslim(metrics)
            fin_metrics = _merge_missing(fin_metrics, metric_inputs)
            warnings.extend(metric_warnings)
            if metrics.get("is_mock") or metrics.get("data_source") == "mock":
                is_mock = True
                warnings.append("live financial metrics used mock fallback")
    except Exception as exc:
        warnings.append(f"live financial metrics fallback unavailable: {exc}")
        is_mock = True

    if not detail and not fin_metrics:
        warnings.append("fundamental live fallback returned no CANSLIM-compatible fields")
        is_mock = True
    return detail, fin_metrics, None, warnings, is_mock


def _market_features(
    as_of_date: str,
    store: HistoricalDataStore,
    warnings: list[str],
    *,
    universe: list[str],
) -> MarketFeatures:
    try:
        return build_market_features(as_of_date, store=store, universe=universe)
    except Exception as exc:
        warnings.append(f"market regime unavailable: {exc}")
        return MarketFeatures(data_warnings=[f"market regime unavailable: {exc}"])


_N_CACHE_NAMESPACE = "n_pillar"


def _n_cache_key(symbol: str, as_of_date: str) -> str:
    return f"{symbol}_{as_of_date}"


async def _news_inputs(symbol: str, as_of_date: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], bool]:
    """Free per-stock news for the N pillar (Google News RSS, no key).

    Reads the on-disk cache for (symbol, as_of_date) first so the same stock on the
    same day does not re-hit the network. An empty result is never cached, so a
    stock with no news yet keeps re-checking. is_mock stays False (the source is
    real/free); an empty result just leaves N as AI_Review_Required.
    """
    cached = file_cache.load(_N_CACHE_NAMESPACE, _n_cache_key(symbol, as_of_date))
    if isinstance(cached, dict) and cached.get("raw_news"):
        return list(cached["raw_news"]), [], [], False

    warnings: list[str] = []
    yahoo_news: list[dict[str, Any]] = []
    try:
        yahoo_news = list(await get_tw_stock_news_yahoo(symbol))
    except Exception as exc:
        warnings.append(f"per-stock news unavailable: {exc}")
    if not yahoo_news:
        warnings.append("no per-stock news found; N pillar requires manual review")
    return yahoo_news, [], warnings, False


_N_ANALYSIS_CACHE: dict[tuple[str, str], NPillarAnalysis] = {}


async def _n_pillar_for(
    symbol: str, as_of_date: str, yahoo_news: list[dict[str, Any]], tw_news: list[dict[str, Any]]
) -> NPillarAnalysis:
    """Hybrid N analysis (Gemini summary + Claude classify, else deterministic).

    Cached in-process and on disk per (symbol, as_of_date), so repeated screens of
    the same stock on the same day re-use the recorded news titles/summaries instead
    of re-fetching news or re-calling the models. Only non-empty results are
    persisted to disk (an empty/not_found result stays cheap and keeps re-checking).
    """
    key = (str(symbol), str(as_of_date))
    cached = _N_ANALYSIS_CACHE.get(key)
    if cached is not None:
        return cached

    disk = file_cache.load(_N_CACHE_NAMESPACE, _n_cache_key(symbol, as_of_date))
    if isinstance(disk, dict) and disk.get("analysis"):
        try:
            result = NPillarAnalysis(**disk["analysis"])
            _N_ANALYSIS_CACHE[key] = result
            return result
        except Exception:
            pass  # corrupt/old shape -> recompute

    result = await analyze_n_pillar_sources_with_ai(yahoo_news=yahoo_news, tw_news_sentiment=tw_news)
    _N_ANALYSIS_CACHE[key] = result
    if yahoo_news:
        file_cache.save(
            _N_CACHE_NAMESPACE,
            _n_cache_key(symbol, as_of_date),
            {"raw_news": list(yahoo_news), "analysis": result.model_dump()},
        )
    return result


def clear_n_analysis_cache() -> None:
    _N_ANALYSIS_CACHE.clear()
    file_cache.clear(_N_CACHE_NAMESPACE)


def _fallback_result(symbol: str, as_of_date: str, warnings: list[str]) -> ScreeningResult:
    clean_warnings = _dedupe(warnings)
    return ScreeningResult(
        stock_id=str(symbol),
        as_of_date=str(as_of_date),
        is_mock=True,
        candidate_grade="D",
        canslim_match="0/7",
        pillars={pillar: "Insufficient_Data" for pillar in PILLARS},
        market_regime="unknown",
        interpretation="CANSLIM screening data is incomplete; condition status requires manual review.",
        evidence=[],
        data_warnings=clean_warnings,
        needs_manual_review=list(PILLARS),
        action_type="Manual Review Required",
    )


def _detail_to_canslim_detail(detail: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    rev = detail.get("revenue_summary") or {}
    inst = detail.get("institutional_summary") or {}
    out: dict[str, Any] = {}
    warnings: list[str] = []
    revenue_series = _series_or_none(rev.get("month_revenue_yoy") or rev.get("revenue_yoy_series"), min_len=3)
    if revenue_series:
        out["month_revenue_yoy"] = revenue_series
    elif rev.get("yoy_pct") is not None:
        warnings.append("monthly revenue multi-period series unavailable from live fallback; C revenue acceleration partial")
    for source_key, out_key in [
        ("foreign_net_5d", "foreign_net_5"),
        ("trust_net_5d", "trust_net_5"),
        ("dealer_net_5d", "dealer_net_5"),
    ]:
        series = _series_or_none(inst.get(out_key) or inst.get(source_key), min_len=3)
        if series:
            out[out_key] = series
        elif inst.get(source_key) is not None:
            warnings.append(f"{out_key} 5-day series unavailable from live fallback; I pillar partial")
    return out, warnings


def _detail_to_canslim_metrics(detail: dict[str, Any]) -> dict[str, Any]:
    val = detail.get("valuation_summary") or {}
    out = {
        "quarterly_eps_yoy": detail.get("eps_yoy"),
        "annual_eps": detail.get("annual_eps"),
        "roe": detail.get("roe"),
        "op_margin_last4": detail.get("op_margin_last4"),
        "pe_ttm": val.get("per"),
    }
    return {key: value for key, value in out.items() if value is not None}


def _metrics_to_canslim(metrics: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    # fetch_real_metrics emits growth as PERCENT (e.g. eps_yoy=25.0 means 25%). The
    # CANSLIM contract is that quarterly_eps_yoy is a FRACTION (features no longer
    # magnitude-normalizes it), so convert here at the source. roe stays percent —
    # features._normalize_ratio safely handles it (bounded <=1 as a fraction).
    raw_eps_yoy = metrics.get("eps_yoy") or metrics.get("eps_growth")
    out = {
        "quarterly_eps_yoy": (float(raw_eps_yoy) / 100.0) if raw_eps_yoy is not None else None,
        "roe": metrics.get("roe"),
        "pe_ttm": metrics.get("pe_ratio") or metrics.get("pe_ttm"),
    }
    warnings: list[str] = []
    margin_series = _series_or_none(metrics.get("op_margin_last4") or metrics.get("operating_margin_series"), min_len=4)
    if margin_series:
        out["op_margin_last4"] = margin_series
    elif metrics.get("operating_margin") is not None:
        warnings.append("operating margin multi-period series unavailable from live fallback; A margin trend partial")
    return {key: value for key, value in out.items() if value is not None}, warnings


def _series_or_none(value: Any, *, min_len: int) -> list[Any] | None:
    if not isinstance(value, list):
        return None
    cleaned = [item for item in value if item is not None]
    return cleaned if len(cleaned) >= min_len else None


def _merge_missing(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary or {})
    for key, value in (fallback or {}).items():
        if merged.get(key) in (None, [], {}):
            merged[key] = value
    return merged


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if item))
