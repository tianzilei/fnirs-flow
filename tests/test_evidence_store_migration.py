from __future__ import annotations

import csv
from pathlib import Path

from fnirs_flow.evidence import VersionedEvidenceStore, migrate_legacy_csv
from fnirs_flow.registry.methodatom_library import PACKAGE_LIBRARY_DIR


def _write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _library(root: Path) -> None:
    _write(
        root / "sources.csv",
        ["source_id", "study_id", "title", "year", "source_type", "source_path_or_url"],
        [{
            "source_id": "S1", "study_id": "ST1", "title": "Paper", "year": "2025",
            "source_type": "paper", "source_path_or_url": "paper.md",
        }],
    )
    _write(
        root / "atom_evidence_links.csv",
        [
            "link_id", "source_id", "target_object_type", "target_object_id", "evidence_use",
            "confidence", "quote_or_summary",
        ],
        [
            {
                "link_id": "L1", "source_id": "S1", "target_object_type": "method_atom",
                "target_object_id": "A1", "evidence_use": "method_atom", "confidence": "high",
                "quote_or_summary": "summary",
            },
            {
                "link_id": "L2", "source_id": "MISSING", "target_object_type": "",
                "target_object_id": "", "evidence_use": "background_only", "confidence": "direct",
                "quote_or_summary": "background",
            },
        ],
    )


def test_migration_dry_run_is_conservative_and_writes_nothing(tmp_path: Path) -> None:
    _library(tmp_path)
    store = VersionedEvidenceStore(tmp_path / "store")
    report = migrate_legacy_csv(tmp_path, store)
    assert report.total_input == 2
    assert report.conserved
    assert report.status_counts["needs_repair"] == 2
    assert report.link_events_written == 0
    assert not store.events_path.exists()


def test_migration_executes_atomically_and_repeat_is_duplicate(tmp_path: Path) -> None:
    _library(tmp_path)
    store = VersionedEvidenceStore(tmp_path / "store")
    first = migrate_legacy_csv(tmp_path, store, dry_run=False)
    assert first.conserved
    assert first.source_events_written == 1
    assert first.link_events_written == 2
    legacy = [event for event in store.events() if event.object_type.value == "legacy_evidence_link"]
    assert len(legacy) == 2
    assert all(event.payload["admitted"] is False for event in legacy)
    assert all(event.payload["scientific_score"] is None for event in legacy)
    second = migrate_legacy_csv(tmp_path, store, dry_run=False)
    assert second.status_counts["duplicate"] == 2
    assert second.link_events_written == 0
    assert len(store.events()) == 3


def test_fresh_migrations_are_byte_deterministic(tmp_path: Path) -> None:
    _library(tmp_path)
    first = VersionedEvidenceStore(tmp_path / "store-1")
    second = VersionedEvidenceStore(tmp_path / "store-2")
    first_report = migrate_legacy_csv(tmp_path, first, dry_run=False)
    second_report = migrate_legacy_csv(tmp_path, second, dry_run=False)
    assert first_report.input_sha256 == second_report.input_sha256
    assert first.events_path.read_bytes() == second.events_path.read_bytes()


def test_packaged_migration_conserves_all_3222_links(tmp_path: Path) -> None:
    report = migrate_legacy_csv(PACKAGE_LIBRARY_DIR, VersionedEvidenceStore(tmp_path / "store"))
    assert report.total_input == 3222
    assert report.conserved
    assert report.link_events_written == 0
    assert sum(report.status_counts.values()) == 3222
