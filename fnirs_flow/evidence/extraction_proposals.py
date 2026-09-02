"""Strict extraction proposal contracts; extractors never write formal claims."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .segment_ledger import SegmentLocator


class ExtractorLane(str, Enum):
    A = "a"
    B = "b"


class ClaimDirection(str, Enum):
    SUPPORTS = "supports"
    DISCOURAGES = "discourages"
    MIXED = "mixed"
    INSUFFICIENT = "insufficient"


class TargetType(str, Enum):
    METHOD_ATOM = "MethodAtom"
    PARAMETER_CANDIDATE = "ParameterCandidate"
    FLOW_SLOT = "FlowSlot"
    RISK_RULE = "RiskRule"
    REPORTING_REQUIREMENT = "ReportingRequirement"
    REPRODUCIBILITY_ARTIFACT = "ReproducibilityArtifact"


class NumericValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw: str
    value: float | None = None
    unit: str | None = None
    lower: float | None = None
    upper: float | None = None
    uncertainty: float | None = None
    context: str = ""


class ExtractionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: str = "2.0.0"
    proposal_id: str
    source_version_id: str
    segment_id: str
    quote: str = Field(min_length=1)
    locator: SegmentLocator
    claim_type: str
    subject: str
    predicate: str
    object: str
    qualifiers: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    extractor_run_id: str
    extractor_lane: ExtractorLane
    model_family: str
    model_version: str
    prompt_sha256: str
    target_type: TargetType
    target_id: str
    direction: ClaimDirection = ClaimDirection.INSUFFICIENT
    study_id: str | None = None
    dataset_id: str | None = None
    numeric: NumericValue | None = None
    external_knowledge: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_unanchored_knowledge(self) -> ExtractionProposal:
        if self.external_knowledge:
            raise ValueError("external_knowledge_not_allowed")
        return self


CRITICAL_FIELDS = (
    "claim_type", "subject", "predicate", "object", "numeric", "direction",
    "target_type", "target_id", "study_id", "dataset_id", "locator",
)


def normalized_critical_fields(proposal: ExtractionProposal) -> dict[str, Any]:
    data = proposal.model_dump(mode="json")
    normalized = {key: data[key] for key in CRITICAL_FIELDS}
    for key in ("claim_type", "subject", "predicate", "object", "target_id", "study_id", "dataset_id"):
        value = normalized[key]
        normalized[key] = value.strip() if isinstance(value, str) else value
    return normalized


def validate_extractor_independence(a: ExtractionProposal, b: ExtractionProposal) -> None:
    if a.extractor_lane is not ExtractorLane.A or b.extractor_lane is not ExtractorLane.B:
        raise ValueError("extractor_lanes_must_be_a_and_b")
    if a.model_family == b.model_family:
        raise ValueError("extractors_not_independent:model_family")
    if a.segment_id != b.segment_id or a.source_version_id != b.source_version_id:
        raise ValueError("extractors_received_different_source_segment")
