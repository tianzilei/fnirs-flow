"""Decision policy for static/shadow rollout; evidence mode is gated."""

from __future__ import annotations

from .contracts import DecisionStatus, ExecutionStatus, MethodFit, SourceMode, Tier


def apply_policy(
    *,
    source_mode: SourceMode,
    method_fit: MethodFit,
    execution_status: ExecutionStatus,
    evidence_ready: bool,
    has_conflict: bool = False,
) -> tuple[Tier | None, DecisionStatus]:
    if method_fit.status in {"excluded", "ineligible"} or has_conflict:
        return Tier.NOT_RECOMMENDED, DecisionStatus.EXCLUDED
    if execution_status is ExecutionStatus.BLOCKED:
        return None, DecisionStatus.NEEDS_INPUT
    if source_mode in {SourceMode.EVIDENCE_DRIVEN, SourceMode.AUTOMATED_EVIDENCE} and not evidence_ready:
        return None, DecisionStatus.NEEDS_REVIEW
    if source_mode not in {SourceMode.EVIDENCE_DRIVEN, SourceMode.AUTOMATED_EVIDENCE}:
        return Tier.RECOMMENDED, DecisionStatus.ELIGIBLE
    return Tier.ALTERNATIVE, DecisionStatus.ELIGIBLE
