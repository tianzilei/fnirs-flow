"""Fail-closed artifact-mask sidecars for vendor processed-Hb recordings."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProcessedHbArtifactMask:
    mask: Any
    sha256: str
    source_name: str
    policy_id: str
    policy_version: str


def detect_processed_hb_artifacts(
    processed_hb: Any,
    *,
    derivative_z_threshold: float = 8.0,
    level_z_threshold: float = 8.0,
    padding_seconds_each_side: float = 0.5,
    policy_id: str = "processed_hb_robust_derivative_level_v1",
    policy_version: str = "1",
) -> ProcessedHbArtifactMask:
    """Detect HbO/HbR artifacts without targets or cross-record fitting.

    Robust scales are estimated independently for each channel in one record.
    A sample is masked when either chromophore has a level or first-difference
    excursion above its frozen threshold, or when either value is non-finite.
    """
    import numpy as np

    from .windows import _normalized_signal

    if derivative_z_threshold <= 0 or level_z_threshold <= 0:
        raise ValueError("artifact z thresholds must be positive")
    if padding_seconds_each_side < 0:
        raise ValueError("artifact padding must be non-negative")
    times, hbo, hbr, _names, provenance = _normalized_signal(processed_hb)
    if len(times) < 3:
        raise ValueError("at least three samples are required for artifact detection")

    def robust_z(values: Any) -> Any:
        center = np.nanmedian(values, axis=0)
        scale = 1.4826 * np.nanmedian(np.abs(values - center), axis=0)
        fallback = np.nanstd(values, axis=0)
        scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, fallback)
        scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, 1.0)
        return np.abs(values - center) / scale

    finite = np.isfinite(hbo) & np.isfinite(hbr)
    safe_hbo = np.where(np.isfinite(hbo), hbo, np.nan)
    safe_hbr = np.where(np.isfinite(hbr), hbr, np.nan)
    mask = (
        (~finite)
        | (robust_z(safe_hbo) >= level_z_threshold)
        | (robust_z(safe_hbr) >= level_z_threshold)
    )
    mask[1:] |= (
        (robust_z(np.diff(safe_hbo, axis=0)) >= derivative_z_threshold)
        | (robust_z(np.diff(safe_hbr, axis=0)) >= derivative_z_threshold)
    )
    dt = float(np.median(np.diff(times)))
    pad = int(np.ceil(padding_seconds_each_side / dt))
    if pad:
        original = mask.copy()
        for offset in range(1, pad + 1):
            mask[offset:] |= original[:-offset]
            mask[:-offset] |= original[offset:]
    contract = {
        "policy_id": policy_id,
        "policy_version": policy_version,
        "input_sha256": str(provenance.get("sha256", "")),
        "derivative_z_threshold": derivative_z_threshold,
        "level_z_threshold": level_z_threshold,
        "padding_seconds_each_side": padding_seconds_each_side,
        "joint_chromophore_rule": "HbO_or_HbR",
        "nonfinite_is_artifact": True,
        "fit_scope": "single_record_per_channel",
    }
    digest = hashlib.sha256(
        mask.astype(np.uint8).tobytes()
        + str(times.dtype).encode()
        + times.tobytes()
        + repr(sorted(contract.items())).encode()
    ).hexdigest()
    return ProcessedHbArtifactMask(mask, digest, "automatic_detection", policy_id, policy_version)


def read_processed_hb_artifact_mask(
    path: str | Path,
    target_time_s: Sequence[float],
    channel_ids: Sequence[str],
    *,
    max_time_deviation_s: float,
    policy_id: str = "cap_processed_hb_artifact_mask_v1",
    policy_version: str = "1",
) -> ProcessedHbArtifactMask:
    """Read a ``time_s + channel`` Boolean mask and align it by nearest time.

    Values must be explicit ``0/1`` (or ``true/false``). Missing rows,
    channels, ambiguous timestamps and excessive alignment deviation fail
    closed; an absent mask is never interpreted as an all-good recording.
    """
    import numpy as np

    source = Path(path)
    payload = source.read_bytes()
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or fields[0] != "time_s":
        raise ValueError("ARTIFACT_MASK_SCHEMA_INVALID: first column must be time_s")
    expected = list(map(str, channel_ids))
    observed = fields[1:]
    if observed != expected:
        raise ValueError("ARTIFACT_MASK_CHANNEL_MISMATCH")
    if not rows:
        raise ValueError("ARTIFACT_MASK_EMPTY")
    try:
        source_time = np.asarray([float(row["time_s"]) for row in rows], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("ARTIFACT_MASK_TIME_INVALID") from exc
    if not np.isfinite(source_time).all() or np.any(np.diff(source_time) <= 0):
        raise ValueError("ARTIFACT_MASK_TIME_INVALID")

    truth = {"1", "true"}
    falsehood = {"0", "false"}
    source_mask = np.empty((len(rows), len(expected)), dtype=bool)
    for row_index, row in enumerate(rows):
        for channel_index, channel in enumerate(expected):
            value = str(row.get(channel, "")).strip().casefold()
            if value not in truth | falsehood:
                raise ValueError("ARTIFACT_MASK_VALUE_INVALID")
            source_mask[row_index, channel_index] = value in truth

    target = np.asarray(target_time_s, dtype=float)
    if target.ndim != 1 or not np.isfinite(target).all():
        raise ValueError("ARTIFACT_MASK_TARGET_TIME_INVALID")
    right = np.searchsorted(source_time, target, side="left")
    right = np.clip(right, 0, len(source_time) - 1)
    left = np.clip(right - 1, 0, len(source_time) - 1)
    choose_left = np.abs(target - source_time[left]) <= np.abs(source_time[right] - target)
    nearest = np.where(choose_left, left, right)
    deviation = np.abs(target - source_time[nearest])
    if np.any(deviation > float(max_time_deviation_s)):
        raise ValueError("ARTIFACT_MASK_ALIGNMENT_EXCEEDED")
    return ProcessedHbArtifactMask(
        source_mask[nearest],
        hashlib.sha256(payload).hexdigest(),
        source.name,
        policy_id,
        policy_version,
    )
