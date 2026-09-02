"""Application facade for deterministic recommendation decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from fnirs_flow.evidence.store import VersionedEvidenceStore

from .candidates import order_method_fit
from .contracts import (
    CandidateScope,
    EvidenceAppraisal,
    EvidenceSynthesis,
    ExecutionFeasibility,
    ExecutionStatus,
    MethodFit,
    RecommendationContext,
    RecommendationDecision,
    SourceMode,
)
from .policy import apply_policy


def build_static_decision(
    *, scenario: str, slot_id: str, candidate_id: str, reasons: tuple[str, ...] = ()
) -> RecommendationDecision:
    """Build a fallback decision without consulting scores or citation counts."""
    fit = MethodFit(candidate_id=candidate_id, status="eligible", reasons=reasons)
    execution = ExecutionFeasibility(candidate_id=candidate_id, status=ExecutionStatus.READY, reasons=reasons)
    tier, status = apply_policy(
        source_mode=SourceMode.RULE_BASED_FALLBACK,
        method_fit=fit,
        execution_status=execution.status,
        evidence_ready=False,
    )
    return RecommendationDecision(
        decision_id=f"dec-{uuid4().hex[:16]}",
        rules_version="1.3.0-static",
        context=RecommendationContext(scenario=scenario),
        candidate_scope=CandidateScope(slot_id=slot_id, candidate_ids=(candidate_id,)),
        method_fit=(fit,),
        execution=(execution,),
        tier=tier,
        decision_status=status,
        execution_status=execution.status,
        source_mode=SourceMode.RULE_BASED_FALLBACK,
        reasons=reasons or ("static checklist fallback",),
        generated_at=datetime.now(timezone.utc),
    )


def build_shadow_decision(
    *,
    scenario: str,
    slot_id: str,
    candidates: tuple[MethodFit, ...],
    execution_status: ExecutionStatus = ExecutionStatus.READY,
) -> RecommendationDecision:
    """Produce an auditable shadow result without changing static behavior."""
    ordered = order_method_fit(candidates)
    chosen = ordered[0] if ordered else MethodFit(candidate_id="", status="excluded", reasons=("no candidates",))
    tier, status = apply_policy(
        source_mode=SourceMode.SHADOW,
        method_fit=chosen,
        execution_status=execution_status,
        evidence_ready=False,
    )
    return RecommendationDecision(
        decision_id=f"shadow-{uuid4().hex[:16]}",
        rules_version="1.3.0-shadow",
        context=RecommendationContext(scenario=scenario),
        candidate_scope=CandidateScope(slot_id=slot_id, candidate_ids=tuple(item.candidate_id for item in ordered)),
        method_fit=ordered,
        tier=tier,
        decision_status=status,
        execution_status=execution_status,
        source_mode=SourceMode.SHADOW,
        reasons=("shadow result does not alter static ordering or persisted user choice",),
        generated_at=datetime.now(timezone.utc),
    )


def build_evidence_decision(
    *,
    scenario: str,
    slot_id: str,
    candidates: tuple[MethodFit, ...],
    appraisals: tuple[EvidenceAppraisal, ...],
    syntheses: tuple[EvidenceSynthesis, ...],
    evidence_ready: bool,
    execution: tuple[ExecutionFeasibility, ...] = (),
    reasons: tuple[str, ...] = (),
) -> RecommendationDecision:
    """Build an evidence decision only for an explicitly ready slot.

    This is intentionally score-free: until calibrated weights and holdout
    metrics exist, evidence mode may only return a reviewable alternative and
    never silently promote a candidate to ``best``.
    """
    ordered = order_method_fit(candidates)
    chosen = ordered[0] if ordered else MethodFit(candidate_id="", status="excluded", reasons=("no candidates",))
    conflict = any(item.strength.value == "conflicting" for item in syntheses)
    tier, status = apply_policy(
        source_mode=SourceMode.EVIDENCE_DRIVEN,
        method_fit=chosen,
        execution_status=(execution[0].status if execution else ExecutionStatus.READY),
        evidence_ready=evidence_ready,
        has_conflict=conflict,
    )
    return RecommendationDecision(
        decision_id=f"evidence-{uuid4().hex[:16]}",
        rules_version="1.3.0-evidence-v0",
        context=RecommendationContext(scenario=scenario),
        candidate_scope=CandidateScope(slot_id=slot_id, candidate_ids=tuple(item.candidate_id for item in ordered)),
        appraisals=appraisals,
        syntheses=syntheses,
        method_fit=ordered,
        execution=execution,
        tier=tier,
        decision_status=status,
        execution_status=execution[0].status if execution else ExecutionStatus.READY,
        source_mode=SourceMode.EVIDENCE_DRIVEN,
        reasons=reasons or ("evidence slot is not calibrated for best recommendation",),
        required_user_confirmation=True,
        generated_at=datetime.now(timezone.utc),
    )


def build_automated_evidence_decision(
    *, scenario: str, slot_id: str, candidates: tuple[MethodFit, ...],
    appraisals: tuple[EvidenceAppraisal, ...], syntheses: tuple[EvidenceSynthesis, ...],
    snapshot_id: str, release_gate_passed: bool, independent_fnirs_benchmark: bool,
    execution: tuple[ExecutionFeasibility, ...] = (), reasons: tuple[str, ...] = (),
    evidence_store: VersionedEvidenceStore | str | Path | None = None,
) -> RecommendationDecision:
    """Expose automated evidence only after both snapshot and domain-gold gates.

    A failed gate remains a shadow decision and can never acquire ``best``
    semantics or modify runtime parameters.
    """
    if not snapshot_id.strip():
        raise ValueError("snapshot_id is required")
    manifest = None
    if evidence_store is not None:
        from fnirs_flow.evidence.store import VersionedEvidenceStore

        store = (
            evidence_store
            if isinstance(evidence_store, VersionedEvidenceStore)
            else VersionedEvidenceStore(evidence_store)
        )
        manifest = store.verify_snapshot(snapshot_id)
        if manifest.status != "published" or manifest.slot_id not in {None, slot_id}:
            raise ValueError("automated_evidence_snapshot_not_eligible")
        release_gate_passed = manifest.release_gate_passed
    enabled = (
        release_gate_passed and independent_fnirs_benchmark and evidence_store is not None
        and manifest is not None and manifest.release_metrics_sha256 is not None
        and manifest.benchmark_version is not None
    )
    ordered = order_method_fit(candidates)
    chosen = ordered[0] if ordered else MethodFit(candidate_id="", status="excluded", reasons=("no candidates",))
    conflict = any(item.strength.value == "conflicting" for item in syntheses)
    execution_by_candidate = {item.candidate_id: item for item in execution}
    selected_execution = execution_by_candidate.get(chosen.candidate_id)
    selected_status = selected_execution.status if selected_execution else ExecutionStatus.READY
    mode = SourceMode.AUTOMATED_EVIDENCE if enabled else SourceMode.SHADOW
    tier, status = apply_policy(
        source_mode=mode, method_fit=chosen,
        execution_status=selected_status,
        evidence_ready=enabled, has_conflict=conflict,
    )
    # Automated evidence is machine verified, not expert validated; ``best``
    # remains unavailable even after release gates pass.
    if tier is not None and tier.value == "best":
        tier = None
    return RecommendationDecision(
        decision_id=f"automated-{uuid4().hex[:16]}", rules_version="2.0.0-automated",
        evidence_store_snapshot=snapshot_id, context=RecommendationContext(scenario=scenario),
        candidate_scope=CandidateScope(slot_id=slot_id, candidate_ids=tuple(item.candidate_id for item in ordered)),
        appraisals=appraisals, syntheses=syntheses, method_fit=ordered, execution=execution,
        tier=tier, decision_status=status,
        execution_status=selected_status,
        source_mode=mode,
        reasons=reasons
        or (("machine_verified_not_expert_validated",) if enabled else ("release_gate_failed_shadow_only",)),
        required_user_confirmation=True, generated_at=datetime.now(timezone.utc),
    )
def confirm_decision(decision: RecommendationDecision, *, confirmed_by: str) -> RecommendationDecision:
    reviewer = confirmed_by.strip()
    if not reviewer:
        raise ValueError("confirmed_by is required")
    return decision.model_copy(update={
        "decision_id": f"confirm-{uuid4().hex[:16]}",
        "rules_version": f"{decision.rules_version}-confirmed",
        "user_override": reviewer,
        "required_user_confirmation": False,
        "supersedes_decision_id": decision.decision_id,
        "reasons": tuple((*decision.reasons, f"confirmed_by:{reviewer}")),
        "generated_at": datetime.now(timezone.utc),
    })
