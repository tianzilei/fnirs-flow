"""Evidence synthesis using study/dataset independence and explicit conflicts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from .contracts import EvidenceDirection, EvidenceStrength, EvidenceSynthesis


def synthesize_evidence(
    claim_id: str,
    records: Iterable[Mapping[str, str | None]],
) -> EvidenceSynthesis:
    """Synthesize deterministically; duplicate study/dataset reports count once."""
    rows = sorted((dict(row) for row in records), key=lambda row: str(row.get("evidence_id", "")))
    clusters: dict[str, list[str]] = defaultdict(list)
    directions: set[str] = set()
    admitted: list[dict[str, str | None]] = []
    exclusion_reasons: set[str] = set()
    for row in rows:
        # Synthesis is fail-closed: only an explicit admission decision may
        # enter the evidence base. Missing admission metadata is not treated
        # as implicitly admitted.
        if row.get("admitted") not in {True, 1, "true", "1"}:
            exclusion_reasons.add("not_admitted")
            continue
        if row.get("withdrawn_or_corrected") in {True, 1, "true", "1"}:
            exclusion_reasons.add("withdrawn_or_corrected")
            continue
        if row.get("direction") == EvidenceDirection.BACKGROUND_ONLY.value:
            exclusion_reasons.add("background_only")
            continue
        direction_raw = row.get("direction")
        if direction_raw not in {item.value for item in EvidenceDirection}:
            exclusion_reasons.add("invalid_direction")
            continue
        key = str(row.get("study_id") or row.get("dataset_id") or row.get("evidence_id"))
        clusters[key].append(str(row.get("evidence_id", "")))
        directions.add(str(row.get("direction") or EvidenceDirection.NEUTRAL.value))
        admitted.append(row)
    if not admitted:
        strength = EvidenceStrength.INSUFFICIENT
        direction = EvidenceDirection.NEUTRAL
    elif EvidenceDirection.SUPPORTS.value in directions and EvidenceDirection.OPPOSES.value in directions:
        strength = EvidenceStrength.CONFLICTING
        direction = EvidenceDirection.NEUTRAL
    else:
        # Report or cluster counts are coverage information, never a proxy for
        # scientific strength.  Until versioned appraisal/directness/
        # imprecision inputs pass calibration, synthesis must abstain.
        required = ("appraisal_complete", "directness_resolved", "precision_resolved")
        calibrated = all(row.get("calibrated") in {"true", "1"} for row in admitted)
        complete = calibrated and all(row.get(field) in {"true", "1"} for row in admitted for field in required)
        strength = EvidenceStrength.LOW if complete else EvidenceStrength.INSUFFICIENT
        direction = EvidenceDirection(next(iter(directions))) if directions else EvidenceDirection.NEUTRAL
    return EvidenceSynthesis(
        claim_id=claim_id,
        strength=strength,
        direction=direction,
        evidence_ids=tuple(str(row.get("evidence_id", "")) for row in admitted),
        independent_study_clusters=tuple(tuple(values) for _, values in sorted(clusters.items())),
        coverage="known" if admitted else "unknown",
        conflicts=("opposing admitted evidence",) if strength is EvidenceStrength.CONFLICTING else (),
        reasons=tuple(sorted(exclusion_reasons)) + (
            "independence clustered by study/dataset",
            "cluster count does not determine evidence strength",
        ),
    )
