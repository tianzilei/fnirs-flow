"""Exact A/B/C consensus with mandatory abstention on every disagreement."""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, ConfigDict

from fnirs_flow.history.canonical import canonical_json_bytes

from .deterministic_verifier import DeterministicVerificationResult
from .extraction_proposals import (
    ExtractionProposal,
    normalized_critical_fields,
    validate_extractor_independence,
)
from .semantic_verifier import SemanticVerificationResult, semantic_result_is_admissible


class AdmissionOutcome(str, Enum):
    ADMITTED = "admitted"
    QUARANTINED = "quarantined"


class ConsensusDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    admission_run_id: str
    outcome: AdmissionOutcome
    reason_codes: tuple[str, ...]
    proposal_ids: tuple[str, str]
    deterministic_verification_ids: tuple[str, str]
    semantic_verification_id: str
    claim_fingerprint: str | None = None


def decide_consensus(
    a: ExtractionProposal,
    b: ExtractionProposal,
    deterministic_a: DeterministicVerificationResult,
    deterministic_b: DeterministicVerificationResult,
    semantic: SemanticVerificationResult,
    *,
    admission_run_id: str,
    segment_length: int,
    source_active: bool = True,
    cluster_blocked: bool = False,
) -> ConsensusDecision:
    reasons: list[str] = []
    try:
        validate_extractor_independence(a, b)
    except ValueError as exc:
        reasons.append(str(exc))
    if normalized_critical_fields(a) != normalized_critical_fields(b):
        reasons.append("extractor_critical_field_disagreement")
    if not deterministic_a.passed or not deterministic_b.passed:
        reasons.append("deterministic_verification_failed")
    if not semantic_result_is_admissible(semantic, segment_id=a.segment_id, segment_length=segment_length):
        reasons.append("semantic_not_entailed")
    if semantic.proposal_id not in {a.proposal_id, b.proposal_id}:
        reasons.append("semantic_proposal_binding_failed")
    if not source_active:
        reasons.append("source_invalidated")
    if cluster_blocked:
        reasons.append("cluster_unknown_blocking")
    outcome = AdmissionOutcome.QUARANTINED if reasons else AdmissionOutcome.ADMITTED
    fingerprint = None
    if outcome is AdmissionOutcome.ADMITTED:
        fingerprint = hashlib.sha256(canonical_json_bytes(normalized_critical_fields(a))).hexdigest()
    return ConsensusDecision(
        admission_run_id=admission_run_id, outcome=outcome,
        reason_codes=tuple(sorted(set(reasons))) or ("all_automated_admission_gates_passed",),
        proposal_ids=(a.proposal_id, b.proposal_id),
        deterministic_verification_ids=(
            deterministic_a.verification_run_id, deterministic_b.verification_run_id,
        ),
        semantic_verification_id=semantic.verification_run_id,
        claim_fingerprint=fingerprint,
    )
