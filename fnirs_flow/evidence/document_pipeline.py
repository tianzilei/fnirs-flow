"""Deterministic source-version contracts for the fully automated evidence path."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PipelineState(str, Enum):
    DISCOVERED = "discovered"
    ACQUIRED = "acquired"
    PARSED = "parsed"
    SEGMENTED = "segmented"
    PROPOSED_A = "proposed_a"
    PROPOSED_B = "proposed_b"
    DETERMINISTIC_VERIFIED = "deterministic_verified"
    SEMANTIC_VERIFIED = "semantic_verified"
    CLUSTERED = "clustered"
    APPRAISED = "appraised"
    ADMITTED = "admitted"
    SYNTHESIZED = "synthesized"
    SNAPSHOT_PUBLISHED = "snapshot_published"
    QUARANTINED = "quarantined"
    REPROCESSING = "reprocessing"
    INVALIDATED = "invalidated"
    METADATA_ONLY = "metadata_only"


class ContentLevel(str, Enum):
    FULL_TEXT = "full_text"
    SECTIONAL_FULL_TEXT = "sectional_full_text"
    ABSTRACT_ONLY = "abstract_only"
    METADATA_ONLY = "metadata_only"


class SourceVersion(BaseModel):
    """Immutable acquisition record; changed bytes always mean a new version."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source_version_id: str
    source_id: str
    study_id: str | None = None
    report_type: str = "article"
    identifiers: dict[str, str] = Field(default_factory=dict)
    canonical_url: str | None = None
    content_level: ContentLevel
    raw_sha256: str | None = None
    acquired_at: datetime
    response_metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)
    license_status: str = "unknown"
    parser_version: str
    source_status: str = "active"

    @model_validator(mode="after")
    def validate_content(self) -> SourceVersion:
        if self.content_level in {ContentLevel.FULL_TEXT, ContentLevel.SECTIONAL_FULL_TEXT} and self.raw_sha256 is None:
            raise ValueError("text source versions require raw_sha256")
        if self.raw_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", self.raw_sha256):
            raise ValueError("raw_sha256 must be a 64-character hexadecimal SHA-256")
        return self

    @property
    def synthesis_eligible(self) -> bool:
        return self.content_level in {
            ContentLevel.FULL_TEXT,
            ContentLevel.SECTIONAL_FULL_TEXT,
        } and self.source_status == "active"


class StateTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    object_id: str
    old_state: PipelineState
    new_state: PipelineState
    reason_code: str
    input_sha256: str
    output_sha256: str
    execution_version: str
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_hashes(self) -> StateTransition:
        for value in (self.input_sha256, self.output_sha256):
            if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                raise ValueError("state transition hashes must be 64-character SHA-256 values")
        return self


_FORWARD: dict[PipelineState, frozenset[PipelineState]] = {
    PipelineState.DISCOVERED: frozenset({PipelineState.ACQUIRED, PipelineState.METADATA_ONLY}),
    PipelineState.ACQUIRED: frozenset({PipelineState.PARSED}),
    PipelineState.PARSED: frozenset({PipelineState.SEGMENTED}),
    PipelineState.SEGMENTED: frozenset({PipelineState.PROPOSED_A, PipelineState.PROPOSED_B}),
    PipelineState.PROPOSED_A: frozenset({PipelineState.PROPOSED_B, PipelineState.DETERMINISTIC_VERIFIED}),
    PipelineState.PROPOSED_B: frozenset({PipelineState.PROPOSED_A, PipelineState.DETERMINISTIC_VERIFIED}),
    PipelineState.DETERMINISTIC_VERIFIED: frozenset({PipelineState.SEMANTIC_VERIFIED}),
    PipelineState.SEMANTIC_VERIFIED: frozenset({PipelineState.CLUSTERED}),
    PipelineState.CLUSTERED: frozenset({PipelineState.APPRAISED}),
    PipelineState.APPRAISED: frozenset({PipelineState.ADMITTED}),
    PipelineState.ADMITTED: frozenset({PipelineState.SYNTHESIZED}),
    PipelineState.SYNTHESIZED: frozenset({PipelineState.SNAPSHOT_PUBLISHED}),
    PipelineState.QUARANTINED: frozenset({PipelineState.REPROCESSING}),
    PipelineState.REPROCESSING: frozenset({PipelineState.PARSED, PipelineState.SEGMENTED}),
}


def validate_transition(old_state: PipelineState, new_state: PipelineState) -> None:
    """Reject state skipping. Failure and source invalidation are explicit side exits."""
    if old_state in {PipelineState.INVALIDATED, PipelineState.SNAPSHOT_PUBLISHED}:
        raise ValueError(f"invalid_evidence_state_transition:{old_state.value}:{new_state.value}")
    if new_state in {PipelineState.QUARANTINED, PipelineState.INVALIDATED} and old_state not in {
        PipelineState.QUARANTINED, PipelineState.INVALIDATED,
    }:
        return
    if new_state not in _FORWARD.get(old_state, frozenset()):
        raise ValueError(f"invalid_evidence_state_transition:{old_state.value}:{new_state.value}")


def normalize_source_text(value: str) -> str:
    """Normalize layout noise without paraphrasing or interpreting source text."""
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n"))


def source_version_id(source_id: str, raw_bytes: bytes, parser_version: str) -> str:
    digest = hashlib.sha256(raw_bytes).hexdigest()
    identity = hashlib.sha256(f"{source_id}\0{digest}\0{parser_version}".encode()).hexdigest()
    return f"srcv-{identity[:24]}"
