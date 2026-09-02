"""Audit contract for an externally validated TXT-to-SNIRF conversion.

This module deliberately does not implement or register a converter. It only
verifies evidence produced by the project-side converter and independent
round-trip reader, keeping ``hardware_import`` distinct from validated
Shimadzu/NIRS-SPM TXT-to-SNIRF conversion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REQUIRED_PRESERVATION_CHECKS = (
    "channel_count_equal",
    "time_axis_equal",
    "timestamps_equal",
    "events_equal",
    "hbo_values_equal",
    "hbr_values_equal",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_txt_to_snirf_roundtrip_audit(
    audit: str | Path | Mapping[str, Any],
    *,
    input_txt: str | Path | None = None,
    output_snirf: str | Path | None = None,
) -> dict[str, Any]:
    """Validate converter identity, file hashes, and preservation evidence."""
    if isinstance(audit, Mapping):
        payload = dict(audit)
    else:
        payload = json.loads(Path(audit).read_text(encoding="utf-8"))
    required_text = (
        "converter_name",
        "converter_version",
        "converter_commit",
        "input_txt_sha256",
        "output_snirf_sha256",
    )
    missing = [key for key in required_text if not str(payload.get(key, "")).strip()]
    if missing:
        raise ValueError(f"CONVERSION_AUDIT_REQUIRED_FIELD_MISSING: {', '.join(missing)}")
    for key in ("input_txt_sha256", "output_snirf_sha256", "converter_commit"):
        value = str(payload[key]).lower()
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(f"CONVERSION_AUDIT_INVALID_SHA256: {key}")
    checks = payload.get("roundtrip_checks")
    if not isinstance(checks, Mapping):
        raise ValueError("CONVERSION_AUDIT_ROUNDTRIP_CHECKS_MISSING")
    failed = [key for key in REQUIRED_PRESERVATION_CHECKS if checks.get(key) is not True]
    if failed:
        raise ValueError(f"CONVERSION_ROUNDTRIP_NOT_PRESERVED: {', '.join(failed)}")
    if input_txt is not None:
        path = Path(input_txt)
        if not path.is_file() or _sha256(path) != str(payload["input_txt_sha256"]).lower():
            raise ValueError("CONVERSION_INPUT_HASH_MISMATCH")
    if output_snirf is not None:
        path = Path(output_snirf)
        if not path.is_file() or _sha256(path) != str(payload["output_snirf_sha256"]).lower():
            raise ValueError("CONVERSION_OUTPUT_HASH_MISMATCH")
    return {
        "status": "validated_external_roundtrip_evidence",
        "converter_name": str(payload["converter_name"]),
        "converter_version": str(payload["converter_version"]),
        "converter_commit": str(payload["converter_commit"]).lower(),
        "input_txt_sha256": str(payload["input_txt_sha256"]).lower(),
        "output_snirf_sha256": str(payload["output_snirf_sha256"]).lower(),
        "roundtrip_checks": {key: True for key in REQUIRED_PRESERVATION_CHECKS},
        "operation_registration": "not_registered",
    }
