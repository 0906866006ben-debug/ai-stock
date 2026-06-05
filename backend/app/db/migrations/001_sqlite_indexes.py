from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from backend.app.db.sqlite_utils import connect_sqlite, safe_create_index


REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class IndexSpec:
    db_key: str
    index_name: str
    table_name: str
    columns: tuple[str, ...]
    reason: str


DEFAULT_DB_PATHS = {
    "historical": REPO_ROOT / "backend" / "historical_data.db",
    "pit": REPO_ROOT / "backend" / "pit_fundamentals.db",
    "stock_master": REPO_ROOT / "backend" / "data" / "stock_master.db",
}


INDEX_SPECS = (
    IndexSpec(
        "historical",
        "idx_ohlcv_stock_date",
        "ohlcv",
        ("stock_id", "date"),
        "Single-stock OHLCV range/as-of reads; usually satisfied by the table primary key.",
    ),
    IndexSpec(
        "historical",
        "idx_ohlcv_date",
        "ohlcv",
        ("date",),
        "All-stock same-date OHLCV and trading-date scans.",
    ),
    IndexSpec(
        "historical",
        "idx_ohlcv_date_stock",
        "ohlcv",
        ("date", "stock_id"),
        "Date-first all-stock scans for heatmap/screening and future feature builds.",
    ),
    IndexSpec(
        "pit",
        "idx_month_revenue_stock_date",
        "month_revenue",
        ("stock_id", "date"),
        "Single-stock monthly revenue point-in-time reads; usually satisfied by the primary key.",
    ),
    IndexSpec(
        "pit",
        "idx_month_revenue_date_stock",
        "month_revenue",
        ("date", "stock_id"),
        "Date-first monthly revenue scans for cross-sectional feature generation.",
    ),
    IndexSpec(
        "pit",
        "idx_institutional_stock_date",
        "institutional",
        ("stock_id", "date"),
        "Single-stock institutional flow point-in-time reads; usually satisfied by the primary key.",
    ),
    IndexSpec(
        "pit",
        "idx_institutional_date_stock",
        "institutional",
        ("date", "stock_id"),
        "Date-first institutional flow scans for daily screening/feature generation.",
    ),
    IndexSpec(
        "pit",
        "idx_margin_stock_date",
        "margin",
        ("stock_id", "date"),
        "Single-stock margin/short balance point-in-time reads; usually satisfied by the primary key.",
    ),
    IndexSpec(
        "pit",
        "idx_margin_date_stock",
        "margin",
        ("date", "stock_id"),
        "Date-first margin/short scans for daily risk feature generation.",
    ),
    IndexSpec(
        "pit",
        "idx_per_stock_date",
        "per",
        ("stock_id", "date"),
        "Single-stock PER/PBR point-in-time reads; usually satisfied by the primary key.",
    ),
    IndexSpec(
        "pit",
        "idx_per_date_stock",
        "per",
        ("date", "stock_id"),
        "Date-first valuation scans for daily feature generation.",
    ),
    IndexSpec(
        "pit",
        "idx_financials_stock_filing",
        "financials",
        ("stock_id", "filing_date"),
        "Financial-statement PIT reads must gate by filing_date, not period_end.",
    ),
    IndexSpec(
        "pit",
        "idx_financials_filing_stock_period",
        "financials",
        ("filing_date", "stock_id", "period_end"),
        "Cross-sectional PIT financial feature builds by market-available filing date.",
    ),
    IndexSpec(
        "pit",
        "idx_balance_sheet_stock_filing",
        "balance_sheet",
        ("stock_id", "filing_date"),
        "Balance-sheet PIT reads must gate by filing_date, not period_end.",
    ),
    IndexSpec(
        "pit",
        "idx_balance_sheet_filing_stock_period",
        "balance_sheet",
        ("filing_date", "stock_id", "period_end"),
        "Cross-sectional PIT balance-sheet feature builds by market-available filing date.",
    ),
    IndexSpec(
        "pit",
        "idx_cash_flow_stock_filing",
        "cash_flow",
        ("stock_id", "filing_date"),
        "Cash-flow PIT reads must gate by filing_date, not period_end.",
    ),
    IndexSpec(
        "pit",
        "idx_cash_flow_filing_stock_period",
        "cash_flow",
        ("filing_date", "stock_id", "period_end"),
        "Cross-sectional PIT cash-flow feature builds by market-available filing date.",
    ),
    IndexSpec(
        "stock_master",
        "idx_stock_master_market_code",
        "stock_master",
        ("market_type", "stock_code"),
        "Market-filtered stock directory reads ordered by stock code.",
    ),
    IndexSpec(
        "stock_master",
        "idx_stock_master_industry_code",
        "stock_master",
        ("industry", "stock_code"),
        "Industry-filtered stock directory reads ordered by stock code.",
    ),
)


def migrate(db_paths: dict[str, Path | str] | None = None) -> list[dict]:
    resolved = {key: Path(value) for key, value in (db_paths or DEFAULT_DB_PATHS).items()}
    results: list[dict] = []

    for db_key in ("historical", "pit", "stock_master"):
        db_path = resolved.get(db_key)
        specs = [spec for spec in INDEX_SPECS if spec.db_key == db_key]
        if db_path is None or not db_path.exists():
            for spec in specs:
                results.append(
                    {
                        "db": db_key,
                        "db_path": str(db_path) if db_path is not None else None,
                        "index": spec.index_name,
                        "table": spec.table_name,
                        "columns": list(spec.columns),
                        "reason": spec.reason,
                        "status": "skipped_missing_db",
                        "warning": f"database not found: {db_path}",
                    }
                )
            continue

        conn = connect_sqlite(db_path)
        try:
            for spec in specs:
                result = safe_create_index(conn, spec.index_name, spec.table_name, spec.columns)
                result.update({"db": db_key, "db_path": str(db_path), "reason": spec.reason})
                results.append(result)
            conn.execute("PRAGMA optimize")
            conn.commit()
        except Exception as exc:
            results.append(
                {
                    "db": db_key,
                    "db_path": str(db_path),
                    "index": None,
                    "table": None,
                    "columns": [],
                    "reason": "database-level migration failure",
                    "status": "error",
                    "warning": f"{type(exc).__name__}: {exc}",
                }
            )
        finally:
            conn.close()

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Create safe SQLite indexes for local ai-stock stores.")
    parser.add_argument("--historical-db", default=str(DEFAULT_DB_PATHS["historical"]))
    parser.add_argument("--pit-db", default=str(DEFAULT_DB_PATHS["pit"]))
    parser.add_argument("--stock-master-db", default=str(DEFAULT_DB_PATHS["stock_master"]))
    args = parser.parse_args()

    results = migrate(
        {
            "historical": args.historical_db,
            "pit": args.pit_db,
            "stock_master": args.stock_master_db,
        }
    )
    for result in results:
        columns = ", ".join(result.get("columns") or [])
        warning = f" warning={result['warning']}" if result.get("warning") else ""
        print(
            f"{result['status']}: {result.get('db')}:{result.get('table')}"
            f".{result.get('index')} ({columns}){warning}"
        )
    return 1 if any(result["status"] == "error" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

