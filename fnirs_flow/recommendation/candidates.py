"""Deterministic candidate generation and ordering for shadow evaluation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .contracts import CandidateScope, MethodFit


def build_candidate_scope(slot_id: str, candidates: Iterable[Mapping[str, object]]) -> CandidateScope:
    """Normalize candidate IDs in stable order and retain coverage metadata."""
    rows = sorted(candidates, key=lambda row: str(row.get("candidate_id", "")))
    ids = tuple(str(row.get("candidate_id")) for row in rows if row.get("candidate_id"))
    known = tuple(str(row["candidate_id"]) for row in rows if row.get("known", True) and row.get("candidate_id"))
    unknown = tuple(str(row["candidate_id"]) for row in rows if not row.get("known", True) and row.get("candidate_id"))
    return CandidateScope(slot_id=slot_id, candidate_ids=ids, known_coverage=known, unknown_coverage=unknown)


def order_method_fit(candidates: Iterable[MethodFit]) -> tuple[MethodFit, ...]:
    """Stable order by status then candidate ID; no citation/count weighting."""
    priority = {"eligible": 0, "needs_review": 1, "ineligible": 2, "excluded": 3}
    return tuple(sorted(candidates, key=lambda item: (priority.get(item.status, 9), item.candidate_id)))
