"""Deterministic field-level diffs and explicit recommendation re-evaluation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .candidates import order_method_fit
from .contracts import CandidateScope, RecommendationDecision
from .policy import apply_policy


def decision_diff(before: RecommendationDecision, after: RecommendationDecision) -> dict[str, Any]:
    """Return a stable, JSON-safe field-level diff between two decisions."""
    left = before.model_dump(mode="json")
    right = after.model_dump(mode="json")
    changes: list[dict[str, Any]] = []
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            changes.append({"field": key, "before": left.get(key), "after": right.get(key)})
    return {"from_decision_id": before.decision_id, "to_decision_id": after.decision_id, "changes": changes}


def reevaluate_decision(previous: RecommendationDecision, *, candidates=None) -> RecommendationDecision:
    """Create a new decision explicitly linked to an immutable prior decision."""
    fits = tuple(candidates) if candidates is not None else previous.method_fit
    ordered = order_method_fit(fits)
    chosen = ordered[0] if ordered else None
    tier, status = apply_policy(
        source_mode=previous.source_mode,
        method_fit=chosen or previous.method_fit[0],
        execution_status=previous.execution_status,
        evidence_ready=False,
    ) if chosen or previous.method_fit else (None, previous.decision_status)
    return previous.model_copy(update={
        "decision_id": f"reeval-{uuid4().hex[:16]}",
        "supersedes_decision_id": previous.decision_id,
        "candidate_scope": CandidateScope(
            slot_id=previous.candidate_scope.slot_id,
            candidate_ids=tuple(item.candidate_id for item in ordered),
            known_coverage=previous.candidate_scope.known_coverage,
            unknown_coverage=previous.candidate_scope.unknown_coverage,
        ),
        "method_fit": ordered,
        "tier": tier,
        "decision_status": status,
        "generated_at": datetime.now(timezone.utc),
    })
