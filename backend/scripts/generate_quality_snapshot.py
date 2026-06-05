"""Generate a quarterly durability quality-watch snapshot.

Example:
    .venv\\Scripts\\python backend/scripts/generate_quality_snapshot.py --quarter 2026-Q1 --durability-min 50
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.scripts._env import load_backend_env
from backend.app.models.quality_snapshot import QuarterlySnapshot, SnapshotStock
from backend.app.services.backtest.historical_data_store import HistoricalDataStore, DEFAULT_DB_PATH
from backend.app.services.backtest.pit_fundamentals_store import PitFundamentalsStore, DEFAULT_PIT_DB_PATH
from backend.app.services.quality_snapshot_store import QualitySnapshotStore, DEFAULT_QUALITY_SNAPSHOT_DB
from backend.app.services.strategy.canslim.live_screening import durability_metrics_for_symbol
from backend.app.services.strategy.canslim.multicycle_backtest import fundamentals_covered_symbols
from backend.app.services.strategy.canslim.pit_inputs import _shares_outstanding
from backend.app.services.strategy.canslim.universe_source import get_tech_universe_symbols

logger = logging.getLogger(__name__)


def generate_quality_snapshot(
    *,
    quarter: str | None = None,
    as_of_date: str | None = None,
    durability_min: float = 50.0,
    ohlcv_db_path: Path | str = DEFAULT_DB_PATH,
    pit_db_path: Path | str = DEFAULT_PIT_DB_PATH,
    snapshot_db_path: Path | str = DEFAULT_QUALITY_SNAPSHOT_DB,
    output_dir: Path | str = "artifacts",
    universe_source: str = "tech",
    limit: int | None = None,
) -> QuarterlySnapshot:
    quarter = quarter or previous_completed_quarter(date.today())
    as_of_date = as_of_date or quarter_end_date(quarter)
    pit_store = PitFundamentalsStore(pit_db_path)
    ohlcv_store = HistoricalDataStore(ohlcv_db_path)
    symbols = fundamentals_covered_symbols(pit_db_path)
    status = "ok"
    warnings: list[str] = []
    if universe_source == "tech":
        try:
            tech = set(get_tech_universe_symbols())
            if tech:
                symbols = [symbol for symbol in symbols if symbol in tech]
            else:
                message = "tech universe resolved to zero symbols; writing a no-data tech snapshot"
                logger.warning(message)
                warnings.append(message)
                status = "no_data"
                symbols = []
        except Exception as exc:
            message = f"tech universe fetch failed ({exc}); writing a no-data tech snapshot"
            logger.warning(message)
            warnings.append(message)
            status = "no_data"
            symbols = []
    if limit:
        symbols = symbols[:limit]

    stocks: list[SnapshotStock] = []
    for idx, symbol in enumerate(symbols, start=1):
        metrics = durability_metrics_for_symbol(symbol, as_of_date, pit_store=pit_store)
        score = metrics.get("score")
        if score is None or float(score) < float(durability_min):
            continue
        price = _latest_close(ohlcv_store, symbol, as_of_date)
        shares = _latest_shares(pit_store, symbol, as_of_date)
        stocks.append(SnapshotStock(
            symbol=symbol,
            name=symbol,
            durability_score=float(score),
            durability_components={key: float(value) for key, value in (metrics.get("components") or {}).items()},
            confidence=float(metrics.get("confidence") or 0),
            sector=None,
            price_at_snapshot=price,
            market_cap_ntd=(float(price) * float(shares) if price is not None and shares is not None else None),
        ))
        if idx % 100 == 0:
            logger.info("processed %d/%d symbols, kept %d", idx, len(symbols), len(stocks))

    stocks.sort(key=lambda item: item.durability_score, reverse=True)
    snapshot = QuarterlySnapshot(
        quarter=quarter,
        as_of_date=as_of_date,
        generated_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        warnings=warnings,
        snapshot_stocks=stocks,
    )
    QualitySnapshotStore(snapshot_db_path).write_snapshot(snapshot)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"quality_snapshot_{quarter}.json").write_text(
        json.dumps(snapshot.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return snapshot


def quarter_end_date(quarter: str) -> str:
    year_str, q_str = quarter.upper().split("-Q", 1)
    year = int(year_str)
    q = int(q_str)
    ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    if q not in ends:
        raise ValueError("quarter must be like 2026-Q1")
    return f"{year}-{ends[q]}"


def previous_completed_quarter(today: date) -> str:
    q = (today.month - 1) // 3 + 1
    if q == 1:
        return f"{today.year - 1}-Q4"
    return f"{today.year}-Q{q - 1}"


def _latest_close(store: HistoricalDataStore, symbol: str, as_of_date: str) -> float | None:
    try:
        bars = store.get_ohlcv_as_of(symbol, as_of_date, 1)
    except Exception:
        return None
    if bars is None or bars.empty:
        return None
    try:
        return float(bars.iloc[-1]["close"])
    except Exception:
        return None


def _latest_shares(pit_store: PitFundamentalsStore, symbol: str, as_of_date: str) -> float | None:
    try:
        bs = pit_store.get_balance_sheet_as_of(symbol, as_of_date, limit=1)
    except Exception:
        return None
    return _shares_outstanding(bs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quarter", default=None)
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--durability-min", type=float, default=50.0)
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pit-db", default=str(DEFAULT_PIT_DB_PATH))
    parser.add_argument("--snapshot-db", default=str(DEFAULT_QUALITY_SNAPSHOT_DB))
    parser.add_argument("--out", default="artifacts")
    parser.add_argument("--universe-source", choices=("all", "tech"), default="tech")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    load_backend_env()
    snapshot = generate_quality_snapshot(
        quarter=args.quarter,
        as_of_date=args.as_of_date,
        durability_min=args.durability_min,
        ohlcv_db_path=args.ohlcv_db,
        pit_db_path=args.pit_db,
        snapshot_db_path=args.snapshot_db,
        output_dir=args.out,
        universe_source=args.universe_source,
        limit=args.limit,
    )
    logger.info("quality snapshot %s complete: %d stocks", snapshot.quarter, len(snapshot.snapshot_stocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
