from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from zipfile import ZipFile

import pandas as pd

from backend.technical_analyzer.v1.backtest import BacktestConfig, run_backtest


def _write_price_csv(path, symbol: str, rows: int = 220) -> None:
    start = date(2024, 1, 1)
    price = Decimal("100")
    records = []
    for index in range(rows):
        day = start + timedelta(days=index)
        drift = Decimal("0.25") if index % 35 < 25 else Decimal("-0.15")
        price = max(Decimal("20"), price + drift)
        open_price = price - Decimal("0.2")
        high = price + Decimal("1.5")
        low = price - Decimal("1.0")
        records.append({
            "date": day.isoformat(),
            "open": float(open_price),
            "high": float(high),
            "low": float(low),
            "close": float(price),
            "volume": 1_000_000 + index * 1000,
            "turnover_value": float(price * Decimal("1000000")),
        })
    pd.DataFrame(records).to_csv(path / f"{symbol}.csv", index=False)


def test_backtest_runner_writes_csv_json_and_xlsx(tmp_path) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "out"
    data_dir.mkdir()
    _write_price_csv(data_dir, "2330")

    config = BacktestConfig(
        symbols=["2330"],
        start=date(2024, 4, 1),
        end=date(2024, 7, 10),
        data_dir=data_dir,
        output_dir=output_dir,
        warmup_bars=60,
        min_signal=45,
        min_confidence=20,
        max_risk=95,
        require_rr_pass=False,
    )

    result = run_backtest(config)

    assert result.summary.total_trades >= 1
    assert result.daily_signals
    assert result.hypothesis_rows
    assert result.generated_files["xlsx"].exists()
    assert result.generated_files["summary_json"].exists()
    assert (result.generated_files["run_dir"] / "Trades.csv").exists()
    assert (result.generated_files["run_dir"] / "DailySignals.csv").exists()
    assert (result.generated_files["run_dir"] / "Hypotheses.csv").exists()

    with ZipFile(result.generated_files["xlsx"]) as archive:
        assert "xl/workbook.xml" in archive.namelist()
        assert "xl/worksheets/sheet1.xml" in archive.namelist()


def test_backtest_strict_rr_mode_can_produce_no_trades_but_keeps_signals(tmp_path) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "out"
    data_dir.mkdir()
    _write_price_csv(data_dir, "2454")

    config = BacktestConfig(
        symbols=["2454"],
        start=date(2024, 4, 1),
        end=date(2024, 7, 10),
        data_dir=data_dir,
        output_dir=output_dir,
        warmup_bars=60,
        require_rr_pass=True,
    )

    result = run_backtest(config, write_files=False)

    assert result.daily_signals
    assert all(row.symbol == "2454" for row in result.daily_signals)
