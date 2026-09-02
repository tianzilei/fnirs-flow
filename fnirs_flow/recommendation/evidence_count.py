"""Transparent, count-based evidence ranking for shadow evaluation.

This module deliberately does not produce a ``best`` recommendation.  It
counts independent study/dataset clusters after conservative provenance
checks, so the result is reproducible without requiring subjective appraisal
scores.  It is a triage signal, not a causal estimate of method quality.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from math import log1p


@dataclass(frozen=True)
class CountEvidence:
    evidence_id: str
    candidate_id: str
    study_id: str | None = None
    dataset_id: str | None = None
    direction: str = "neutral"
    source_content_level: str = "metadata_only"
    evidence_level: str = "not_reported"
    source_valid: bool = False
    has_locator: bool = False
    has_claim: bool = False
    has_target: bool = False
    withdrawn_or_corrected: bool = False


@dataclass(frozen=True)
class EvidenceCountRank:
    candidate_id: str
    supporting_studies: int
    opposing_studies: int
    supporting_weight: float
    opposing_weight: float
    independent_study_clusters: tuple[str, ...]
    score: float | None
    eligible_evidence_count: int
    excluded_evidence_count: int
    status: str
    reasons: tuple[str, ...] = ()


_SOURCE_WEIGHT = {"full_text": 1.0, "abstract_only": 0.5, "metadata_only": 0.1}
_LEVEL_WEIGHT = {"verbatim": 1.0, "inferred": 0.5, "not_reported": 0.0, "not_applicable": 0.0}


def _eligible(item: CountEvidence) -> bool:
    return (
        item.source_valid
        and item.has_locator
        and item.has_claim
        and item.has_target
        and not item.withdrawn_or_corrected
        and item.direction in {"supports", "opposes"}
        and _LEVEL_WEIGHT.get(item.evidence_level, 0.0) > 0
    )


def _cluster_id(item: CountEvidence) -> str:
    # Dataset identity is preferred; study identity is the next-best unit.
    # Falling back to source keeps the row count auditable but does not claim
    # that separate sources are independent studies.
    return (item.dataset_id or item.study_id or f"source:{item.evidence_id}").strip()


def rank_by_evidence_count(
    evidence: Iterable[CountEvidence], *, min_independent_studies: int = 2
) -> tuple[EvidenceCountRank, ...]:
    """Rank candidates by weighted independent support minus opposition.

    Multiple evidence rows from one study/dataset count once per direction;
    the row with the highest provenance weight is retained.  The score uses
    ``log1p`` to prevent a large bibliography from overwhelming replication
    breadth.  ``status`` is ``ranked_shadow`` only when the candidate has the
    configured minimum independent clusters and no tie/conflict gate is
    required by the caller.
    """
    grouped: dict[str, dict[str, dict[str, CountEvidence]]] = defaultdict(lambda: defaultdict(dict))
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for item in evidence:
        if not _eligible(item):
            totals[item.candidate_id][1] += 1
            continue
        totals[item.candidate_id][0] += 1
        cluster = _cluster_id(item)
        current = grouped[item.candidate_id][item.direction].get(cluster)
        weight = _SOURCE_WEIGHT.get(item.source_content_level, 0.1) * _LEVEL_WEIGHT[item.evidence_level]
        current_weight = (
            _SOURCE_WEIGHT.get(current.source_content_level, 0.1)
            * _LEVEL_WEIGHT.get(current.evidence_level, 0.0)
            if current
            else -1.0
        )
        if weight > current_weight:
            grouped[item.candidate_id][item.direction][cluster] = item

    ranks: list[EvidenceCountRank] = []
    for candidate_id in sorted(set(grouped) | set(totals)):
        supports = grouped[candidate_id].get("supports", {})
        opposes = grouped[candidate_id].get("opposes", {})
        sw = sum(
            _SOURCE_WEIGHT.get(x.source_content_level, 0.1) * _LEVEL_WEIGHT[x.evidence_level]
            for x in supports.values()
        )
        ow = sum(
            _SOURCE_WEIGHT.get(x.source_content_level, 0.1) * _LEVEL_WEIGHT[x.evidence_level]
            for x in opposes.values()
        )
        clusters = tuple(sorted(set(supports) | set(opposes)))
        # A candidate with no eligible evidence has no estimable score.  Keep
        # this distinct from a neutral numeric score so downstream consumers
        # cannot mistake an empty record set for balanced evidence.
        eligible, excluded = totals[candidate_id]
        score = log1p(sw) - log1p(ow) if eligible else None
        reasons: list[str] = []
        if eligible == 0:
            reasons.append("no_eligible_evidence")
        if len(clusters) < min_independent_studies:
            reasons.append("insufficient_independent_studies")
        if supports and opposes:
            reasons.append("conflicting_directions")
        status = "ranked_shadow" if not reasons else "needs_review"
        ranks.append(
            EvidenceCountRank(
                candidate_id,
                len(supports),
                len(opposes),
                round(sw, 6),
                round(ow, 6),
                clusters,
                round(score, 6) if score is not None else None,
                eligible,
                excluded,
                status,
                tuple(reasons),
            )
        )
    # ``None`` scores sort after numeric scores while retaining deterministic
    # candidate ordering.
    return tuple(sorted(ranks, key=lambda x: (x.score is None, -(x.score or 0.0), x.candidate_id)))
