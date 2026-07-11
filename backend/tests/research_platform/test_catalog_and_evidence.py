from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.research_platform.catalog import inspect_crypto_sqlite
from backend.app.research_platform.evidence import parse_legacy_report
from backend.app.research_platform.schemas import DataTier


def test_catalog_keeps_missing_oi_explicit(market_db: Path) -> None:
    asset = inspect_crypto_sqlite(
        market_db,
        now=datetime(2026, 7, 10, 1, 30, tzinfo=timezone.utc),
    )

    assert asset.data_tier == DataTier.PRICE_FUNDING_ONLY
    assert asset.oi_available is False
    assert asset.premium_available is False
    assert asset.funding_rows == 1
    assert max(item.symbols for item in asset.intervals) == 2
    assert asset.sampled_ohlc_violations == 0
    assert any("Missing OI" in warning for warning in asset.warnings)


def test_catalog_rejects_empty_store(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    path.touch()
    with pytest.raises(ValueError, match="empty"):
        inspect_crypto_sqlite(path)


def test_legacy_report_before_oos_is_train_but_never_candidate_evidence(runs_path: Path) -> None:
    report = next(runs_path.glob("*/report.txt"))
    experiment = parse_legacy_report(report)

    assert experiment.dataset_role == "TRAIN"
    assert experiment.tuning_allowed is True
    assert experiment.profit_factor == pytest.approx(0.88)
    assert experiment.win_rate == pytest.approx(0.425)
    assert experiment.is_mock is False
    assert experiment.higher_timeframe_policy == "closed_only"
    assert experiment.quality_findings_count == 1
    assert experiment.sample_adequate is False
    assert any("cannot promote" in warning for warning in experiment.warnings)


def test_legacy_report_crossing_oos_is_sealed(runs_path: Path) -> None:
    report = next(runs_path.glob("*/report.txt"))
    text = report.read_text(encoding="utf-8").replace(
        "2026-05-31T00:00:00Z", "2026-07-01T00:00:00Z"
    )
    sealed = report.parent / "sealed.txt"
    sealed.write_text(text, encoding="utf-8")

    experiment = parse_legacy_report(sealed)

    assert experiment.dataset_role == "LOCKED_OR_FORWARD_EVIDENCE"
    assert experiment.tuning_allowed is False
    assert any("optimizer access is forbidden" in warning for warning in experiment.warnings)
