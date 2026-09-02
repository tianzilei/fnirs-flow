"""Non-generative verification for exact quotes, locators, values, units and targets."""

from __future__ import annotations

import math
import re
from enum import Enum

from pydantic import BaseModel, ConfigDict

from .document_pipeline import normalize_source_text
from .extraction_proposals import ExtractionProposal
from .segment_ledger import DocumentSegment, replay_locator


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class VerificationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    check_id: str
    status: CheckStatus
    reason_code: str


class DeterministicVerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    verification_run_id: str
    proposal_id: str
    verifier_version: str
    checks: tuple[VerificationCheck, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(item.status is CheckStatus.PASS for item in self.checks)


_UNITS: dict[str, tuple[str, float]] = {
    "hz": ("frequency", 1.0),
    "mhz": ("frequency", 0.001),
    "s": ("time", 1.0),
    "ms": ("time", 0.001),
    "%": ("ratio", 0.01),
    "nm": ("length", 1e-9),
    "mm": ("length", 1e-3),
    "cm": ("length", 1e-2),
    "m": ("length", 1.0),
}


def unit_dimension(unit: str) -> str | None:
    entry = _UNITS.get(unit.strip().lower())
    return entry[0] if entry else None


def verify_proposal(
    proposal: ExtractionProposal,
    segment: DocumentSegment,
    source_text: str,
    *,
    verification_run_id: str,
    verifier_version: str,
    valid_target_ids: set[str] | frozenset[str],
    source_active: bool = True,
    minimum_ocr_confidence: float = 0.99,
) -> DeterministicVerificationResult:
    checks: list[VerificationCheck] = []

    def record(check_id: str, passed: bool, fail_code: str) -> None:
        checks.append(
            VerificationCheck(
                check_id=check_id,
                status=CheckStatus.PASS if passed else CheckStatus.FAIL,
                reason_code="ok" if passed else fail_code,
            )
        )

    record("source_binding", proposal.source_version_id == segment.source_version_id, "source_version_mismatch")
    record("segment_binding", proposal.segment_id == segment.segment_id, "segment_id_mismatch")
    try:
        replayed = replay_locator(source_text, segment)
        locator_ok = proposal.locator == segment.locator
    except ValueError:
        replayed, locator_ok = "", False
    record("locator_replay", locator_ok, "locator_replay_failed")
    normalized_source = normalize_source_text(source_text)
    prefix_ok = (
        not proposal.locator.prefix
        or normalized_source[
            max(0, proposal.locator.char_start - len(proposal.locator.prefix)) : proposal.locator.char_start
        ]
        == proposal.locator.prefix
    )
    suffix_ok = (
        not proposal.locator.suffix
        or normalized_source[proposal.locator.char_end : proposal.locator.char_end + len(proposal.locator.suffix)]
        == proposal.locator.suffix
    )
    record("locator_prefix", prefix_ok, "locator_prefix_mismatch")
    record("locator_suffix", suffix_ok, "locator_suffix_mismatch")
    record("quote_exact_match", proposal.quote in replayed, "quote_exact_match_failed")
    record("source_status", source_active, "source_invalidated")
    record("target_exists", proposal.target_id in valid_target_ids, "target_not_registered")
    record(
        "atomic_claim_fields",
        bool(proposal.subject.strip() and proposal.predicate.strip() and proposal.object.strip()),
        "claim_not_atomic",
    )
    if segment.ocr_min_character_confidence is not None:
        record(
            "ocr_confidence",
            segment.ocr_min_character_confidence >= minimum_ocr_confidence,
            "ocr_numeric_or_unit_confidence_low",
        )
    if proposal.numeric is not None:
        parsed = re.search(r"[-+]?\d+(?:\.\d+)?", proposal.numeric.raw.replace(",", ""))
        parsed_value = float(parsed.group()) if parsed else None
        numeric_ok = (
            parsed_value is not None
            and proposal.numeric.value is not None
            and math.isclose(parsed_value, proposal.numeric.value, rel_tol=1e-12, abs_tol=1e-12)
        )
        record("numeric_round_trip", numeric_ok, "numeric_round_trip_failed")
        unit_ok = proposal.numeric.unit is not None and unit_dimension(proposal.numeric.unit) is not None
        record("unit_dimension", unit_ok, "unit_unknown_or_dimension_invalid")
        record("numeric_anchored", proposal.numeric.raw in proposal.quote, "numeric_not_in_quote")
    return DeterministicVerificationResult(
        verification_run_id=verification_run_id,
        proposal_id=proposal.proposal_id,
        verifier_version=verifier_version,
        checks=tuple(checks),
    )
