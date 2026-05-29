from datetime import date, timedelta

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.strategy.canslim.regime import build_market_features
from backend.app.services.strategy.canslim.rules_market import evaluate_m1
from backend.app.services.strategy.canslim.params import load_params


def _index_rows(start: str = "2024-01-01", n: int = 180, *, start_close: float = 100.0, step: float = 1.0):
    start_date = date.fromisoformat(start)
    rows = []
    close = start_close
    for idx in range(n):
        close += step
        rows.append(
            {
                "date": (start_date + timedelta(days=idx)).isoformat(),
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000 + idx,
            }
        )
    return rows


def _store_with_universe(tmp_path, *, rising: bool = True) -> HistoricalDataStore:
    store = HistoricalDataStore(tmp_path / "regime.db")
    rows = []
    start = date(2024, 1, 1)
    for code, offset in {"1001": 0, "1002": 100, "1003": 200}.items():
        for idx in range(80):
            close = 100 + idx + offset if rising or code != "1003" else 300 - idx
            rows.append(
                {
                    "stock_id": code,
                    "date": (start + timedelta(days=idx)).isoformat(),
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1000,
                    "turnover": close * 1000,
                }
            )
    store.upsert_rows(rows)
    return store


def _bundle(**overrides):
    bundle = {
        "taiex": _index_rows(step=1.0),
        "tpex": _index_rows(step=0.5),
        "sox": _index_rows(n=80, step=1.0),
        "nasdaq": _index_rows(n=80, step=1.0),
    }
    bundle.update(overrides)
    return bundle


def test_build_market_features_uptrend_flows_into_m1(tmp_path):
    params = load_params()
    store = _store_with_universe(tmp_path)
    features = build_market_features(
        "2024-06-28",
        index_bundle=_bundle(),
        store=store,
        universe=["1001", "1002", "1003"],
    )

    assert features.taiex_close is not None
    assert features.taiex_ma150 is not None
    assert features.taiex_ma150_slope is not None
    assert features.taiex_ma150_slope > 0
    assert features.breadth_above_ma60_pct == 1.0
    assert features.sox_above_ma60 is True
    assert features.nasdaq_above_ma60 is True
    assert evaluate_m1(features, params).triggered is True


def test_build_market_features_downtrend_has_negative_slope(tmp_path):
    store = _store_with_universe(tmp_path)
    features = build_market_features(
        "2024-06-28",
        index_bundle=_bundle(taiex=_index_rows(start_close=300.0, step=-1.0)),
        store=store,
        universe=["1001", "1002", "1003"],
    )

    assert features.taiex_close is not None
    assert features.taiex_ma150_slope is not None
    assert features.taiex_ma150_slope < 0
    assert evaluate_m1(features, load_params()).triggered is False


def test_distribution_day_count_detects_multiple_distribution_days(tmp_path):
    rows = _index_rows()
    for idx in range(len(rows) - 10, len(rows), 2):
        rows[idx]["close"] = rows[idx - 1]["close"] * 0.995
        rows[idx]["volume"] = rows[idx - 1]["volume"] + 500
    features = build_market_features("2024-06-28", index_bundle=_bundle(taiex=rows), store=_store_with_universe(tmp_path))

    assert features.distribution_day_count is not None
    assert features.distribution_day_count >= 5


def test_follow_through_day_detects_rally_on_rising_volume(tmp_path):
    rows = _index_rows(start_close=100.0, step=-0.2)
    rows[-6]["close"] = 80.0
    rows[-5]["close"] = 81.5
    rows[-5]["volume"] = rows[-6]["volume"] + 1000
    rows[-4]["close"] = 82.0
    rows[-3]["close"] = 82.4
    rows[-2]["close"] = 82.8
    rows[-1]["close"] = 83.2
    features = build_market_features("2024-06-28", index_bundle=_bundle(taiex=rows), store=_store_with_universe(tmp_path))

    assert features.follow_through_day is True


def test_missing_index_path_leaves_fields_none_with_warnings(tmp_path):
    features = build_market_features(
        "2024-06-28",
        index_bundle={},
        store=_store_with_universe(tmp_path),
        universe=["1001", "1002", "1003"],
    )

    assert features.taiex_close is None
    assert features.tpex_close is None
    assert features.sox_above_ma60 is None
    assert "taiex_close" in features.missing_fields
    assert features.data_warnings


def test_ex_tsmc_proxy_unavailable_is_warning_not_estimate(tmp_path):
    features = build_market_features(
        "2024-06-28",
        index_bundle=_bundle(),
        store=_store_with_universe(tmp_path),
        universe=["1001", "1002", "1003"],
    )

    assert features.taiex_ex_tsmc_close is None
    assert "taiex_ex_tsmc_close" in features.missing_fields
    assert "ex-TSMC proxy unavailable; using full TAIEX" in features.data_warnings
