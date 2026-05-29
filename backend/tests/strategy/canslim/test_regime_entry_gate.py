from __future__ import annotations

from pathlib import Path

from backend.app.services.strategy.canslim.observer import observe
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.rules_market import is_regime_risk_off, regime_severity
from backend.app.services.strategy.canslim.rules_risk import evaluate_r5
from backend.app.services.strategy.canslim.types import MarketFeatures
from backend.app.services.strategy.canslim.walk_forward import _regime_entry_gate_blocks, run_real_data_walk_forward
from backend.tests.strategy.canslim.test_phase_c6_risk import _features
from backend.tests.strategy.canslim.test_phase_j2_pit_inputs import AS_OF, _market, _ohlcv_store, _pit_store


def test_is_regime_risk_off_true_false_and_unknown():
    params = load_params()

    assert is_regime_risk_off(_risk_off_market(), params) is True
    assert regime_severity(_risk_off_market(), params) == "severe"
    assert regime_severity(_moderate_risk_off_market(), params) == "risk_off"
    assert is_regime_risk_off(_market(), params) is False
    assert regime_severity(_market(), params) == "risk_on"
    assert is_regime_risk_off(MarketFeatures(taiex_close=None), params) is None
    assert regime_severity(MarketFeatures(taiex_close=None), params) is None


def test_r5_regression_after_helper_refactor():
    params = load_params()

    short = evaluate_r5(_features(), _risk_off_market(), params, "short_term")
    swing = evaluate_r5(_features(), _risk_off_market(), params, "swing_term")
    unknown = evaluate_r5(_features(), MarketFeatures(taiex_close=None), params, "short_term")

    assert short.triggered is True
    assert short.hard_block is True
    assert swing.triggered is True
    assert swing.hard_block is False
    assert swing.risk_delta == params["risk"]["rules"]["R-5"]["effects"]["swing_long_risk_delta"]
    assert unknown.triggered is False
    assert unknown.hard_block is False
    assert unknown.data_warning is not None


def test_entry_gate_blocks_swing_risk_off_and_allows_risk_on_unknown_and_off():
    params = load_params()

    assert _regime_entry_gate_blocks("swing_term", "B", _moderate_risk_off_market(), params, enabled=True) is True
    assert _regime_entry_gate_blocks("swing_term", "A", _moderate_risk_off_market(), params, enabled=True) is False
    assert _regime_entry_gate_blocks("swing_term", "S", _risk_off_market(), params, enabled=True) is False
    assert _regime_entry_gate_blocks("swing_term", "A", _risk_off_market(), params, enabled=True) is True
    assert _regime_entry_gate_blocks("swing_term", "B", _market(), params, enabled=True) is False
    assert _regime_entry_gate_blocks("swing_term", "B", MarketFeatures(), params, enabled=True) is False
    assert _regime_entry_gate_blocks("swing_term", "B", _risk_off_market(), params, enabled=False) is False
    assert _regime_entry_gate_blocks("short_term", "B", _risk_off_market(), params, enabled=True) is False


def test_real_walk_forward_entry_gate_removes_b_grade_without_hiding_cards(tmp_path: Path):
    ohlcv = _ohlcv_store(tmp_path)
    pit = _pit_store(tmp_path)

    risk_on_cards = _cards(tmp_path, _market())
    risk_off_cards = _cards(tmp_path, _risk_off_market())
    assert risk_on_cards["swing_term"].scores["grade"] in {"S", "A", "B", "C"}
    assert risk_off_cards["swing_term"].scores["grade"] in {"S", "A", "B", "C"}
    assert risk_off_cards["swing_term"].scores["risk"] >= risk_on_cards["swing_term"].scores["risk"]

    report = run_real_data_walk_forward(
        run_id="regime_gate_risk_off",
        ohlcv_db_path=ohlcv.db_path,
        pit_db_path=pit.db_path,
        stock_universe=["2330"],
        windows=[(AS_OF, AS_OF, AS_OF, AS_OF)],
        params={
            "backtest.canslim.min_entry_grade": "B",
            "backtest.canslim.max_hold_days": 30,
            "scoring.grades.A_signal_min": 95,
            "scoring.grades.B_signal_min": 1,
        },
        output_dir=tmp_path / "artifacts",
        min_trades=1,
        market=_risk_off_market(),
    )

    window = report.windows[0]
    assert window.regime_gate_removed >= 1
    assert window.regime_gate_diagnostics["severe"]["B"]["removed"] >= 1
    assert window.grade_distribution == {}
    assert window.oos_metrics["n_trades"] == 0


def test_real_walk_forward_unknown_regime_fails_open(tmp_path: Path):
    ohlcv = _ohlcv_store(tmp_path)
    pit = _pit_store(tmp_path)

    report = run_real_data_walk_forward(
        run_id="regime_gate_unknown",
        ohlcv_db_path=ohlcv.db_path,
        pit_db_path=pit.db_path,
        stock_universe=["2330"],
        windows=[(AS_OF, AS_OF, AS_OF, AS_OF)],
        params={
            "backtest.canslim.min_entry_grade": "B",
            "backtest.canslim.max_hold_days": 30,
            "scoring.grades.A_signal_min": 55,
            "scoring.grades.B_signal_min": 35,
        },
        output_dir=tmp_path / "artifacts",
        min_trades=1,
        market=MarketFeatures(),
    )

    window = report.windows[0]
    assert window.regime_gate_removed == 0
    assert window.grade_distribution
    assert window.oos_metrics["n_trades"] >= 1


def _risk_off_market() -> MarketFeatures:
    return MarketFeatures(
        taiex_close=18_000,
        taiex_ma150=19_000,
        taiex_ma150_slope=-0.01,
        tpex_close=230,
        tpex_ma150=240,
        tpex_ma150_slope=-0.01,
        breadth_above_ma60_pct=0.20,
        sox_above_ma60=True,
        nasdaq_above_ma60=True,
    )


def _moderate_risk_off_market() -> MarketFeatures:
    return MarketFeatures(
        taiex_close=18_000,
        taiex_ma150=19_000,
        taiex_ma150_slope=-0.01,
        tpex_close=250,
        tpex_ma150=240,
        tpex_ma150_slope=0.01,
        breadth_above_ma60_pct=0.65,
        sox_above_ma60=True,
        nasdaq_above_ma60=True,
    )


def _cards(tmp_path: Path, market: MarketFeatures):
    ohlcv = _ohlcv_store(tmp_path)
    pit = _pit_store(tmp_path)
    from backend.app.services.strategy.canslim.pit_inputs import build_pit_inputs

    detail, fin_metrics, eps_filing_date = build_pit_inputs("2330", AS_OF, pit)
    return observe(
        "2330",
        AS_OF,
        store=ohlcv,
        market=market,
        fin_metrics=fin_metrics,
        detail=detail,
        universe_returns_60d={"2330": 0.8, "2454": 0.1},
        universe_returns_252d={"2330": 0.8, "2454": 0.1},
        event_window_active=False,
        eps_filing_date=eps_filing_date,
    )
