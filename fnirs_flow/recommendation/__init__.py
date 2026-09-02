"""Evidence-readiness and recommendation domain contracts.

The recommendation package is deliberately independent from the registry and
API layers.  It contains serialisable contracts and deterministic audits; it
does not assign scientific scores or mutate persisted project decisions.
"""

from .appraisal import appraise_evidence
from .calibration import CalibrationMetrics, ReleaseGateResult, evaluate_release_gates
from .contracts import (
    CandidateScope,
    EvidenceAdmission,
    EvidenceAppraisal,
    EvidenceSynthesis,
    ExecutionFeasibility,
    MethodFit,
    RecommendationContext,
    RecommendationDecision,
)
from .diff import decision_diff, reevaluate_decision
from .evidence_count import CountEvidence, EvidenceCountRank, rank_by_evidence_count
from .readiness import EvidenceReadinessAudit, audit_library
from .service import (
    build_automated_evidence_decision,
    build_evidence_decision,
    build_shadow_decision,
    build_static_decision,
    confirm_decision,
)
from .synthesis import synthesize_evidence

__all__ = [
    "CandidateScope",
    "EvidenceAdmission",
    "EvidenceAppraisal",
    "EvidenceReadinessAudit",
    "EvidenceSynthesis",
    "ExecutionFeasibility",
    "MethodFit",
    "RecommendationContext",
    "RecommendationDecision",
    "audit_library",
    "appraise_evidence",
    "CalibrationMetrics",
    "ReleaseGateResult",
    "evaluate_release_gates",
    "build_static_decision",
    "build_shadow_decision",
    "build_evidence_decision",
    "build_automated_evidence_decision",
    "confirm_decision",
    "synthesize_evidence",
    "decision_diff",
    "reevaluate_decision",
    "CountEvidence",
    "EvidenceCountRank",
    "rank_by_evidence_count",
]
