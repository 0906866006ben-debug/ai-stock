"""Probe candidate data sources for CANSLIM expansion.

Probe only: this script performs small sample requests and writes an availability
report. It does not backfill data and it never logs the FinMind token.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx

FINMIND_BASE = "https://api.finmindtrade.com/api/v4"
DEFAULT_OUTPUT_DIR = Path("artifacts/data_probe")


@dataclass
class ProbeResult:
    source: str
    dataset: str
    available: bool
    earliest_date: str | None = None
    cadence: str = "unknown"
    fields: list[str] = field(default_factory=list)
    pit_usable: bool = False
    notes: str = ""
    recommendation: str = "limited"


def main(argv: list[str] | None = None) -> int:
    _load_backend_env()
    parser = argparse.ArgumentParser(description="Probe CANSLIM data-expansion source availability.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--symbol", default="2330")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--days", type=int, default=45, help="Recent sample window for most probes")
    args = parser.parse_args(argv)

    token = os.getenv("FINMIND_API_KEY", "")
    if not token:
        raise SystemExit("FINMIND_API_KEY is required for the real probe.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=20.0) as client:
        report = run_probe(
            token=token,
            symbol=args.symbol,
            start=args.start,
            days=args.days,
            finmind_get=lambda endpoint, params: _finmind_get(client, endpoint, params),
            yf_download=_yfinance_download,
        )

    write_reports(report, output_dir, token=token)
    print(f"Wrote {output_dir / 'availability_report.md'}")
    print(f"Wrote {output_dir / 'availability_report.json'}")
    return 0


def _load_backend_env() -> None:
    from backend.scripts._env import load_backend_env
    load_backend_env()


def run_probe(
    *,
    token: str,
    symbol: str = "2330",
    start: str = "2010-01-01",
    days: int = 45,
    finmind_get: Callable[[str, dict[str, Any]], dict[str, Any]],
    yf_download: Callable[[str, str], Any],
) -> dict[str, Any]:
    catalog_payload = _try_dataset_catalog(token, finmind_get)
    catalog_names = parse_dataset_names(catalog_payload)
    recent_start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    today = date.today().strftime("%Y-%m-%d")

    results: list[ProbeResult] = []
    results.extend(_probe_finmind_candidates(
        source="News / announcements",
        candidates=[
            "TaiwanStockNews",
            "TaiwanStockAnnouncement",
            "TaiwanStockInvestorConference",
            "TaiwanStockBoardMeeting",
        ],
        catalog_names=catalog_names,
        token=token,
        symbol=symbol,
        start=start,
        end=today,
        finmind_get=finmind_get,
        cadence_hint="event",
        pit_hint=True,
    ))
    results.extend(_probe_finmind_candidates(
        source="Day-trade ratio",
        candidates=[
            "TaiwanStockDayTrading",
            "TaiwanStockDayTradingRatio",
            "TaiwanStockDayTradingInfo",
        ],
        catalog_names=catalog_names,
        token=token,
        symbol=symbol,
        start=recent_start,
        end=today,
        finmind_get=finmind_get,
        cadence_hint="daily",
        pit_hint=True,
    ))
    results.extend(_probe_finmind_candidates(
        source="Shareholder concentration / holder count",
        candidates=[
            "TaiwanStockHoldingSharesPer",
            "TaiwanStockSharesHolding",
            "TaiwanStockShareholding",
            "TaiwanStockShareholdingDistribution",
            "TaiwanStockHoldingShares",
        ],
        catalog_names=catalog_names,
        token=token,
        symbol=symbol,
        start=start,
        end=today,
        finmind_get=finmind_get,
        cadence_hint="weekly/monthly",
        pit_hint=True,
    ))
    results.extend(_probe_finmind_candidates(
        source="TW sector indices",
        candidates=[
            "TaiwanStockMarketIndex",
            "TaiwanStockIndustryIndex",
            "TaiwanStockSectorIndex",
            "TaiwanStockTotalReturnIndex",
        ],
        catalog_names=catalog_names,
        token=token,
        symbol="",
        start=recent_start,
        end=today,
        finmind_get=finmind_get,
        cadence_hint="daily",
        pit_hint=True,
    ))
    results.extend(_probe_finmind_candidates(
        source="Cash-flow statement (CFO for earnings quality / F-Score)",
        candidates=[
            "TaiwanStockCashFlowsStatement",
            "TaiwanStockCashFlow",
            "TaiwanStockStatementOfCashFlows",
        ],
        catalog_names=catalog_names,
        token=token,
        symbol=symbol,
        start=start,
        end=today,
        finmind_get=finmind_get,
        cadence_hint="quarterly",
        pit_hint=True,
    ))
    results.append(_probe_taiwan_stock_info(catalog_names, token, finmind_get))
    results.extend(_probe_yfinance_indices(yf_download, start="2010-01-01"))

    payload = {
        "generated_at": date.today().isoformat(),
        "sample_symbol": symbol,
        "dataset_catalog_available": bool(catalog_names),
        "dataset_catalog_count": len(catalog_names),
        "results": [asdict(result) for result in results],
    }
    return sanitize_report(payload, token)


def parse_dataset_names(payload: dict[str, Any] | None) -> set[str]:
    names: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in {"dataset", "dataset_name", "name", "data_name"} and isinstance(item, str):
                    if item.startswith("Taiwan") or item.startswith("Tai"):
                        names.add(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and value.startswith("Taiwan"):
            names.add(value)

    if payload:
        walk(payload)
    return names


def write_reports(report: dict[str, Any], output_dir: Path, *, token: str = "") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    clean = sanitize_report(report, token)
    (output_dir / "availability_report.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "availability_report.md").write_text(render_markdown(clean), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    rows = report.get("results", [])
    lines = [
        "# Data Expansion Availability Probe",
        "",
        f"- Generated: {report.get('generated_at')}",
        f"- Sample symbol: {report.get('sample_symbol')}",
        f"- Dataset catalog available: {report.get('dataset_catalog_available')}",
        f"- Dataset catalog count: {report.get('dataset_catalog_count')}",
        "",
        "| Source | Dataset | Available | Earliest | Cadence | Fields | PIT-usable | Recommendation | Notes |",
        "|---|---:|---:|---:|---:|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {source} | {dataset} | {available} | {earliest} | {cadence} | {fields} | {pit} | {rec} | {notes} |".format(
                source=_md(row.get("source")),
                dataset=_md(row.get("dataset")),
                available="Y" if row.get("available") else "N",
                earliest=_md(row.get("earliest_date") or "-"),
                cadence=_md(row.get("cadence") or "unknown"),
                fields=_md(", ".join(row.get("fields") or []) or "-"),
                pit="Y" if row.get("pit_usable") else "N",
                rec=_md(row.get("recommendation")),
                notes=_md(row.get("notes")),
            )
        )
    lines.append("")
    lines.append("## Per-source recommendation")
    for row in rows:
        lines.append(f"- **{_md(row.get('source'))} / {_md(row.get('dataset'))}**: {_md(row.get('recommendation'))}. {_md(row.get('notes'))}")
    lines.append("")
    return "\n".join(lines)


def sanitize_report(value: Any, token: str = "") -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_report(item, token) for key, item in value.items() if str(key).lower() not in {"token", "api_key", "authorization"}}
    if isinstance(value, list):
        return [sanitize_report(item, token) for item in value]
    if isinstance(value, str):
        clean = value
        if token:
            clean = clean.replace(token, "[REDACTED]")
        return clean
    return value


def _try_dataset_catalog(token: str, finmind_get: Callable[[str, dict[str, Any]], dict[str, Any]]) -> dict[str, Any] | None:
    for endpoint, params in [
        ("datasets", {"token": token}),
        ("dataset", {"token": token}),
        ("data", {"dataset": "TaiwanStockInfo", "token": token}),
    ]:
        try:
            payload = finmind_get(endpoint, params)
            if payload:
                return payload
        except Exception:
            continue
    return None


def _probe_finmind_candidates(
    *,
    source: str,
    candidates: list[str],
    catalog_names: set[str],
    token: str,
    symbol: str,
    start: str,
    end: str,
    finmind_get: Callable[[str, dict[str, Any]], dict[str, Any]],
    cadence_hint: str,
    pit_hint: bool,
) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    names_to_try = _verified_or_candidate_names(candidates, catalog_names)
    for dataset in names_to_try:
        verified = not catalog_names or dataset in catalog_names
        params = {"dataset": dataset, "start_date": start, "end_date": end, "token": token}
        if symbol:
            params["data_id"] = symbol
        try:
            payload = finmind_get("data", params)
            rows = _payload_rows(payload)
            fields = sorted({key for row in rows[:5] for key in row.keys()})
            available = bool(rows) and _payload_ok(payload)
            results.append(ProbeResult(
                source=source,
                dataset=dataset,
                available=available,
                earliest_date=_earliest_date(rows),
                cadence=_infer_cadence(rows, cadence_hint),
                fields=fields,
                pit_usable=available and pit_hint and _has_date_field(fields),
                notes=_notes(payload, verified, rows),
                recommendation=_recommendation(available, pit_hint and _has_date_field(fields), verified),
            ))
        except Exception as exc:
            results.append(ProbeResult(
                source=source,
                dataset=dataset,
                available=False,
                cadence=cadence_hint,
                notes=f"sample request failed: {type(exc).__name__}; verified={verified}",
                recommendation="not available",
            ))
    return results


def _probe_taiwan_stock_info(catalog_names: set[str], token: str, finmind_get: Callable[[str, dict[str, Any]], dict[str, Any]]) -> ProbeResult:
    dataset = "TaiwanStockInfo"
    verified = not catalog_names or dataset in catalog_names
    try:
        payload = finmind_get("data", {"dataset": dataset, "token": token})
        rows = _payload_rows(payload)
        listed = [
            row for row in rows
            if str(row.get("type") or row.get("stock_type") or "").lower() in {"twse", "tpex", "上市", "上櫃"}
            or str(row.get("market") or "").upper() in {"TWSE", "TPEX"}
        ]
        count = len(listed) or len(rows)
        fields = sorted({key for row in rows[:10] for key in row.keys()})
        return ProbeResult(
            source="Full TWSE+TPEX universe",
            dataset=dataset,
            available=bool(rows),
            cadence="current snapshot",
            fields=fields,
            pit_usable=False,
            notes=f"verified={verified}; current listed count estimate={count}; current-list survivorship bias remains",
            recommendation="backfill-worthy for current universe only" if rows else "not available",
        )
    except Exception as exc:
        return ProbeResult(
            source="Full TWSE+TPEX universe",
            dataset=dataset,
            available=False,
            cadence="current snapshot",
            notes=f"sample request failed: {type(exc).__name__}; verified={verified}",
            recommendation="not available",
        )


def _probe_yfinance_indices(yf_download: Callable[[str, str], Any], *, start: str) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    for ticker, source in [("^SOX", "SOX via yfinance"), ("^IXIC", "Nasdaq via yfinance")]:
        try:
            df = yf_download(ticker, start)
            empty = bool(getattr(df, "empty", True))
            columns = [str(col) for col in list(getattr(df, "columns", []))]
            earliest = None
            if not empty:
                idx = getattr(df, "index", [])
                if len(idx):
                    earliest = str(idx.min())[:10]
            results.append(ProbeResult(
                source=source,
                dataset=ticker,
                available=not empty,
                earliest_date=earliest,
                cadence="daily",
                fields=columns,
                pit_usable=not empty,
                notes="external index via yfinance; not FinMind PIT but dated market data",
                recommendation="backfill-worthy now" if not empty else "not available",
            ))
        except Exception as exc:
            results.append(ProbeResult(
                source=source,
                dataset=ticker,
                available=False,
                cadence="daily",
                notes=f"yfinance request failed: {type(exc).__name__}",
                recommendation="not available",
            ))
    return results


def _finmind_get(client: httpx.Client, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    url = f"{FINMIND_BASE}/{endpoint.lstrip('/')}"
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def _yfinance_download(ticker: str, start: str):
    import yfinance as yf

    return yf.download(ticker, start=start, progress=False, auto_adjust=False, threads=False)


def _verified_or_candidate_names(candidates: list[str], catalog_names: set[str]) -> list[str]:
    if not catalog_names:
        return candidates
    lower_candidates = [name.lower() for name in candidates]
    matched = [name for name in catalog_names if name.lower() in lower_candidates]
    fuzzy = [
        name for name in catalog_names
        if any(token in name.lower() for token in _candidate_tokens(candidates))
    ]
    ordered = []
    for name in [*matched, *fuzzy, *candidates]:
        if name not in ordered:
            ordered.append(name)
    return ordered[:8]


def _candidate_tokens(candidates: list[str]) -> set[str]:
    tokens: set[str] = set()
    for name in candidates:
        lowered = name.lower()
        for token in ["news", "announcement", "conference", "daytrading", "holding", "share", "industry", "sector", "index"]:
            if token in lowered:
                tokens.add(token)
    return tokens


def _payload_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _payload_ok(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    return status in {None, 200, "200", True}


def _earliest_date(rows: list[dict[str, Any]]) -> str | None:
    dates: list[str] = []
    for row in rows:
        for key in ["date", "published_at", "announcement_date", "start_date"]:
            value = row.get(key)
            if value:
                dates.append(str(value)[:10])
                break
    return min(dates) if dates else None


def _infer_cadence(rows: list[dict[str, Any]], fallback: str) -> str:
    if not rows:
        return fallback
    fields = {key.lower() for row in rows[:5] for key in row.keys()}
    if "week" in fields:
        return "weekly"
    if "month" in fields or "revenue_month" in fields:
        return "monthly"
    return fallback


def _has_date_field(fields: list[str]) -> bool:
    lowered = {field.lower() for field in fields}
    return bool({"date", "published_at", "announcement_date", "start_date"} & lowered)


def _notes(payload: dict[str, Any], verified: bool, rows: list[dict[str, Any]]) -> str:
    msg = str(payload.get("msg") or payload.get("message") or "").strip()
    parts = [f"verified_by_dataset_list={verified}", f"sample_rows={len(rows)}"]
    if msg:
        parts.append(f"api_message={msg[:160]}")
    return "; ".join(parts)


def _recommendation(available: bool, pit_usable: bool, verified: bool) -> str:
    if available and pit_usable and verified:
        return "backfill-worthy now"
    if available and pit_usable:
        return "limited - dataset-list verification unavailable"
    if available:
        return "limited"
    return "not available"


def _md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
