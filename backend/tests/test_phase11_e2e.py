from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.services.backtest.historical_data_store import HistoricalDataStore
from backend.app.services.backtest.signal_replay import ReplayConfig, load_signals, replay_signals
from backend.app.services.backtest.trade_simulator import EntryStatus, TradeRules, load_trades, simulate_trades


class _FlatStore:
    def get_ohlcv(self, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame([
            {"date": "2024-01-02", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1_000_000},
            {"date": "2024-01-03", "open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0, "volume": 1_000_000},
        ])


def test_min_entry_tier_filter_skips_low_tier(tmp_path: Path):
    signals = pd.DataFrame([
        {"run_id": "min_tier", "signal_date": "2024-01-01", "stock_id": "AAA", "candidate_type": "起漲前觀察", "close_price": 100.0, "entry_tier": 1},
        {"run_id": "min_tier", "signal_date": "2024-01-01", "stock_id": "BBB", "candidate_type": "起漲前觀察", "close_price": 100.0, "entry_tier": 2},
    ])
    rules = TradeRules(
        measured_move_method="fixed",
        target_pct=0.10,
        commission_pct=0.0,
        transaction_tax_pct=0.0,
        slippage_pct=0.0,
        min_entry_tier=2,
    )

    simulate_trades(signals_df=signals, data_store=_FlatStore(), rules=rules, run_id="min_tier", db_path=tmp_path / "min_tier.db")
    trades = load_trades(tmp_path / "min_tier.db", "min_tier")

    assert set(trades["entry_status"]) == {EntryStatus.SKIPPED_TIER_LOW.value, EntryStatus.FILLED.value}
    skipped = trades[trades["entry_status"] == EntryStatus.SKIPPED_TIER_LOW.value].iloc[0]
    filled = trades[trades["entry_status"] == EntryStatus.FILLED.value].iloc[0]
    assert int(skipped["entry_tier"]) == 1
    assert int(filled["entry_tier"]) == 2


def _tier_candidate_rows(stock_id: str) -> list[dict]:
    base_date = pd.Timestamp("2024-01-01")
    rows = []
    close_60d = 100.0
    close_20d = 108.0
    close_today = 110.0
    closes = [96.0] * 30
    base = [
        close_60d + (close_20d - close_60d) * (idx / 40) + ((idx % 5) - 2) * 0.25
        for idx in range(41)
    ]
    base[0] = close_60d
    base[-1] = close_20d
    recent_to_5d = [108.0 + (109.0 - 108.0) * min(idx / 14, 1) for idx in range(1, 15)]
    final_5 = [109.0 + (close_today - 109.0) * (idx / 4) for idx in range(5)]
    closes = (closes + base + recent_to_5d + final_5)[:90]

    volumes = [1_000_000] * 30
    volumes += [1_000_000] * 20
    volumes += [700_000] * 21
    volumes += [900_000] * 14
    volumes += [2_000_000] * 5
    volumes = volumes[:90]

    for i, (close, volume) in enumerate(zip(closes, volumes)):
        date = (base_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append({
            "stock_id": stock_id,
            "date": date,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
            "turnover": close * volume * 2.0,
        })
    return rows


def test_phase11_signal_replay_persists_entry_tier(tmp_path: Path):
    db_path = tmp_path / "phase11.db"
    store = HistoricalDataStore(db_path)
    rows = _tier_candidate_rows("TIER")
    store.upsert_rows(rows)
    last_date = rows[-1]["date"]

    replay_signals(
        ReplayConfig(
            run_id="phase11",
            start_date=last_date,
            end_date=last_date,
            stock_universe=["TIER"],
            target_candidate_types=["起漲前觀察"],
        ),
        data_store=store,
        db_path=db_path,
    )
    signals = load_signals(db_path, "phase11")

    assert "entry_tier" in signals.columns
    assert not signals.empty
    assert int(signals["entry_tier"].max()) >= 1
