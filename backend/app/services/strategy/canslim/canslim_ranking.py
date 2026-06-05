"""Whole-market CANSLIM scoring & ranking (one as-of snapshot).

Scores EVERY data-bearing stock at a single date and ranks them by the consolidated
`overall_score` (0-100) + `grade` (S/A/B/C/D) — independent of pass_status. This is the
"give every stock a CANSLIM score/grade" tool: a live leaderboard, not a backtest.

Reuses the existing screening pipeline (build_screening_result + build_full_result) and
the cohort/walk-forward universe helpers. Does NOT change any signal/score/grade math.
PIT-safe: each stock is screened using only data on/before as_of.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.backtest.historical_data_store import CachedHistoricalDataStore, DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import CachedPitFundamentalsStore, DEFAULT_PIT_DB_PATH
from backend.app.services.strategy.canslim.canslim_output import build_full_result
from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
from backend.app.services.strategy.canslim.params import load_params
from backend.app.services.strategy.canslim.pit_inputs import build_pit_inputs, universe_shares_as_of
from backend.app.services.strategy.canslim.pit_universe import get_universe_as_of
from backend.app.services.strategy.canslim.screening import build_screening_result
from backend.app.services.strategy.canslim.walk_forward import _market_features_for_entry, _universe_returns_as_of

logger = logging.getLogger(__name__)

FACTORS = ("C", "A", "N", "S", "L", "I", "M")
RANK_COLUMNS = [
    "rank", "stock_id", "overall_score", "grade", "pass_status", "confidence",
    "risk_level", "structure_status", "regime", "data_quality", "is_mock",
    *[f"{p}_score" for p in FACTORS], *[f"{p}_status" for p in FACTORS],
]


@dataclass
class RankingReport:
    run_id: str
    as_of_date: str
    candidate_symbols: int
    n_ranked: int
    grade_distribution: dict[str, int]
    pass_status_distribution: dict[str, int]
    ranked_csv: str
    summary_json: str
    elapsed_seconds: float = 0.0


def rank_universe(
    as_of_date: str,
    data_store,
    pit_store,
    *,
    candidate_symbols: list[str],
    params=None,
    turnover_floor: float | None = None,
) -> pd.DataFrame:
    """Score every eligible symbol at as_of_date; return rows sorted by overall_score
    desc. Pure over injected stores (unit-testable without the Cached layer)."""
    params = params or load_params()
    universe = get_universe_as_of(as_of_date, data_store, turnover_floor=turnover_floor, candidate_symbols=candidate_symbols)
    if not universe:
        return pd.DataFrame(columns=RANK_COLUMNS)
    market = _market_features_for_entry(as_of_date, market=None, data_store=data_store, universe=universe, cache={})
    # RS percentile must be ranked against the broadest peer set available —
    # the full OHLCV store (all listed stocks), not just the candidate subset.
    # Ranking 200 tech stocks against each other gives distorted percentiles;
    # ranking against 1000+ market stocks gives a market-relative signal.
    try:
        broad_rs_universe = sorted(str(s) for s in data_store.list_stocks()
                                   if str(s) not in {"TAIEX", "TPEX"})
    except Exception:
        broad_rs_universe = universe  # fallback to candidate universe
    r60 = _universe_returns_as_of(data_store, broad_rs_universe, as_of_date, 60)
    r252 = _universe_returns_as_of(data_store, broad_rs_universe, as_of_date, 252)
    ushares = universe_shares_as_of(pit_store, universe, as_of_date)

    rows: list[dict[str, Any]] = []
    for i, symbol in enumerate(universe, start=1):
        if i % 200 == 0:
            logger.info("ranking %d/%d at %s", i, len(universe), as_of_date)
        try:
            detail, fin, filing = build_pit_inputs(symbol, as_of_date, pit_store)
            result = build_screening_result(
                symbol, as_of_date, store=data_store, market=market, fin_metrics=fin, detail=detail,
                universe_returns_60d=r60, universe_returns_252d=r252,
                event_window_active=False, eps_filing_date=filing, n_pillar_analysis=None,
                universe_shares=ushares,
            )
            full = build_full_result(result, params=params)
        except Exception:
            continue
        by_factor = {f.factor: f for f in full.per_factor_scores}
        row = {
            "stock_id": symbol, "overall_score": full.overall_score, "grade": full.grade,
            "pass_status": full.pass_status, "confidence": full.confidence, "risk_level": full.risk_level,
            "structure_status": result.structure_status, "regime": result.market_regime,
            "data_quality": full.data_quality, "is_mock": full.is_mock_or_fallback_data,
        }
        for p in FACTORS:
            fac = by_factor.get(p)
            row[f"{p}_score"] = fac.score if fac else None
            row[f"{p}_status"] = fac.status if fac else None
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=RANK_COLUMNS)
    # Rank by overall_score, then grade order, then lower risk first.
    grade_rank = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
    df["_g"] = df["grade"].map(grade_rank).fillna(9)
    df = df.sort_values(["overall_score", "_g"], ascending=[False, True]).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df.drop(columns=["_g"])[RANK_COLUMNS]


def run_ranking(
    *,
    run_id: str = "canslim_ranking_v1",
    as_of_date: str | None = None,
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    output_dir: Path | str = "artifacts/canslim_ranking",
    candidate_symbols: list[str] | None = None,
    turnover_floor: float | None = None,
) -> RankingReport:
    started = time.time()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = candidate_symbols or fundamentals_covered_symbols(pit_db_path)
    # Single-date snapshot: resolve as_of from the raw store first, then RAM-cache only a
    # ~600-day window around it (a 15-year preload is wasteful for one date).
    from backend.app.services.backtest.historical_data_store import HistoricalDataStore
    resolved = as_of_date or _latest_date(HistoricalDataStore(ohlcv_db_path), candidates)
    load_start = (pd.Timestamp(resolved) - pd.Timedelta(days=600)).strftime("%Y-%m-%d")
    data_store = CachedHistoricalDataStore(
        # TPEX is REQUIRED: regime_severity returns unknown (M-2 warns) without it,
        # which forces confidence=LOW and makes pass_status unreachable.
        ohlcv_db_path, universe=[*candidates, "TAIEX", "TPEX"], start_date=load_start,
        end_date=resolved, lookback_buffer_days=10, forward_buffer_days=0,
    )
    pit_store = CachedPitFundamentalsStore(pit_db_path, universe=candidates)
    logger.info("ranking %d candidates as of %s", len(candidates), resolved)
    df = rank_universe(resolved, data_store, pit_store, candidate_symbols=candidates, turnover_floor=turnover_floor)

    ranked_csv = out_dir / f"ranking_{resolved}.csv"
    df.to_csv(ranked_csv, index=False, encoding="utf-8-sig")
    grade_dist = df["grade"].value_counts().to_dict() if not df.empty else {}
    pass_dist = df["pass_status"].value_counts().to_dict() if not df.empty else {}
    report = RankingReport(
        run_id=run_id, as_of_date=resolved, candidate_symbols=len(candidates),
        n_ranked=int(len(df)),
        grade_distribution={str(k): int(v) for k, v in grade_dist.items()},
        pass_status_distribution={str(k): int(v) for k, v in pass_dist.items()},
        ranked_csv=str(ranked_csv), summary_json=str(out_dir / f"ranking_{resolved}.json"),
        elapsed_seconds=round(time.time() - started, 1),
    )
    Path(report.summary_json).write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ranking done: %d stocks scored as of %s -> %s", report.n_ranked, resolved, ranked_csv)
    return report


def _latest_date(store, candidates: list[str]) -> str:
    """Most recent trading date available across a sample of candidates."""
    latest = ""
    for sym in [*candidates[:50], "TAIEX"]:
        try:
            d = store.get_latest_date(sym)
        except Exception:
            d = None
        if d and str(d) > latest:
            latest = str(d)
    from datetime import date
    return latest or date.today().isoformat()
