#!/usr/bin/env python
"""Refresh the CANONICAL app data stores to the latest available trading date.

Updates the SAME two SQLite stores that the scan, single-stock screen, and the
backtest scripts all read by default — so there is ONE source of truth:

    backend/historical_data.db   (OHLCV, incl. TAIEX/TPEX indices)
    backend/pit_fundamentals.db  (PIT fundamentals: revenue / institutional / financials …)

Steps:
  1. OHLCV incremental update for every symbol already in the store (fills the
     gap from each symbol's last local bar to today; falls back to yfinance when
     FinMind is rate-limited).
  2. TAIEX/TPEX index refresh (needed for the market-regime / M pillar).
  3. Fundamentals resume (skips already-stored stock/dataset pairs; auto-sleeps
     and resumes when the FinMind free-tier rolling limit is hit).

Run from the repo root:
    .venv\\Scripts\\python.exe refresh_data.py
Optional flags:
    --skip-fundamentals   only refresh OHLCV (fast; fundamentals are quarterly)
    --fund-passes N       cap fundamentals auto-resume passes (default 4)
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable  # use the same interpreter this script runs under (the venv)
OHLCV_DB = ROOT / "backend" / "historical_data.db"
PIT_DB = ROOT / "backend" / "pit_fundamentals.db"


def _ohlcv_state() -> tuple[int, str]:
    if not OHLCV_DB.exists():
        return (0, "—")
    con = sqlite3.connect(str(OHLCV_DB))
    try:
        n = con.execute("SELECT COUNT(DISTINCT stock_id) FROM ohlcv").fetchone()[0]
        mx = con.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0]
        return (int(n or 0), str(mx))
    finally:
        con.close()


def _pit_state() -> str:
    if not PIT_DB.exists():
        return "—"
    con = sqlite3.connect(str(PIT_DB))
    try:
        fin = con.execute("SELECT COUNT(DISTINCT stock_id) FROM financials").fetchone()[0]
        inst_mx = con.execute("SELECT MAX(date) FROM institutional").fetchone()[0]
        return f"{fin} financials syms, institutional latest {inst_mx}"
    except sqlite3.Error as exc:
        return f"(read error: {exc})"
    finally:
        con.close()


def run(args: list[str]) -> int:
    print("\n>>> python -m " + " ".join(args), flush=True)
    return subprocess.call([PY, "-m", *args], cwd=str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fundamentals", action="store_true",
                    help="Only refresh OHLCV (fundamentals are quarterly; skip for a fast price refresh).")
    ap.add_argument("--fund-passes", type=int, default=4,
                    help="Max fundamentals auto-resume passes (default 4).")
    args = ap.parse_args()

    n0, d0 = _ohlcv_state()
    print("=" * 66)
    print("CANONICAL STORE REFRESH")
    print(f"  OHLCV : {OHLCV_DB}")
    print(f"          before: {n0} symbols, latest {d0}")
    print(f"  PIT   : {PIT_DB}")
    print(f"          before: {_pit_state()}")
    print("=" * 66)

    # 1) OHLCV — incremental gap fill for the existing universe.
    rc = run([
        "backend.scripts.download_history",
        "--incremental",
        "--universe-source", "ohlcv",
        "--db", str(OHLCV_DB),
        "--min-days", "10",
        "--buffer-days", "7",
        "--max-days", "400",
    ])
    if rc != 0:
        print(f"[warn] OHLCV incremental returned {rc} (continuing)")

    # 2) Indices for the market-regime / M pillar.
    run([
        "backend.scripts.download_history",
        "--stocks", "TAIEX", "TPEX",
        "--days", "120",
        "--db", str(OHLCV_DB),
    ])

    # 3) Fundamentals — resume/fill (quarterly; skips already-stored pairs).
    if not args.skip_fundamentals:
        run([
            "backend.scripts.download_fundamentals",
            "--universe-source", "ohlcv",
            "--ohlcv-db", str(OHLCV_DB),
            "--db", str(PIT_DB),
            "--auto-resume",
            "--max-passes", str(args.fund_passes),
        ])
    else:
        print("\n[skip] fundamentals refresh (--skip-fundamentals)")

    n1, d1 = _ohlcv_state()
    print("\n" + "=" * 66)
    print("REFRESH COMPLETE")
    print(f"  OHLCV : {n0} -> {n1} symbols, latest {d0} -> {d1}")
    print(f"  PIT   : {_pit_state()}")
    print("=" * 66)
    print("Restart the backend to pick up the refreshed data:")
    print("  .venv\\Scripts\\uvicorn backend.app.main:app --reload --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
