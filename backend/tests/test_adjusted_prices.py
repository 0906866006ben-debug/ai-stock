from __future__ import annotations

from backend.app.services.tw_adjusted_prices import adjust_closes, event_ratios


def test_event_ratios_skips_bad_rows_and_sorts():
    rows = [
        {"date": "2025-07-01", "before_price": 100.0, "after_price": 95.0},
        {"date": "2024-07-01", "before_price": 50.0, "after_price": 48.0},
        {"date": "2023-07-01", "before_price": 0, "after_price": 0},  # skipped
    ]
    ratios = event_ratios(rows)
    assert [d for d, _ in ratios] == ["2024-07-01", "2025-07-01"]
    assert abs(ratios[1][1] - 0.95) < 1e-9


def test_adjust_closes_back_adjusts_history_before_ex_date():
    prices = [
        {"date": "2025-06-30", "close": 100.0},  # before the ex-date -> scaled
        {"date": "2025-07-01", "close": 95.0},   # on/after -> unchanged
        {"date": "2025-07-02", "close": 96.0},
    ]
    dividends = [{"date": "2025-07-01", "before_price": 100.0, "after_price": 95.0}]
    out = {r["date"]: r["adj_close"] for r in adjust_closes(prices, dividends)}
    assert out["2025-06-30"] == 95.0   # 100 * 0.95
    assert out["2025-07-02"] == 96.0   # no future ex-date -> factor 1.0


def test_adjust_closes_compounds_multiple_ex_dates():
    prices = [{"date": "2024-01-01", "close": 100.0}]
    dividends = [
        {"date": "2024-07-01", "before_price": 100.0, "after_price": 90.0},  # 0.9
        {"date": "2025-07-01", "before_price": 100.0, "after_price": 95.0},  # 0.95
    ]
    out = adjust_closes(prices, dividends)[0]
    assert abs(out["adj_close"] - 100.0 * 0.9 * 0.95) < 1e-6


def test_adjust_closes_no_dividends_is_identity():
    prices = [{"date": "2025-01-01", "close": 123.0}]
    assert adjust_closes(prices, [])[0]["adj_close"] == 123.0


def test_dividend_window_factor_uses_cache_only():
    from backend.app.services import file_cache
    from backend.app.services import tw_adjusted_prices as ap
    file_cache.save("dividend_result", "WINX", [
        {"date": "2025-07-01", "before_price": 100.0, "after_price": 95.0},
        {"date": "2026-07-01", "before_price": 100.0, "after_price": 90.0},
    ])
    assert abs(ap.dividend_window_factor("WINX", "2025-01-01", "2025-12-31") - 0.95) < 1e-9
    assert ap.dividend_window_factor("WINX", "2027-01-01", "2027-12-31") == 1.0
    assert ap.dividend_window_factor("NO_CACHE_SYM", "2020-01-01", "2026-01-01") == 1.0


def test_dividend_adjusted_return_lifts_raw_when_ex_date_in_window():
    import pandas as pd
    from backend.app.services import file_cache
    from backend.app.services.strategy.canslim import live_screening as ls
    file_cache.save("dividend_result", "ADJT", [{"date": "2025-09-01", "before_price": 100.0, "after_price": 95.0}])
    bars = pd.DataFrame({"date": ["2025-08-01", "2025-10-01"], "close": [100.0, 99.0]})
    raw = 99.0 / 100.0 - 1.0  # -1% raw (depressed by the ex-dividend gap)
    adj = ls._dividend_adjusted_return("ADJT", bars, raw)
    assert adj > raw
    assert abs(adj - (0.99 / 0.95 - 1.0)) < 1e-9


def test_compute_universe_returns_unchanged_when_flag_off(monkeypatch):
    monkeypatch.delenv("AISTOCK_ADJUSTED_RS", raising=False)
    from backend.app.services.strategy.canslim import live_screening as ls
    assert ls._adjusted_rs_enabled() is False
