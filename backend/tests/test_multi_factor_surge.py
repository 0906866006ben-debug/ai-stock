from __future__ import annotations

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from backend.screeners.multi_factor_surge.config import CONFIG
from backend.screeners.multi_factor_surge.feature_builder import candles_to_dataframe, canonicalize_ohlcv
from backend.screeners.multi_factor_surge.liquidity_signals import score_liquidity
from backend.screeners.multi_factor_surge.risk_signals import score_risk
from backend.screeners.multi_factor_surge.service import MultiFactorParameters, scan_multi_factor_surge
from backend.screeners.multi_factor_surge.sustain_signals import score_sustain
from backend.screeners.multi_factor_surge.technical_signals import (
    bollinger_state,
    kd_high_saturation_days,
    macd_golden_cross_above_zero,
    obv_above_ma10,
)


def make_multi_factor_df(*, rows: int = 220, low_volume: bool = False, upper_shadow: bool = False) -> pd.DataFrame:
    closes = []
    volumes = []
    price = 80.0
    for idx in range(rows):
        if idx < rows - 45:
            price *= 1.001
        elif idx < rows - 5:
            price *= 1 + ((idx % 3) - 1) * 0.0005
        else:
            price *= 1.035
        closes.append(round(price, 2))
        volumes.append(80_000 if low_volume else (900_000 if idx < rows - 5 else 2_200_000))

    candles = []
    for idx, (close, volume) in enumerate(zip(closes, volumes)):
        open_price = close * 0.99
        high = close * 1.01
        low = close * 0.985
        if upper_shadow and idx == rows - 1:
            open_price = close * 0.99
            high = close * 1.18
            low = close * 0.98
            volume = 4_000_000
        candles.append({
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
    return canonicalize_ohlcv(pd.DataFrame(candles))


def make_macd_cross_df() -> pd.DataFrame:
    prices = [100 + idx * 0.2 for idx in range(50)]
    start = prices[-1]
    prices += [start * (1 - 0.02 * idx / 5) for idx in range(1, 6)]
    prices.append(prices[-1] * 1.08)
    return canonicalize_ohlcv(pd.DataFrame([
        {"open": p * 0.99, "high": p * 1.01, "low": p * 0.98, "close": p, "volume": 1_000_000}
        for p in prices
    ]))


async def high_fundamentals(_stock_id: str) -> dict:
    return {
        "eps_yoy": 0.55,
        "roe": 0.24,
        "revenue_2m_avg_vs_12m_max": True,
        "eps_qoq_streak": 3,
        "source": "fixture",
        "is_mock": False,
    }


async def missing_fundamentals(_stock_id: str) -> dict | None:
    return None


@pytest.mark.asyncio
async def test_resonance_case_is_multi_factor_candidate(monkeypatch) -> None:
    df = make_multi_factor_df()

    async def fake_history(symbol: str, days: int):
        return df.to_dict("records"), False

    monkeypatch.setattr("backend.screeners.multi_factor_surge.feature_builder.get_tw_price_history", fake_history)
    response = await scan_multi_factor_surge(
        MultiFactorParameters(limit=10, include_unfit=True),
        universe=[{"stock_code": "2330", "company_name": "台積電", "market_type": "上市"}],
        fundamentals_provider=high_fundamentals,
    )

    assert response.results[0].candidate_type == "多因子共振候選"
    assert response.results[0].surge_score >= 75


@pytest.mark.asyncio
async def test_technical_only_missing_fundamentals_is_initial_candidate(monkeypatch) -> None:
    df = make_multi_factor_df()

    async def fake_history(symbol: str, days: int):
        return df.to_dict("records"), False

    monkeypatch.setattr("backend.screeners.multi_factor_surge.feature_builder.get_tw_price_history", fake_history)
    response = await scan_multi_factor_surge(
        MultiFactorParameters(limit=10, include_unfit=True),
        universe=[{"stock_code": "2454", "company_name": "聯發科", "market_type": "上市"}],
        fundamentals_provider=missing_fundamentals,
    )

    row = response.results[0]
    assert row.candidate_type == "技術初動候選"
    assert row.confidence_score < 100
    assert "eps_unavailable" in row.missing_data


@pytest.mark.asyncio
async def test_chip_missing_is_neutral_and_flagged(monkeypatch) -> None:
    df = make_multi_factor_df()

    async def fake_history(symbol: str, days: int):
        return df.to_dict("records"), False

    monkeypatch.setattr("backend.screeners.multi_factor_surge.feature_builder.get_tw_price_history", fake_history)
    response = await scan_multi_factor_surge(
        MultiFactorParameters(limit=10, include_unfit=True),
        universe=[{"stock_code": "2317", "company_name": "鴻海", "market_type": "上市"}],
        fundamentals_provider=high_fundamentals,
    )

    row = response.results[0]
    assert row.scores.chip_score == 50
    assert "chip_data_unavailable" in row.missing_data
    assert row.candidate_type != "籌碼推升候選"


@pytest.mark.asyncio
async def test_liquidity_below_threshold_is_unfit_and_counted(monkeypatch) -> None:
    df = make_multi_factor_df(low_volume=True)

    async def fake_history(symbol: str, days: int):
        return df.to_dict("records"), False

    monkeypatch.setattr("backend.screeners.multi_factor_surge.feature_builder.get_tw_price_history", fake_history)
    response = await scan_multi_factor_surge(
        MultiFactorParameters(limit=10, include_unfit=True, debug=True),
        universe=[{"stock_code": "1111", "company_name": "低量股", "market_type": "上市"}],
        fundamentals_provider=high_fundamentals,
    )

    assert response.results[0].candidate_type == "不符合"
    assert response.funnel_report is not None
    assert response.funnel_report["stages"]["liquidity_pass_count"] == 0


def test_kd_high_saturation_detected() -> None:
    assert kd_high_saturation_days(make_multi_factor_df()) >= 3


def test_bb_squeeze_expand_detected() -> None:
    state, squeeze_expand, breakout = bollinger_state(make_multi_factor_df())
    assert state == "squeeze_then_expand"
    assert squeeze_expand
    assert breakout


def test_macd_golden_cross_above_zero_detected() -> None:
    assert macd_golden_cross_above_zero(make_macd_cross_df())


def test_obv_cross_above_ma10_detected() -> None:
    prices = [100 - idx * 0.2 for idx in range(20)] + [96 + idx * 2.5 for idx in range(1, 3)]
    volumes = [1_000_000] * 20 + [3_000_000, 5_000_000]
    df = canonicalize_ohlcv(pd.DataFrame([
        {"open": p * 0.99, "high": p * 1.01, "low": p * 0.98, "close": p, "volume": v}
        for p, v in zip(prices, volumes)
    ]))
    above, crossed = obv_above_ma10(df)
    assert above
    assert crossed


def test_sustain_new_high_fallback_when_history_lt_200() -> None:
    module, metrics = score_sustain(make_multi_factor_df(rows=90))
    assert metrics["new_high_count_in_5d"] >= 3
    assert "history_lt_200" in module.data_quality_flags


def test_long_upper_shadow_high_volume_is_hot_observation(monkeypatch) -> None:
    df = make_multi_factor_df(upper_shadow=True)
    technical_metrics = {"kd_k": 95}
    module, _metrics = score_risk(df, technical_metrics)
    assert "long_upper_shadow_on_high_volume" in module.risk_flags


@pytest.mark.asyncio
async def test_debug_true_returns_required_funnel_keys(monkeypatch) -> None:
    df = make_multi_factor_df()

    async def fake_history(symbol: str, days: int):
        return df.to_dict("records"), False

    monkeypatch.setattr("backend.screeners.multi_factor_surge.feature_builder.get_tw_price_history", fake_history)
    response = await scan_multi_factor_surge(
        MultiFactorParameters(limit=10, include_unfit=True, debug=True),
        universe=[{"stock_code": "2330", "company_name": "台積電", "market_type": "上市"}],
        fundamentals_provider=high_fundamentals,
    )

    assert response.funnel_report is not None
    stages = response.funnel_report["stages"]
    for key in (
        "universe_size",
        "common_stock_filter_count",
        "ohlcv_sufficient_count",
        "liquidity_pass_count",
        "fundamental_data_available_count",
        "fundamental_score_high_count",
        "chip_data_available_count",
        "chip_score_high_count",
        "technical_score_high_count",
        "sustain_score_high_count",
        "risk_filter_pass_count",
        "final_matched_count",
        "error_count",
    ):
        assert key in stages


def test_volume_unit_contract_500_lots_equals_500000_shares() -> None:
    df = canonicalize_ohlcv(pd.DataFrame([
        {"open": 10, "high": 11, "low": 9, "close": 10, "volume": 500_000}
        for _ in range(20)
    ]))
    module, metrics = score_liquidity(df)
    assert CONFIG["liquidity"]["min_avg_volume_5d_lots"] * CONFIG["liquidity"]["lots_to_shares"] == 500_000
    assert metrics["avg_volume_5d_lots"] == 500
    assert metrics["liquidity_pass"]
    assert module.score >= 60


def test_api_route_registered(monkeypatch) -> None:
    from backend.app.main import app

    async def fake_scan(params):
        from backend.screeners.multi_factor_surge.schemas import MultiFactorResponse

        return MultiFactorResponse(
            generated_at="2026-05-15T00:00:00+08:00",
            universe_size=1,
            matched_count=0,
            parameters=params.to_dict(),
            data_warnings=[],
            results=[],
        )

    monkeypatch.setattr("backend.screeners.multi_factor_surge.api.scan_multi_factor_surge", fake_scan)
    client = TestClient(app)
    response = client.get("/screeners/multi-factor-surge?debug=true")
    assert response.status_code == 200
    assert response.json()["strategy"] == "Taiwan Multi-Factor Surge Screener"
