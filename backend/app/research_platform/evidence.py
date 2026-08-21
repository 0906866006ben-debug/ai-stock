from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .schemas import ExperimentSummary


OOS_BOUNDARY = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _parse_datetime(value: str) -> datetime | None:
    value = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_number(value: str | None, *, percent: bool = False) -> float | None:
    if value is None or value.strip() in {"", "-", "None", "nan"}:
        return None
    raw = value.strip().rstrip("%")
    try:
        number = float(raw)
    except ValueError:
        return None
    return number / 100.0 if percent or value.strip().endswith("%") else number


def parse_legacy_report(path: Path, *, imported_at: datetime | None = None) -> ExperimentSummary:
    imported_at = imported_at or datetime.now(timezone.utc)
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    def line_value(prefix: str) -> str:
        match = re.search(rf"(?m)^{re.escape(prefix)}=(.*)$", text)
        return match.group(1).strip() if match else ""

    variant = line_value("variant").split(" cost=", 1)[0] or path.parent.name
    period = re.search(r"(?m)^period=(.*?) to (.*?)$", text)
    start = _parse_datetime(period.group(1)) if period else None
    end = _parse_datetime(period.group(2)) if period else None
    overview = re.search(
        r"(?m)^trades=(\d+) win_rate=([^ ]+) totalR=([^ ]+) avgR=([^ ]+) PF=([^ ]+) netPnL=([^ ]+)$",
        text,
    )
    risk = re.search(
        r"(?m)^CAGR=([^ ]+) maxDD_R=([^ ]+) Sharpe=([^ ]+) exposure=([^ ]+) turnover=([^ ]+)$",
        text,
    )
    if not overview:
        raise ValueError(f"legacy report is missing overview metrics: {path}")

    role = "UNKNOWN"
    tuning_allowed = False
    warnings = [
        "Legacy artifact lacks a complete engine/data manifest and cannot promote a candidate by itself.",
        "Historical OI is unavailable; this is not a full-five-factor validation.",
    ]
    if start and end:
        if end > OOS_BOUNDARY:
            role = "LOCKED_OR_FORWARD_EVIDENCE"
            warnings.append("Period crosses the sealed 2026-06-01 boundary; optimizer access is forbidden.")
        else:
            role = "TRAIN"
            tuning_allowed = True

    artifact_hash = hashlib.sha256(raw).hexdigest()
    policy_match = re.search(
        r"(?m)^Higher-timeframe policy: (closed_only|partial_live_mirror)\.\s*$",
        text,
    )
    quality_findings_count = len(re.findall(r"(?m)^- .*?(?:excluded|skipped|missing)", text, flags=re.IGNORECASE))
    trades = int(overview.group(1))
    return ExperimentSummary(
        experiment_id=f"legacy:{artifact_hash[:20]}",
        variant=variant,
        hypothesis=line_value("hypothesis") or "Legacy experiment; hypothesis not recorded",
        period_start=start,
        period_end=end,
        dataset_role=role,
        tuning_allowed=tuning_allowed,
        trades=trades,
        win_rate=_optional_number(overview.group(2), percent=True),
        total_r=_optional_number(overview.group(3)) or 0.0,
        average_r=_optional_number(overview.group(4)),
        profit_factor=_optional_number(overview.group(5)),
        net_pnl=_optional_number(overview.group(6)) or 0.0,
        cagr=_optional_number(risk.group(1), percent=True) if risk else None,
        max_drawdown_r=_optional_number(risk.group(2)) if risk else None,
        sharpe=_optional_number(risk.group(3)) if risk else None,
        exposure=_optional_number(risk.group(4), percent=True) if risk else None,
        turnover=_optional_number(risk.group(5)) if risk else None,
        source_path=str(path.resolve()),
        artifact_hash=artifact_hash,
        data_version="legacy-cache-unversioned",
        engine_version="crypto_backtester-legacy",
        imported_at=imported_at,
        higher_timeframe_policy=policy_match.group(1) if policy_match else "unknown",
        quality_findings_count=quality_findings_count,
        sample_adequate=trades >= 100,
        warnings=warnings,
    )


def discover_legacy_experiments(runs_path: Path) -> list[ExperimentSummary]:
    if not runs_path.exists():
        return []
    experiments: list[ExperimentSummary] = []
    for report in sorted(runs_path.glob("*/report.txt")):
        try:
            experiments.append(parse_legacy_report(report))
        except (OSError, ValueError):
            continue
    return experiments
