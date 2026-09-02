"""Strict output contract and boundary checks for the independent semantic verifier C."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SemanticVerdict(str, Enum):
    ENTAILED = "entailed"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    segment_id: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_span(self) -> EvidenceSpan:
        if self.char_end <= self.char_start:
            raise ValueError("semantic evidence span must be non-empty")
        return self


class SemanticVerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    verification_run_id: str
    proposal_id: str
    verifier_model_family: str
    verifier_model_version: str
    prompt_sha256: str
    verdict: SemanticVerdict
    evidence_spans: tuple[EvidenceSpan, ...] = ()
    checks: dict[str, SemanticVerdict] = Field(default_factory=dict)


def semantic_result_is_admissible(
    result: SemanticVerificationResult, *, segment_id: str, segment_length: int
) -> bool:
    if result.verdict is not SemanticVerdict.ENTAILED or not result.evidence_spans:
        return False
    if any(value is not SemanticVerdict.ENTAILED for value in result.checks.values()):
        return False
    return all(
        span.segment_id == segment_id and span.char_end <= segment_length
        for span in result.evidence_spans
    )
