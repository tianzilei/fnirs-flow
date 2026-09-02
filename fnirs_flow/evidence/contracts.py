"""Versioned contracts for the post-v1.3 Evidence Store.

The evidence domain is intentionally separate from recommendation execution.
These objects describe evidence facts, review state, lineage, and immutable
storage events; they never turn legacy confidence or citation counts into a
scientific score.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.functional_validators import field_validator

from fnirs_flow.recommendation.contracts import EvidenceDirection

EVIDENCE_SCHEMA_VERSION = "2.0.0"
EVIDENCE_ADMISSION_RULES_VERSION = "2.0.0-automated"


class StringEnum(str, Enum):
    """String enum compatible with Python 3.10."""


class EvidenceObjectType(StringEnum):
    SOURCE_DOCUMENT = "source_document"
    EVIDENCE_CLAIM = "evidence_claim"
    ADMISSION = "admission"
    APPRAISAL = "appraisal"
    INDEPENDENCE_CLUSTER = "independence_cluster"
    SYNTHESIS = "synthesis"
    DERIVED_OBJECT = "derived_object"
    LEGACY_EVIDENCE_LINK = "legacy_evidence_link"
    SOURCE_VERSION = "source_version"
    SEGMENT = "segment"
    EXTRACTION_PROPOSAL = "extraction_proposal"
    VERIFICATION_RESULT = "verification_result"
    QUARANTINE = "quarantine"
    PARAMETER_CANDIDATE = "parameter_candidate"
    RISK_RULE_CANDIDATE = "risk_rule_candidate"
    REPORTING_REQUIREMENT = "reporting_requirement"
    FLOW_SLOT_CONTRACT = "flow_slot_contract"
    FLOW_TEMPLATE = "flow_template"
    ADAPTER_DEFINITION = "adapter_definition"


class EvidenceEventAction(StringEnum):
    UPSERT = "upsert"
    TOMBSTONE = "tombstone"


class EvidenceReasonCode(StringEnum):
    CREATED = "created"
    MIGRATED_LEGACY = "migrated_legacy"
    CORRECTED = "corrected"
    REVIEWED = "reviewed"
    ADJUDICATED = "adjudicated"
    RETRACTION_PROPAGATED = "retraction_propagated"
    SUPERSEDED = "superseded"
    DELETED = "deleted"
    MACHINE_PROPOSED = "machine_proposed"
    MACHINE_VERIFIED = "machine_verified"
    MACHINE_ADMITTED = "machine_admitted"
    AUTOMATED_REPROCESSING = "automated_reprocessing"
    SNAPSHOT_ACTIVATED = "snapshot_activated"
    SNAPSHOT_ROLLED_BACK = "snapshot_rolled_back"


class EvidenceAdmissionReasonCode(StringEnum):
    INVALID_SOURCE = "invalid_source"
    MISSING_SOURCE_RECORD = "missing_source_record"
    MISSING_SOURCE_LOCATOR = "missing_source_locator"
    MISSING_TARGET_OBJECT_TYPE = "missing_target_object_type"
    UNBOUND_TARGET = "unbound_target"
    MISSING_CLAIM_METADATA = "missing_claim_metadata"
    UNREVIEWED_DIRECTION = "unreviewed_direction"
    MISSING_STUDY_ID = "missing_study_id"
    EXTRACTION_NOT_REVIEWED = "extraction_not_reviewed"
    WITHDRAWN_OR_CORRECTED = "withdrawn_or_corrected"
    UNKNOWN_CLAIM_TYPE = "unknown_claim_type"


class EvidenceRole(StringEnum):
    CURATOR = "evidence_curator"
    REVIEWER = "reviewer"
    ADJUDICATOR = "adjudicator"
    POLICY_MAINTAINER = "policy_maintainer"
    ANALYST = "analyst"
    AUDITOR = "auditor"
    HARVESTER = "harvester"
    PARSER = "parser"
    EXTRACTOR = "extractor"
    DETERMINISTIC_VERIFIER = "deterministic_verifier"
    SEMANTIC_VERIFIER = "semantic_verifier"
    ADMISSION_ENGINE = "admission_engine"
    CLUSTER_ENGINE = "cluster_engine"
    APPRAISAL_ENGINE = "appraisal_engine"
    SYNTHESIS_ENGINE = "synthesis_engine"
    PUBLISHER = "publisher"


class EvidencePermission(StringEnum):
    READ = "read"
    CURATE = "curate"
    REVIEW = "review"
    ADJUDICATE = "adjudicate"
    PUBLISH_POLICY = "publish_policy"
    PUBLISH_SNAPSHOT = "publish_snapshot"


ROLE_PERMISSIONS: dict[EvidenceRole, frozenset[EvidencePermission]] = {
    EvidenceRole.CURATOR: frozenset({EvidencePermission.READ, EvidencePermission.CURATE}),
    EvidenceRole.REVIEWER: frozenset({EvidencePermission.READ, EvidencePermission.REVIEW}),
    EvidenceRole.ADJUDICATOR: frozenset(
        {EvidencePermission.READ, EvidencePermission.REVIEW, EvidencePermission.ADJUDICATE}
    ),
    EvidenceRole.POLICY_MAINTAINER: frozenset(
        {EvidencePermission.READ, EvidencePermission.PUBLISH_POLICY, EvidencePermission.PUBLISH_SNAPSHOT}
    ),
    EvidenceRole.ANALYST: frozenset({EvidencePermission.READ}),
    EvidenceRole.AUDITOR: frozenset({EvidencePermission.READ}),
    EvidenceRole.HARVESTER: frozenset({EvidencePermission.READ, EvidencePermission.CURATE}),
    EvidenceRole.PARSER: frozenset({EvidencePermission.READ, EvidencePermission.CURATE}),
    EvidenceRole.EXTRACTOR: frozenset({EvidencePermission.READ, EvidencePermission.CURATE}),
    EvidenceRole.DETERMINISTIC_VERIFIER: frozenset({EvidencePermission.READ, EvidencePermission.REVIEW}),
    EvidenceRole.SEMANTIC_VERIFIER: frozenset({EvidencePermission.READ, EvidencePermission.REVIEW}),
    EvidenceRole.ADMISSION_ENGINE: frozenset({EvidencePermission.READ, EvidencePermission.REVIEW}),
    EvidenceRole.CLUSTER_ENGINE: frozenset({EvidencePermission.READ, EvidencePermission.ADJUDICATE}),
    EvidenceRole.APPRAISAL_ENGINE: frozenset({EvidencePermission.READ, EvidencePermission.REVIEW}),
    EvidenceRole.SYNTHESIS_ENGINE: frozenset({EvidencePermission.READ, EvidencePermission.PUBLISH_POLICY}),
    EvidenceRole.PUBLISHER: frozenset(
        {EvidencePermission.READ, EvidencePermission.PUBLISH_POLICY, EvidencePermission.PUBLISH_SNAPSHOT}
    ),
}


class EvidenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourceLocator(EvidenceContract):
    document_version: str
    locator: str
    verbatim_text: str = ""
    content_sha256: str
    extraction_method: str

    @field_validator("content_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("content_sha256 must be a 64-character hexadecimal SHA-256")
        return value.lower()


class SourceDocument(EvidenceContract):
    source_id: str
    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    source_type: str
    identifiers: dict[str, str] = Field(default_factory=dict)
    full_text_status: str = "unknown"
    document_version: str = "1"
    source_status: str = "unverified"
    acquired_at: datetime | None = None
    content_sha256: str | None = None
    access_notes: str = ""
    migration_metadata: dict[str, Any] = Field(default_factory=dict)
    study_id: str | None = None
    report_type: str = "article"
    canonical_url: str | None = None
    journal_identifier: str | None = None
    publication_date: str | None = None
    license_status: str = "unknown"
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    parser_version: str | None = None


class EvidenceClaim(EvidenceContract):
    claim_id: str
    evidence_id: str
    source_id: str
    source_locator: SourceLocator
    normalized_claim: str
    claim_type: str
    direction: EvidenceDirection
    target_object_type: str
    target_object_id: str
    population_or_context: str = ""
    study_id: str
    dataset_id: str | None = None
    extraction_method: str
    extraction_review_status: str = "not_reviewed"
    created_by: str
    reviewed_by: tuple[str, ...] = ()
    record_version: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime
    proposal_ids: tuple[str, str] | None = None
    deterministic_verification_id: str | None = None
    semantic_verification_id: str | None = None
    admission_run_id: str | None = None
    automated: bool = False

    @model_validator(mode="after")
    def validate_automated_lineage(self) -> EvidenceClaim:
        required = (
            self.proposal_ids,
            self.deterministic_verification_id,
            self.semantic_verification_id,
            self.admission_run_id,
        )
        if self.automated and not all(required):
            raise ValueError("automated EvidenceClaim requires A/B, deterministic, semantic and admission lineage")
        return self


class LineageReference(EvidenceContract):
    object_type: EvidenceObjectType
    object_id: str
    object_version: int = Field(ge=1)


class EvidenceEvent(EvidenceContract):
    event_id: str
    sequence: int = Field(ge=1)
    object_type: EvidenceObjectType
    object_id: str
    object_version: int = Field(ge=1)
    action: EvidenceEventAction
    payload: dict[str, Any] = Field(default_factory=dict)
    lineage: tuple[LineageReference, ...] = ()
    actor_id: str
    actor_role: EvidenceRole
    reason_code: EvidenceReasonCode
    rules_version: str = EVIDENCE_ADMISSION_RULES_VERSION
    occurred_at: datetime
    previous_event_sha256: str | None = None
    event_sha256: str


class EvidenceSnapshotManifest(EvidenceContract):
    snapshot_id: str
    status: str
    schema_version: str
    rules_version: str
    input_sha256: str
    objects_sha256: str
    qa_sha256: str
    event_count: int
    object_counts: dict[str, int]
    tombstone_count: int
    generated_at: datetime
    rollback_snapshot_id: str | None = None
    parent_snapshot_id: str | None = None
    policy_version: str = EVIDENCE_ADMISSION_RULES_VERSION
    code_commit: str = "unknown"
    model_versions: dict[str, str] = Field(default_factory=dict)
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    rule_set_hash: str = ""
    benchmark_version: str | None = None
    release_gate_passed: bool = False
    slot_id: str | None = None
    release_metrics_sha256: str | None = None
    # Hash of the canonical manifest payload (excluding this field).  This
    # protects release metadata such as status and gate state from silent
    # edits after publication.
    manifest_sha256: str = ""

    @field_validator("input_sha256", "objects_sha256", "qa_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("snapshot checksums must be 64-character hexadecimal SHA-256 values")
        return value.lower()

    @field_validator("manifest_sha256")
    @classmethod
    def validate_manifest_sha256(cls, value: str) -> str:
        if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower())):
            raise ValueError("manifest_sha256 must be a 64-character hexadecimal SHA-256")
        return value.lower()


class EvidenceQAReport(EvidenceContract):
    schema_version: str
    rules_version: str
    input_sha256: str
    event_count: int
    object_counts: dict[str, int]
    tombstone_count: int = 0
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    missing_field_counts: dict[str, int] = Field(default_factory=dict)
    migration_counts: dict[str, int] = Field(default_factory=dict)
    re_review_queue_count: int = 0

    @property
    def passed(self) -> bool:
        return not self.errors

    @field_validator("input_sha256")
    @classmethod
    def validate_input_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("input_sha256 must be a 64-character hexadecimal SHA-256")
        return value.lower()

    def to_markdown(self) -> str:
        lines = [
            "# Evidence Store QA",
            "",
            f"- Schema version: `{self.schema_version}`",
            f"- Rules version: `{self.rules_version}`",
            f"- Input SHA-256: `{self.input_sha256}`",
            f"- Result: `{'pass' if self.passed else 'fail'}`",
            f"- Events: {self.event_count}",
            f"- Tombstones: {self.tombstone_count}",
            "",
            "## Object counts",
            "",
        ]
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.object_counts.items()))
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- `{item}`" for item in self.errors)
        if not self.errors:
            lines.append("- None")
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{item}`" for item in self.warnings)
        if not self.warnings:
            lines.append("- None")
        lines.extend(["", "## Migration counts", ""])
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.migration_counts.items()))
        if not self.migration_counts:
            lines.append("- None")
        return "\n".join(lines) + "\n"


class MigrationRowStatus(StringEnum):
    IMPORTED = "imported"
    DUPLICATE = "duplicate"
    QUARANTINED = "quarantined"
    NEEDS_REPAIR = "needs_repair"
    NOT_APPLICABLE = "not_applicable"


class MigrationRowResult(EvidenceContract):
    row_number: int = Field(ge=1)
    evidence_id: str
    status: MigrationRowStatus
    stored: bool = False
    reasons: tuple[str, ...] = ()


class EvidenceMigrationReport(EvidenceContract):
    migration_version: str = "1.0.0"
    dry_run: bool
    input_sha256: str
    total_input: int
    status_counts: dict[str, int]
    source_records_seen: int
    source_events_written: int
    link_events_written: int
    rows: tuple[MigrationRowResult, ...]

    @property
    def conserved(self) -> bool:
        return self.total_input == sum(self.status_counts.values()) == len(self.rows)


OBJECT_PAYLOAD_MODELS: dict[EvidenceObjectType, type[BaseModel]] = {
    EvidenceObjectType.SOURCE_DOCUMENT: SourceDocument,
    EvidenceObjectType.EVIDENCE_CLAIM: EvidenceClaim,
}
