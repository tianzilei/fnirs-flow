"""Conservative, dry-run-first migration of the packaged evidence CSVs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fnirs_flow.history.canonical import canonical_json_bytes

from .contracts import (
    EvidenceAdmissionReasonCode,
    EvidenceMigrationReport,
    EvidenceObjectType,
    EvidenceReasonCode,
    EvidenceRole,
    MigrationRowResult,
    MigrationRowStatus,
)
from .store import EvidenceWrite, VersionedEvidenceStore

MIGRATION_TIMESTAMP = datetime(2026, 8, 28, tzinfo=timezone.utc)


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _input_sha256(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.exists() else b"")
        digest.update(b"\0")
    return digest.hexdigest()


def _repair_reasons(link: dict[str, str], source: dict[str, str] | None) -> tuple[str, ...]:
    reasons: list[str] = []
    if source is None:
        reasons.append(EvidenceAdmissionReasonCode.MISSING_SOURCE_RECORD.value)
    if not (link.get("source_locator") or (source or {}).get("source_path_or_url")):
        reasons.append(EvidenceAdmissionReasonCode.MISSING_SOURCE_LOCATOR.value)
    if not link.get("target_object_type"):
        reasons.append(EvidenceAdmissionReasonCode.MISSING_TARGET_OBJECT_TYPE.value)
    if not link.get("target_object_id"):
        reasons.append(EvidenceAdmissionReasonCode.UNBOUND_TARGET.value)
    if not (link.get("claim_id") and link.get("claim_type")):
        reasons.append(EvidenceAdmissionReasonCode.MISSING_CLAIM_METADATA.value)
    if link.get("direction") not in {"supports", "opposes", "neutral", "background_only"}:
        reasons.append(EvidenceAdmissionReasonCode.UNREVIEWED_DIRECTION.value)
    if not (link.get("study_id") or (source or {}).get("study_id")):
        reasons.append(EvidenceAdmissionReasonCode.MISSING_STUDY_ID.value)
    if (link.get("extraction_review_status") or "not_reviewed").lower() != "reviewed":
        reasons.append(EvidenceAdmissionReasonCode.EXTRACTION_NOT_REVIEWED.value)
    return tuple(sorted(reasons))


def migrate_legacy_csv(
    library_dir: str | Path,
    store: VersionedEvidenceStore,
    *,
    dry_run: bool = True,
    actor_id: str = "legacy-csv-migrator",
) -> EvidenceMigrationReport:
    root = Path(library_dir)
    source_path = root / "sources.csv"
    link_path = root / "atom_evidence_links.csv"
    sources = _rows(source_path)
    links = _rows(link_path)
    input_sha = _input_sha256((source_path, link_path))
    source_by_id = {(row.get("source_id") or "").strip(): row for row in sources}
    versions = store.latest_versions()
    seen: set[str] = set()
    results: list[MigrationRowResult] = []
    writes: list[EvidenceWrite] = []
    source_writes = 0

    for source_id, row in sorted(source_by_id.items()):
        if not source_id or (EvidenceObjectType.SOURCE_DOCUMENT, source_id) in versions:
            continue
        identifiers = {
            key: row[key].strip()
            for key in ("doi", "pmid", "pmcid")
            if row.get(key, "").strip()
        }
        source_payload: dict[str, Any] = {
            "source_id": source_id,
            "title": row.get("title", "") or source_id,
            "authors": (),
            "year": int(row["year"]) if row.get("year", "").isdigit() else None,
            "source_type": row.get("source_type", "") or "unknown",
            "identifiers": identifiers,
            "full_text_status": row.get("content_level", "") or "unknown",
            "document_version": "legacy-1",
            "source_status": "unverified",
            "acquired_at": None,
            "content_sha256": None,
            "access_notes": row.get("notes", ""),
            "migration_metadata": {
                "legacy_source_file": "sources.csv",
                "raw_row_sha256": hashlib.sha256(canonical_json_bytes(row)).hexdigest(),
            },
        }
        writes.append(EvidenceWrite(
            object_type=EvidenceObjectType.SOURCE_DOCUMENT,
            object_id=source_id,
            payload=source_payload,
            actor_id=actor_id,
            actor_role=EvidenceRole.CURATOR,
            reason_code=EvidenceReasonCode.MIGRATED_LEGACY,
            occurred_at=MIGRATION_TIMESTAMP,
        ))
        source_writes += 1

    for row_number, link in enumerate(links, start=1):
        evidence_id = (link.get("evidence_id") or link.get("link_id") or "").strip()
        source = source_by_id.get((link.get("source_id") or "").strip())
        reasons = _repair_reasons(link, source)
        key = (EvidenceObjectType.LEGACY_EVIDENCE_LINK, evidence_id)
        if evidence_id in seen or key in versions:
            status = MigrationRowStatus.DUPLICATE
            stored = False
        elif not evidence_id:
            status = MigrationRowStatus.QUARANTINED
            stored = False
            reasons = (*reasons, "missing_evidence_id")
        else:
            status = MigrationRowStatus.NEEDS_REPAIR if reasons else MigrationRowStatus.IMPORTED
            stored = not dry_run
            payload: dict[str, Any] = {
                "evidence_id": evidence_id,
                "legacy_row_number": row_number,
                "legacy_source_file": "atom_evidence_links.csv",
                "source_id": link.get("source_id", ""),
                "target_object_type": link.get("target_object_type", ""),
                "target_object_id": link.get("target_object_id", ""),
                "evidence_use": link.get("evidence_use", ""),
                "quote_or_summary": link.get("quote_or_summary", ""),
                "legacy_confidence": link.get("confidence", ""),
                "admitted": False,
                "scientific_score": None,
                "repair_reasons": list(reasons),
                "raw_row_sha256": hashlib.sha256(canonical_json_bytes(link)).hexdigest(),
            }
            writes.append(EvidenceWrite(
                object_type=EvidenceObjectType.LEGACY_EVIDENCE_LINK,
                object_id=evidence_id,
                payload=payload,
                actor_id=actor_id,
                actor_role=EvidenceRole.CURATOR,
                reason_code=EvidenceReasonCode.MIGRATED_LEGACY,
                occurred_at=MIGRATION_TIMESTAMP,
            ))
        seen.add(evidence_id)
        results.append(MigrationRowResult(
            row_number=row_number,
            evidence_id=evidence_id,
            status=status,
            stored=stored,
            reasons=tuple(sorted(set(reasons))),
        ))

    if not dry_run:
        store.append_batch(writes)
    counts = Counter(row.status.value for row in results)
    for status in MigrationRowStatus:
        counts.setdefault(status.value, 0)
    report = EvidenceMigrationReport(
        dry_run=dry_run,
        input_sha256=input_sha,
        total_input=len(links),
        status_counts=dict(sorted(counts.items())),
        source_records_seen=len(sources),
        source_events_written=0 if dry_run else source_writes,
        link_events_written=0 if dry_run else sum(row.stored for row in results),
        rows=tuple(results),
    )
    if not report.conserved:
        raise RuntimeError("Migration row conservation check failed")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy evidence CSVs into a versioned Evidence Store")
    parser.add_argument("library_dir", nargs="?", default="fnirs_flow/registry/methodatom_lib")
    parser.add_argument("--store", type=Path, default=Path("outputs/evidence_store"))
    parser.add_argument("--execute", action="store_true", help="Write events; the default is dry-run")
    parser.add_argument("--report", type=Path, default=Path("outputs/evidence_store/migration_report.json"))
    args = parser.parse_args()
    report = migrate_legacy_csv(args.library_dir, VersionedEvidenceStore(args.store), dry_run=not args.execute)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Evidence migration ({'execute' if args.execute else 'dry-run'}): {report.total_input} rows")
    print(f"Status counts: {report.status_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
