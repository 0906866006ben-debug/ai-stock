from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.research_platform.settings import ResearchSettings


@pytest.fixture()
def market_db(tmp_path: Path) -> Path:
    path = tmp_path / "market.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE klines (
                sym TEXT NOT NULL,
                itv TEXT NOT NULL,
                open_ms INTEGER NOT NULL,
                o REAL NOT NULL,
                h REAL NOT NULL,
                l REAL NOT NULL,
                c REAL NOT NULL,
                v REAL NOT NULL,
                qv REAL NOT NULL,
                PRIMARY KEY(sym,itv,open_ms)
            );
            CREATE TABLE funding (
                sym TEXT NOT NULL,
                ts INTEGER NOT NULL,
                rate REAL NOT NULL,
                PRIMARY KEY(sym,ts)
            );
            """
        )
        conn.executemany(
            "INSERT INTO klines VALUES(?,?,?,?,?,?,?,?,?)",
            [
                ("BTCUSDT", "1m", 1783641600000, 100, 102, 99, 101, 10, 1010),
                ("BTCUSDT", "1h", 1783638000000, 98, 103, 97, 101, 1000, 101000),
                ("ETHUSDT", "1h", 1783638000000, 50, 51, 49, 50.5, 800, 40400),
            ],
        )
        conn.execute("INSERT INTO funding VALUES(?,?,?)", ("BTCUSDT", 1783612800000, 0.0001))
    return path


@pytest.fixture()
def runs_path(tmp_path: Path) -> Path:
    path = tmp_path / "runs" / "20260710_baseline"
    path.mkdir(parents=True)
    (path / "report.txt").write_text(
        """# Crypto Backtest Report

## Overview
variant=baseline
period=2026-04-01T00:00:00Z to 2026-05-31T00:00:00Z
hypothesis=baseline evidence import
trades=40 win_rate=42.5% totalR=-2.50 avgR=-0.06 PF=0.88 netPnL=-12.50
CAGR=-18.0% maxDD_R=6.20 Sharpe=-0.40 exposure=12.0% turnover=8.50
fees=10.00 funding_paid=0.30 timeouts=0 ambiguous=1 crossed_settlement=4
""",
        encoding="utf-8",
    )
    return path.parent


def make_settings(tmp_path: Path, market_db: Path, runs_path: Path, token: str = "") -> ResearchSettings:
    return ResearchSettings(
        market_db_path=market_db,
        runs_path=runs_path,
        metadata_db_path=tmp_path / "research.db",
        api_token=token,
        require_read_auth=False,
        live_trading_enabled=False,
        openai_model="test-model",
        openai_auto_calls_limit=2,
        openai_manual_calls_limit=2,
        openai_total_calls_limit=4,
        openai_monthly_target_usd=1.5,
        openai_monthly_hard_stop_usd=4.5,
        openai_min_days_between_auto=7,
        openai_min_new_valid_backtests=10_000,
    )

