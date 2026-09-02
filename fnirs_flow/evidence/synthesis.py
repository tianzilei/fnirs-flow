"""Deterministic, conservative synthesis for admitted automated evidence."""

from __future__ import annotations

from collections import Counter
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SynthesisStatus(str, Enum):
    UNVERIFIED = "unverified"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"
    SUPPORTED = "supported"
    DISCOURAGED = "discouraged"


class AdmittedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_id: str
    evidence_id: str
    component_id: str
    direction: str
    source_status: str = "active"
    appraisal_complete: bool = False
    direct: bool = True
    precise: bool = False
    context: str = ""


class AutomatedSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    synthesis_id: str
    snapshot_id: str
    policy_version: str
    query_context: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    status: SynthesisStatus
    score: None = None
    supporting_components: tuple[str, ...] = ()
    discouraging_components: tuple[str, ...] = ()
    excluded_evidence: dict[str, str] = Field(default_factory=dict)
    direction_counts: dict[str, int] = Field(default_factory=dict)
    lineage: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


def synthesize(
    *, synthesis_id: str, snapshot_id: str, policy_version: str,
    evidence: tuple[AdmittedEvidence, ...], query_context: dict[str, str | int | float | bool | None] | None = None,
) -> AutomatedSynthesis:
    """Deduplicate components and abstain unless every required fact is machine-verifiable."""
    excluded: dict[str, str] = {}
    representatives: dict[tuple[str, str], AdmittedEvidence] = {}
    for item in sorted(evidence, key=lambda row: (row.component_id, row.direction, row.evidence_id)):
        if item.source_status != "active":
            excluded[item.evidence_id] = "source_invalidated"
            continue
        if item.direction not in {"supports", "discourages"}:
            excluded[item.evidence_id] = "direction_insufficient_or_mixed"
            continue
        representatives.setdefault((item.component_id, item.direction), item)
    supports = tuple(sorted(key[0] for key in representatives if key[1] == "supports"))
    discourages = tuple(sorted(key[0] for key in representatives if key[1] == "discourages"))
    eligible = tuple(representatives.values())
    if not eligible:
        status, reasons = SynthesisStatus.UNVERIFIED, ("no_eligible_evidence",)
    elif supports and discourages:
        status, reasons = SynthesisStatus.CONFLICTING, ("opposing_independent_components",)
    elif len({item.component_id for item in eligible}) < 2:
        status, reasons = SynthesisStatus.INSUFFICIENT, ("fewer_than_two_independence_components",)
    elif not all(item.appraisal_complete and item.direct and item.precise for item in eligible):
        status, reasons = SynthesisStatus.INSUFFICIENT, ("quality_directness_or_precision_unknown",)
    elif supports:
        status, reasons = SynthesisStatus.SUPPORTED, ("deterministic_policy_satisfied",)
    else:
        status, reasons = SynthesisStatus.DISCOURAGED, ("deterministic_policy_satisfied",)
    counts = Counter(item.direction for item in eligible)
    return AutomatedSynthesis(
        synthesis_id=synthesis_id, snapshot_id=snapshot_id, policy_version=policy_version,
        query_context=query_context or {}, status=status, supporting_components=supports,
        discouraging_components=discourages, excluded_evidence=dict(sorted(excluded.items())),
        direction_counts=dict(sorted(counts.items())),
        lineage=tuple(sorted(item.claim_id for item in eligible)), reason_codes=reasons,
    )
