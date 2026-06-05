"""Backfill dated PIT fundamentals/chip datasets from FinMind.

The script is idempotent and resumable: every row is keyed by stock_id plus its
effective date (or period_end for financials), so re-running replaces/fills
without duplication. It never logs the FinMind token.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.backtest.historical_data_store import DEFAULT_DB_PATH, HistoricalDataStore
from backend.app.services.backtest.pit_fundamentals_store import DEFAULT_PIT_DB_PATH, PitFundamentalsStore
from backend.app.services.strategy.canslim.universe_source import get_all_universe_symbols, get_tech_universe_symbols

logger = logging.getLogger(__name__)

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"


async def _fetch_with_status(dataset: str, data_id: str, start_date: str, token: str) -> tuple[list[dict], bool]:
    """Fetch a FinMind dataset, distinguishing genuine-empty from rate-limit/error.

    Returns (rows, ok). ok=True only on HTTP 200 + api status 200 (even if the data
    list is empty, meaning FinMind genuinely has nothing). ok=False on HTTP error,
    api status != 200 (e.g. 402 request-limit), or any exception — the caller must
    NOT mark such a (stock, dataset) as completed, or it gets permanently skipped.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                FINMIND_BASE,
                params={"dataset": dataset, "data_id": data_id, "start_date": start_date, "token": token},
            )
        if resp.status_code != 200:
            return [], False
        payload = resp.json()
        if payload.get("status") == 200:
            return list(payload.get("data", [])), True
        return [], False
    except Exception:
        return [], False

DATASETS = (
    "TaiwanStockMonthRevenue",
    "TaiwanStockInstitutionalInvestorsBuySell",
    "TaiwanStockMarginPurchaseShortSale",
    "TaiwanStockPER",
    "TaiwanStockFinancialStatements",
    "TaiwanStockBalanceSheet",
    "TaiwanStockCashFlowsStatement",
)

DATASET_TABLES = {
    "TaiwanStockMonthRevenue": ("month_revenue", "date"),
    "TaiwanStockInstitutionalInvestorsBuySell": ("institutional", "date"),
    "TaiwanStockMarginPurchaseShortSale": ("margin", "date"),
    "TaiwanStockPER": ("per", "date"),
    "TaiwanStockFinancialStatements": ("financials", "period_end"),
    "TaiwanStockBalanceSheet": ("balance_sheet", "period_end"),
    "TaiwanStockCashFlowsStatement": ("cash_flow", "period_end"),
}


def load_ai_tech_codes(json_path: Path) -> list[str]:
    with json_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    codes: list[str] = []
    for category in data.get("categories", {}).values():
        for stock in category.get("stocks", []):
            code = str(stock.get("code", "")).strip()
            if code:
                codes.append(code)
    return codes


def resolve_universe_symbols(
    *,
    stocks: list[str] | None,
    universe_source: str,
    universe_file: str,
    ohlcv_db: str | Path | None = None,
) -> list[str]:
    if stocks:
        return _dedupe_symbols(stocks)
    if universe_source == "broad":
        return _dedupe_symbols(get_tech_universe_symbols())
    if universe_source == "all":
        return _dedupe_symbols(get_all_universe_symbols())
    if universe_source == "ohlcv":
        return _dedupe_symbols(HistoricalDataStore(ohlcv_db).list_stocks())

    universe_path = Path(universe_file)
    if not universe_path.exists():
        raise FileNotFoundError(f"Universe file not found: {universe_path}")
    return _dedupe_symbols(load_ai_tech_codes(universe_path))


def _dedupe_symbols(stocks: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for stock in stocks:
        symbol = str(stock).strip()
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


class _Progress:
    """Lightweight, dependency-free carriage-return progress bar (stdout)."""

    def __init__(self, total: int, *, enabled: bool = True) -> None:
        self.total = max(1, int(total))
        self.enabled = enabled and sys.stdout.isatty()
        self.start = time.time()

    def update(self, job: int, stock: str, dataset: str, total_rows: int, *, skipped: bool = False) -> None:
        if not self.enabled:
            return
        pct = job / self.total * 100.0
        elapsed = time.time() - self.start
        rate = job / elapsed if elapsed > 0 else 0.0
        eta_min = ((self.total - job) / rate / 60.0) if rate > 0 else 0.0
        bar_len = 24
        filled = int(bar_len * job / self.total)
        bar = "#" * filled + "-" * (bar_len - filled)
        tag = "skip" if skipped else "get "
        line = (
            f"\r[{bar}] {pct:5.1f}% {job}/{self.total} "
            f"{tag} {str(stock):>6} {dataset[:24]:<24} rows={total_rows} ETA {eta_min:5.1f}m"
        )
        sys.stdout.write(line[:160])
        sys.stdout.flush()

    def close(self) -> None:
        if self.enabled:
            sys.stdout.write("\n")
            sys.stdout.flush()


async def download_all(
    *,
    stocks: list[str],
    datasets: list[str],
    start_date: str,
    token: str,
    store: PitFundamentalsStore,
    rate_limit: float,
    resume: bool = True,
    show_progress: bool = True,
    max_consecutive_failures: int = 25,
) -> tuple[dict[str, int], bool]:
    ensure_progress_table(store)
    counts = {dataset: 0 for dataset in datasets}
    total_jobs = len(stocks) * len(datasets)
    progress = _Progress(total_jobs, enabled=show_progress)
    job = 0
    consecutive_failures = 0
    stopped_early = False
    try:
        for stock_id in stocks:
            for dataset in datasets:
                job += 1
                if resume and has_dataset_since_start(store, stock_id, dataset, start_date):
                    logger.debug("(%d/%d) skipping %s %s; rows already cover requested start", job, total_jobs, stock_id, dataset)
                    progress.update(job, stock_id, dataset, sum(counts.values()), skipped=True)
                    continue
                logger.debug("(%d/%d) downloading %s %s", job, total_jobs, stock_id, dataset)
                try:
                    fetched = await _fetch_with_status(dataset, stock_id, start_date, token)
                    # Tolerate test fakes that return a bare list (treated as a successful fetch).
                    raw_rows, ok = fetched if isinstance(fetched, tuple) else (fetched, True)
                    fail_reason = "rate limit / non-200 response"
                except Exception as exc:
                    raw_rows, ok, fail_reason = [], False, str(exc)
                if not ok:
                    # Rate-limited or transient error. Do NOT mark progress (so a later
                    # run retries this stock/dataset) — marking a rate-limited empty as
                    # "done" is exactly what poisons coverage. Back off and, after too
                    # many consecutive failures (free-tier hourly limit hit), stop so the
                    # user can resume later when the quota resets.
                    consecutive_failures += 1
                    logger.warning("Fetch failed for %s %s: %s — not marking done", stock_id, dataset, fail_reason)
                    progress.update(job, stock_id, dataset, sum(counts.values()), skipped=True)
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(
                            "Stopped after %d consecutive failed fetches — FinMind free-tier limit likely reached. "
                            "Re-run the SAME command later to resume (already-stored stocks are skipped).",
                            consecutive_failures,
                        )
                        stopped_early = True
                        break
                    await asyncio.sleep(rate_limit * 5)
                    continue
                consecutive_failures = 0
                rows = normalize_dataset(dataset, stock_id, raw_rows)
                wrote = _upsert_dataset(store, dataset, rows)
                # ok=True even when genuinely empty (FinMind has nothing) -> mark done so
                # we don't retry truly-absent symbols every run.
                mark_dataset_progress(store, stock_id, dataset, start_date, wrote)
                counts[dataset] += wrote
                logger.debug("  wrote %d rows", wrote)
                progress.update(job, stock_id, dataset, sum(counts.values()))
                await asyncio.sleep(rate_limit)
            else:
                continue
            break  # inner loop broke on rate limit -> stop outer loop too
    finally:
        progress.close()
    return counts, stopped_early


def ensure_progress_table(store: PitFundamentalsStore) -> None:
    with store._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentals_backfill_progress (
                stock_id TEXT NOT NULL,
                dataset TEXT NOT NULL,
                start_date TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                row_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (stock_id, dataset, start_date)
            )
            """
        )


def mark_dataset_progress(store: PitFundamentalsStore, stock_id: str, dataset: str, start_date: str, row_count: int) -> None:
    with store._connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO fundamentals_backfill_progress
                (stock_id, dataset, start_date, completed_at, row_count)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
            """,
            (str(stock_id), dataset, start_date, int(row_count)),
        )


def clear_empty_progress(store: PitFundamentalsStore) -> int:
    """Delete progress rows that completed with 0 rows.

    The original bulk run marked rate-limited empty responses as "done" (row_count
    0), permanently skipping legitimate stocks. Clearing those lets a resume retry
    them; genuinely-absent symbols simply re-confirm as empty (cheap) and re-mark.
    """
    ensure_progress_table(store)
    with store._connect() as conn:
        cur = conn.execute("DELETE FROM fundamentals_backfill_progress WHERE row_count = 0")
        return int(cur.rowcount or 0)


def has_dataset_since_start(store: PitFundamentalsStore, stock_id: str, dataset: str, start_date: str) -> bool:
    """Return True when a previous run has already stored this stock/dataset.

    New M2 broad runs record explicit completion by requested start date. For
    legacy J1 databases without that progress table, fall back to the stored
    minimum effective date so an old 2017-only run is not mistaken for a 2010
    backfill.
    """

    ensure_progress_table(store)
    with store._connect() as conn:
        progress = conn.execute(
            """
            SELECT 1
            FROM fundamentals_backfill_progress
            WHERE stock_id = ? AND dataset = ? AND start_date <= ?
            LIMIT 1
            """,
            (str(stock_id), dataset, start_date),
        ).fetchone()
    if progress:
        return True

    table, date_col = DATASET_TABLES[dataset]
    with store._connect() as conn:
        row = conn.execute(
            f"SELECT MIN({date_col}) FROM {table} WHERE stock_id = ?",
            (str(stock_id),),
        ).fetchone()
    min_date = row[0] if row else None
    return bool(min_date and str(min_date)[:10] <= start_date)


def table_row_counts(store: PitFundamentalsStore) -> dict[str, int]:
    return {table: store.row_count(table) for table, _date_col in DATASET_TABLES.values()}


def normalize_dataset(dataset: str, stock_id: str, rows: list[dict]) -> list[dict]:
    if dataset == "TaiwanStockMonthRevenue":
        return [_normalize_month_revenue(stock_id, row) for row in rows if _date_value(row)]
    if dataset == "TaiwanStockInstitutionalInvestorsBuySell":
        return _normalize_institutional(stock_id, rows)
    if dataset == "TaiwanStockMarginPurchaseShortSale":
        return [_normalize_margin(stock_id, row) for row in rows if _date_value(row)]
    if dataset == "TaiwanStockPER":
        return [_normalize_per(stock_id, row) for row in rows if _date_value(row)]
    if dataset == "TaiwanStockFinancialStatements":
        return _normalize_financials(stock_id, rows)
    if dataset == "TaiwanStockBalanceSheet":
        return _normalize_balance_sheet(stock_id, rows)
    if dataset == "TaiwanStockCashFlowsStatement":
        return _normalize_cash_flow(stock_id, rows)
    raise ValueError(f"Unsupported dataset: {dataset}")


# FinMind cash-flow operating line item (primary, then fallback alias).
_CFO_TYPES = ("CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities")


def _normalize_cash_flow(stock_id: str, rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        period_end = _date_value(row)
        if not period_end:
            continue
        out = grouped.setdefault(
            period_end,
            {
                "stock_id": stock_id,
                "period_end": period_end,
                "filing_date": row.get("filing_date") or row.get("announcement_date") or row.get("publish_date"),
                "cfo": None,
                "raw_rows": [],
            },
        )
        type_code = str(row.get("type") or "")
        value = _float_value(row, "value", "Value")
        if value is not None and type_code in _CFO_TYPES and out["cfo"] is None:
            out["cfo"] = value
        out["raw_rows"].append(row)
    normalized = []
    for out in grouped.values():
        raw_rows = out.pop("raw_rows")
        out["raw_json"] = json.dumps(raw_rows, ensure_ascii=False, sort_keys=True)
        normalized.append(out)
    return normalized


def _normalize_balance_sheet(stock_id: str, rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        period_end = _date_value(row)
        if not period_end:
            continue
        out = grouped.setdefault(
            period_end,
            {
                "stock_id": stock_id,
                "period_end": period_end,
                "filing_date": row.get("filing_date") or row.get("announcement_date") or row.get("publish_date"),
                "equity": None,
                "equity_parent": None,
                "raw_rows": [],
            },
        )
        type_code = str(row.get("type") or "")
        value = _float_value(row, "value", "Value")
        if value is not None:
            if type_code == "Equity" and out["equity"] is None:
                out["equity"] = value
            elif type_code == "EquityAttributableToOwnersOfParent" and out["equity_parent"] is None:
                out["equity_parent"] = value
        out["raw_rows"].append(row)
    normalized = []
    for out in grouped.values():
        raw_rows = out.pop("raw_rows")
        out["raw_json"] = json.dumps(raw_rows, ensure_ascii=False, sort_keys=True)
        normalized.append(out)
    return normalized


def _normalize_month_revenue(stock_id: str, row: dict) -> dict:
    return {
        "stock_id": stock_id,
        "date": _date_value(row),
        "revenue": _float_value(row, "revenue", "Revenue"),
        # FinMind monthly revenue ships no YoY/MoM (only revenue + revenue_year +
        # revenue_month, which are date parts, NOT growth rates). Leave these null;
        # YoY is computed downstream from the revenue series.
        "revenue_yoy": _float_value(row, "revenue_yoy", "YoY"),
        "revenue_mom": _float_value(row, "revenue_mom", "MoM"),
        "raw_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
    }


def _normalize_institutional(stock_id: str, rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        date_value = _date_value(row)
        if not date_value:
            continue
        out = grouped.setdefault(
            date_value,
            {
                "stock_id": stock_id,
                "date": date_value,
                "foreign_net": 0.0,
                "trust_net": 0.0,
                "dealer_net": 0.0,
                "raw_rows": [],
            },
        )
        name = str(row.get("name") or row.get("institutional_investors") or "")
        net = _float_value(row, "buy_sell", "buy_sell_difference", "net")
        if net is None:
            buy = _float_value(row, "buy", "Buy") or 0.0
            sell = _float_value(row, "sell", "Sell") or 0.0
            net = buy - sell
        if name in {"Foreign_Investor", "Foreign_Dealer_Self"}:
            out["foreign_net"] += net
        elif name == "Investment_Trust":
            out["trust_net"] += net
        elif name in {"Dealer_self", "Dealer", "Dealer_Hedging"}:
            out["dealer_net"] += net
        out["raw_rows"].append(row)
    normalized = []
    for out in grouped.values():
        raw_rows = out.pop("raw_rows")
        out["raw_json"] = json.dumps(raw_rows, ensure_ascii=False, sort_keys=True)
        normalized.append(out)
    return normalized


def _normalize_margin(stock_id: str, row: dict) -> dict:
    return {
        "stock_id": stock_id,
        "date": _date_value(row),
        "margin_balance": _float_value(row, "MarginPurchaseTodayBalance", "margin_balance"),
        "short_balance": _float_value(row, "ShortSaleTodayBalance", "short_balance"),
        "raw_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
    }


def _normalize_per(stock_id: str, row: dict) -> dict:
    return {
        "stock_id": stock_id,
        "date": _date_value(row),
        "per": _float_value(row, "PER", "per"),
        "pbr": _float_value(row, "PBR", "pbr"),
        "dividend_yield": _float_value(row, "dividend_yield", "DividendYield"),
        "raw_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
    }


def _normalize_financials(stock_id: str, rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        period_end = _date_value(row)
        if not period_end:
            continue
        out = grouped.setdefault(
            period_end,
            {
                "stock_id": stock_id,
                "period_end": period_end,
                "filing_date": row.get("filing_date") or row.get("announcement_date") or row.get("publish_date"),
                "eps": None,
                "roe": None,
                "gross_margin": None,
                "operating_margin": None,
                "net_margin": None,
                "raw_rows": [],
            },
        )
        key = _financial_metric_key(row)
        value = _float_value(row, "value", "Value")
        if key in {"eps", "roe", "gross_margin", "operating_margin", "net_margin"} and value is not None:
            out[key] = value
        type_code = str(row.get("type") or "")
        if type_code and value is not None:
            out.setdefault("_items", {}).setdefault(type_code, value)
        out["raw_rows"].append(row)
    normalized = []
    for out in grouped.values():
        _fill_margins_from_items(out, out.pop("_items", {}))
        raw_rows = out.pop("raw_rows")
        out["raw_json"] = json.dumps(raw_rows, ensure_ascii=False, sort_keys=True)
        normalized.append(out)
    return normalized


def _fill_margins_from_items(out: dict, items: dict[str, float]) -> None:
    """Derive margins from FinMind income-statement line items.

    FinMind FinancialStatements provides raw line items (Revenue, GrossProfit,
    OperatingIncome, IncomeAfterTaxes) by `type` — it does NOT ship ready-made
    margin or ROE fields. ROE additionally needs balance-sheet equity (a separate
    dataset) and is intentionally left null here.
    """
    revenue = items.get("Revenue")
    if not revenue:
        return
    if out.get("gross_margin") is None and items.get("GrossProfit") is not None:
        out["gross_margin"] = items["GrossProfit"] / revenue
    if out.get("operating_margin") is None and items.get("OperatingIncome") is not None:
        out["operating_margin"] = items["OperatingIncome"] / revenue
    if out.get("net_margin") is None and items.get("IncomeAfterTaxes") is not None:
        out["net_margin"] = items["IncomeAfterTaxes"] / revenue


def _financial_metric_key(row: dict) -> str | None:
    metric = str(row.get("type") or row.get("account") or row.get("name") or "").lower()
    if metric in {"eps", "basic_eps", "基本每股盈餘"}:
        return "eps"
    if metric in {"roe", "return_on_equity"}:
        return "roe"
    if "gross" in metric and "margin" in metric:
        return "gross_margin"
    if "operating" in metric and "margin" in metric:
        return "operating_margin"
    if "net" in metric and "margin" in metric:
        return "net_margin"
    return None


def _upsert_dataset(store: PitFundamentalsStore, dataset: str, rows: list[dict]) -> int:
    if dataset == "TaiwanStockMonthRevenue":
        return store.upsert_month_revenue(rows)
    if dataset == "TaiwanStockInstitutionalInvestorsBuySell":
        return store.upsert_institutional(rows)
    if dataset == "TaiwanStockMarginPurchaseShortSale":
        return store.upsert_margin(rows)
    if dataset == "TaiwanStockPER":
        return store.upsert_per(rows)
    if dataset == "TaiwanStockFinancialStatements":
        return store.upsert_financials(rows)
    if dataset == "TaiwanStockBalanceSheet":
        return store.upsert_balance_sheet(rows)
    if dataset == "TaiwanStockCashFlowsStatement":
        return store.upsert_cash_flow(rows)
    raise ValueError(f"Unsupported dataset: {dataset}")


def _date_value(row: dict) -> str | None:
    value = row.get("date") or row.get("period_end")
    return str(value)[:10] if value else None


def _float_value(row: dict, *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _load_backend_env() -> None:
    """Load backend/.env so standalone script runs see FINMIND_API_KEY."""
    from backend.scripts._env import load_backend_env
    load_backend_env()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2017-01-01", help="Inclusive start date YYYY-MM-DD")
    parser.add_argument("--stocks", nargs="*", help="Override universe with explicit stock codes")
    parser.add_argument(
        "--universe-source",
        choices=("ai_tech", "broad", "all", "ohlcv"),
        default="ai_tech",
        help="Universe source when --stocks is not provided. broad=FinMind TaiwanStockInfo tech industries; all=every listed common stock (all industries, ETFs excluded); ohlcv=HistoricalDataStore.list_stocks().",
    )
    parser.add_argument(
        "--universe-file",
        default=str(Path(__file__).resolve().parent.parent / "data" / "sectors" / "ai_tech_tw.json"),
    )
    parser.add_argument("--db", default=str(DEFAULT_PIT_DB_PATH))
    parser.add_argument("--ohlcv-db", default=str(DEFAULT_DB_PATH), help="OHLCV SQLite path used by --universe-source ohlcv")
    parser.add_argument("--rate-limit", type=float, default=1.0, help="Sleep seconds between FinMind requests")
    parser.add_argument("--datasets", nargs="*", choices=DATASETS, default=list(DATASETS))
    parser.add_argument("--no-resume", action="store_true", help="Fetch every stock/dataset even if rows already exist")
    parser.add_argument("--retry-empty", action="store_true", help="Clear progress rows that completed with 0 rows so rate-limited/falsely-skipped stocks are retried")
    parser.add_argument("--max-consecutive-failures", type=int, default=25, help="Stop after this many consecutive failed fetches (free-tier rate limit reached); re-run later to resume")
    parser.add_argument("--auto-resume", action="store_true", help="When the rate limit is hit, sleep ~60 min (rolling-window reset) and resume automatically; repeat until a full pass completes")
    parser.add_argument("--max-passes", type=int, default=48, help="Safety cap on auto-resume passes")
    parser.add_argument("--resume-wait-minutes", type=float, default=61.0, help="Minutes to sleep on rate limit before resuming (FinMind free tier = rolling 60-min window)")
    parser.add_argument("--no-progress", action="store_true", help="Disable the live progress bar (e.g. when piping output to a file)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _load_backend_env()
    token = os.getenv("FINMIND_API_KEY") or os.getenv("FINMIND_TOKEN")
    if not token:
        logger.error("FINMIND_API_KEY is required (checked env + backend/.env)")
        return 2

    try:
        stocks = resolve_universe_symbols(
            stocks=args.stocks,
            universe_source=args.universe_source,
            universe_file=args.universe_file,
            ohlcv_db=args.ohlcv_db,
        )
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    if not stocks:
        logger.error("%s universe resolved to zero stocks", args.universe_source)
        return 2

    store = PitFundamentalsStore(args.db)
    if args.retry_empty:
        cleared = clear_empty_progress(store)
        logger.info("Cleared %d empty (0-row) progress entries for retry", cleared)
    before_counts = table_row_counts(store)
    logger.info("Backfilling %d stocks × %d datasets to %s", len(stocks), len(args.datasets), args.db)
    logger.info("Starting table row counts: %s", before_counts)
    start_time = time.time()

    def run_pass() -> tuple[dict[str, int], bool]:
        return asyncio.run(
            download_all(
                stocks=stocks,
                datasets=list(args.datasets),
                start_date=args.start,
                token=token,
                store=store,
                rate_limit=float(args.rate_limit),
                resume=not bool(args.no_resume),
                show_progress=not bool(args.no_progress),
                max_consecutive_failures=int(args.max_consecutive_failures),
            )
        )

    if args.auto_resume:
        for pass_no in range(1, int(args.max_passes) + 1):
            counts, stopped_early = run_pass()
            logger.info("Pass %d: +%d rows, stopped_early=%s", pass_no, sum(counts.values()), stopped_early)
            if not stopped_early:
                logger.info("Backfill completed a full pass without hitting the rate limit — done.")
                break
            # FinMind free tier is a ROLLING 60-minute window (not clock-hour aligned),
            # so wait a full ~60 min from now for the quota to clear.
            wait = float(args.resume_wait_minutes) * 60.0
            logger.info("Rate limit reached; sleeping %.0f min (rolling-window reset) before resuming...", wait / 60.0)
            time.sleep(wait)
        counts = table_row_counts(store)
    else:
        counts, _stopped = run_pass()

    elapsed = time.time() - start_time
    after_counts = table_row_counts(store)
    logger.info("Done in %.1f seconds. Newly written row counts: %s", elapsed, counts)
    logger.info("Final table row counts: %s", after_counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
