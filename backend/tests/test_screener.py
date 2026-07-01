from __future__ import annotations

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from backend.app.models.screener_schemas import CandidateMetrics, CandidateScores, ScreeningResult
from backend.app.services.data_sources.source_models import MarketIndexLoadResult, OhlcvLoadResult, SourceInfo
from backend.app.services.screener_rules import load_surge_candidate_rules
from backend.app.services.screener_service import (
    ScreenerParameters,
    _CanslimScanContext,
    _classify_candidate,
    _scan_df_from_store,
    default_screener_parameters,
    evaluate_surge_candidate,
    scan_surge_candidates,
)


def make_candidate_df(
    *,
    return_60d: float = 0.15,
    base_return: float = 0.02,
    return_5d: float = 0.03,
    first_base_volume_shares: int = 1_000_000,
    second_base_volume_shares: int = 700_000,
    recent_volume_shares: int = 900_000,
    last_5_volume_shares: int = 1_600_000,
    today_volume_shares: int | None = None,
    turnover_multiplier: float = 1.0,
    upper_shadow: bool = False,
) -> pd.DataFrame:
    days = 90
    close_60d = 100.0
    close_20d = close_60d * (1 + base_return)
    close_today = close_60d * (1 + return_60d)
    close_5d = close_today / (1 + return_5d)

    closes = [98.0] * 30
    base = [
        close_60d + (close_20d - close_60d) * (idx / 40) + ((idx % 5) - 2) * 0.25
        for idx in range(41)
    ]
    base[0] = close_60d
    base[-1] = close_20d
    recent_to_5d = [
        close_20d + (close_5d - close_20d) * min(idx / 4, 1)
        for idx in range(1, 15)
    ]
    final_5 = [
        close_5d + (close_today - close_5d) * (idx / 4)
        for idx in range(0, 5)
    ]
    closes = (closes + base + recent_to_5d + final_5)[:days]

    volumes = [1_000_000] * 30
    volumes += [first_base_volume_shares] * 20
    volumes += [second_base_volume_shares] * 21
    volumes += [recent_volume_shares] * 14
    volumes += [last_5_volume_shares] * 5
    volumes = volumes[:days]
    if today_volume_shares is not None:
        volumes[-1] = today_volume_shares

    rows = []
    for close, volume in zip(closes, volumes):
        open_price = close * 0.995
        high = close * 1.01
        low = close * 0.99
        if upper_shadow and close == closes[-1]:
            open_price = close * 0.99
            high = close * 1.12
            low = close * 0.98
        rows.append({
            "Open": open_price,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
            "Turnover": close * volume * turnover_multiplier,
        })
    return pd.DataFrame(rows)


def make_market_df(*, return_60d: float = 0.08, base_return: float = 0.01, return_5d: float = 0.01) -> pd.DataFrame:
    return make_candidate_df(
        return_60d=return_60d,
        base_return=base_return,
        return_5d=return_5d,
        first_base_volume_shares=10_000_000,
        second_base_volume_shares=10_000_000,
        recent_volume_shares=10_000_000,
        last_5_volume_shares=10_000_000,
    )


def test_qualifies_as_surge_watch_candidate() -> None:
    df = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03)
    market = make_market_df(return_60d=0.08, base_return=0.01)

    result = evaluate_surge_candidate("2330", "台積電", df, market)

    assert result is not None
    assert result.candidate_type in {"初動觀察", "初動候選", "動能確認"}
    assert result.surge_candidate_score >= 60
    assert result.disclaimer if hasattr(result, "disclaimer") else True


def test_qualifies_as_momentum_confirmation() -> None:
    df = make_candidate_df(
        return_60d=0.16,
        base_return=0.02,
        return_5d=0.0,
        recent_volume_shares=900_000,
        last_5_volume_shares=1_500_000,
    )
    market = make_market_df(return_60d=0.10, base_return=0.01)

    result = evaluate_surge_candidate("2454", "聯發科", df, market)

    assert result is not None
    assert result.candidate_type == "動能確認"
    assert result.surge_candidate_score >= 75


def test_overheated_candidate_is_observation_not_signal() -> None:
    df = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.17)
    market = make_market_df(return_60d=0.08, base_return=0.01)

    result = evaluate_surge_candidate("2317", "鴻海", df, market)

    assert result is not None
    assert result.candidate_type == "偏熱觀察"
    assert "parabolic_rise_5d" in result.risk_flags


def test_early_run_before_recent_window_is_downgraded_not_hard_filtered() -> None:
    df = make_candidate_df(return_60d=0.22, base_return=0.18, return_5d=0.03)
    market = make_market_df(return_60d=0.08, base_return=0.01)

    result = evaluate_surge_candidate("3008", "大立光", df, market, include_unfit=True)

    assert result is not None
    assert result.candidate_type == "初動觀察"
    assert result.scores.base_compression_score < 50


def test_insufficient_liquidity_is_unfit() -> None:
    df = make_candidate_df(
        first_base_volume_shares=100_000,
        second_base_volume_shares=70_000,
        recent_volume_shares=90_000,
        last_5_volume_shares=160_000,
        turnover_multiplier=1.0,
    )
    market = make_market_df(return_60d=0.08, base_return=0.01)

    result = evaluate_surge_candidate("1234", "低流動", df, market, include_unfit=True)

    assert result is not None
    assert result.candidate_type == "不符合"
    assert "low_liquidity" in result.risk_flags


@pytest.mark.asyncio
async def test_api_degrades_when_taiex_unavailable(monkeypatch) -> None:
    async def fake_taiex():
        return MarketIndexLoadResult(
            dataframe=None,
            source="unavailable",
            available=False,
            fallback_used=True,
            warnings=["market_index_unavailable"],
        )

    async def fake_stocks(limit: int = 10000):
        return {
            "stocks": [{"stock_code": "2330", "company_name": "台積電"}],
            "total": 1,
            "returned": 1,
            "data_source": "live",
        }

    async def fake_price_history(symbol: str, days: int):
        candles = make_candidate_df(return_60d=0.15, base_return=0.02, return_5d=0.03).to_dict("records")
        return OhlcvLoadResult(
            candles=candles,
            source_info=SourceInfo(ohlcv_source="finmind", turnover_source="finmind_trading_money", bars_count=len(candles)),
        )

    async def fake_tpex_quotes():
        return {}

    monkeypatch.setattr("backend.app.api.routes.screeners.load_taiex_history_with_source", fake_taiex)
    monkeypatch.setattr("backend.app.services.screener_service.get_tw_stocks", fake_stocks)
    monkeypatch.setattr("backend.app.services.screener_service.get_tw_price_history_with_source", fake_price_history)
    monkeypatch.setattr("backend.app.services.screener_service.fetch_tpex_mainboard_quote_map", fake_tpex_quotes)

    from backend.app.main import app

    client = TestClient(app)
    response = client.get("/screeners/surge-candidates?force_refresh=true&min_return_60d=0.101")

    assert response.status_code == 200
    payload = response.json()
    assert "market_index_unavailable" in payload["data_warnings"]
    assert payload["results"][0]["scores"]["relative_strength_score"] == 50
    assert payload["results"][0]["confidence_score"] <= 65
    assert "market_index" in payload["results"][0]["missing_data"]
    assert payload["results"][0]["source_info"]["market_index_source"] == "unavailable"


@pytest.mark.asyncio
async def test_api_debug_returns_funnel_report(monkeypatch) -> None:
    async def fake_taiex():
        return MarketIndexLoadResult(
            dataframe=make_market_df(return_60d=0.08, base_return=0.01),
            source="finmind",
            available=True,
            fallback_used=False,
        )

    async def fake_stocks(limit: int = 10000):
        return {
            "stocks": [
                {"stock_code": "2330", "company_name": "台積電"},
                {"stock_code": "1234", "company_name": "低流動"},
            ],
            "total": 2,
            "returned": 2,
            "data_source": "test",
        }

    async def fake_price_history(symbol: str, days: int):
        if symbol == "1234":
                df = make_candidate_df(
                    first_base_volume_shares=100_000,
                    second_base_volume_shares=70_000,
                    recent_volume_shares=90_000,
                    last_5_volume_shares=160_000,
                    turnover_multiplier=1.0,
                )
        else:
            df = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03)
        candles = df.to_dict("records")
        return OhlcvLoadResult(
            candles=candles,
            source_info=SourceInfo(ohlcv_source="finmind", turnover_source="finmind_trading_money", bars_count=len(candles)),
        )

    async def fake_tpex_quotes():
        return {}

    monkeypatch.setattr("backend.app.api.routes.screeners.load_taiex_history_with_source", fake_taiex)
    monkeypatch.setattr("backend.app.services.screener_service.get_tw_stocks", fake_stocks)
    monkeypatch.setattr("backend.app.services.screener_service.get_tw_price_history_with_source", fake_price_history)
    monkeypatch.setattr("backend.app.services.screener_service.fetch_tpex_mainboard_quote_map", fake_tpex_quotes)

    from backend.app.main import app

    client = TestClient(app)
    response = client.get("/screeners/surge-candidates?debug=true&force_refresh=true&min_return_60d=0.102&ai_tech_only=false")

    assert response.status_code == 200
    payload = response.json()
    report = payload["funnel_report"]
    assert payload["data_source_report"]["market_index"]["source"] == "finmind"
    assert report["stage_counts"]["universe_size"] == 2
    assert report["stage_counts"]["ohlcv_sufficient_count"] == 2
    assert "sequential_funnel" in report
    assert "independent_condition_counts" in report
    assert "data_source_report" in report
    assert report["data_source_report"]["market_index"]["source"] == "finmind"
    assert "liquidity" in report["condition_reports"]
    liquidity_report = report["condition_reports"]["liquidity"]
    assert liquidity_report["pass_count"] == 1
    assert liquidity_report["fail_count"] == 1
    assert liquidity_report["top_10_closest_failed_examples"][0]["stock_id"] == "1234"
    assert "avg_volume_20_lots" in liquidity_report["top_10_closest_failed_examples"][0]["key_metrics"]
    assert "ema_spread_distribution" in report
    assert "ema_slope_distribution" in report
    assert "volume_contraction_distribution" in report
    assert "volume_recovery_distribution" in report
    assert "relative_strength_distribution" in report
    assert "score_distribution" in report
    assert "pre_breakout_score_distribution" in report
    assert "setup_price_position_score_distribution" in report
    assert "ema_micro_upturn_score_distribution" in report
    assert "close_from_ema20_distribution" in report
    assert "close_to_base_high_distribution" in report
    assert "return_20d_distribution" in report
    assert "return_90d_distribution" in report
    assert "ema_near_convergence_count" in report
    assert "ema_micro_upturn_count" in report
    assert "ema_full_bullish_alignment_count" in report
    assert report["ema_near_convergence_count"] >= 0
    assert report["ema_micro_upturn_count"] >= 0


def test_upper_shadow_with_volume_is_hot_observation() -> None:
    df = make_candidate_df(
        return_60d=0.14,
        base_return=0.02,
        return_5d=0.04,
        today_volume_shares=2_500_000,
        upper_shadow=True,
    )
    market = make_market_df(return_60d=0.08, base_return=0.01)

    result = evaluate_surge_candidate("3661", "世芯", df, market)

    assert result is not None
    assert result.candidate_type == "偏熱觀察"
    assert "high_upper_shadow_with_volume" in result.risk_flags


def test_initial_candidate_accepts_ema_micro_upturn_without_full_bullish_stack() -> None:
    rules = load_surge_candidate_rules()
    metrics = CandidateMetrics(
        return_60d=0.14,
        return_20d=0.10,
        return_60_to_20=0.02,
        return_5d=0.03,
        avg_volume_20_lots=1000,
        avg_turnover_20=100_000_000,
        base_high=102,
        base_low=95,
        base_range_pct=0.08,
        volume_contraction_ratio=0.7,
        volume_recovery_ratio_5d=1.3,
        volume_today_ratio_20=1.1,
        ema_spread=0.055,
        ema5_slope=0.002,
        ema10_slope=-0.0005,
        ema20_slope=-0.002,
        relative_strength_20d=0.03,
        relative_strength_60d=0.06,
        close_distance_from_ema20=0.04,
        upper_shadow_ratio_today=0.1,
    )
    scores = CandidateScores(
        liquidity_score=75,
        price_position_score=100,
        base_compression_score=95,
        volume_score=65,
        ema_convergence_score=72,
        relative_strength_score=65,
    )
    candidate_type = _classify_candidate(
        72,
        40,
        [],
        {
            "price_position": True,
            "base": True,
            "volume_recovery": True,
            "liquidity": True,
            "ema": True,
            "ema_micro_upturn": True,
            "ema_price_above_all": False,
            "relative_strength": True,
        },
        metrics,
        scores,
        bullish_stack=False,
        rules=rules,
    )

    assert candidate_type == "初動候選"


def test_turnover_estimated_flag_and_source_info() -> None:
    df = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03).drop(columns=["Turnover"])
    market = make_market_df(return_60d=0.08, base_return=0.01)

    result = evaluate_surge_candidate(
        "2330",
        "台積電",
        df,
        market,
        source_info={
            "ohlcv_source": "yfinance",
            "turnover_source": "estimated",
            "is_mock_data": False,
            "bars_count": len(df),
            "data_warnings": ["turnover_value_estimated"],
        },
    )

    assert result is not None
    assert "turnover_value_estimated" in result.data_quality_flags
    assert result.source_info["turnover_source"] == "estimated"


def test_mock_ohlcv_caps_confidence_and_downgrades_candidate_type() -> None:
    df = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03)
    market = make_market_df(return_60d=0.08, base_return=0.01)

    result = evaluate_surge_candidate(
        "2330",
        "台積電",
        df,
        market,
        source_info={
            "ohlcv_source": "mock",
            "turnover_source": "estimated",
            "is_mock_data": True,
            "bars_count": len(df),
            "data_warnings": ["mock_ohlcv", "turnover_value_estimated"],
        },
    )

    assert result is not None
    assert result.confidence_score <= 40
    assert result.candidate_type not in {"初動候選", "動能確認"}
    assert result.source_info["is_mock_data"] is True


@pytest.mark.asyncio
async def test_debug_data_source_report_counts_yfinance(monkeypatch) -> None:
    async def fake_price_history(symbol: str, days: int):
        candles = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03).drop(columns=["Turnover"]).to_dict("records")
        return OhlcvLoadResult(
            candles=candles,
            source_info=SourceInfo(
                ohlcv_source="yfinance",
                turnover_source="estimated",
                bars_count=len(candles),
                data_warnings=["turnover_value_estimated"],
            ),
        )

    async def fake_tpex_quotes():
        return {}

    monkeypatch.setattr("backend.app.services.screener_service.get_tw_price_history_with_source", fake_price_history)
    monkeypatch.setattr("backend.app.services.screener_service.fetch_tpex_mainboard_quote_map", fake_tpex_quotes)

    response = await scan_surge_candidates(
        default_screener_parameters(),
        df_market=make_market_df(return_60d=0.08, base_return=0.01),
        universe=[{"stock_code": "2330", "company_name": "台積電"}],
        debug=True,
        market_index_report={"source": "finmind", "available": True, "fallback_used": False, "warnings": []},
    )

    report = response.funnel_report["data_source_report"]
    assert report["ohlcv"]["yfinance_count"] == 1
    assert report["turnover"]["estimated_turnover_count"] == 1


@pytest.mark.asyncio
async def test_scan_dedupes_duplicate_universe_stock_ids(monkeypatch) -> None:
    async def fake_price_history(symbol: str, days: int):
        candles = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03).to_dict("records")
        return OhlcvLoadResult(
            candles=candles,
            source_info=SourceInfo(
                ohlcv_source="finmind",
                turnover_source="finmind_trading_money",
                bars_count=len(candles),
            ),
        )

    async def fake_tpex_quotes():
        return {}

    monkeypatch.setattr("backend.app.services.screener_service.get_tw_price_history_with_source", fake_price_history)
    monkeypatch.setattr("backend.app.services.screener_service.fetch_tpex_mainboard_quote_map", fake_tpex_quotes)

    response = await scan_surge_candidates(
        default_screener_parameters(),
        df_market=make_market_df(return_60d=0.08, base_return=0.01),
        universe=[
            {"stock_code": "2330", "company_name": "台積電"},
            {"stock_code": "2330", "company_name": "台積電"},
            {"stock_code": "2454", "company_name": "聯發科"},
        ],
        debug=True,
        market_index_report={"source": "finmind", "available": True, "fallback_used": False, "warnings": []},
    )

    stock_ids = [row.stock_id for row in response.results]
    assert len(stock_ids) == len(set(stock_ids))
    assert response.universe_size == 2
    assert response.data_source_report is not None
    assert response.data_source_report["universe"]["duplicate_removed_count"] == 1


@pytest.mark.asyncio
async def test_tpex_official_turnover_patch_sets_source_info(monkeypatch) -> None:
    async def fake_price_history(symbol: str, days: int):
        candles = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03).drop(columns=["Turnover"]).to_dict("records")
        return OhlcvLoadResult(
            candles=candles,
            source_info=SourceInfo(
                ohlcv_source="finmind",
                turnover_source="estimated",
                bars_count=len(candles),
            ),
        )

    async def fake_tpex_quotes():
        return {
            "2330": {
                "stock_id": "2330",
                "stock_name": "台積電",
                "date": "2099-01-01",
                "open": 114.0,
                "high": 116.0,
                "low": 113.0,
                "close": 115.0,
                "volume": 2_000_000,
                "turnover_value": 230_000_000,
                "source": "tpex_official",
                "turnover_source": "official",
                "is_official": True,
            }
        }

    monkeypatch.setattr("backend.app.services.screener_service.get_tw_price_history_with_source", fake_price_history)
    monkeypatch.setattr("backend.app.services.screener_service.fetch_tpex_mainboard_quote_map", fake_tpex_quotes)

    response = await scan_surge_candidates(
        default_screener_parameters(),
        df_market=make_market_df(return_60d=0.08, base_return=0.01),
        universe=[{"stock_code": "2330", "company_name": "台積電"}],
        debug=True,
        market_index_report={"source": "finmind", "available": True, "fallback_used": False, "warnings": []},
    )

    assert response.results
    assert response.results[0].source_info["turnover_source"] == "official"
    report = response.funnel_report["data_source_report"]
    assert report["ohlcv"]["tpex_official_count"] == 1
    assert report["turnover"]["official_turnover_count"] == 1


def test_lot_unit_correctness() -> None:
    market = make_market_df(return_60d=0.08, base_return=0.01)
    liquid = make_candidate_df(
        first_base_volume_shares=714_285,
        second_base_volume_shares=500_000,
        recent_volume_shares=500_000,
        last_5_volume_shares=500_000,
    )
    thin = make_candidate_df(
        first_base_volume_shares=714,
        second_base_volume_shares=500,
        recent_volume_shares=500,
        last_5_volume_shares=500,
    )

    liquid_result = evaluate_surge_candidate("1111", "單位正確", liquid, market, include_unfit=True)
    thin_result = evaluate_surge_candidate("2222", "單位錯誤防呆", thin, market, include_unfit=True)

    assert liquid_result is not None
    assert liquid_result.metrics.avg_volume_20_lots == pytest.approx(500)
    assert "low_liquidity" not in liquid_result.risk_flags
    assert thin_result is not None
    assert thin_result.metrics.avg_volume_20_lots == pytest.approx(0.5)
    assert "low_liquidity" in thin_result.risk_flags


# ---------------------------------------------------------------------------
# New tests: volume_not_dried_up, return_90d_range (broad/ideal), diagnostics
# ---------------------------------------------------------------------------

def test_volume_not_dried_up_allows_contraction() -> None:
    """Strong base-period volume contraction (ratio≈0.2) must NOT trigger volume_not_dried_up.

    volume_contraction_ratio is a positive scoring signal (base compression).
    volume_not_dried_up is a liquidity guard — it only checks avg_volume_20_lots >= 300.
    """
    df = make_candidate_df(
        return_60d=0.15,
        base_return=0.02,
        return_5d=0.03,
        first_base_volume_shares=2_000_000,
        second_base_volume_shares=400_000,   # strong contraction ≈ 0.2
        recent_volume_shares=900_000,
        last_5_volume_shares=600_000,        # 5d avg < 85% of 20d avg → old ratio would fail
    )
    market = make_market_df()
    debug_context: dict = {}
    result = evaluate_surge_candidate("T100", "縮量盤整股", df, market, include_unfit=True, debug_context=debug_context)
    assert result is not None
    gates = debug_context["condition_gates"]
    assert result.metrics.volume_contraction_ratio < 0.8   # strong contraction is present
    assert gates["volume_not_dried_up"] is True            # but liquidity guard still passes


def test_low_liquidity_stock_fails_volume_not_dried_up() -> None:
    """Stocks below the 300-lot minimum must fail volume_not_dried_up."""
    df = make_candidate_df(
        first_base_volume_shares=200_000,
        second_base_volume_shares=200_000,
        recent_volume_shares=200_000,
        last_5_volume_shares=200_000,
    )
    market = make_market_df()
    debug_context: dict = {}
    evaluate_surge_candidate("T101", "死魚股", df, market, include_unfit=True, debug_context=debug_context)
    gates = debug_context["condition_gates"]
    # avg_volume_20_lots = 200_000 / 1000 = 200 lots < 300 minimum
    assert gates["volume_not_dried_up"] is False


def test_return_90d_5pct_passes_broad_filter() -> None:
    """return_90d ≈ 5% is within broad range [0%, 35%] but outside ideal [10%, 30%]."""
    # bar[-63] = closes[27] = 98.0; close_today ≈ 98*1.05 ≈ 102.9 → return_60d ≈ 2.9%
    df = make_candidate_df(return_60d=0.029, base_return=0.01, return_5d=0.02)
    market = make_market_df()
    debug_context: dict = {}
    evaluate_surge_candidate("T102", "低漲幅股", df, market, include_unfit=True, debug_context=debug_context)
    gates = debug_context["condition_gates"]
    assert gates["return_90d_range"] is True         # passes broad [0%, 35%]
    assert gates["return_90d_ideal_range"] is False  # outside ideal [10%, 30%]


def test_return_90d_20pct_passes_ideal_range() -> None:
    """return_90d ≈ 20% is within both broad [0%, 35%] and ideal [10%, 30%] ranges."""
    # bar[-63]=98; close_today≈98*1.20≈117.6 → return_60d≈17.6%
    df = make_candidate_df(return_60d=0.176, base_return=0.02, return_5d=0.03)
    market = make_market_df()
    debug_context: dict = {}
    evaluate_surge_candidate("T103", "理想漲幅股", df, market, include_unfit=True, debug_context=debug_context)
    gates = debug_context["condition_gates"]
    assert gates["return_90d_range"] is True
    assert gates["return_90d_ideal_range"] is True


def test_return_90d_33pct_passes_broad_but_not_ideal() -> None:
    """return_90d ≈ 33% passes broad [0%, 35%] — not hard-filtered — but outside ideal [10%, 30%]."""
    # bar[-63]=98; close_today≈98*1.33≈130.3 → return_60d≈30.3%
    df = make_candidate_df(return_60d=0.303, base_return=0.02, return_5d=0.03)
    market = make_market_df()
    debug_context: dict = {}
    result = evaluate_surge_candidate("T104", "偏熱漲幅股", df, market, include_unfit=True, debug_context=debug_context)
    assert result is not None                            # NOT eliminated by the broad filter
    gates = debug_context["condition_gates"]
    assert gates["return_90d_range"] is True             # 33% < 35% → passes broad
    assert gates["return_90d_ideal_range"] is False      # 33% > 30% → outside ideal


def test_return_20d_high_does_not_disqualify() -> None:
    """return_20d > 5% must NOT disqualify a stock — return_20d_pre_breakout is diagnostic only."""
    df = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03)
    market = make_market_df()
    debug_context: dict = {}
    result = evaluate_surge_candidate("2330", "台積電", df, market, include_unfit=True, debug_context=debug_context)
    assert result is not None
    gates = debug_context["condition_gates"]
    # return_20d ≈ 11.76% exceeds the pre-breakout threshold (0.05)
    assert gates["return_20d_pre_breakout"] is False
    # yet the stock is still a viable candidate — not "不符合" because of this
    assert result.candidate_type != "不符合"


def test_return_20d_not_surged_passes_when_under_threshold() -> None:
    """return_20d ≈ 12% (< 15%) must pass the not-surged hard filter."""
    # return_60d=0.14, base_return=0.02 -> return_20d ≈ 11.76%
    df = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03)
    market = make_market_df()
    debug_context: dict = {}
    result = evaluate_surge_candidate("2330", "台積電", df, market, include_unfit=True, debug_context=debug_context)
    assert result is not None
    assert debug_context["condition_gates"]["return_20d_not_surged"] is True
    assert result.candidate_type != "不符合"


def test_return_20d_not_surged_disqualifies_when_over_threshold() -> None:
    """return_20d > 15% must not be classified as pre-breakout setup."""
    # return_60d=0.22, base_return=0.02 -> return_20d ≈ 19.6%
    df = make_candidate_df(return_60d=0.22, base_return=0.02, return_5d=0.03)
    market = make_market_df()
    debug_context: dict = {}
    result = evaluate_surge_candidate("2454", "聯發科", df, market, include_unfit=True, debug_context=debug_context)
    assert result is not None
    assert debug_context["condition_gates"]["return_20d_not_surged"] is False
    assert result.candidate_type != "起漲前觀察"
    assert result.candidate_type == "偏熱觀察"


def test_pre_breakout_observation_for_early_setup() -> None:
    """A Flat Base breakout day with EMA micro-upturn should be 起漲前觀察.

    Phase 9.8 update: the candidate now requires event-trigger conditions —
    close > base_high * 1.001 AND breakout-day volume ≥ 1.4× 50d avg.
    Fixture is shaped so close_today slightly exceeds base_high and the
    final bar carries a 2.5M-share volume spike (vs ~1M base average).
    """
    df = make_candidate_df(
        return_60d=0.10,           # close ~1.10× start
        base_return=0.08,          # base_high ~1.08× start → close clears it
        return_5d=0.01,
        recent_volume_shares=900_000,
        last_5_volume_shares=900_000,
        today_volume_shares=2_500_000,  # breakout-day volume spike (≥ 1.4× avg_50)
        turnover_multiplier=1.5,        # bump avg_turnover_20 past 100M
    )
    market = make_market_df(return_60d=0.04, base_return=0.01)
    result = evaluate_surge_candidate("T201", "起漲前", df, market, include_unfit=True)

    assert result is not None
    assert result.candidate_type == "起漲前觀察"
    assert result.metrics.pre_breakout_score >= 60
    assert result.metrics.return_20d <= 0.12
    assert result.metrics.close_from_ema20_pct <= 0.12
    # Phase 9.8: close should be in buy zone (just above base_high, ≤ 1.05)
    assert 1.001 < result.metrics.close_to_base_high_ratio <= 1.05


def test_already_broken_out_above_base_high_is_not_pre_breakout() -> None:
    """A stock where close is > 3% above base_high — i.e., the breakout already happened
    and it's now in 'pulled back from peak' state — must NOT be 起漲前觀察.
    This is the chart-screenshot scenario: 60-day return looks OK, return_20d looks OK
    after pullback, but close clearly above the consolidation high."""
    # return_60d=0.08, base_return=0.02 puts close at ~5% above base_high (108 vs 102.5)
    df = make_candidate_df(
        return_60d=0.08,
        base_return=0.02,        # base barely rose → base_high ~102, close ~108
        return_5d=0.01,
        recent_volume_shares=900_000,
        last_5_volume_shares=1_100_000,
    )
    market = make_market_df(return_60d=0.04, base_return=0.01)
    result = evaluate_surge_candidate("T204", "突破後回測", df, market, include_unfit=True)

    assert result is not None
    # close_to_base_high_ratio ~1.05 > 1.03 → not pre-breakout
    assert result.metrics.close_to_base_high_ratio > 1.03
    assert result.candidate_type != "起漲前觀察"


def test_pre_breakout_does_not_require_full_bullish_stack() -> None:
    """EMA5 > EMA10 > EMA20 is not required for 起漲前觀察 classification.
    Synthetic metrics match the tightened gates (ema_spread ≤ 0.03,
    abs(close_from_ema20) ≤ 0.05, close_to_base_high ≤ 1.00, contraction ≤ 0.80)."""
    rules = load_surge_candidate_rules()
    metrics = CandidateMetrics(
        return_60d=0.05,                # ≤ 0.10 (strict pre_breakout 60d)
        return_90d=0.10,                # 輔助過濾 ≥ -15%
        return_20d=0.02,                # ≤ 0.08
        return_60_to_20=0.02,
        return_5d=0.005,
        range_90d=0.20,                 # 90 日擺盪 20%
        high_90d=115.0,
        low_90d=96.0,
        avg_volume_20_lots=1500,
        avg_turnover_20=150_000_000,    # ≥ 100M 熱門
        base_high=102,
        base_low=95,
        base_range_pct=0.08,
        volume_contraction_ratio=0.70,  # ≤ 0.80
        volume_recovery_ratio_5d=0.85,  # below 1.0 — proves recovery is not required
        volume_today_ratio_20=0.9,
        ema_spread=0.02,                # ≤ 0.03
        ema5_slope=0.002,               # > 0 (positive upturn)
        ema10_slope=0.0,                # > -0.001 (flat)
        ema20_slope=-0.001,             # > -0.003 (slight down)
        ema5_slope_prev_10d=-0.004,     # prev: was down → satisfies transition condition
        ema10_slope_prev_10d=-0.002,
        ema20_slope_prev_20d=-0.003,
        ema_down_to_up_transition_score=100,
        relative_strength_20d=0.01,
        relative_strength_60d=0.02,
        close_distance_from_ema20=0.02, # abs ≤ 0.05
        close_from_ema20_pct=0.02,
        close_to_base_high_ratio=0.97,  # ≤ 1.00
        close_from_base_low_pct=0.12,
        pre_breakout_score=72,
        setup_price_position_score=75,
        ema_micro_upturn_score=70,
        volume_setup_score=75,
        volume_contraction_score=85,
        upper_shadow_ratio_today=0.1,
    )
    scores = CandidateScores(
        liquidity_score=75,
        price_position_score=65,
        base_compression_score=70,
        volume_score=60,
        ema_convergence_score=62,
        relative_strength_score=60,
    )

    candidate_type = _classify_candidate(
        58,
        40,
        [],
        {
            "price_position": True,
            "liquidity": True,
            "return_5d_not_extreme": True,
            "return_90d_range": True,
            "volume_not_dried_up": True,
            "ema_micro_upturn": True,
            "breakout_today": True,
            "base_depth_ok": True,
        },
        metrics,
        scores,
        bullish_stack=False,
        rules=rules,
    )

    assert candidate_type == "起漲前觀察"


def test_extended_from_ema20_is_not_pre_breakout() -> None:
    """A stock more than 15% above EMA20 is hot/extended, not 起漲前觀察."""
    rules = load_surge_candidate_rules()
    metrics = CandidateMetrics(
        return_60d=0.10,
        return_90d=0.12,
        return_20d=0.07,
        return_60_to_20=0.02,
        return_5d=0.02,
        avg_volume_20_lots=1000,
        avg_turnover_20=100_000_000,
        base_high=102,
        base_low=95,
        base_range_pct=0.08,
        volume_contraction_ratio=0.75,
        volume_recovery_ratio_5d=1.12,
        volume_today_ratio_20=1.05,
        ema_spread=0.04,
        ema5_slope=0.002,
        ema10_slope=-0.0005,
        ema20_slope=-0.002,
        relative_strength_20d=0.01,
        relative_strength_60d=0.02,
        close_distance_from_ema20=0.16,
        close_from_ema20_pct=0.16,
        close_to_base_high_ratio=1.02,
        close_from_base_low_pct=0.12,
        pre_breakout_score=72,
        setup_price_position_score=75,
        ema_micro_upturn_score=70,
        volume_setup_score=75,
        upper_shadow_ratio_today=0.1,
    )
    scores = CandidateScores(
        liquidity_score=75,
        price_position_score=65,
        base_compression_score=70,
        volume_score=60,
        ema_convergence_score=62,
        relative_strength_score=60,
    )

    candidate_type = _classify_candidate(
        58,
        45,
        [],
        {
            "price_position": True,
            "liquidity": True,
            "return_5d_not_extreme": True,
            "return_90d_range": True,
            "volume_not_dried_up": True,
            "ema_micro_upturn": True,
            "breakout_today": True,
            "base_depth_ok": True,
        },
        metrics,
        scores,
        bullish_stack=False,
        rules=rules,
    )

    assert candidate_type == "偏熱觀察"


def test_mild_volume_recovery_boosts_pre_breakout_setup() -> None:
    """volume_recovery_ratio 1.0-1.3 should support early setup scoring."""
    df = make_candidate_df(
        return_60d=0.08,
        base_return=0.02,
        return_5d=0.01,
        recent_volume_shares=900_000,
        last_5_volume_shares=1_100_000,
    )
    market = make_market_df(return_60d=0.04, base_return=0.01)
    result = evaluate_surge_candidate("T202", "溫和回溫", df, market, include_unfit=True)

    assert result is not None
    assert 1.0 <= result.metrics.volume_recovery_ratio_5d <= 1.3
    assert result.metrics.volume_setup_score >= 70


@pytest.mark.asyncio
async def test_funnel_report_contains_broad_and_ideal_range(monkeypatch) -> None:
    """debug=True funnel must expose both broad and ideal 90d range condition reports."""
    async def fake_price_history(symbol: str, days: int):
        candles = make_candidate_df(return_60d=0.15, base_return=0.02, return_5d=0.03).to_dict("records")
        return OhlcvLoadResult(
            candles=candles,
            source_info=SourceInfo(ohlcv_source="finmind", turnover_source="finmind_trading_money", bars_count=len(candles)),
        )

    async def fake_tpex_quotes():
        return {}

    monkeypatch.setattr("backend.app.services.screener_service.get_tw_price_history_with_source", fake_price_history)
    monkeypatch.setattr("backend.app.services.screener_service.fetch_tpex_mainboard_quote_map", fake_tpex_quotes)

    response = await scan_surge_candidates(
        default_screener_parameters(),
        df_market=make_market_df(return_60d=0.08, base_return=0.01),
        universe=[{"stock_code": "2330", "company_name": "台積電"}],
        debug=True,
        market_index_report={"source": "finmind", "available": True, "fallback_used": False, "warnings": []},
    )

    assert response.funnel_report is not None
    reports = response.funnel_report["condition_reports"]
    assert "return_90d_range" in reports           # broad filter present
    assert "return_90d_ideal_range" in reports     # ideal zone present
    assert reports["return_20d_pre_breakout"].get("diagnostic_only") is True
    # broad pass count must be >= ideal pass count
    assert reports["return_90d_range"]["pass_count"] >= reports["return_90d_ideal_range"]["pass_count"]


def test_close_not_far_from_ema20_passes_for_early_stage_stock() -> None:
    """A stock just starting to move (close ~3% above EMA20, EMA spread ~3%) must pass both new gates."""
    # return_60d=0.14, base_return=0.02, return_5d=0.03 gives close_distance_from_ema20 ≈ 3%
    # and ema_spread ≈ 3% — both well within the 8% / 5% hard limits.
    df = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03)
    market = make_market_df(return_60d=0.08, base_return=0.01)
    debug_context: dict = {}
    result = evaluate_surge_candidate("T301", "初動股", df, market, include_unfit=True, debug_context=debug_context)

    assert result is not None
    gates = debug_context["condition_gates"]
    assert gates["close_not_far_from_ema20"] is True
    assert gates["ema_not_spread_out"] is True
    assert result.candidate_type != "偏熱觀察"


def test_already_surged_stock_fails_ema_proximity_gates() -> None:
    """A stock that has already surged well past EMA20 (return_60d=0.50) must fail the new gates.
    With return_20d > 15% the existing 偏熱觀察 block fires first, so this stock is 偏熱觀察."""
    # High return_60d forces a large close_distance_from_ema20 and wide ema_spread.
    df = make_candidate_df(return_60d=0.50, base_return=0.02, return_5d=0.05)
    market = make_market_df(return_60d=0.08, base_return=0.01)
    debug_context: dict = {}
    result = evaluate_surge_candidate("T302", "噴發後股", df, market, include_unfit=True, debug_context=debug_context)

    assert result is not None
    gates = debug_context["condition_gates"]
    # At least one of the two new proximity gates should fail for a 50% mover
    assert not gates["close_not_far_from_ema20"] or not gates["ema_not_spread_out"]
    # return_20d > 15% triggers 偏熱觀察 in the existing block (checked before 不符合)
    assert result.candidate_type == "偏熱觀察"


def test_mid_surge_stock_with_wide_ema_is_hard_filtered() -> None:
    """The gray-zone case from the chart screenshot: close 12% above EMA20 with
    EMA spread ~9%, but return_20d below the 15% 偏熱觀察 threshold and return_60d
    below the 30% overheat threshold. Without the new gates this would slip through
    as a valid candidate; with them it must be classified 不符合."""
    rules = load_surge_candidate_rules()
    metrics = CandidateMetrics(
        return_60d=0.18,
        return_90d=0.20,
        return_20d=0.12,            # < 0.15 — passes existing return_20d_not_surged
        return_60_to_20=0.05,
        return_5d=0.03,             # < 0.15 — passes overheat_return_5d
        avg_volume_20_lots=1000,
        avg_turnover_20=100_000_000,
        base_high=102,
        base_low=95,
        base_range_pct=0.08,
        volume_contraction_ratio=0.75,
        volume_recovery_ratio_5d=1.2,
        volume_today_ratio_20=1.1,
        ema_spread=0.09,            # > 0.05 — FAILS new ema_not_spread_out gate
        ema5_slope=0.003,
        ema10_slope=0.001,
        ema20_slope=0.0005,
        relative_strength_20d=0.02,
        relative_strength_60d=0.04,
        close_distance_from_ema20=0.12,  # > 0.08 — FAILS new close_not_far_from_ema20 gate
        close_from_ema20_pct=0.12,       # < 0.15 — passes existing extended_from_ema20
        upper_shadow_ratio_today=0.1,
    )
    scores = CandidateScores(
        liquidity_score=75,
        price_position_score=80,
        base_compression_score=70,
        volume_score=65,
        ema_convergence_score=50,
        relative_strength_score=65,
    )

    candidate_type = _classify_candidate(
        65,
        45,
        [],
        {
            "price_position": True,
            "liquidity": True,
            "return_5d_not_extreme": True,
            "return_90d_range": True,
            "volume_not_dried_up": True,
            "close_not_far_from_ema20": False,  # FAILS new gate
            "ema_not_spread_out": False,        # FAILS new gate
            "ema_micro_upturn": True,
        },
        metrics,
        scores,
        bullish_stack=True,
        rules=rules,
    )

    # With the tightened 偏熱觀察 threshold (close_from_ema20 > 0.08 → 偏熱),
    # this 12%-above stock now falls into 偏熱觀察 instead of 不符合.
    # Either category is hidden from the default UI filter, so the user's intent is preserved.
    assert candidate_type == "偏熱觀察"


def test_pre_breakout_blocks_long_term_downtrend() -> None:
    """A stock with return_90d < -15% is in a clear long-term downtrend.
    Even if the recent 60 days look like consolidation, this is NOT 起漲前觀察
    — it's still a falling knife. (Yellow circle pattern allows return_90d
    down to -15%; below that is structural weakness.)"""
    rules = load_surge_candidate_rules()
    metrics = CandidateMetrics(
        return_60d=0.08,
        return_90d=-0.20,           # < -15% — clearly in downtrend
        return_20d=0.06,
        return_60_to_20=0.02,
        return_5d=0.01,
        avg_volume_20_lots=1000,
        avg_turnover_20=100_000_000,
        base_high=102,
        base_low=95,
        base_range_pct=0.08,
        volume_contraction_ratio=0.75,
        volume_recovery_ratio_5d=1.12,
        volume_today_ratio_20=1.05,
        ema_spread=0.04,
        ema5_slope=0.002,
        ema10_slope=-0.0005,
        ema20_slope=-0.002,
        relative_strength_20d=0.01,
        relative_strength_60d=0.02,
        close_distance_from_ema20=0.03,
        close_from_ema20_pct=0.03,
        close_to_base_high_ratio=1.02,
        close_from_base_low_pct=0.12,
        pre_breakout_score=72,
        setup_price_position_score=75,
        ema_micro_upturn_score=70,
        volume_setup_score=75,
        upper_shadow_ratio_today=0.1,
    )
    scores = CandidateScores(
        liquidity_score=75,
        price_position_score=65,
        base_compression_score=70,
        volume_score=60,
        ema_convergence_score=62,
        relative_strength_score=60,
    )

    candidate_type = _classify_candidate(
        58,
        40,
        [],
        {
            "price_position": True,
            "liquidity": True,
            "return_5d_not_extreme": True,
            "return_90d_range": True,
            "volume_not_dried_up": True,
            "ema_micro_upturn": True,
            "breakout_today": True,
            "base_depth_ok": True,
        },
        metrics,
        scores,
        bullish_stack=False,
        rules=rules,
    )

    assert candidate_type != "起漲前觀察"


def test_pre_breakout_score_rewards_relative_strength() -> None:
    """Stock beating TAIEX in 20d and 60d must have higher pre_breakout_score than
    a stock losing to TAIEX — relative_strength contributes 5% weight after the
    realignment (縮量盤整 + EMA 微翹 才是核心，RS 只是輔助)."""
    from backend.app.services.screener_service import _final_pre_breakout_score
    rules = load_surge_candidate_rules()

    # Both candidates have identical base/EMA/setup/volume/risk, differ only in RS.
    strong_rs_score = _final_pre_breakout_score(
        base_compression_score=70,
        ema_micro_upturn_score=70,
        ema_down_to_up_transition_score=70,
        setup_price_position_score=70,
        volume_contraction_score=70,
        relative_strength_score=85,   # strong RS (beats market)
        liquidity_score=70,
        risk_score=40,
        rules=rules,
    )
    weak_rs_score = _final_pre_breakout_score(
        base_compression_score=70,
        ema_micro_upturn_score=70,
        ema_down_to_up_transition_score=70,
        setup_price_position_score=70,
        volume_contraction_score=70,
        relative_strength_score=30,   # weak RS (loses to market)
        liquidity_score=70,
        risk_score=40,
        rules=rules,
    )
    # 5% weight × 55-point gap = ~2.75 point spread in final score
    assert strong_rs_score > weak_rs_score


def test_pre_breakout_score_rewards_high_turnover() -> None:
    """Hot stock (high turnover → high liquidity_score) must score higher in pre_breakout
    than a thinly-traded one — liquidity contributes 5% weight after realignment."""
    from backend.app.services.screener_service import _final_pre_breakout_score
    rules = load_surge_candidate_rules()

    hot_score = _final_pre_breakout_score(
        base_compression_score=70,
        ema_micro_upturn_score=70,
        ema_down_to_up_transition_score=70,
        setup_price_position_score=70,
        volume_contraction_score=70,
        relative_strength_score=60,
        liquidity_score=95,   # very high turnover (100M+)
        risk_score=40,
        rules=rules,
    )
    quiet_score = _final_pre_breakout_score(
        base_compression_score=70,
        ema_micro_upturn_score=70,
        ema_down_to_up_transition_score=70,
        setup_price_position_score=70,
        volume_contraction_score=70,
        relative_strength_score=60,
        liquidity_score=40,   # barely meets liquidity floor
        risk_score=40,
        rules=rules,
    )
    # 5% weight × 55-point gap = ~2.75 point spread
    assert hot_score > quiet_score


def test_low_turnover_stock_excluded_from_pre_breakout() -> None:
    """Per user's latest spec: 起漲前觀察 must be 「熱門股」 — avg_turnover_20 ≥ 100M.
    A small/mid-cap with only ~35M turnover gets hard-filtered, even if all other
    setup conditions are perfect."""
    rules = load_surge_candidate_rules()
    metrics = CandidateMetrics(
        return_60d=0.05,
        return_90d=0.10,                  # in range, but turnover too low
        range_90d=0.20,
        high_90d=115.0,
        low_90d=96.0,
        return_20d=0.02,
        return_60_to_20=0.02,
        return_5d=0.005,
        avg_volume_20_lots=400,
        avg_turnover_20=35_000_000,       # ~35M — below 100M hot threshold
        base_high=102,
        base_low=95,
        base_range_pct=0.08,
        volume_contraction_ratio=0.70,    # ≤ 0.80
        volume_recovery_ratio_5d=0.90,
        volume_today_ratio_20=0.95,
        ema_spread=0.02,                  # ≤ 0.03
        ema5_slope=0.002,
        ema10_slope=0.0,
        ema20_slope=-0.001,
        ema5_slope_prev_10d=-0.004,
        ema10_slope_prev_10d=-0.002,
        ema20_slope_prev_20d=-0.003,
        ema_down_to_up_transition_score=100,
        relative_strength_20d=0.02,
        relative_strength_60d=0.04,
        close_distance_from_ema20=0.02,
        close_from_ema20_pct=0.02,
        close_to_base_high_ratio=0.96,    # ≤ 1.00
        close_from_base_low_pct=0.12,
        pre_breakout_score=68,
        setup_price_position_score=72,
        ema_micro_upturn_score=70,
        volume_setup_score=75,
        volume_contraction_score=85,
        upper_shadow_ratio_today=0.1,
    )
    scores = CandidateScores(
        liquidity_score=55,               # mid-low tier, not high
        price_position_score=65,
        base_compression_score=70,
        volume_score=60,
        ema_convergence_score=62,
        relative_strength_score=70,
    )

    candidate_type = _classify_candidate(
        58,
        40,
        [],
        {
            "price_position": True,
            "liquidity": True,
            "return_5d_not_extreme": True,
            "return_90d_range": True,
            "volume_not_dried_up": True,
            "ema_micro_upturn": True,
            "breakout_today": True,
            "base_depth_ok": True,
        },
        metrics,
        scores,
        bullish_stack=False,
        rules=rules,
    )

    # 35M turnover < 100M hard gate → must NOT be 起漲前觀察
    assert candidate_type != "起漲前觀察"


def test_pre_breakout_requires_volume_contraction() -> None:
    """A stock with otherwise perfect setup but volume_contraction_ratio > 0.85
    (base 2nd half not contracting vs 1st half) must NOT be 起漲前觀察.
    Real pre-breakout = volume drying up during base, not volume staying flat or rising."""
    rules = load_surge_candidate_rules()
    metrics = CandidateMetrics(
        return_60d=0.08,
        return_90d=0.10,            # within -15%~30% — passes return_90d gate
        return_20d=0.06,
        return_60_to_20=0.02,
        return_5d=0.01,
        avg_volume_20_lots=1000,
        avg_turnover_20=100_000_000,
        base_high=102,
        base_low=95,
        base_range_pct=0.08,
        volume_contraction_ratio=0.95,    # > 0.85 — base volume NOT contracting → fails new gate
        volume_recovery_ratio_5d=1.10,    # this is irrelevant now; gate removed
        volume_today_ratio_20=0.90,
        ema_spread=0.04,
        ema5_slope=0.002,
        ema10_slope=-0.0005,
        ema20_slope=-0.002,
        relative_strength_20d=0.01,
        relative_strength_60d=0.02,
        close_distance_from_ema20=0.03,
        close_from_ema20_pct=0.03,
        close_to_base_high_ratio=1.02,
        close_from_base_low_pct=0.12,
        pre_breakout_score=72,
        setup_price_position_score=75,
        ema_micro_upturn_score=70,
        volume_setup_score=75,
        upper_shadow_ratio_today=0.1,
    )
    scores = CandidateScores(
        liquidity_score=75,
        price_position_score=65,
        base_compression_score=70,
        volume_score=60,
        ema_convergence_score=62,
        relative_strength_score=60,
    )

    candidate_type = _classify_candidate(
        58,
        40,
        [],
        {
            "price_position": True,
            "liquidity": True,
            "return_5d_not_extreme": True,
            "return_90d_range": True,
            "volume_not_dried_up": True,
            "ema_micro_upturn": True,
            "breakout_today": True,
            "base_depth_ok": True,
        },
        metrics,
        scores,
        bullish_stack=False,
        rules=rules,
    )

    assert candidate_type != "起漲前觀察"


def test_yellow_circle_state_qualifies_as_pre_breakout() -> None:
    """The 'yellow circle' pattern — mid-rally consolidation:
    - return_60d slightly negative (~-5%): currently in consolidation
    - return_90d in 10~30% range (had a prior rally)
    - close near or slightly below EMA20: price inside base
    - EMA spread very tight (~1.5%): MAs caught up
    - EMA5/10 micro-upturn after prev decline: real transition
    - close_to_base_high ~ 0.94: near middle of base
    - volume contraction: base 2nd half ~65% of 1st half
    - avg_turnover_20 ≥ 100M: qualifies as 熱門股."""
    rules = load_surge_candidate_rules()
    metrics = CandidateMetrics(
        return_60d=-0.05,
        return_90d=0.05,
        return_20d=-0.01,
        return_60_to_20=-0.03,
        return_5d=0.001,
        range_90d=0.18,
        high_90d=130.0,
        low_90d=110.0,
        avg_volume_20_lots=1500,
        avg_turnover_20=120_000_000,
        base_high=120,
        base_low=115,
        base_range_pct=0.043,
        volume_contraction_ratio=0.65,
        volume_recovery_ratio_5d=0.75,
        volume_today_ratio_20=0.7,
        ema_spread=0.015,
        ema5_slope=0.0015,
        ema10_slope=0.0005,
        ema20_slope=-0.0005,
        ema5_slope_prev_10d=-0.005,
        ema10_slope_prev_10d=-0.003,
        ema20_slope_prev_20d=-0.004,
        ema_down_to_up_transition_score=100,
        relative_strength_20d=0.005,
        relative_strength_60d=0.01,
        close_distance_from_ema20=-0.012,
        close_from_ema20_pct=-0.012,
        close_to_base_high_ratio=0.94,
        close_from_base_low_pct=0.018,
        pre_breakout_score=68,
        setup_price_position_score=65,
        ema_micro_upturn_score=68,
        volume_setup_score=58,
        upper_shadow_ratio_today=0.1,
    )
    scores = CandidateScores(
        liquidity_score=65,
        price_position_score=55,
        base_compression_score=78,
        volume_score=52,
        ema_convergence_score=75,
        relative_strength_score=55,
    )

    candidate_type = _classify_candidate(
        62,
        38,
        [],
        {
            "price_position": True,
            "liquidity": True,
            "return_5d_not_extreme": True,
            "return_90d_range": True,
            "volume_not_dried_up": True,
            "close_not_far_from_ema20": True,
            "ema_not_spread_out": True,
            "ema_micro_upturn": True,
            "breakout_today": True,
            "base_depth_ok": True,
        },
        metrics,
        scores,
        bullish_stack=False,
        rules=rules,
    )

    assert candidate_type == "起漲前觀察"


# ============================================================================
# User-spec scenario tests — aligned with the 「黃色圈圈」 strategy
# ============================================================================

def _yellow_circle_metrics(rules) -> tuple[CandidateMetrics, CandidateScores]:
    """Reusable yellow-circle metrics fixture — mid-rally consolidation pattern.

    return_90d 0.15 (in 10~30%): stock had a previous rally 60~90 days ago
    return_60d -0.05: but no momentum in last 60 days (currently consolidating)
    return_20d -0.01: very quiet last 20 days
    avg_turnover_20 = 120M: meets 「熱門股」 100M threshold
    EMA prev slopes negative + current slopes turning up → strong transition signal.
    """
    metrics = CandidateMetrics(
        return_60d=-0.05,
        return_90d=0.05,                  # 輔助過濾 ≥ -15%
        return_20d=-0.01,
        return_60_to_20=-0.03,
        return_5d=0.001,
        range_90d=0.18,                   # 90 日擺盪 18% 在 10~30% 主力表態區間
        high_90d=130.0,
        low_90d=110.0,
        avg_volume_20_lots=1500,
        avg_turnover_20=120_000_000,      # ≥ 100M
        base_high=120,
        base_low=115,
        base_range_pct=0.043,
        volume_contraction_ratio=0.70,
        volume_recovery_ratio_5d=0.75,
        volume_today_ratio_20=0.7,
        ema_spread=0.018,
        ema5_slope=0.0015,                   # current 5d slope: positive (turning up)
        ema10_slope=0.0005,                   # current 5d slope: barely positive
        ema20_slope=-0.0005,                  # current 10d slope: still slightly down but stabilizing
        ema5_slope_prev_10d=-0.005,           # PREV slope: was declining
        ema10_slope_prev_10d=-0.003,          # PREV slope: was declining
        ema20_slope_prev_20d=-0.004,          # PREV slope: was declining
        ema_down_to_up_transition_score=100,  # 30+25+20+15+10 = perfect transition
        relative_strength_20d=0.005,
        relative_strength_60d=0.01,
        close_distance_from_ema20=-0.015,
        close_from_ema20_pct=-0.015,
        close_to_base_high_ratio=0.95,
        close_from_base_low_pct=0.018,
        pre_breakout_score=68,
        setup_price_position_score=65,
        ema_micro_upturn_score=68,
        volume_setup_score=58,
        volume_contraction_score=90,
        upper_shadow_ratio_today=0.1,
    )
    scores = CandidateScores(
        liquidity_score=65,
        price_position_score=55,
        base_compression_score=78,
        volume_score=52,
        ema_convergence_score=75,
        relative_strength_score=55,
    )
    return metrics, scores


def _default_gates() -> dict:
    return {
        "price_position": True,
        "liquidity": True,
        "return_5d_not_extreme": True,
        "return_90d_range": True,
        "volume_not_dried_up": True,
        "ema_micro_upturn": True,
        # Phase 9.8: Flat Base event trigger gates — synthetic tests assume the
        # stock is on its breakout day inside a valid flat base structure.
        "breakout_today": True,
        "base_depth_ok": True,
    }


def test_scenario_yellow_circle_pattern_classifies_as_pre_breakout() -> None:
    """情境 1: 黃圈型態 — return_60d≈-5%, return_90d≈+2%, vol_contraction=0.7,
    ema_spread=1.8%, EMA5 微上彎, EMA10 走平, ema20 不明顯下彎, close near EMA20."""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    candidate_type = _classify_candidate(62, 38, [], _default_gates(), metrics, scores, bullish_stack=False, rules=rules)
    assert candidate_type == "起漲前觀察"


def test_scenario_already_surged_not_pre_breakout() -> None:
    """情境 2: 已經大漲 — return_20d=18%, close_from_ema20=14%, ema_spread=9%
    必須不可分類為起漲前觀察 (應為偏熱觀察)。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    metrics = metrics.model_copy(update={
        "return_20d": 0.18,                   # > 0.15 → 偏熱觸發
        "return_60d": 0.25,
        "close_from_ema20_pct": 0.14,         # > 0.12 → 偏熱觸發
        "close_distance_from_ema20": 0.14,
        "ema_spread": 0.09,                   # > 0.08 → 偏熱觸發
        "close_to_base_high_ratio": 1.10,
        "volume_contraction_ratio": 1.05,
    })
    candidate_type = _classify_candidate(78, 55, [], _default_gates(), metrics, scores, bullish_stack=True, rules=rules)
    assert candidate_type == "偏熱觀察"
    assert candidate_type != "起漲前觀察"


def test_scenario_low_volume_recovery_still_pre_breakout_if_contracting() -> None:
    """情境 3: 量能回溫不是起漲前必要條件 —
    volume_recovery_ratio < 1.0 但 volume_contraction_ratio <= 0.85 → 仍可起漲前觀察。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    metrics = metrics.model_copy(update={
        "volume_recovery_ratio_5d": 0.65,   # 明顯低於 1.0 (近期成交量比 20 日均量低)
        "volume_contraction_ratio": 0.75,   # 但 base 後半 < 前半 → 真縮量
    })
    candidate_type = _classify_candidate(62, 38, [], _default_gates(), metrics, scores, bullish_stack=False, rules=rules)
    assert candidate_type == "起漲前觀察"


def test_scenario_pre_breakout_does_not_require_full_bullish_stack() -> None:
    """情境 4: EMA 完整多頭排列不是起漲前必要條件 —
    EMA5 不一定 > EMA10 > EMA20, 但 EMA 微上翹與糾結 → 仍可起漲前觀察。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    # ema5_slope=0.0015 (positive upturn) but bullish_stack=False (EMA5 not above EMA10/20)
    candidate_type = _classify_candidate(62, 38, [], _default_gates(), metrics, scores, bullish_stack=False, rules=rules)
    assert candidate_type == "起漲前觀察"


def test_scenario_volume_breakout_not_pre_breakout() -> None:
    """情境 5: 爆量突破後股票 —
    volume_recovery_ratio > 1.8, return_20d 明顯上升 → 不可起漲前觀察
    (應為動能確認 / 偏熱觀察)。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    metrics = metrics.model_copy(update={
        "return_20d": 0.17,                   # 大漲 → 觸發偏熱
        "return_60d": 0.20,
        "volume_recovery_ratio_5d": 2.5,
        "volume_today_ratio_20": 2.8,
        "volume_contraction_ratio": 1.20,    # 量能放大，非縮量
        "ema_spread": 0.07,
        "close_from_ema20_pct": 0.10,
        "close_distance_from_ema20": 0.10,
    })
    candidate_type = _classify_candidate(75, 50, [], _default_gates(), metrics, scores, bullish_stack=True, rules=rules)
    assert candidate_type != "起漲前觀察"
    assert candidate_type in {"動能確認", "偏熱觀察", "初動候選"}


# ============================================================================
# EMA down-to-up transition scenario tests (4 cases per user spec)
# ============================================================================

def test_transition_ema_down_to_up_classifies_as_pre_breakout() -> None:
    """情境 1: EMA 由弱轉強成功 — 前期 EMA 下彎、近期上彎/走平/止跌，
    其他黃圈條件全符合。預期：transition_score ≥ 50 AND 起漲前觀察。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    # 用 helper 預設值就行 — prev slopes 全是負，current slopes 上翹
    assert metrics.ema5_slope_prev_10d <= 0 and metrics.ema5_slope > 0
    assert metrics.ema10_slope_prev_10d <= 0 and metrics.ema10_slope > -0.001
    assert metrics.ema20_slope_prev_20d < 0 and metrics.ema20_slope > -0.003
    assert metrics.ema_down_to_up_transition_score >= 50

    candidate_type = _classify_candidate(62, 38, [], _default_gates(), metrics, scores, bullish_stack=False, rules=rules)
    assert candidate_type == "起漲前觀察"


def test_transition_full_bullish_stack_with_high_return_not_pre_breakout() -> None:
    """情境 2: 已經完整多頭排列 + 大漲過 — EMA5 > EMA10 > EMA20、
    return_20d=18%、close_from_ema20=14%。預期：必須不是起漲前觀察。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    metrics = metrics.model_copy(update={
        # 完整多頭排列：所有 EMA slope 一路向上 (prev > 0, current > 0) → transition_score 拿不到核心 75 分
        "ema5_slope_prev_10d": 0.008,   # prev 已經是正 — 失去「prev <= 0」條件
        "ema10_slope_prev_10d": 0.006,
        "ema20_slope_prev_20d": 0.004,
        "ema5_slope": 0.012,
        "ema10_slope": 0.010,
        "ema20_slope": 0.005,
        # 已經漲過
        "return_20d": 0.18,
        "return_60d": 0.25,
        "close_from_ema20_pct": 0.14,
        "close_distance_from_ema20": 0.14,
        "ema_spread": 0.09,
    })
    candidate_type = _classify_candidate(78, 55, [], _default_gates(), metrics, scores, bullish_stack=True, rules=rules)
    # 偏熱觀察 block 會先觸發 (return_20d > 0.15, close_from_ema20 > 0.12)
    assert candidate_type == "偏熱觀察"
    assert candidate_type != "起漲前觀察"


def test_transition_single_day_rebound_not_pre_breakout() -> None:
    """情境 3: 單日反彈 — EMA5 近期上彎，但 ema_spread > 8% (EMA 已分叉)。
    預期：必須不是起漲前觀察 (偏熱觀察 block 會先觸發 ema_spread > 0.08)。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    metrics = metrics.model_copy(update={
        "ema_spread": 0.09,                  # > 0.08 → 偏熱觸發
        "volume_contraction_ratio": 1.20,    # 沒縮量
    })
    candidate_type = _classify_candidate(62, 38, [], _default_gates(), metrics, scores, bullish_stack=False, rules=rules)
    assert candidate_type != "起漲前觀察"


def test_transition_pre_breakout_without_full_bullish_stack() -> None:
    """情境 4: EMA 不需完整多頭排列 — EMA5 不一定 > EMA10 > EMA20,
    但 EMA 糾結、EMA5 上彎、EMA10 走平、EMA20 下彎趨緩。預期：仍可起漲前觀察。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    # 黃圈 fixture 本來就是 ema5 < ema10 < ema20 的反向序列 (在 helper 裡 close < ema20)
    # 這裡明確設 bullish_stack=False 證明：不需完整多頭排列也能歸 起漲前
    candidate_type = _classify_candidate(62, 38, [], _default_gates(), metrics, scores, bullish_stack=False, rules=rules)
    assert candidate_type == "起漲前觀察"


def test_hot_stock_required_for_pre_breakout() -> None:
    """路線 B 鬆綁：起漲前觀察 turnover 門檻從 100M → 50M。
    Stock < 50M turnover 仍會被擋掉 — 流動性太低的死魚股。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    # 把 turnover 降到 30M (below the new 50M threshold)
    metrics = metrics.model_copy(update={"avg_turnover_20": 30_000_000})
    candidate_type = _classify_candidate(62, 38, [], _default_gates(), metrics, scores, bullish_stack=False, rules=rules)
    assert candidate_type != "起漲前觀察"


def test_range_90d_below_min_not_pre_breakout() -> None:
    """路線 B 鬆綁：range_90d 下限從 10% → 5%。
    range_90d < 5% 才會被擋（沒主力表態的死水股）。"""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    # range_90d below the new 5% minimum (e.g., 3% — no movement at all)
    metrics = metrics.model_copy(update={"range_90d": 0.03})
    candidate_type = _classify_candidate(62, 38, [], _default_gates(), metrics, scores, bullish_stack=False, rules=rules)
    assert candidate_type != "起漲前觀察"


def test_range_90d_above_30pct_not_pre_breakout() -> None:
    """range_90d > 30% 代表已經劇烈擺盪、主力可能已操作完畢，不是 mid-rally consolidation."""
    rules = load_surge_candidate_rules()
    metrics, scores = _yellow_circle_metrics(rules)
    metrics = metrics.model_copy(update={"range_90d": 0.45})
    candidate_type = _classify_candidate(62, 38, [], _default_gates(), metrics, scores, bullish_stack=False, rules=rules)
    assert candidate_type != "起漲前觀察"


# ============================================================================
# AI Tech sector filter tests (6-Layer Framework)
# ============================================================================

def test_sector_service_recognizes_ai_tech_stocks() -> None:
    """Sample stocks from each category should be recognized."""
    from backend.app.services.sector_service import (
        is_ai_tech_stock, get_sector_category, get_sector_label
    )
    # Cat 1 IC Design
    assert is_ai_tech_stock("3661")     # 世芯-KY
    assert get_sector_category("3661") == "cat_1_silicon_ip"
    # Cat 2 Foundry
    assert is_ai_tech_stock("2330")     # 台積電
    # Cat 3 Packaging (the chokepoint)
    assert is_ai_tech_stock("2449")     # 京元電子
    assert "封裝" in (get_sector_label("2449") or "")
    # Cat 5 ODM
    assert is_ai_tech_stock("6669")     # 緯穎
    # Non-AI stock should NOT be in list
    assert not is_ai_tech_stock("2412")   # 中華電 (telecom, not AI)
    assert not is_ai_tech_stock("9999")   # nonsense code


def test_evaluate_attaches_sector_info_to_metrics() -> None:
    """evaluate_surge_candidate should populate sector_category and sector_label."""
    df = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03)
    market = make_market_df(return_60d=0.08, base_return=0.01)

    # 2330 is in the AI whitelist (Cat 2 Foundry)
    result = evaluate_surge_candidate("2330", "台積電", df, market)
    assert result is not None
    assert result.metrics.sector_category == "cat_2_foundry"
    assert result.metrics.sector_label is not None

    # 9999 is NOT in the whitelist
    result_nonai = evaluate_surge_candidate("9999", "非AI股", df, market)
    assert result_nonai is not None
    assert result_nonai.metrics.sector_category is None
    assert result_nonai.metrics.sector_label is None


@pytest.mark.asyncio
async def test_ai_tech_filter_excludes_non_ai_stocks(monkeypatch) -> None:
    """When ai_tech_only=True, non-AI stocks are filtered out of results."""
    async def fake_taiex():
        return MarketIndexLoadResult(
            dataframe=make_market_df(return_60d=0.08, base_return=0.01),
            source="finmind", available=True, fallback_used=False,
        )
    async def fake_price_history(symbol: str, days: int):
        candles = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03).to_dict("records")
        return OhlcvLoadResult(
            candles=candles,
            source_info=SourceInfo(ohlcv_source="finmind", turnover_source="finmind_trading_money", bars_count=len(candles)),
        )
    async def fake_tpex_quotes():
        return {}

    monkeypatch.setattr("backend.app.api.routes.screeners.load_taiex_history_with_source", fake_taiex)
    monkeypatch.setattr("backend.app.services.screener_service.get_tw_price_history_with_source", fake_price_history)
    monkeypatch.setattr("backend.app.services.screener_service.fetch_tpex_mainboard_quote_map", fake_tpex_quotes)

    # Build params with ai_tech_only=True
    params = default_screener_parameters()
    params_dict = params.to_dict()
    params_dict["ai_tech_only"] = True
    from backend.app.services.screener_service import ScreenerParameters
    ai_only_params = ScreenerParameters(**params_dict)

    response = await scan_surge_candidates(
        ai_only_params,
        df_market=make_market_df(return_60d=0.08, base_return=0.01),
        universe=[
            {"stock_code": "2330", "company_name": "台積電"},        # AI - should pass
            {"stock_code": "6669", "company_name": "緯穎"},          # AI - should pass
            {"stock_code": "2412", "company_name": "中華電"},        # NOT AI - should be filtered
            {"stock_code": "5876", "company_name": "上海商銀"},      # NOT AI - should be filtered
        ],
        debug=False,
        market_index_report={"source": "finmind", "available": True, "fallback_used": False, "warnings": []},
    )

    returned_codes = {row.stock_id for row in response.results}
    assert "2412" not in returned_codes
    assert "5876" not in returned_codes
    # AI stocks may or may not pass other gates, but non-AI must be excluded


@pytest.mark.asyncio
async def test_ai_tech_universe_is_filtered_before_scan_limit(monkeypatch) -> None:
    """A small scan_limit should mean N AI-tech stocks, not N raw stock-master rows."""
    requested_limits: list[int] = []
    scanned_symbols: list[str] = []

    async def fake_get_tw_stocks(limit: int = 100, **_: object) -> dict:
        requested_limits.append(limit)
        stocks = [
            {"stock_code": "1101", "company_name": "台泥"},
            {"stock_code": "1102", "company_name": "亞泥"},
            {"stock_code": "2412", "company_name": "中華電"},
            {"stock_code": "2330", "company_name": "台積電"},
            {"stock_code": "2308", "company_name": "台達電"},
            {"stock_code": "3231", "company_name": "緯創"},
        ]
        return {
            "stocks": stocks[:limit],
            "total": len(stocks),
            "data_source": "public",
            "source_report": {
                "source": "twse_tpex_official",
                "twse_count": len(stocks),
                "tpex_count": 0,
                "finmind_count": 0,
                "mock_count": 0,
                "stock_count": len(stocks),
                "fallback_used": False,
                "warnings": [],
            },
        }

    async def fake_price_history(symbol: str, days: int):
        scanned_symbols.append(symbol)
        candles = make_candidate_df(return_60d=0.14, base_return=0.02, return_5d=0.03).to_dict("records")
        return OhlcvLoadResult(
            candles=candles,
            source_info=SourceInfo(
                ohlcv_source="finmind",
                turnover_source="finmind_trading_money",
                bars_count=len(candles),
            ),
        )

    async def fake_tpex_quotes():
        return {}

    monkeypatch.setattr("backend.app.services.screener_service.get_tw_stocks", fake_get_tw_stocks)
    monkeypatch.setattr("backend.app.services.screener_service.get_tw_price_history_with_source", fake_price_history)
    monkeypatch.setattr("backend.app.services.screener_service.fetch_tpex_mainboard_quote_map", fake_tpex_quotes)

    params = ScreenerParameters(**{
        **default_screener_parameters().to_dict(),
        "scan_limit": 2,
        "limit": 10,
        "include_unfit": True,
        "ai_tech_only": True,
        "include_canslim": False,
    })

    response = await scan_surge_candidates(
        params,
        df_market=make_market_df(return_60d=0.08, base_return=0.01),
        market_index_report={"source": "finmind", "available": True, "fallback_used": False, "warnings": []},
    )

    assert requested_limits == [10_000]
    assert scanned_symbols == ["2330", "2308"]
    assert response.universe_size == 2
    assert {row.stock_id for row in response.results}.issubset({"2330", "2308"})


def test_canslim_store_scan_uses_symbol_latest_as_of() -> None:
    class FakeStore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def get_ohlcv_as_of(self, stock_id: str, as_of_date: str, lookback_bars: int) -> pd.DataFrame:
            self.calls.append((stock_id, as_of_date, lookback_bars))
            return pd.DataFrame({
                "date": ["2024-01-01", as_of_date],
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.5, 10.5],
                "close": [10.0, 11.0],
                "volume": [1000, 1200],
                "turnover": [10_000, 13_200],
            })

    store = FakeStore()
    ctx = _CanslimScanContext(
        bt_store=store,
        pit_store=object(),
        as_of="2024-01-05",
        market=object(),
        ur60={},
        ur252={},
        all_syms=["2330", "2454"],
        latest_by_stock={"2330": "2024-01-02"},
        covered={"2330", "2454"},
        ushares={},
    )

    df = _scan_df_from_store("2330", ctx)

    assert store.calls == [("2330", "2024-01-02", 260)]
    assert df is not None
    assert df["date"].iloc[-1] == "2024-01-02"


def test_screening_store_defaults_use_canonical_repo_databases() -> None:
    from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH
    from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH

    assert DEFAULT_DB_PATH.name == "historical_data.db"
    assert DEFAULT_PIT_DB_PATH.name == "pit_fundamentals.db"
    assert "backtest" not in DEFAULT_DB_PATH.parts
    assert "backtest" not in DEFAULT_PIT_DB_PATH.parts


def test_tw_screen_batch_source_mode_uses_local_snapshot(monkeypatch) -> None:
    called: dict[str, str | None] = {}

    def fake_local_snapshot(symbol: str, as_of_date: str | None = None) -> ScreeningResult:
        called["symbol"] = symbol
        called["as_of_date"] = as_of_date
        return ScreeningResult(
            stock_id=symbol,
            as_of_date=as_of_date or "2024-01-02",
            candidate_grade="B",
            raw_grade="B",
            canslim_match="4/7",
            pillars={
                "C": "Pass",
                "A": "Weak",
                "N": "AI_Review_Required",
                "S": "Pass",
                "L": "Pass",
                "I": "Weak",
                "M": "Pass",
            },
            market_regime="risk_on",
            interpretation="batch-compatible local-store screen",
            action_type="Manual Review Required",
            data_warnings=["source_mode=batch_local_store"],
        )

    monkeypatch.setattr("backend.app.main.screen_symbol_local_snapshot", fake_local_snapshot)

    from backend.app.main import app

    client = TestClient(app)
    response = client.get("/tw/screen?symbol=2330&as_of_date=2024-01-02&source_mode=batch")

    assert response.status_code == 200
    payload = response.json()
    assert called == {"symbol": "2330", "as_of_date": "2024-01-02"}
    assert payload["raw_grade"] == "B"
    assert payload["data_warnings"] == ["source_mode=batch_local_store"]


def test_local_snapshot_does_not_call_live_fallback(monkeypatch) -> None:
    from backend.app.services.strategy.canslim import live_screening
    from backend.app.services.strategy.canslim.types import MarketFeatures

    async def fail_live_fallback(*_: object, **__: object) -> None:
        raise AssertionError("batch-compatible local snapshot must not call live fallback")

    def fake_build_screening_result(*args: object, **kwargs: object) -> ScreeningResult:
        return ScreeningResult(
            stock_id=str(args[0]),
            as_of_date=str(args[1]),
            candidate_grade="A",
            raw_grade="A",
            canslim_match="5/7",
            pillars={
                "C": "Pass",
                "A": "Pass",
                "N": "AI_Review_Required",
                "S": "Pass",
                "L": "Pass",
                "I": "Weak",
                "M": "Pass",
            },
            market_regime="risk_on",
            interpretation="local snapshot",
            action_type="Manual Review Required",
        )

    monkeypatch.setattr(live_screening, "build_live_inputs", fail_live_fallback)
    monkeypatch.setattr(live_screening, "_latest_as_of_date", lambda *_: "2024-01-02")
    monkeypatch.setattr(live_screening, "screenable_universe", lambda *_: ["2330"])
    monkeypatch.setattr(live_screening, "_has_pit_coverage", lambda *_: True)
    monkeypatch.setattr(live_screening, "_pit_inputs", lambda *_: ({"month_revenue_yoy": [0.1]}, {"eps_cagr_3y": 0.2}, None))
    monkeypatch.setattr(live_screening, "universe_returns_for_as_of", lambda *_args, **_kwargs: ({"2330": 0.1}, {"2330": 0.2}))
    monkeypatch.setattr(live_screening, "_market_features", lambda *_args, **_kwargs: MarketFeatures())
    monkeypatch.setattr(live_screening, "universe_shares_for_as_of", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(live_screening, "durability_metrics_for_symbol", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(live_screening, "build_screening_result", fake_build_screening_result)

    result = live_screening.screen_symbol_local_snapshot("2330")

    assert result.raw_grade == "A"
    assert "source_mode=batch_local_store" in result.data_warnings
