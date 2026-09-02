"""Read-mostly audit API and batch controls for fully automated evidence processing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from fnirs_flow.api.router_dependencies import bind_router_context, current_store
from fnirs_flow.evidence import (
    AutomatedEvidenceWorkspace,
    ReleaseMetrics,
    SnapshotController,
    VersionedEvidenceStore,
    evaluate_automated_gates,
)
from fnirs_flow.evidence.contracts import (
    EvidenceAdmissionReasonCode,
    EvidenceObjectType,
    EvidenceReasonCode,
    EvidenceRole,
)
from fnirs_flow.evidence.store import EvidenceWrite
from fnirs_flow.history.canonical import canonical_json_bytes
from fnirs_flow.recommendation.readiness import audit_library
from fnirs_flow.registry.methodatom_library import PACKAGE_LIBRARY_DIR

router = APIRouter(prefix="/api/evidence", dependencies=[Depends(bind_router_context)])


def _root() -> Path:
    return Path(current_store()._base_dir) / "automated_evidence"


def _workspace() -> AutomatedEvidenceWorkspace:
    return AutomatedEvidenceWorkspace(_root() / "workspace.sqlite3")


def _store() -> VersionedEvidenceStore:
    return VersionedEvidenceStore(_root() / "store")


class RunRequest(BaseModel):
    source_ids: tuple[str, ...] = ()
    slot_ids: tuple[str, ...] = ()
    versions: dict[str, str] = Field(default_factory=dict)
    options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class SnapshotBuildRequest(BaseModel):
    input_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    code_commit: str = "unknown"
    model_versions: dict[str, str] = Field(default_factory=dict)
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    rule_set_hash: str = ""
    benchmark_version: str | None = None
    slot_id: str
    independent_fnirs_benchmark: bool = False
    distribution_drift: bool = False
    release_metrics: ReleaseMetrics | None = None
    gate_attestation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")

    @model_validator(mode="after")
    def validate_release_attestation(self) -> SnapshotBuildRequest:
        if self.independent_fnirs_benchmark and not self.benchmark_version:
            raise ValueError("independent benchmark requires benchmark_version")
        if self.release_metrics is not None and self.gate_attestation_sha256 is None:
            raise ValueError("release metrics require server-issued gate_attestation_sha256")
        return self


def _verify_gate_attestation(request: SnapshotBuildRequest) -> None:
    if request.release_metrics is None:
        return
    payload = {
        "slot_id": request.slot_id,
        "benchmark_version": request.benchmark_version,
        "independent_fnirs_benchmark": request.independent_fnirs_benchmark,
        "distribution_drift": request.distribution_drift,
        "release_metrics": request.release_metrics.model_dump(mode="json"),
    }
    expected = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    observed = (request.gate_attestation_sha256 or "").lower()
    attestation = _root() / "gate_attestations" / f"{observed}.json"
    if observed != expected or not attestation.is_file():
        raise HTTPException(status_code=422, detail={"reason_code": "release_gate_attestation_invalid"})
    try:
        persisted = json.loads(attestation.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"reason_code": "release_gate_attestation_invalid"},
        ) from exc
    if canonical_json_bytes(persisted) != canonical_json_bytes(payload):
        raise HTTPException(status_code=422, detail={"reason_code": "release_gate_attestation_invalid"})


class SnapshotActivateRequest(BaseModel):
    snapshot_id: str


class EvidenceObjectWriteRequest(BaseModel):
    object_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_version: int = Field(default=0, ge=0)


class ClaimReviewRequest(BaseModel):
    decision: str = Field(pattern=r"^(accepted|rejected|needs_review)$")
    reviewer_id: str = Field(min_length=1, max_length=200)
    rationale: str = ""


def _principal(actor_id: str) -> str:
    principal = actor_id.strip()
    if not principal:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_actor_id"})
    return principal


def _idempotent_mutation(
    operation_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    key = idempotency_key.strip()
    if not key:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_idempotency_key"})
    payload_sha256 = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    workspace = _workspace()
    try:
        replay = workspace.reserve_operation(
            operation_type=operation_type,
            idempotency_key=key,
            payload_sha256=payload_sha256,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"reason_code": str(exc)}) from exc
    if replay is not None:
        return replay
    try:
        result = action()
    except Exception:
        workspace.cancel_operation(operation_type=operation_type, idempotency_key=key)
        raise
    workspace.complete_operation(operation_type=operation_type, idempotency_key=key, result=result)
    return result


def _start_run(stage: str, request: RunRequest, idempotency_key: str) -> dict[str, Any]:
    idempotency_key = idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_idempotency_key"})
    payload = request.model_dump(mode="json")
    identity = hashlib.sha256(f"{stage}\0{idempotency_key}".encode()).hexdigest()
    run_id = f"run-{identity[:24]}"
    provenance = {
        "service_identity": f"evidence_{stage}",
        "versions": dict(sorted(request.versions.items())),
        "request_sha256": hashlib.sha256(request.model_dump_json().encode()).hexdigest(),
    }
    try:
        result = _workspace().start_run(
            run_id=run_id,
            stage=stage,
            idempotency_key=idempotency_key,
            payload=payload,
            provenance=provenance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"reason_code": str(exc)}) from exc
    persisted_provenance = json.loads(result["provenance_json"])
    return {
        "run_id": result["run_id"],
        "stage": result["stage"],
        "status": result["status"],
        "version": result["version"],
        "reason_code": "run_created_or_replayed",
        "provenance": persisted_provenance,
    }


@router.post("/runs/harvest", status_code=202)
async def harvest(request: RunRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    result = _start_run("harvest", request, idempotency_key)
    return {**result, "dispatch_status": "not_configured"}


@router.post("/runs/extract", status_code=202)
async def extract(request: RunRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    result = _start_run("extract", request, idempotency_key)
    return {**result, "dispatch_status": "not_configured"}


@router.post("/runs/verify", status_code=202)
async def verify(request: RunRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    result = _start_run("verify", request, idempotency_key)
    return {**result, "dispatch_status": "not_configured"}


@router.post("/runs/reprocess", status_code=202)
async def reprocess(request: RunRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    allowed = {"source", "parser", "schema", "model", "rules", "registered_defect"}
    trigger = str(request.options.get("trigger", ""))
    if trigger not in allowed:
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_reprocessing_trigger"})
    result = _start_run("reprocess", request, idempotency_key)
    return {**result, "dispatch_status": "not_configured"}


def _page(items: list[dict[str, Any]], limit: int, offset: int) -> dict[str, Any]:
    ordered = sorted(
        items, key=lambda item: (str(item.get("object_id", item.get("run_id", ""))), str(item.get("event_id", "")))
    )
    return {
        "items": ordered[offset : offset + limit],
        "count": len(ordered),
        "limit": limit,
        "offset": offset,
        "reason_code": "audit_read",
    }


@router.get("/proposals")
async def proposals(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    records = _workspace().records("extraction_proposal", status)
    return _page(records, limit, offset)


@router.get("/sources")
async def sources(
    source_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List immutable source records with deterministic ordering and filtering."""
    items = [
        item
        for item in _store().materialize()
        if item["object_type"] == EvidenceObjectType.SOURCE_DOCUMENT.value
        and not item["deleted"]
        and (source_id is None or item["object_id"] == source_id)
    ]
    return _page(items, limit, offset)


@router.post("/sources")
async def create_source(
    request: EvidenceObjectWriteRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    actor_id: str = Header(alias="X-Actor-ID"),
) -> dict[str, Any]:
    """Curator source ingestion with optimistic version protection."""
    principal = _principal(actor_id)

    def perform() -> dict[str, Any]:
        try:
            event = _store().append(
                EvidenceWrite(
                    object_type=EvidenceObjectType.SOURCE_DOCUMENT,
                    object_id=request.object_id,
                    payload=request.payload,
                    expected_version=request.expected_version,
                    actor_id=principal,
                    actor_role=EvidenceRole.CURATOR,
                    reason_code=EvidenceReasonCode.CREATED,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail={"reason_code": "version_conflict", "message": str(exc)}
            ) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"reason_code": "permission_denied"}) from exc
        return {"event": event.model_dump(mode="json"), "reason_code": "source_recorded"}

    return _idempotent_mutation(
        "source_create", idempotency_key, {**request.model_dump(mode="json"), "actor_id": principal}, perform
    )


@router.get("/claims/queue")
async def claims_queue(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Return claims requiring review; queue is read-only and fail-closed."""
    items = [
        item
        for item in _store().materialize()
        if item["object_type"] == EvidenceObjectType.EVIDENCE_CLAIM.value and not item["deleted"]
    ]
    if status:
        items = [item for item in items if item["payload"].get("extraction_review_status") == status]
    return _page(items, limit, offset) | {"reason_code": "review_queue"}


@router.post("/{evidence_id}/admission")
async def admission(
    evidence_id: str,
    request: EvidenceObjectWriteRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    actor_id: str = Header(alias="X-Actor-ID"),
) -> dict[str, Any]:
    """Persist a versioned admission result; policy remains fail-closed."""
    if request.object_id != evidence_id:
        raise HTTPException(status_code=422, detail={"reason_code": "object_id_mismatch"})
    principal = _principal(actor_id)
    payload = dict(request.payload)
    payload.setdefault("evidence_id", evidence_id)
    # Admission is fail-closed.  A positive decision must carry all
    # auditable prerequisites; otherwise preserve the record as non-admitted
    # with stable reason codes for the remediation queue.
    blocking: list[str] = []
    if payload.get("admitted") in {True, "true", "1"}:
        if payload.get("source_valid") is not True and payload.get("source_valid") not in {"true", "1"}:
            blocking.append(EvidenceAdmissionReasonCode.INVALID_SOURCE.value)
        for field, reason in (
            ("source_locator", EvidenceAdmissionReasonCode.MISSING_SOURCE_LOCATOR),
            ("claim_id", EvidenceAdmissionReasonCode.MISSING_CLAIM_METADATA),
            ("target_object_type", EvidenceAdmissionReasonCode.MISSING_TARGET_OBJECT_TYPE),
            ("target_object_id", EvidenceAdmissionReasonCode.UNBOUND_TARGET),
            ("study_id", EvidenceAdmissionReasonCode.MISSING_STUDY_ID),
        ):
            if not payload.get(field):
                blocking.append(reason.value)
        if payload.get("direction") not in {"supports", "opposes", "neutral"}:
            blocking.append(EvidenceAdmissionReasonCode.UNREVIEWED_DIRECTION.value)
        if payload.get("extraction_review_status") not in {"reviewed", "accepted"}:
            blocking.append(EvidenceAdmissionReasonCode.EXTRACTION_NOT_REVIEWED.value)
        if payload.get("withdrawn_or_corrected") in {True, "true", "1"}:
            blocking.append(EvidenceAdmissionReasonCode.WITHDRAWN_OR_CORRECTED.value)
        if blocking:
            raise HTTPException(
                status_code=422, detail={"reason_code": "admission_blocked", "blocking_reasons": sorted(set(blocking))}
            )
    # Persist machine-readable reasons on every admission record.  A rejected
    # or quarantined item therefore remains actionable in the repair queue.
    if blocking:
        payload["admission_reason_codes"] = tuple(sorted(set(blocking)))
    elif payload.get("admitted") not in {True, "true", "1"}:
        payload.setdefault("admission_reason_codes", ("not_admitted",))

    def perform() -> dict[str, Any]:
        try:
            event = _store().append(
                EvidenceWrite(
                    object_type=EvidenceObjectType.ADMISSION,
                    object_id=evidence_id,
                    payload=payload,
                    expected_version=request.expected_version,
                    actor_id=principal,
                    actor_role=EvidenceRole.REVIEWER,
                    reason_code=EvidenceReasonCode.REVIEWED,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail={"reason_code": "version_conflict", "message": str(exc)}
            ) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"reason_code": "permission_denied"}) from exc
        return {"event": event.model_dump(mode="json"), "reason_code": "admission_recorded"}

    return _idempotent_mutation(
        "admission_create", idempotency_key, {**request.model_dump(mode="json"), "actor_id": principal}, perform
    )


@router.post("/{evidence_id}/appraisal")
async def appraisal(
    evidence_id: str,
    request: EvidenceObjectWriteRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    actor_id: str = Header(alias="X-Actor-ID"),
) -> dict[str, Any]:
    if request.object_id != evidence_id:
        raise HTTPException(status_code=422, detail={"reason_code": "object_id_mismatch"})
    principal = _principal(actor_id)
    payload = dict(request.payload)
    payload.setdefault("evidence_id", evidence_id)

    def perform() -> dict[str, Any]:
        try:
            event = _store().append(
                EvidenceWrite(
                    object_type=EvidenceObjectType.APPRAISAL,
                    object_id=evidence_id,
                    payload=payload,
                    expected_version=request.expected_version,
                    actor_id=principal,
                    actor_role=EvidenceRole.REVIEWER,
                    reason_code=EvidenceReasonCode.REVIEWED,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail={"reason_code": "version_conflict", "message": str(exc)}
            ) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"reason_code": "permission_denied"}) from exc
        return {"event": event.model_dump(mode="json"), "reason_code": "appraisal_recorded"}

    return _idempotent_mutation(
        "appraisal_create", idempotency_key, {**request.model_dump(mode="json"), "actor_id": principal}, perform
    )


@router.get("/{evidence_id}/admission")
async def get_admission(evidence_id: str) -> dict[str, Any]:
    items = [
        item
        for item in _store().materialize()
        if item["object_type"] == EvidenceObjectType.ADMISSION.value
        and item["object_id"] == evidence_id
        and not item["deleted"]
    ]
    if not items:
        raise HTTPException(status_code=404, detail={"reason_code": "admission_not_found"})
    return items[0]


@router.get("/{evidence_id}/appraisal")
async def get_appraisal(evidence_id: str) -> dict[str, Any]:
    items = [
        item
        for item in _store().materialize()
        if item["object_type"] == EvidenceObjectType.APPRAISAL.value
        and item["object_id"] == evidence_id
        and not item["deleted"]
    ]
    if not items:
        raise HTTPException(status_code=404, detail={"reason_code": "appraisal_not_found"})
    return items[0]


@router.post("/clusters")
async def create_cluster(
    request: EvidenceObjectWriteRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    actor_id: str = Header(alias="X-Actor-ID"),
) -> dict[str, Any]:
    principal = _principal(actor_id)

    def perform() -> dict[str, Any]:
        try:
            event = _store().append(
                EvidenceWrite(
                    object_type=EvidenceObjectType.INDEPENDENCE_CLUSTER,
                    object_id=request.object_id,
                    payload=request.payload,
                    expected_version=request.expected_version,
                    actor_id=principal,
                    actor_role=EvidenceRole.ADJUDICATOR,
                    reason_code=EvidenceReasonCode.ADJUDICATED,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail={"reason_code": "version_conflict", "message": str(exc)}
            ) from exc
        return {"event": event.model_dump(mode="json"), "reason_code": "cluster_recorded"}

    return _idempotent_mutation(
        "cluster_create", idempotency_key, {**request.model_dump(mode="json"), "actor_id": principal}, perform
    )


@router.get("/readiness/{slot_id}")
async def readiness(slot_id: str) -> dict[str, Any]:
    report = audit_library(PACKAGE_LIBRARY_DIR)
    matches = [item.model_dump(mode="json") for item in report.slots if item.slot_id == slot_id]
    if not matches:
        raise HTTPException(status_code=404, detail={"reason_code": "slot_not_found"})
    return {"slot_id": slot_id, "readiness": matches[0], "audit_version": report.audit_version}


@router.get("/claims/{claim_id}")
async def claim(claim_id: str) -> dict[str, Any]:
    items = [
        item
        for item in _store().materialize()
        if item["object_type"] == "evidence_claim" and item["object_id"] == claim_id and not item["deleted"]
    ]
    if not items:
        raise HTTPException(status_code=404, detail={"reason_code": "claim_not_found"})
    return items[0]


@router.post("/claims/{claim_id}/reviews")
async def review_claim(
    claim_id: str,
    request: ClaimReviewRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    actor_id: str = Header(alias="X-Actor-ID"),
) -> dict[str, Any]:
    if actor_id.strip() != request.reviewer_id.strip():
        raise HTTPException(status_code=403, detail={"reason_code": "reviewer_identity_mismatch"})
    principal = _principal(actor_id)

    def perform() -> dict[str, Any]:
        current = next(
            (
                item
                for item in _store().materialize()
                if item["object_type"] == EvidenceObjectType.EVIDENCE_CLAIM.value
                and item["object_id"] == claim_id
                and not item["deleted"]
            ),
            None,
        )
        if current is None:
            raise HTTPException(status_code=404, detail={"reason_code": "claim_not_found"})
        payload = dict(current["payload"])
        # The extracting principal cannot be the sole final reviewer.  Claims
        # lacking an extractor identity remain reviewable, but an explicit
        # self-review is rejected to preserve separation of duties.
        extractor_id = payload.get("extractor_id") or payload.get("extracted_by")
        reviewed_by = tuple(str(item) for item in payload.get("reviewed_by", ()))
        if extractor_id and str(extractor_id) == request.reviewer_id and not reviewed_by:
            raise HTTPException(status_code=422, detail={"reason_code": "reviewer_independence_required"})
        previous_status = payload.get("extraction_review_status", "not_reviewed")
        payload["extraction_review_status"] = "reviewed" if request.decision == "accepted" else request.decision
        payload["reviewed_by"] = tuple(sorted(set((*reviewed_by, request.reviewer_id))))
        payload["review_rationale"] = request.rationale
        payload["review_record"] = {
            "reviewer_id": request.reviewer_id,
            "decision": request.decision,
            "previous_status": previous_status,
            "new_status": payload["extraction_review_status"],
            "rationale": request.rationale,
        }
        try:
            event = _store().append(
                EvidenceWrite(
                    object_type=EvidenceObjectType.EVIDENCE_CLAIM,
                    object_id=claim_id,
                    payload=payload,
                    expected_version=int(current["object_version"]),
                    actor_id=principal,
                    actor_role=EvidenceRole.REVIEWER,
                    reason_code=EvidenceReasonCode.REVIEWED,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail={"reason_code": "version_conflict", "message": str(exc)}
            ) from exc
        return {"event": event.model_dump(mode="json"), "reason_code": "claim_review_recorded"}

    return _idempotent_mutation(
        "claim_review",
        idempotency_key,
        {"claim_id": claim_id, **request.model_dump(mode="json"), "actor_id": principal},
        perform,
    )


@router.get("/verification-runs/{run_id}")
async def verification_run(run_id: str) -> dict[str, Any]:
    items = [item for item in _workspace().records("verification_result") if item["run_id"] == run_id]
    if not items:
        raise HTTPException(status_code=404, detail={"reason_code": "verification_run_not_found"})
    return {"run_id": run_id, "items": items, "count": len(items)}


@router.get("/quarantine")
async def quarantine() -> dict[str, Any]:
    items = _workspace().records(status="quarantined")
    return {"items": items, "count": len(items), "business_outcome": "abstained"}


@router.get("/clusters")
async def clusters(
    limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)
) -> dict[str, Any]:
    items = [
        item
        for item in _store().materialize()
        if item["object_type"] == EvidenceObjectType.INDEPENDENCE_CLUSTER.value and not item["deleted"]
    ]
    return _page(items, limit, offset)


@router.get("/syntheses/{claim_id}")
async def synthesis(claim_id: str) -> dict[str, Any]:
    items = [
        item
        for item in _store().materialize()
        if item["object_type"] == EvidenceObjectType.SYNTHESIS.value
        and not item["deleted"]
        and item["payload"].get("claim_id") == claim_id
    ]
    if not items:
        raise HTTPException(status_code=404, detail={"reason_code": "synthesis_not_found"})
    return {"items": items, "count": len(items), "claim_id": claim_id}


@router.get("/syntheses")
async def syntheses(
    limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)
) -> dict[str, Any]:
    items = [
        item
        for item in _store().materialize()
        if item["object_type"] == EvidenceObjectType.SYNTHESIS.value and not item["deleted"]
    ]
    return _page(items, limit, offset)


@router.post("/syntheses")
async def create_synthesis(
    request: EvidenceObjectWriteRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    actor_id: str = Header(alias="X-Actor-ID"),
) -> dict[str, Any]:
    principal = _principal(actor_id)

    def perform() -> dict[str, Any]:
        try:
            event = _store().append(
                EvidenceWrite(
                    object_type=EvidenceObjectType.SYNTHESIS,
                    object_id=request.object_id,
                    payload=request.payload,
                    expected_version=request.expected_version,
                    actor_id=principal,
                    actor_role=EvidenceRole.SYNTHESIS_ENGINE,
                    reason_code=EvidenceReasonCode.REVIEWED,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail={"reason_code": "version_conflict", "message": str(exc)}
            ) from exc
        return {"event": event.model_dump(mode="json"), "reason_code": "synthesis_recorded"}

    return _idempotent_mutation(
        "synthesis_create", idempotency_key, {**request.model_dump(mode="json"), "actor_id": principal}, perform
    )


@router.get("/lineage/{object_type}/{object_id}")
async def lineage(object_type: str, object_id: str) -> dict[str, Any]:
    events = [
        event for event in _store().events() if event.object_type.value == object_type and event.object_id == object_id
    ]
    if not events:
        raise HTTPException(status_code=404, detail={"reason_code": "lineage_not_found"})
    return {
        "object_type": object_type,
        "object_id": object_id,
        "events": [event.model_dump(mode="json") for event in events],
    }


@router.post("/snapshots/build")
async def build_snapshot(
    request: SnapshotBuildRequest, idempotency_key: str = Header(alias="Idempotency-Key")
) -> dict[str, Any]:
    _verify_gate_attestation(request)

    def perform() -> dict[str, Any]:
        gate = None
        if request.release_metrics is not None:
            gate = evaluate_automated_gates(
                request.release_metrics,
                slot_id=request.slot_id,
                independent_fnirs_benchmark=request.independent_fnirs_benchmark,
                distribution_drift=request.distribution_drift,
            )
        manifest = _store().publish_snapshot(
            input_sha256=request.input_sha256.lower(),
            code_commit=request.code_commit,
            model_versions=request.model_versions,
            prompt_hashes=request.prompt_hashes,
            rule_set_hash=request.rule_set_hash,
            benchmark_version=request.benchmark_version,
            release_gate_passed=bool(gate and gate.passed),
            slot_id=request.slot_id,
            release_metrics_sha256=(
                request.gate_attestation_sha256.lower() if request.gate_attestation_sha256 else None
            ),
            activate=False,
        )
        return {
            "manifest": manifest.model_dump(mode="json"),
            "release_gate": gate.model_dump(mode="json")
            if gate
            else {
                "passed": False,
                "source_mode": "shadow",
                "reason_codes": ["release_metrics_missing"],
                "failed_metrics": [],
            },
            "idempotency_key": idempotency_key.strip(),
            "reason_code": "candidate_snapshot_built",
        }

    return _idempotent_mutation(
        "snapshot_build",
        idempotency_key,
        request.model_dump(mode="json"),
        perform,
    )


@router.post("/snapshots/{snapshot_id}/activate")
async def activate_snapshot(snapshot_id: str, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    def perform() -> dict[str, Any]:
        try:
            manifest = SnapshotController(_store()).activate(snapshot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"reason_code": "snapshot_not_found"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"reason_code": str(exc)}) from exc
        return {
            "manifest": manifest.model_dump(mode="json"),
            "idempotency_key": idempotency_key.strip(),
            "reason_code": "snapshot_activated",
        }

    return _idempotent_mutation("snapshot_activate", idempotency_key, {"snapshot_id": snapshot_id}, perform)


@router.post("/snapshots/activate")
async def activate_snapshot_contract(
    request: SnapshotActivateRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, Any]:
    """Normative ES-API endpoint; path-ID form remains as a compatibility alias."""
    return cast(dict[str, Any], await activate_snapshot(request.snapshot_id, idempotency_key))


@router.get("/snapshots/{snapshot_id}/qa")
async def snapshot_qa(snapshot_id: str) -> dict[str, Any]:
    try:
        return SnapshotController(_store()).qa(snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"reason_code": "snapshot_not_found"}) from exc


@router.post("/snapshots/{snapshot_id}/rollback")
async def rollback_snapshot(snapshot_id: str, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, Any]:
    def perform() -> dict[str, Any]:
        try:
            manifest = SnapshotController(_store()).rollback(snapshot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"reason_code": "snapshot_not_found"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"reason_code": str(exc)}) from exc
        return {
            "manifest": manifest.model_dump(mode="json"),
            "idempotency_key": idempotency_key.strip(),
            "reason_code": "snapshot_rolled_back",
        }

    return _idempotent_mutation("snapshot_rollback", idempotency_key, {"snapshot_id": snapshot_id}, perform)
