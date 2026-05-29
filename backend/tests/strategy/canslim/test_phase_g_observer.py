from __future__ import annotations

from datetime import date, timedelta
import re

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.observer import observe
from backend.app.services.strategy.canslim.types import MarketFeatures


def _store(tmp_path, *, low_turnover: bool = False) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "observer.db")
    start = date(2024, 1, 1)
    rows = []
    for idx in range(260):
        close = 100.0 + idx * 0.12
        volume = 1200.0
        if idx == 259:
            volume = 3000.0
            close += 25.0
        turnover = 50_000_000.0 if not low_turnover else 100_000.0
        rows.append(
            {
                "stock_id": "2330",
                "date": (start + timedelta(days=idx)).isoformat(),
                "open": close - 0.2,
                "high": close + 0.4,
                "low": close - 0.4,
                "close": close,
                "volume": volume,
                "turnover": turnover,
            }
        )
    store.upsert_rows(rows)
    return store


def _market(**overrides) -> MarketFeatures:
    values = {
        "taiex_close": 20_000.0,
        "taiex_ma150": 19_000.0,
        "taiex_ma150_slope": 0.01,
        "tpex_close": 250.0,
        "tpex_ma150": 240.0,
        "tpex_ma150_slope": 0.01,
        "breadth_above_ma60_pct": 0.70,
        "sox_above_ma60": True,
        "nasdaq_above_ma60": True,
    }
    values.update(overrides)
    return MarketFeatures(**values)


def _fin_metrics(**overrides):
    values = {
        "eps_yoy": 0.30,  # fraction contract (+30%)
        "annual_eps": [10.0, 12.0, 16.0],
        "roe": 18.0,
        "op_margin_last4": [20.0, 21.0, 22.0, 23.0],
        "pe_ttm": 30.0,
    }
    values.update(overrides)
    return values


def _detail(**overrides):
    values = {
        "month_revenue_yoy": [0.18, 0.22, 0.28],
        "foreign_net_5": [1.0, 2.0, 30.0, 30.0, 30.0],
        "trust_net_5": [1.0, -1.0, 2.0, -1.0, 3.0],
        "dealer_net_5": [0.0, 0.0, 0.0, 0.0, 0.0],
    }
    values.update(overrides)
    return values


def _observe(tmp_path, **overrides):
    store = overrides.pop("store") if "store" in overrides else _store(tmp_path)
    return observe(
        "2330",
        "2024-09-16",
        store=store,
        market=overrides.pop("market", _market()),
        fin_metrics=overrides.pop("fin_metrics", _fin_metrics()),
        detail=overrides.pop("detail", _detail()),
        universe_returns_60d=overrides.pop("universe_returns_60d", {"1000": -0.1, "2330": 0.4, "1001": 0.1}),
        universe_returns_252d=overrides.pop("universe_returns_252d", {"1000": -0.1, "2330": 0.4, "1001": 0.1}),
        event_window_active=overrides.pop("event_window_active", False),
        eps_filing_date=overrides.pop("eps_filing_date", "2024-09-01"),
    )


def test_end_to_end_observe_returns_three_horizon_cards(tmp_path):
    cards = _observe(tmp_path)

    assert set(cards) == {"short_term", "swing_term", "long_term"}
    for card in cards.values():
        assert 0 <= card.scores["signal"] <= 100
        assert 0 <= card.scores["signal_raw"] <= 100
        assert card.scores["signal_achievable_max"] > 0
        assert 0 <= card.scores["risk"] <= 100
        assert 0 <= card.scores["confidence"] <= 100
        assert card.scores["grade"] in {"S", "A", "B", "C"}
        assert card.triggered_rule_ids
        assert card.invalidation_signals


def test_observation_strings_are_action_verb_free(tmp_path):
    cards = _observe(tmp_path)
    forbidden = ("買", "賣", "持有", "buy", "sell", "hold")
    strings = _collect_strings(cards)

    for text in strings:
        lowered = text.lower()
        assert all(word not in lowered for word in forbidden), text


def test_hard_block_liquidity_still_returns_cards_and_scores(tmp_path):
    cards = _observe(tmp_path, store=_store(tmp_path, low_turnover=True))
    short = cards["short_term"]

    assert short.scores["hard_blocked"] is True
    assert "R-6" in short.scores["blocking_rule_ids"]
    assert short.status == "watching"
    assert 0 <= short.scores["signal"] <= 100
    assert short.scores["grade"] in {"S", "A", "B", "C"}


def test_partial_match_still_surfaces_as_grade_card(tmp_path):
    cards = _observe(
        tmp_path,
        fin_metrics={"eps_yoy": 0.05, "annual_eps": [10.0, 10.0, 10.0], "roe": 5.0, "pe_ttm": 20.0},
        detail={"month_revenue_yoy": [0.01, 0.02, 0.03], "foreign_net_5": [-1, -1, -1], "trust_net_5": [-1, -1, -1]},
        universe_returns_60d={"2330": 0.1, "1000": 0.2},
        universe_returns_252d={"2330": 0.1, "1000": 0.2},
    )

    assert cards["short_term"].scores["grade"] in {"S", "A", "B", "C"}
    assert cards["short_term"].scores["signal"] > 0
    assert cards["short_term"].scores["signal_raw"] > 0
    assert cards["short_term"].scores["signal_achievable_max"] > 0
    assert cards["short_term"].status in {"neutral", "watching", "trigger_proximity", "invalidating"}


def test_conflict_strong_fundamentals_and_short_overheat_is_sideways(tmp_path):
    cards = _observe(tmp_path)

    assert "R-1" in cards["short_term"].triggered_rule_ids
    assert cards["short_term"].direction_hint == "sideways"


def test_conflict_hard_block_regime_points_down(tmp_path):
    cards = _observe(tmp_path, market=_market(taiex_close=18_000.0, taiex_ma150=19_000.0))

    assert "R-5" in cards["short_term"].triggered_rule_ids
    assert cards["short_term"].scores["hard_blocked"] is True
    assert cards["short_term"].direction_hint == "down"


def test_conflict_foreign_positive_and_trust_negative_is_unclear(tmp_path):
    cards = _observe(
        tmp_path,
        detail=_detail(trust_net_5=[1.0, 2.0, -1.0, -2.0, -3.0]),
    )

    assert "I-1" in cards["swing_term"].triggered_rule_ids
    assert "I-2" not in cards["swing_term"].triggered_rule_ids
    assert cards["swing_term"].direction_hint == "unclear"


def test_rule_id_attribution_in_evidence_reasons(tmp_path):
    cards = _observe(tmp_path)
    rule_id = re.compile(r"\b(?:G|T|SD|I|M|R)-\d\b")

    for card in cards.values():
        for reason in card.evidence_based_reasons:
            assert rule_id.search(reason), reason


def _collect_strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            out.extend(_collect_strings(str(key)))
            out.extend(_collect_strings(item))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            out.extend(_collect_strings(item))
        return out
    if hasattr(value, "model_dump"):
        return _collect_strings(value.model_dump())
    return []
