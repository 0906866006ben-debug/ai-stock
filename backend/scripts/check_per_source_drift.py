"""Quantify valuation-source drift between the LIVE and the BACKTESTED long bucket.

The long bucket's OOS validation (Docs/backtest/experiments_ledger.md, Iteration 1b)
was computed on the local FinMind ``TaiwanStockPER`` snapshot. The live endpoint
(backend/app/services/tw_daily_opportunities.py) instead reads TWSE ``BWIBBU_ALL``.
Before shipping the long bucket as the production core we must confirm the two
sources agree closely enough that the live BWIBBU version inherits the FinMind
validation (plan Phase 1a).

FinMind's free ("register") tier cannot return an all-stock PER cross-section, so
the *decisive* check is same-date, per-stock: for a systematic sample we pull
FinMind ``TaiwanStockPER`` (data_id) and compare PER / PBR / dividend_yield to
BWIBBU on the SAME trading date. A secondary full-universe check compares BWIBBU
today against the local FinMind snapshot (accepting the date gap) purely for
coverage.

Gate (plan): Spearman/Pearson corr >= 0.98 and small median |diff| -> pass.

Run:  .venv/Scripts/python.exe backend/scripts/check_per_source_drift.py
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
P_DB = ROOT / "backend" / "pit_fundamentals.db"
BWIBBU_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
SAMPLE_SIZE = 50


def _token() -> str:
    tok = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN") or ""
    if tok:
        return tok
    for p in (ROOT / "backend" / ".env", ROOT / ".env"):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                m = re.match(r"\s*(FINMIND_API_KEY|FINMIND_TOKEN)\s*=\s*(.+)", line)
                if m:
                    return m.group(2).strip().strip('"').strip("'")
        except FileNotFoundError:
            continue
    return ""


def fetch_bwibbu(client: httpx.Client) -> dict[str, dict]:
    r = client.get(BWIBBU_URL, headers={"accept": "application/json"})
    r.raise_for_status()
    out: dict[str, dict] = {}
    for row in r.json():
        sid = str(row.get("Code") or "").strip()

        def num(key):
            try:
                v = float(row.get(key) or 0)
                return v if v > 0 else None
            except (TypeError, ValueError):
                return None

        if sid.isdigit() and len(sid) == 4:
            out[sid] = {"per": num("PEratio"), "pbr": num("PBratio"), "yield": num("DividendYield")}
    return out


def fetch_finmind_latest(client: httpx.Client, sid: str, token: str) -> dict | None:
    """Latest TaiwanStockPER row for one stock (per/PER, pbr/PBR, yield/dividend_yield)."""
    try:
        r = client.get(FINMIND_URL, params={
            "dataset": "TaiwanStockPER", "data_id": sid,
            "start_date": "2026-06-15", "token": token,
        })
        j = r.json()
    except Exception:
        return None
    rows = j.get("data") or []
    if j.get("status") != 200 or not rows:
        return None
    rows.sort(key=lambda x: x.get("date", ""))
    last = rows[-1]

    def g(*keys):
        for k in keys:
            v = last.get(k)
            if v not in (None, ""):
                try:
                    fv = float(v)
                    return fv if fv > 0 else None
                except (TypeError, ValueError):
                    return None
        return None

    return {
        "date": last.get("date"),
        "per": g("PER", "per"),
        "pbr": g("PBR", "pbr"),
        "yield": g("dividend_yield", "yield", "DividendYield"),
    }


def _stats(name: str, a: list[float], b: list[float]) -> str:
    a, b = np.array(a), np.array(b)
    m = (a > 0) & (b > 0) & np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if len(a) < 5:
        return f"  {name}: n={len(a)} (too few to correlate)"
    pear = float(np.corrcoef(a, b)[0, 1])
    ra = a.argsort().argsort()
    rb = b.argsort().argsort()
    spear = float(np.corrcoef(ra, rb)[0, 1])
    med_abs = float(np.median(np.abs(a - b)))
    med_rel = float(np.median(np.abs(a - b) / b))
    return (f"  {name}: n={len(a)} pearson={pear:.4f} spearman={spear:.4f} "
            f"median|diff|={med_abs:.3f} median_rel={med_rel:.2%}")


def main() -> None:
    token = _token()
    if not token:
        print("NO FINMIND TOKEN — cannot run same-date check")
        return

    with httpx.Client(timeout=30.0) as client:
        print("fetching BWIBBU_ALL (today snapshot)...")
        bw = fetch_bwibbu(client)
        print(f"  BWIBBU stocks: {len(bw)}")

        # systematic sample across the code range (not cherry-picked)
        sids = sorted(bw.keys())
        step = max(1, len(sids) // SAMPLE_SIZE)
        sample = sids[::step][:SAMPLE_SIZE]
        print(f"same-date per-stock check on {len(sample)} sampled stocks...")

        pairs = {"per": ([], []), "pbr": ([], []), "yield": ([], [])}
        fm_dates: dict[str, int] = {}
        matched = 0
        for sid in sample:
            fm = fetch_finmind_latest(client, sid, token)
            time.sleep(0.15)
            if not fm:
                continue
            fm_dates[fm["date"]] = fm_dates.get(fm["date"], 0) + 1
            b = bw[sid]
            matched += 1
            for k in pairs:
                if fm.get(k) and b.get(k):
                    pairs[k][0].append(fm[k])
                    pairs[k][1].append(b[k])

        print(f"\n=== SAME-DATE per-stock (FinMind API vs BWIBBU) ===")
        print(f"matched {matched} stocks; FinMind latest dates: {fm_dates}")
        for k in ("per", "pbr", "yield"):
            print(_stats(k, pairs[k][0], pairs[k][1]))

    # secondary: full-universe local snapshot vs BWIBBU (date gap ~ weeks, coverage only)
    print("\n=== SECONDARY full-universe (local FinMind snapshot vs BWIBBU, DATE-GAPPED) ===")
    c = sqlite3.connect(P_DB)
    cur = c.cursor()
    latest = cur.execute("SELECT MAX(date) FROM per").fetchone()[0]
    snap = {r[0]: {"per": r[1], "pbr": r[2], "yield": r[3]}
            for r in cur.execute("SELECT stock_id,per,pbr,dividend_yield FROM per WHERE date=?", (latest,))}
    c.close()
    common = [s for s in snap if s in bw]
    print(f"snapshot date {latest}; common stocks {len(common)}")
    for k in ("per", "pbr", "yield"):
        a = [snap[s][k] for s in common if snap[s][k] and bw[s][k]]
        b = [bw[s][k] for s in common if snap[s][k] and bw[s][k]]
        print(_stats(k, a, b))
    print("\n(gate: SAME-DATE pearson/spearman >= 0.98 & small median_rel -> live BWIBBU inherits FinMind validation)")


if __name__ == "__main__":
    main()
