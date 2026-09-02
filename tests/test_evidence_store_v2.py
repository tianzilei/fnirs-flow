from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fnirs_flow.evidence import (
    EvidenceClaim,
    EvidenceObjectType,
    EvidenceReasonCode,
    EvidenceRole,
    EvidenceWrite,
    LineageReference,
    VersionedEvidenceStore,
)
from fnirs_flow.evidence.contracts import SourceLocator
from fnirs_flow.recommendation.contracts import EvidenceDirection


def _source_payload(source_id: str = "S1") -> dict[str, object]:
    return {
        "source_id": source_id,
        "title": "Test source",
        "authors": ["A. Reviewer"],
        "year": 2026,
        "source_type": "paper",
        "identifiers": {"doi": "10.1/example"},
    }


def test_store_is_versioned_append_only_and_checks_optimistic_version(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    first = store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        payload=_source_payload(),
        actor_id="curator-1",
        actor_role=EvidenceRole.CURATOR,
        reason_code=EvidenceReasonCode.CREATED,
        occurred_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    ))
    assert first.object_version == 1
    with pytest.raises(ValueError, match="Version conflict"):
        store.append(EvidenceWrite(
            object_type=EvidenceObjectType.SOURCE_DOCUMENT,
            object_id="S1",
            payload=_source_payload(),
            actor_id="curator-2",
            actor_role=EvidenceRole.CURATOR,
            reason_code=EvidenceReasonCode.CORRECTED,
        ))
    revised = dict(_source_payload())
    revised["title"] = "Corrected title"
    second = store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        payload=revised,
        actor_id="curator-2",
        actor_role=EvidenceRole.CURATOR,
        reason_code=EvidenceReasonCode.CORRECTED,
        expected_version=1,
    ))
    assert second.object_version == 2
    assert len(store.events()) == 2


def test_tombstone_preserves_history_and_snapshot_is_deterministic(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        payload=_source_payload(),
        actor_id="curator",
        actor_role=EvidenceRole.CURATOR,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    first = store.publish_snapshot(input_sha256="a" * 64)
    store.tombstone(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        expected_version=1,
        actor_id="curator",
        actor_role=EvidenceRole.CURATOR,
    )
    second = store.publish_snapshot(input_sha256="a" * 64)
    assert first.snapshot_id != second.snapshot_id
    assert second.rollback_snapshot_id == first.snapshot_id
    assert second.tombstone_count == 1
    assert len(store.events()) == 2
    assert store.rollback(first.snapshot_id).snapshot_id == first.snapshot_id


def test_failed_snapshot_keeps_previous_current_snapshot(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        payload=_source_payload(),
        actor_id="curator",
        actor_role=EvidenceRole.CURATOR,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    valid = store.publish_snapshot(input_sha256="a" * 64)
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SYNTHESIS,
        object_id="SYN1",
        payload={"claim_id": "C1"},
        actor_id="policy",
        actor_role=EvidenceRole.POLICY_MAINTAINER,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    rejected = store.publish_snapshot(input_sha256="b" * 64)
    assert rejected.status == "rejected"
    assert store.current_snapshot() == valid
    assert (store.rejected_dir / f"{rejected.snapshot_id}.json").exists()


def test_event_hash_chain_detects_tampering(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        payload=_source_payload(),
        actor_id="curator",
        actor_role=EvidenceRole.CURATOR,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    row = json.loads(store.events_path.read_text(encoding="utf-8"))
    row["payload"]["title"] = "tampered"
    store.events_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash chain invalid"):
        store.events()


def test_derived_objects_require_lineage_for_snapshot_publication(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    claim = EvidenceClaim(
        claim_id="C1",
        evidence_id="E1",
        source_id="S1",
        source_locator=SourceLocator(
            document_version="1",
            locator="page 1, paragraph 2",
            verbatim_text="Method A reduced motion artifacts.",
            content_sha256="d" * 64,
            extraction_method="verbatim",
        ),
        normalized_claim="Method A reduces motion artifacts.",
        claim_type="comparative_choice",
        direction=EvidenceDirection.SUPPORTS,
        target_object_type="method_atom",
        target_object_id="A1",
        study_id="ST1",
        extraction_method="manual",
        extraction_review_status="reviewed",
        created_by="curator",
        reviewed_by=("reviewer",),
        created_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.EVIDENCE_CLAIM,
        object_id="C1",
        payload=claim.model_dump(mode="json"),
        actor_id="reviewer",
        actor_role=EvidenceRole.REVIEWER,
        reason_code=EvidenceReasonCode.REVIEWED,
    ))
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SYNTHESIS,
        object_id="SYN1",
        payload={"claim_id": "C1"},
        lineage=(LineageReference(
            object_type=EvidenceObjectType.EVIDENCE_CLAIM,
            object_id="C1",
            object_version=1,
        ),),
        actor_id="policy",
        actor_role=EvidenceRole.POLICY_MAINTAINER,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    snapshot = store.publish_snapshot(input_sha256="c" * 64)
    assert snapshot.status == "published"
    assert (store.snapshots_dir / snapshot.snapshot_id / "qa.md").exists()


def test_snapshot_rejects_unresolved_lineage(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SYNTHESIS,
        object_id="SYN1",
        payload={"claim_id": "missing"},
        lineage=(LineageReference(
            object_type=EvidenceObjectType.EVIDENCE_CLAIM,
            object_id="missing",
            object_version=1,
        ),),
        actor_id="policy",
        actor_role=EvidenceRole.POLICY_MAINTAINER,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    assert store.publish_snapshot(input_sha256="d" * 64).status == "rejected"


def test_snapshot_integrity_is_checked_before_rollback(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        payload=_source_payload(),
        actor_id="curator",
        actor_role=EvidenceRole.CURATOR,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    snapshot = store.publish_snapshot(input_sha256="e" * 64)
    objects = store.snapshots_dir / snapshot.snapshot_id / "objects.json"
    objects.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        store.rollback(snapshot.snapshot_id)


def test_snapshot_manifest_tampering_is_detected(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        payload=_source_payload(),
        actor_id="curator",
        actor_role=EvidenceRole.CURATOR,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    snapshot = store.publish_snapshot(
        input_sha256="9" * 64, release_gate_passed=True,
        slot_id="motion_correction_slot", benchmark_version="bench-1",
        release_metrics_sha256="8" * 64,
    )
    path = store.snapshots_dir / snapshot.snapshot_id / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["release_gate_passed"] = False
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="identity mismatch|integrity check failed"):
        store.verify_snapshot(snapshot.snapshot_id)


def test_payload_without_schema_requires_identity(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    with pytest.raises(ValueError, match="missing identity field"):
        store.append(EvidenceWrite(
            object_type=EvidenceObjectType.SYNTHESIS,
            object_id="SYN1",
            payload={"status": "supported"},
            actor_id="policy",
            actor_role=EvidenceRole.POLICY_MAINTAINER,
            reason_code=EvidenceReasonCode.CREATED,
        ))


def test_snapshot_id_traversal_is_rejected(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    with pytest.raises(KeyError, match="Invalid evidence snapshot ID"):
        store.verify_snapshot("../outside")
    with pytest.raises(KeyError, match="Invalid evidence snapshot ID"):
        store.rollback("C:/outside")


def test_current_snapshot_verifies_pointer_and_contents(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        payload=_source_payload(),
        actor_id="curator",
        actor_role=EvidenceRole.CURATOR,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    snapshot = store.publish_snapshot(input_sha256="1" * 64)
    store.current_path.write_text(
        snapshot.model_copy(update={"objects_sha256": "2" * 64}).model_dump_json(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="pointer does not match"):
        store.current_snapshot()


def test_tombstone_requires_existing_object(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    with pytest.raises(ValueError, match="does not exist"):
        store.tombstone(
            object_type=EvidenceObjectType.SOURCE_DOCUMENT,
            object_id="missing",
            expected_version=0,
            actor_id="curator",
            actor_role=EvidenceRole.CURATOR,
        )


def test_analyst_cannot_write_evidence(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    with pytest.raises(PermissionError):
        store.append(EvidenceWrite(
            object_type=EvidenceObjectType.SOURCE_DOCUMENT,
            object_id="S1",
            payload=_source_payload(),
            actor_id="analyst",
            actor_role=EvidenceRole.ANALYST,
            reason_code=EvidenceReasonCode.CREATED,
        ))


def test_republishing_same_content_reuses_immutable_manifest(tmp_path: Path) -> None:
    store = VersionedEvidenceStore(tmp_path / "evidence")
    store.append(EvidenceWrite(
        object_type=EvidenceObjectType.SOURCE_DOCUMENT,
        object_id="S1",
        payload=_source_payload(),
        actor_id="curator",
        actor_role=EvidenceRole.CURATOR,
        reason_code=EvidenceReasonCode.CREATED,
    ))
    first = store.publish_snapshot(
        input_sha256="f" * 64,
        generated_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    second = store.publish_snapshot(
        input_sha256="f" * 64,
        generated_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
    )
    assert second == first
