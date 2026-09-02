"""Versioned, score-free contracts for v1.3 recommendation work.

These models freeze terminology before scoring is implemented.  Optional
scores remain ``None`` when a required appraisal dimension is unavailable;
legacy confidence values are retained only as migration metadata.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StringEnum(str, Enum):
    """String enum compatible with the project's Python 3.10 floor."""


class TriState(StringEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class EvidenceDirection(StringEnum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    NEUTRAL = "neutral"
    BACKGROUND_ONLY = "background_only"


class EvidenceStrength(StringEnum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"


class SourceMode(StringEnum):
    RULE_BASED_FALLBACK = "rule_based_fallback"
    SHADOW = "shadow"
    EVIDENCE_DRIVEN = "evidence_driven"
    AUTOMATED_EVIDENCE = "automated_evidence"


class Tier(StringEnum):
    BEST = "best"
    RECOMMENDED = "recommended"
    ALTERNATIVE = "alternative"
    NOT_RECOMMENDED = "not_recommended"


class DecisionStatus(StringEnum):
    ELIGIBLE = "eligible"
    NEEDS_INPUT = "needs_input"
    NEEDS_REVIEW = "needs_review"
    EXCLUDED = "excluded"


class ExecutionStatus(StringEnum):
    READY = "ready"
    INSTALLABLE = "installable"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceAdmission(ContractModel):
    evidence_id: str
    source_id: str
    source_valid: bool = False
    source_status: str = "unknown"
    source_locator: str | None = None
    target_object_type: str | None = None
    target_object_id: str | None = None
    claim_id: str | None = None
    claim_type: str | None = None
    direction: EvidenceDirection = EvidenceDirection.NEUTRAL
    study_id: str | None = None
    dataset_id: str | None = None
    extraction_review_status: str = "not_reviewed"
    withdrawn_or_corrected: bool = False
    admitted: bool = False
    reasons: tuple[str, ...] = ()


class EvidenceAppraisal(ContractModel):
    evidence_id: str
    claim_type: str
    profile_version: str
    dimensions: dict[str, float | None] = Field(default_factory=dict)
    dimension_reasons: dict[str, str] = Field(default_factory=dict)
    source_locator: str | None = None
    score: float | None = None
    score_reason: str | None = None


class EvidenceSynthesis(ContractModel):
    claim_id: str
    strength: EvidenceStrength
    direction: EvidenceDirection
    evidence_ids: tuple[str, ...] = ()
    independent_study_clusters: tuple[tuple[str, ...], ...] = ()
    coverage: str = "unknown"
    conflicts: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class RecommendationContext(ContractModel):
    scenario: str
    fields: dict[str, TriState | str | float | int | bool | None] = Field(default_factory=dict)
    schema_version: str = "1.3.0"


class CandidateScope(ContractModel):
    slot_id: str
    candidate_ids: tuple[str, ...] = ()
    known_coverage: tuple[str, ...] = ()
    unknown_coverage: tuple[str, ...] = ()


class MethodFit(ContractModel):
    candidate_id: str
    status: Literal["eligible", "needs_review", "ineligible", "excluded"]
    reasons: tuple[str, ...] = ()
    evidence_strength: EvidenceStrength | None = None


class ExecutionFeasibility(ContractModel):
    candidate_id: str
    status: ExecutionStatus
    reasons: tuple[str, ...] = ()
    backend_id: str | None = None


class RecommendationDecision(ContractModel):
    decision_id: str
    rules_version: str
    checklist_version: str | None = None
    evidence_store_snapshot: str | None = None
    context: RecommendationContext
    candidate_scope: CandidateScope
    appraisals: tuple[EvidenceAppraisal, ...] = ()
    syntheses: tuple[EvidenceSynthesis, ...] = ()
    method_fit: tuple[MethodFit, ...] = ()
    execution: tuple[ExecutionFeasibility, ...] = ()
    tier: Tier | None = None
    decision_status: DecisionStatus
    execution_status: ExecutionStatus
    source_mode: SourceMode
    reasons: tuple[str, ...] = ()
    required_user_confirmation: bool = False
    user_override: str | None = None
    supersedes_decision_id: str | None = None
    generated_at: datetime
