"""Exhaustive, replayable document segment ledger."""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .document_pipeline import normalize_source_text


class SegmentKind(str, Enum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    FOOTNOTE = "footnote"
    FIGURE_CAPTION = "figure_caption"
    TABLE_CELL = "table_cell"


class SegmentStatus(str, Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    UNSUPPORTED = "unsupported"
    EMPTY = "empty"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class SegmentLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_version: str
    xpath: str | None = None
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    prefix: str = ""
    suffix: str = ""
    table_row_headers: tuple[str, ...] = ()
    table_column_headers: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_span(self) -> SegmentLocator:
        if self.char_end < self.char_start:
            raise ValueError("char_end must be greater than or equal to char_start")
        if self.xpath is None and self.page is None:
            raise ValueError("locator requires xpath or page")
        return self


class DocumentSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segment_id: str
    source_version_id: str
    parent_segment_id: str | None = None
    kind: SegmentKind
    normalized_text: str
    raw_text_sha256: str
    normalized_text_sha256: str
    locator: SegmentLocator
    parser_version: str
    status: SegmentStatus = SegmentStatus.PENDING
    ocr_page_image_sha256: str | None = None
    ocr_engine_version: str | None = None
    ocr_min_character_confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_table_and_ocr(self) -> DocumentSegment:
        if self.kind is SegmentKind.TABLE_CELL and not (
            self.locator.table_row_headers or self.locator.table_column_headers
        ):
            raise ValueError("table_cell_missing_header_context")
        ocr_fields = (self.ocr_page_image_sha256, self.ocr_engine_version, self.ocr_min_character_confidence)
        if any(value is not None for value in ocr_fields) and not all(value is not None for value in ocr_fields):
            raise ValueError("OCR provenance fields must be supplied together")
        return self


def make_segment(
    *, source_version_id: str, kind: SegmentKind, raw_text: str, locator: SegmentLocator,
    parser_version: str, parent_segment_id: str | None = None,
) -> DocumentSegment:
    normalized = normalize_source_text(raw_text)
    raw_hash = hashlib.sha256(raw_text.encode()).hexdigest()
    text_hash = hashlib.sha256(normalized.encode()).hexdigest()
    identity = hashlib.sha256(
        f"{source_version_id}\0{kind.value}\0{locator.model_dump_json()}\0{text_hash}".encode()
    ).hexdigest()
    return DocumentSegment(
        segment_id=f"seg-{identity[:24]}", source_version_id=source_version_id,
        parent_segment_id=parent_segment_id, kind=kind, normalized_text=normalized,
        raw_text_sha256=raw_hash, normalized_text_sha256=text_hash, locator=locator,
        parser_version=parser_version, status=SegmentStatus.EMPTY if not normalized else SegmentStatus.PENDING,
    )


def replay_locator(source_text: str, segment: DocumentSegment) -> str:
    """Recompute a locator and require both exact text and checksum equality."""
    normalized = normalize_source_text(source_text)
    observed = normalized[segment.locator.char_start:segment.locator.char_end]
    if hashlib.sha256(observed.encode()).hexdigest() != segment.normalized_text_sha256:
        raise ValueError("locator_text_hash_mismatch")
    if observed != segment.normalized_text:
        raise ValueError("locator_exact_match_failed")
    return observed
