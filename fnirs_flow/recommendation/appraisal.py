"""Deterministic claim-level evidence appraisal without implicit scoring."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from typing import cast

from .contracts import EvidenceAppraisal


def _load_profile() -> dict[str, object]:
    resource = files("fnirs_flow.resources.schemas").joinpath("machine_appraisal_profile.v2.json")
    return dict(json.loads(resource.read_text(encoding="utf-8")))


def appraise_evidence(
    *,
    evidence_id: str,
    claim_type: str,
    values: Mapping[str, float | None],
    reasons: Mapping[str, str],
    source_locator: str | None,
) -> EvidenceAppraisal:
    """Create an appraisal; missing required dimensions keep score ``None``."""
    profile = _load_profile()
    configured = cast(dict[str, list[str]], profile["claim_type_dimensions"])
    if claim_type not in configured:
        # Unknown claim types must fail closed; silently applying the
        # method-definition profile would fabricate appraisal semantics.
        raise ValueError(f"unknown_claim_type:{claim_type}")
    dimensions = tuple(configured[claim_type])
    normalized = {name: values.get(name) for name in dimensions}
    normalized_reasons = {name: reasons.get(name, "not provided") for name in dimensions}
    missing = [name for name, value in normalized.items() if value is None]
    return EvidenceAppraisal(
        evidence_id=evidence_id,
        claim_type=claim_type,
        profile_version=str(profile["profile_version"]),
        dimensions=normalized,
        dimension_reasons=normalized_reasons,
        source_locator=source_locator,
        score=None,
        score_reason="required appraisal dimensions missing" if missing else "scoring deferred until calibrated",
    )
