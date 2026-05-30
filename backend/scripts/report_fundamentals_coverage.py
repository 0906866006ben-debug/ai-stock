"""Report PIT fundamentals coverage over the OHLCV universe.

The report is diagnostic only. It reads existing OHLCV/PIT stores and does not
fetch, synthesize, or backfill any missing fundamentals.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH, HistoricalDataStore
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH, PitFundamentalsStore
from backend.scripts.download_fundamentals import DATASET_TABLES, DATASETS


def compute_coverage(
    *,
    ohlcv_store: HistoricalDataStore,
    pit_store: PitFundamentalsStore,
) -> dict[str, Any]:
    symbols = sorted(str(symbol) for symbol in ohlcv_store.list_stocks())
    symbol_set = set(symbols)
    dataset_coverage: dict[str, dict[str, Any]] = {}
    covered_by_dataset: dict[str, set[str]] = {}

    for dataset in DATASETS:
        table, _date_col = DATASET_TABLES[dataset]
        covered = _symbols_with_rows(pit_store, table) & symbol_set
        covered_by_dataset[dataset] = covered
        dataset_coverage[dataset] = {
            "table": table,
            "covered_symbols": len(covered),
            "universe_symbols": len(symbols),
            "coverage_pct": round((len(covered) / len(symbols) * 100), 2) if symbols else 0.0,
        }

    # "Fully covered / screenable" is defined over the CORE datasets that the
    # screener needs. Balance sheet is reported separately as ROE-enabling (A pillar
    # falls back to the operating-margin proxy when it is absent), so adding it must
    # NOT shrink the screenable universe.
    # balance_sheet (ROE) and cash_flow (CFO/durability) are SUPPLEMENTARY — not every symbol
    # has them and they are not required for the core CANSLIM screen, so exclude from "fully covered".
    core_datasets = [d for d in DATASETS if DATASET_TABLES[d][0] not in ("balance_sheet", "cash_flow")]
    if symbols:
        fully_covered = sorted(set.intersection(*(covered_by_dataset[d] for d in core_datasets)))
        any_covered = set.union(*covered_by_dataset.values())
    else:
        fully_covered = []
        any_covered = set()
    no_fundamentals = sorted(symbol for symbol in symbols if symbol not in any_covered)
    progress_absent = _progress_absent_symbols(pit_store) & symbol_set
    roe_ready = sorted(covered_by_dataset.get("TaiwanStockBalanceSheet", set()))
    cfo_ready = sorted(covered_by_dataset.get("TaiwanStockCashFlowsStatement", set()))

    return {
        "ohlcv_universe_count": len(symbols),
        "datasets": dataset_coverage,
        "fully_covered_count": len(fully_covered),
        "fully_covered_symbols": fully_covered,
        "roe_ready_count": len(roe_ready),
        "roe_ready_symbols": roe_ready,
        "cfo_ready_count": len(cfo_ready),
        "cfo_ready_symbols": cfo_ready,
        "no_fundamentals_count": len(no_fundamentals),
        "no_fundamentals_symbols": no_fundamentals,
        "finmind_absent_count": len(progress_absent),
        "finmind_absent_symbols": sorted(progress_absent),
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "fundamentals_coverage.json"
    md_path = output_dir / "fundamentals_coverage.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return md_path, json_path


def _symbols_with_rows(store: PitFundamentalsStore, table: str) -> set[str]:
    with store._connect() as conn:
        rows = conn.execute(f"SELECT DISTINCT stock_id FROM {table}").fetchall()
    return {str(row[0]) for row in rows if row[0]}


def _progress_absent_symbols(store: PitFundamentalsStore) -> set[str]:
    try:
        with store._connect() as conn:
            rows = conn.execute(
                """
                SELECT stock_id, SUM(row_count) AS rows_written, COUNT(DISTINCT dataset) AS datasets_attempted
                FROM fundamentals_backfill_progress
                GROUP BY stock_id
                """
            ).fetchall()
    except Exception:
        return set()
    return {
        str(row["stock_id"])
        for row in rows
        if int(row["datasets_attempted"] or 0) >= len(DATASETS) and int(row["rows_written"] or 0) == 0
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PIT Fundamentals Coverage",
        "",
        f"- OHLCV universe symbols: {report['ohlcv_universe_count']}",
        f"- Fully covered symbols (core screening datasets): {report['fully_covered_count']}",
        f"- ROE-ready symbols (balance sheet present): {report.get('roe_ready_count', 0)}",
        f"- Symbols with no fundamentals: {report['no_fundamentals_count']}",
        f"- Likely FinMind-absent symbols: {report['finmind_absent_count']}",
        "",
        "## Dataset Coverage",
        "",
        "| Dataset | Table | Covered | Universe | Coverage |",
        "|---|---:|---:|---:|---:|",
    ]
    for dataset, item in report["datasets"].items():
        lines.append(
            f"| {dataset} | {item['table']} | {item['covered_symbols']} | "
            f"{item['universe_symbols']} | {item['coverage_pct']:.2f}% |"
        )
    lines.extend(["", "## Symbols With No Fundamentals", ""])
    no_fundamentals = report["no_fundamentals_symbols"]
    if no_fundamentals:
        preview = ", ".join(no_fundamentals[:300])
        suffix = "" if len(no_fundamentals) <= 300 else f"\n\n_Only first 300 shown; total {len(no_fundamentals)}._"
        lines.append(preview + suffix)
    else:
        lines.append("None.")
    lines.extend(["", "## Likely FinMind-Absent Symbols", ""])
    absent = report["finmind_absent_symbols"]
    lines.append(", ".join(absent[:300]) if absent else "None identified from progress rows.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--pit-db", "--db", dest="pit_db", default=str(DEFAULT_PIT_DB_PATH))
    parser.add_argument("--output-dir", default=str(Path("artifacts") / "data_probe"))
    args = parser.parse_args(argv)

    report = compute_coverage(
        ohlcv_store=HistoricalDataStore(args.ohlcv_db),
        pit_store=PitFundamentalsStore(args.pit_db),
    )
    md_path, json_path = write_reports(report, Path(args.output_dir))
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
