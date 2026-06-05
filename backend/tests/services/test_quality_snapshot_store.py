from __future__ import annotations

from backend.app.models.quality_snapshot import QuarterlySnapshot, SnapshotStock
from backend.app.services.quality_snapshot_store import QualitySnapshotStore
from backend.scripts import generate_quality_snapshot as gqs


def _snapshot(quarter: str, score: float = 75.0) -> QuarterlySnapshot:
    return QuarterlySnapshot(
        quarter=quarter,
        as_of_date=f"{quarter[:4]}-03-31" if quarter.endswith("Q1") else f"{quarter[:4]}-06-30",
        generated_at="2026-04-01T00:00:00+00:00",
        snapshot_stocks=[
            SnapshotStock(
                symbol="2330",
                name="台積電",
                durability_score=score,
                durability_components={"op_margin_stability": 0.9},
                confidence=90,
            )
        ],
    )


def test_quality_snapshot_round_trip(tmp_path):
    store = QualitySnapshotStore(tmp_path / "quality.db")
    snapshot = _snapshot("2026-Q1")
    store.write_snapshot(snapshot)

    loaded = store.read_snapshot("2026-Q1")
    assert loaded is not None
    assert loaded.quarter == "2026-Q1"
    assert loaded.snapshot_stocks[0].symbol == "2330"
    assert loaded.snapshot_stocks[0].durability_components["op_margin_stability"] == 0.9


def test_quality_snapshot_latest_and_history(tmp_path):
    store = QualitySnapshotStore(tmp_path / "quality.db")
    store.write_snapshot(_snapshot("2026-Q1"))
    store.write_snapshot(_snapshot("2026-Q2", score=80))

    latest = store.get_latest_snapshot()
    assert latest is not None
    assert latest.quarter == "2026-Q2"

    history = store.list_quarters()
    assert [item.quarter for item in history] == ["2026-Q2", "2026-Q1"]
    assert history[0].stock_count == 1


def test_tech_snapshot_does_not_fallback_to_all_symbols(tmp_path, monkeypatch):
    monkeypatch.setattr(gqs, "fundamentals_covered_symbols", lambda _path: ["2330", "1101"])
    monkeypatch.setattr(gqs, "get_tech_universe_symbols", lambda: [])

    snapshot = gqs.generate_quality_snapshot(
        quarter="2026-Q1",
        as_of_date="2026-03-31",
        pit_db_path=tmp_path / "pit.db",
        ohlcv_db_path=tmp_path / "ohlcv.db",
        snapshot_db_path=tmp_path / "quality.db",
        output_dir=tmp_path,
        universe_source="tech",
    )

    assert snapshot.snapshot_stocks == []
    assert snapshot.status == "no_data"
    assert snapshot.warnings
