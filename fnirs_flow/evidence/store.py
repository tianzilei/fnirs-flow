"""Append-only Evidence Store with atomic, validated snapshot publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from fnirs_flow.history.canonical import canonical_json_bytes

from .contracts import (
    EVIDENCE_ADMISSION_RULES_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    OBJECT_PAYLOAD_MODELS,
    ROLE_PERMISSIONS,
    EvidenceEvent,
    EvidenceEventAction,
    EvidenceObjectType,
    EvidencePermission,
    EvidenceQAReport,
    EvidenceReasonCode,
    EvidenceRole,
    EvidenceSnapshotManifest,
    LineageReference,
)


class EvidenceWrite(BaseModel):
    """One candidate write in an atomic batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: EvidenceObjectType
    object_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_id: str
    actor_role: EvidenceRole
    reason_code: EvidenceReasonCode
    expected_version: int = Field(default=0, ge=0)
    action: EvidenceEventAction = EvidenceEventAction.UPSERT
    lineage: tuple[LineageReference, ...] = ()
    occurred_at: datetime | None = None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


_SNAPSHOT_ID_RE = re.compile(r"^esnap-[0-9a-f]{24}$")


def _snapshot_path(root: Path, snapshot_id: str) -> Path:
    """Resolve a snapshot path while rejecting traversal and malformed IDs."""
    if not _SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise KeyError(f"Invalid evidence snapshot ID: {snapshot_id!r}")
    candidate = (root / snapshot_id).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise KeyError(f"Invalid evidence snapshot ID: {snapshot_id!r}") from exc
    return candidate


def _required_permission(write: EvidenceWrite) -> EvidencePermission:
    if write.object_type in {
        EvidenceObjectType.SOURCE_DOCUMENT,
        EvidenceObjectType.SOURCE_VERSION,
        EvidenceObjectType.SEGMENT,
        EvidenceObjectType.EXTRACTION_PROPOSAL,
        EvidenceObjectType.LEGACY_EVIDENCE_LINK,
    }:
        return EvidencePermission.CURATE
    if write.object_type in {
        EvidenceObjectType.EVIDENCE_CLAIM,
        EvidenceObjectType.VERIFICATION_RESULT,
        EvidenceObjectType.QUARANTINE,
        EvidenceObjectType.ADMISSION,
        EvidenceObjectType.APPRAISAL,
    }:
        return EvidencePermission.REVIEW
    if write.object_type is EvidenceObjectType.INDEPENDENCE_CLUSTER:
        return EvidencePermission.ADJUDICATE
    return EvidencePermission.PUBLISH_POLICY


@contextmanager
def _process_lock(path: Path):
    """Coordinate writers across processes as well as threads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(b"0")
    handle = path.open("r+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl  # type: ignore[import-not-found]
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # type: ignore[import-not-found]
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        finally:
            handle.close()


def _manifest_identity_payload(manifest: EvidenceSnapshotManifest) -> dict[str, Any]:
    """Return the canonical, integrity-protected manifest fields."""
    return manifest.model_dump(mode="json", exclude={"manifest_sha256", "snapshot_id"})


def _manifest_digest(manifest: EvidenceSnapshotManifest) -> str:
    return _sha256_bytes(canonical_json_bytes(_manifest_identity_payload(manifest)))


def _snapshot_id_for_manifest(manifest: EvidenceSnapshotManifest) -> str:
    content = {
        "schema_version": manifest.schema_version,
        "rules_version": manifest.rules_version,
        "input_sha256": manifest.input_sha256,
        "objects_sha256": manifest.objects_sha256,
        "qa_sha256": manifest.qa_sha256,
        "code_commit": manifest.code_commit,
        "model_versions": dict(sorted(manifest.model_versions.items())),
        "prompt_hashes": dict(sorted(manifest.prompt_hashes.items())),
        "rule_set_hash": manifest.rule_set_hash,
        "benchmark_version": manifest.benchmark_version,
        "release_gate_passed": manifest.release_gate_passed,
        "slot_id": manifest.slot_id,
        "release_metrics_sha256": manifest.release_metrics_sha256,
    }
    return f"esnap-{_sha256_bytes(canonical_json_bytes(content))[:24]}"


_PAYLOAD_ID_FIELDS: dict[EvidenceObjectType, tuple[str, ...]] = {
    EvidenceObjectType.SOURCE_VERSION: ("source_version_id", "source_id"),
    EvidenceObjectType.SEGMENT: ("segment_id", "source_version_id"),
    EvidenceObjectType.EXTRACTION_PROPOSAL: ("proposal_id", "segment_id"),
    EvidenceObjectType.VERIFICATION_RESULT: ("verification_run_id", "proposal_id"),
    EvidenceObjectType.ADMISSION: ("admission_run_id", "claim_id", "evidence_id"),
    EvidenceObjectType.APPRAISAL: ("appraisal_id", "object_id", "evidence_id"),
    EvidenceObjectType.INDEPENDENCE_CLUSTER: ("cluster_id", "object_id"),
    EvidenceObjectType.SYNTHESIS: ("synthesis_id", "claim_id"),
    EvidenceObjectType.DERIVED_OBJECT: ("object_id", "derived_id"),
    EvidenceObjectType.LEGACY_EVIDENCE_LINK: ("evidence_id",),
    EvidenceObjectType.PARAMETER_CANDIDATE: ("candidate_id", "object_id"),
    EvidenceObjectType.RISK_RULE_CANDIDATE: ("rule_id", "object_id"),
    EvidenceObjectType.REPORTING_REQUIREMENT: ("requirement_id", "object_id"),
    EvidenceObjectType.FLOW_SLOT_CONTRACT: ("slot_id", "object_id"),
    EvidenceObjectType.FLOW_TEMPLATE: ("template_id", "object_id"),
    EvidenceObjectType.ADAPTER_DEFINITION: ("adapter_id", "object_id"),
    EvidenceObjectType.QUARANTINE: ("quarantine_id", "object_id", "record_id"),
}


def _validate_payload_shape(object_type: EvidenceObjectType, object_id: str, payload: dict[str, Any]) -> None:
    """Apply strict schema validation where available and identity checks elsewhere."""
    model = OBJECT_PAYLOAD_MODELS.get(object_type)
    if model is not None:
        validated_payload = model.model_validate(payload)
        identity_field = {
            EvidenceObjectType.SOURCE_DOCUMENT: "source_id",
            EvidenceObjectType.EVIDENCE_CLAIM: "claim_id",
        }.get(object_type)
        if identity_field and getattr(validated_payload, identity_field) != object_id:
            raise ValueError(
                f"Object ID mismatch for {object_type.value}: event has {object_id}, "
                f"payload has {getattr(validated_payload, identity_field)}"
            )
        return
    fields = _PAYLOAD_ID_FIELDS.get(object_type)
    if fields and not any(isinstance(payload.get(field), str) and payload.get(field) for field in fields):
        raise ValueError(f"Malformed {object_type.value} payload: missing identity field")
    # Ensure nested data is JSON-compatible before it can enter the hash chain.
    try:
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Malformed {object_type.value} payload: not JSON serializable") from exc


class VersionedEvidenceStore:
    """JSONL event store whose published snapshots are immutable directories."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.events_path = self.root / "events.jsonl"
        self.snapshots_dir = self.root / "snapshots"
        self.rejected_dir = self.root / "rejected_snapshots"
        self.current_path = self.root / "current_snapshot.json"
        self.lock_path = self.root / ".store.lock"
        self._lock = RLock()

    def events(self) -> list[EvidenceEvent]:
        if not self.events_path.exists():
            return []
        events: list[EvidenceEvent] = []
        previous: str | None = None
        with self.events_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                event = EvidenceEvent.model_validate_json(line)
                unsigned = event.model_dump(mode="json", exclude={"event_sha256"})
                observed = _sha256_bytes(canonical_json_bytes(unsigned))
                if event.previous_event_sha256 != previous or event.event_sha256 != observed:
                    raise ValueError(f"Evidence event hash chain invalid at line {line_number}")
                previous = event.event_sha256
                events.append(event)
        return events

    def latest_versions(self) -> dict[tuple[EvidenceObjectType, str], int]:
        return {(event.object_type, event.object_id): event.object_version for event in self.events()}

    def append(self, write: EvidenceWrite) -> EvidenceEvent:
        return self.append_batch((write,))[0]

    def append_batch(self, writes: Iterable[EvidenceWrite]) -> tuple[EvidenceEvent, ...]:
        """Validate a complete batch, then atomically replace the event log."""
        candidates = tuple(writes)
        if not candidates:
            return ()
        with self._lock, _process_lock(self.lock_path):
            existing = self.events()
            versions = {(event.object_type, event.object_id): event.object_version for event in existing}
            previous_hash = existing[-1].event_sha256 if existing else None
            additions: list[EvidenceEvent] = []
            for offset, write in enumerate(candidates, start=1):
                permission = _required_permission(write)
                if permission not in ROLE_PERMISSIONS[write.actor_role]:
                    raise PermissionError(f"{write.actor_role.value} cannot perform {permission.value}")
                key = (write.object_type, write.object_id)
                actual_version = versions.get(key, 0)
                if write.expected_version != actual_version:
                    raise ValueError(
                        f"Version conflict for {write.object_type.value}/{write.object_id}: "
                        f"expected {write.expected_version}, found {actual_version}"
                    )
                if write.action is EvidenceEventAction.UPSERT:
                    _validate_payload_shape(write.object_type, write.object_id, write.payload)
                elif write.payload:
                    raise ValueError("Tombstone events cannot carry object payload")
                object_version = actual_version + 1
                unsigned = {
                    "event_id": "pending",
                    "sequence": len(existing) + offset,
                    "object_type": write.object_type.value,
                    "object_id": write.object_id,
                    "object_version": object_version,
                    "action": write.action.value,
                    "payload": write.payload,
                    "lineage": [item.model_dump(mode="json") for item in write.lineage],
                    "actor_id": write.actor_id,
                    "actor_role": write.actor_role.value,
                    "reason_code": write.reason_code.value,
                    "rules_version": EVIDENCE_ADMISSION_RULES_VERSION,
                    "occurred_at": (write.occurred_at or datetime.now(timezone.utc)).isoformat(),
                    "previous_event_sha256": previous_hash,
                }
                identity_sha = _sha256_bytes(canonical_json_bytes(unsigned))
                unsigned["event_id"] = f"evt-{identity_sha[:24]}"
                normalized = EvidenceEvent.model_validate({**unsigned, "event_sha256": "0" * 64})
                normalized_unsigned = normalized.model_dump(mode="json", exclude={"event_sha256"})
                event_sha = _sha256_bytes(canonical_json_bytes(normalized_unsigned))
                event = normalized.model_copy(update={"event_sha256": event_sha})
                additions.append(event)
                versions[key] = object_version
                previous_hash = event_sha
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.events_path.with_suffix(".jsonl.tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                for event in (*existing, *additions):
                    handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.events_path)
            return tuple(additions)

    def tombstone(
        self,
        *,
        object_type: EvidenceObjectType,
        object_id: str,
        expected_version: int,
        actor_id: str,
        actor_role: EvidenceRole,
        reason_code: EvidenceReasonCode = EvidenceReasonCode.DELETED,
    ) -> EvidenceEvent:
        if expected_version < 1:
            raise ValueError("Cannot tombstone an object that does not exist")
        return self.append(
            EvidenceWrite(
                object_type=object_type,
                object_id=object_id,
                expected_version=expected_version,
                actor_id=actor_id,
                actor_role=actor_role,
                reason_code=reason_code,
                action=EvidenceEventAction.TOMBSTONE,
            )
        )

    def materialize(self) -> list[dict[str, Any]]:
        latest: dict[tuple[str, str], EvidenceEvent] = {}
        for event in self.events():
            latest[(event.object_type.value, event.object_id)] = event
        return [
            {
                "object_type": event.object_type.value,
                "object_id": event.object_id,
                "object_version": event.object_version,
                "deleted": event.action is EvidenceEventAction.TOMBSTONE,
                "payload": event.payload,
                "lineage": [item.model_dump(mode="json") for item in event.lineage],
                "event_sha256": event.event_sha256,
            }
            for _, event in sorted(latest.items())
        ]

    def build_qa_report(
        self,
        *,
        input_sha256: str,
        migration_counts: dict[str, int] | None = None,
    ) -> EvidenceQAReport:
        objects = self.materialize()
        counts = Counter(item["object_type"] for item in objects if not item["deleted"])
        tombstones = sum(bool(item["deleted"]) for item in objects)
        errors: list[str] = []
        warnings: list[str] = []
        missing: Counter[str] = Counter()
        lineage_required = {
            EvidenceObjectType.APPRAISAL.value,
            EvidenceObjectType.INDEPENDENCE_CLUSTER.value,
            EvidenceObjectType.SYNTHESIS.value,
            EvidenceObjectType.DERIVED_OBJECT.value,
        }
        object_versions = {
            (event.object_type.value, event.object_id, event.object_version)
            for event in self.events()
            if event.action is EvidenceEventAction.UPSERT
        }
        for item in objects:
            if item["deleted"]:
                continue
            if item["object_type"] in lineage_required and not item["lineage"]:
                errors.append(f"missing_lineage:{item['object_type']}:{item['object_id']}")
            if item["object_type"] == EvidenceObjectType.EVIDENCE_CLAIM.value:
                payload = item["payload"]
                if payload.get("automated", False):
                    required = (
                        "proposal_ids", "deterministic_verification_id",
                        "semantic_verification_id", "admission_run_id",
                    )
                    for field in required:
                        if not payload.get(field):
                            errors.append(f"missing_automated_lineage:{item['object_id']}:{field}")
            for reference in item["lineage"]:
                lineage_key = (
                    reference["object_type"],
                    reference["object_id"],
                    reference["object_version"],
                )
                if lineage_key not in object_versions:
                    errors.append(
                        f"unresolved_lineage:{item['object_type']}:{item['object_id']}:"
                        f"{reference['object_type']}:{reference['object_id']}:{reference['object_version']}"
                    )
            if item["object_type"] == EvidenceObjectType.LEGACY_EVIDENCE_LINK.value:
                for field in item["payload"].get("repair_reasons", []):
                    missing[str(field)] += 1
        legacy_count = counts[EvidenceObjectType.LEGACY_EVIDENCE_LINK.value]
        claim_count = counts[EvidenceObjectType.EVIDENCE_CLAIM.value]
        if legacy_count and not claim_count:
            warnings.append("legacy_links_present_without_reviewed_claims")
        return EvidenceQAReport(
            schema_version=EVIDENCE_SCHEMA_VERSION,
            rules_version=EVIDENCE_ADMISSION_RULES_VERSION,
            input_sha256=input_sha256,
            event_count=len(self.events()),
            object_counts=dict(sorted(counts.items())),
            tombstone_count=tombstones,
            errors=tuple(sorted(errors)),
            warnings=tuple(sorted(warnings)),
            missing_field_counts=dict(sorted(missing.items())),
            migration_counts=dict(sorted((migration_counts or {}).items())),
            re_review_queue_count=counts[EvidenceObjectType.LEGACY_EVIDENCE_LINK.value],
        )

    def publish_snapshot(
        self,
        *,
        input_sha256: str,
        migration_counts: dict[str, int] | None = None,
        generated_at: datetime | None = None,
        code_commit: str = "unknown",
        model_versions: dict[str, str] | None = None,
        prompt_hashes: dict[str, str] | None = None,
        rule_set_hash: str = "",
        benchmark_version: str | None = None,
        release_gate_passed: bool = False,
        slot_id: str | None = None,
        release_metrics_sha256: str | None = None,
        activate: bool = True,
    ) -> EvidenceSnapshotManifest:
        """Publish atomically; a failed candidate never changes current_snapshot."""
        if release_gate_passed and (not slot_id or not benchmark_version or not release_metrics_sha256):
            raise ValueError("passed release gates require slot, benchmark, and metrics attestation")
        with self._lock, _process_lock(self.lock_path):
            objects = self.materialize()
            qa = self.build_qa_report(input_sha256=input_sha256, migration_counts=migration_counts)
            objects_bytes = canonical_json_bytes(objects)
            qa_bytes = canonical_json_bytes(qa.model_dump(mode="json"))
            snapshot_content = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "rules_version": EVIDENCE_ADMISSION_RULES_VERSION,
                "input_sha256": input_sha256,
                "objects_sha256": _sha256_bytes(objects_bytes),
                "qa_sha256": _sha256_bytes(qa_bytes),
                "code_commit": code_commit,
                "model_versions": dict(sorted((model_versions or {}).items())),
                "prompt_hashes": dict(sorted((prompt_hashes or {}).items())),
                "rule_set_hash": rule_set_hash,
                "benchmark_version": benchmark_version,
                "release_gate_passed": release_gate_passed,
                "slot_id": slot_id,
                "release_metrics_sha256": release_metrics_sha256,
            }
            snapshot_id = f"esnap-{_sha256_bytes(canonical_json_bytes(snapshot_content))[:24]}"
            previous = self.current_snapshot()
            if previous is not None and previous.snapshot_id == snapshot_id:
                return previous
            manifest = EvidenceSnapshotManifest(
                snapshot_id=snapshot_id,
                status="published" if qa.passed else "rejected",
                schema_version=EVIDENCE_SCHEMA_VERSION,
                rules_version=EVIDENCE_ADMISSION_RULES_VERSION,
                input_sha256=input_sha256,
                objects_sha256=cast(str, snapshot_content["objects_sha256"]),
                qa_sha256=cast(str, snapshot_content["qa_sha256"]),
                event_count=qa.event_count,
                object_counts=qa.object_counts,
                tombstone_count=qa.tombstone_count,
                generated_at=generated_at or datetime.now(timezone.utc),
                rollback_snapshot_id=previous.snapshot_id if previous else None,
                parent_snapshot_id=previous.snapshot_id if previous else None,
                code_commit=code_commit,
                model_versions=dict(sorted((model_versions or {}).items())),
                prompt_hashes=dict(sorted((prompt_hashes or {}).items())),
                rule_set_hash=rule_set_hash,
                benchmark_version=benchmark_version,
                release_gate_passed=release_gate_passed,
                slot_id=slot_id,
                release_metrics_sha256=release_metrics_sha256,
            )
            manifest = manifest.model_copy(update={"manifest_sha256": _manifest_digest(manifest)})
            if not qa.passed:
                self.rejected_dir.mkdir(parents=True, exist_ok=True)
                target = self.rejected_dir / f"{snapshot_id}.json"
                self._atomic_json(
                    target,
                    {"manifest": manifest.model_dump(mode="json"), "qa": qa.model_dump(mode="json")},
                )
                return manifest

            target = self.snapshots_dir / snapshot_id
            if target.exists():
                manifest = self.verify_snapshot(snapshot_id)
            else:
                staging = self.snapshots_dir / f".{snapshot_id}.tmp"
                staging.mkdir(parents=True, exist_ok=False)
                (staging / "objects.json").write_bytes(objects_bytes + b"\n")
                (staging / "qa.json").write_bytes(qa_bytes + b"\n")
                (staging / "qa.md").write_text(qa.to_markdown(), encoding="utf-8")
                (staging / "manifest.json").write_text(
                    json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                # Same-volume directory rename is atomic.  ``os.replace`` can
                # reject directory sources on Windows even when the target is
                # absent, while ``Path.rename`` preserves the required atomic
                # publish behavior for this new immutable directory.
                staging.rename(target)
            if activate:
                self._atomic_json(self.current_path, manifest.model_dump(mode="json"))
            return manifest

    def current_snapshot(self) -> EvidenceSnapshotManifest | None:
        if not self.current_path.exists():
            return None
        manifest = EvidenceSnapshotManifest.model_validate_json(self.current_path.read_text(encoding="utf-8"))
        if manifest.status != "published":
            raise ValueError("Current evidence snapshot is not published")
        try:
            verified = self.verify_snapshot(manifest.snapshot_id)
        except ValueError as exc:
            raise ValueError("Current evidence snapshot pointer does not match its manifest") from exc
        if verified != manifest:
            raise ValueError("Current evidence snapshot pointer does not match its manifest")
        return verified

    def rollback(self, snapshot_id: str, *, reason: str = "rollback") -> EvidenceSnapshotManifest:
        with self._lock, _process_lock(self.lock_path):
            directory = _snapshot_path(self.snapshots_dir, snapshot_id)
            path = directory / "manifest.json"
            if not path.exists():
                raise KeyError(f"Unknown published evidence snapshot: {snapshot_id}")
            manifest = EvidenceSnapshotManifest.model_validate_json(path.read_text(encoding="utf-8"))
            self.verify_snapshot(snapshot_id)
            self._atomic_json(self.current_path, manifest.model_dump(mode="json"))
            audit_path = self.root / "snapshot_pointer_events.jsonl"
            audit = {
                "reason": reason, "snapshot_id": snapshot_id,
                "manifest_sha256": manifest.manifest_sha256,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            with audit_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(audit, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return manifest

    def verify_snapshot(self, snapshot_id: str) -> EvidenceSnapshotManifest:
        directory = _snapshot_path(self.snapshots_dir, snapshot_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            raise KeyError(f"Unknown published evidence snapshot: {snapshot_id}")
        manifest = EvidenceSnapshotManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if manifest.snapshot_id != snapshot_id:
            raise ValueError(f"Evidence snapshot manifest ID mismatch: {snapshot_id}")
        if _snapshot_id_for_manifest(manifest) != snapshot_id:
            raise ValueError(f"Evidence snapshot identity mismatch: {snapshot_id}")
        if not manifest.manifest_sha256 or _manifest_digest(manifest) != manifest.manifest_sha256:
            raise ValueError(f"Evidence snapshot manifest integrity check failed: {snapshot_id}")
        checks = {
            "objects.json": manifest.objects_sha256,
            "qa.json": manifest.qa_sha256,
        }
        for name, expected in checks.items():
            path = directory / name
            if not path.exists():
                raise ValueError(f"Evidence snapshot is missing {name}: {snapshot_id}")
            observed = _sha256_bytes(path.read_bytes().removesuffix(b"\n"))
            if observed != expected:
                raise ValueError(f"Evidence snapshot checksum mismatch for {name}: {snapshot_id}")
        return manifest

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
