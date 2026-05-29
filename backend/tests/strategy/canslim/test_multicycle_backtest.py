from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from backend.app.services.strategy.canslim import multicycle_backtest as mb
from backend.app.services.strategy.canslim.params import load_params


class FakeStore:
    def __init__(self, dates: list[str] | None = None) -> None:
        self.dates = dates or ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]

    def get_all_trading_dates(self, start_date: str, end_date: str) -> list[str]:
        return [date for date in self.dates if start_date <= date <= end_date]

    def get_ohlcv_as_of(self, stock_id: str, as_of_date: str, lookback_bars: int) -> pd.DataFrame:
        dates = pd.date_range("2023-01-01", periods=max(lookback_bars, 80), freq="D").strftime("%Y-%m-%d")
        return pd.DataFrame(
            {
                "date": list(dates),
                "open": [10.0] * len(dates),
                "high": [11.0] * len(dates),
                "low": [9.5] * len(dates),
                "close": [10.5] * len(dates),
                "volume": [1000] * len(dates),
                "turnover": [50_000_000.0] * len(dates),
            }
        )


def test_cadence_grid_uses_every_nth_trading_date():
    store = FakeStore(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"])

    assert mb.cadence_grid(store, "2024-01-02", "2024-01-09", cadence_days=2) == [
        "2024-01-02",
        "2024-01-04",
        "2024-01-08",
    ]


def test_per_date_universe_pruning_drives_evaluated_symbols(tmp_path: Path, monkeypatch):
    store = FakeStore(["2024-01-02", "2024-01-09"])
    seen: list[tuple[str, str]] = []
    captured_signals: dict[str, pd.DataFrame] = {}

    def fake_universe(as_of_date, store, **kwargs):
        return ["AAA"] if as_of_date == "2024-01-02" else ["BBB"]

    def fake_observe(stock_id, as_of_date, **kwargs):
        seen.append((stock_id, as_of_date))
        card = SimpleNamespace(
            scores={
                "grade": "B",
                "hard_blocked": False,
                "signal": 60,
                "confidence": 50,
                "risk": 10,
                "signal_raw": 60,
                "signal_achievable_max": 80,
            },
            triggered_rule_ids=["G-1"],
        )
        return {"swing_term": card}

    def fake_simulate_trades(*, signals_df, data_store, rules, run_id, db_path):
        captured_signals[run_id] = signals_df.copy()

    def fake_load_trades(db_path, run_id):
        signals = captured_signals[run_id]
        return pd.DataFrame(
            [
                {
                    "stock_id": row.stock_id,
                    "signal_date": row.signal_date,
                    "entry_date": row.signal_date,
                    "entry_status": "filled",
                    "net_return_pct": 0.02,
                    "hold_days": 5,
                }
                for row in signals.itertuples()
            ]
        )

    monkeypatch.setattr(mb, "get_universe_as_of", fake_universe)
    monkeypatch.setattr(mb, "build_pit_inputs", lambda *args, **kwargs: ({}, {}, None))
    monkeypatch.setattr(mb, "observe", fake_observe)
    monkeypatch.setattr(mb, "_market_features_for_entry", lambda *args, **kwargs: object())
    monkeypatch.setattr(mb, "_universe_returns_as_of", lambda *args, **kwargs: {})
    monkeypatch.setattr(mb, "_regime_entry_gate_blocks", lambda *args, **kwargs: False)
    monkeypatch.setattr(mb, "simulate_trades", fake_simulate_trades)
    monkeypatch.setattr(mb, "load_trades", fake_load_trades)
    monkeypatch.setattr(mb, "regime_bucket_at_entry", lambda *args, **kwargs: "risk_on")
    monkeypatch.setattr(
        mb,
        "compute_extension_metrics",
        lambda *args, **kwargs: {
            "close_to_ma20": 1.02,
            "pct_from_52w_high": -0.05,
            "return_20d": 0.01,
            "return_60d": 0.03,
            "days_since_breakout": 2,
        },
    )

    tagged, diagnostics = mb._run_year(
        run_id="test_2024",
        year=2024,
        start_date="2024-01-02",
        end_date="2024-01-09",
        cadence_days=1,
        candidate_symbols=["AAA", "BBB", "CCC"],
        data_store=store,
        pit_store=object(),
        db_path=tmp_path / "trades.db",
        turnover_floor=None,
    )

    assert seen == [("AAA", "2024-01-02"), ("BBB", "2024-01-09")]
    assert tagged["stock_id"].tolist() == ["AAA", "BBB"]
    assert diagnostics["evaluated"] == 2


def test_tagged_trade_output_schema_matches_attribution_tools(monkeypatch):
    signals = pd.DataFrame(
        [
            {
                "stock_id": "AAA",
                "signal_date": "2024-01-02",
                "canslim_grade": "A",
                "canslim_horizon": "swing_term",
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "stock_id": "AAA",
                "signal_date": "2024-01-02",
                "entry_date": "2024-01-03",
                "entry_status": "filled",
                "net_return_pct": 0.04,
                "hold_days": 7,
            }
        ]
    )
    monkeypatch.setattr(mb, "regime_bucket_at_entry", lambda *args, **kwargs: "risk_on")
    monkeypatch.setattr(
        mb,
        "compute_extension_metrics",
        lambda *args, **kwargs: {
            "close_to_ma20": 1.01,
            "pct_from_52w_high": -0.08,
            "return_20d": 0.02,
            "return_60d": 0.05,
            "days_since_breakout": 1,
        },
    )

    tagged = mb.tag_multicycle_trades(
        segment="year_2024",
        horizon="swing_term",
        signals=signals,
        trades=trades,
        data_store=FakeStore(),
        stock_universe=["AAA"],
    )

    assert list(tagged.columns) == mb.TAGGED_TRADE_COLUMNS
    assert {"window", "segment", "horizon", "stock_id", "entry_date", "grade", "regime_bucket_at_entry", "net_return_pct", "holding_days"} <= set(tagged.columns)
    assert tagged.loc[0, "window"] == "year_2024"
    assert tagged.loc[0, "grade"] == "A"


def test_resume_skips_completed_year_and_does_not_mutate_params(tmp_path: Path, monkeypatch):
    original_params = load_params()
    out_dir = tmp_path / "out"
    year_dir = out_dir / "years"
    year_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "window": "year_2024",
                "segment": "year_2024",
                "named_cycle": "other",
                "horizon": "swing_term",
                "stock_id": "AAA",
                "signal_date": "2024-01-02",
                "entry_date": "2024-01-03",
                "grade": "B",
                "regime_bucket_at_entry": "risk_on",
                "net_return_pct": 0.01,
                "holding_days": 5,
            }
        ]
    ).to_csv(year_dir / "2024.csv", index=False)

    monkeypatch.setattr(mb, "CachedHistoricalDataStore", lambda *args, **kwargs: FakeStore())
    monkeypatch.setattr(mb, "CachedPitFundamentalsStore", lambda *args, **kwargs: object())

    def fail_run_year(**kwargs):
        raise AssertionError("completed year should be skipped")

    monkeypatch.setattr(mb, "_run_year", fail_run_year)

    report = mb.run_multicycle_backtest(
        run_id="resume_test",
        ohlcv_db_path=tmp_path / "ohlcv.db",
        pit_db_path=tmp_path / "pit.db",
        start_date="2024-01-01",
        end_date="2024-12-31",
        cadence_days=5,
        output_dir=out_dir,
        candidate_symbols=["AAA"],
        resume=True,
    )

    assert report.years == [{"year": 2024, "status": "skipped", "trades": 1}]
    assert pd.read_csv(report.tagged_trades_csv)["stock_id"].tolist() == ["AAA"]
    assert load_params() == original_params
