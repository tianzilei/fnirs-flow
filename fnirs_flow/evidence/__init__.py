"""Post-v1.3 evidence governance and immutable storage boundary."""

from .automated_gates import AutomatedGateResult, ReleaseMetrics, evaluate_automated_gates
from .consensus import AdmissionOutcome, ConsensusDecision, decide_consensus
from .contracts import (
    EVIDENCE_ADMISSION_RULES_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    EvidenceAdmissionReasonCode,
    EvidenceClaim,
    EvidenceEvent,
    EvidenceMigrationReport,
    EvidenceObjectType,
    EvidenceQAReport,
    EvidenceReasonCode,
    EvidenceRole,
    EvidenceSnapshotManifest,
    LineageReference,
    SourceDocument,
    SourceLocator,
)
from .deterministic_verifier import DeterministicVerificationResult, verify_proposal
from .document_pipeline import PipelineState, SourceVersion, StateTransition, validate_transition
from .extraction_proposals import ExtractionProposal
from .segment_ledger import DocumentSegment, SegmentLocator, SegmentStatus
from .snapshots import AutomatedEvidenceWorkspace, SnapshotController
from .store import EvidenceWrite, VersionedEvidenceStore


def migrate_legacy_csv(*args, **kwargs):
    """Load the migration module lazily so ``python -m`` stays warning-free."""
    from .migration import migrate_legacy_csv as migrate

    return migrate(*args, **kwargs)

__all__ = [
    "EVIDENCE_ADMISSION_RULES_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "EvidenceAdmissionReasonCode",
    "EvidenceClaim",
    "EvidenceEvent",
    "EvidenceMigrationReport",
    "EvidenceObjectType",
    "EvidenceQAReport",
    "EvidenceReasonCode",
    "EvidenceRole",
    "EvidenceSnapshotManifest",
    "EvidenceWrite",
    "LineageReference",
    "SourceDocument",
    "SourceLocator",
    "VersionedEvidenceStore",
    "AdmissionOutcome",
    "AutomatedEvidenceWorkspace",
    "AutomatedGateResult",
    "ConsensusDecision",
    "DeterministicVerificationResult",
    "DocumentSegment",
    "ExtractionProposal",
    "PipelineState",
    "ReleaseMetrics",
    "SegmentLocator",
    "SegmentStatus",
    "SnapshotController",
    "SourceVersion",
    "StateTransition",
    "decide_consensus",
    "evaluate_automated_gates",
    "validate_transition",
    "verify_proposal",
    "migrate_legacy_csv",
]
