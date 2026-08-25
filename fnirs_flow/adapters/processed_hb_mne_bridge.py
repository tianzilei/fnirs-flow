"""Explicit time regularization for processed-Hb recordings.

This module does not infer events and never replaces the delivered native
timestamps. It creates a separate runtime view after all thresholds pass.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fnirs_flow.data.processed_hb_models import ProcessedHbRecording


@dataclass(frozen=True)
class RegularizedHbRecording:
    timestamps_s: np.ndarray
    hbo: np.ndarray
    hbr: np.ndarray
    source: ProcessedHbRecording
    target_sfreq_hz: float
    interpolation_method: str
    max_time_deviation_s: float


def regularize_processed_hb_time(
    recording: ProcessedHbRecording,
    *,
    max_duplicate_fraction: float,
    max_jitter_abs_s: float,
    max_jitter_relative: float,
    max_interpolation_deviation_s: float,
    interpolation_method: str = "linear",
    target_sfreq_hz: float | None = None,
) -> RegularizedHbRecording:
    """Build an equidistant runtime view, failing closed on every gate."""
    if interpolation_method != "linear":
        raise ValueError("INTERPOLATION_METHOD_UNSUPPORTED: only linear interpolation is supported")
    native = recording.native_timestamps_s
    dt = np.diff(native)
    median_dt = float(np.median(dt))
    duplicate_fraction = float(np.mean(dt == 0))
    jitter_abs = float(np.max(np.abs(dt - median_dt)))
    jitter_relative = jitter_abs / median_dt
    if duplicate_fraction > max_duplicate_fraction:
        raise ValueError("DUPLICATE_TIMESTAMP_FRACTION_EXCEEDED")
    if jitter_abs > max_jitter_abs_s or jitter_relative > max_jitter_relative:
        raise ValueError("SAMPLING_JITTER_EXCEEDED")
    sfreq = float(target_sfreq_hz or 1.0 / median_dt)
    count = int(np.floor((native[-1] - native[0]) * sfreq)) + 1
    target = native[0] + np.arange(count) / sfreq
    nearest = np.min(np.abs(target[:, None] - native[None, :]), axis=1)
    max_deviation = float(np.max(nearest))
    if max_deviation > max_interpolation_deviation_s:
        raise ValueError("INTERPOLATION_DEVIATION_EXCEEDED")
    hbo = np.vstack([np.interp(target, native, row) for row in recording.hbo])
    hbr = np.vstack([np.interp(target, native, row) for row in recording.hbr])
    return RegularizedHbRecording(target, hbo, hbr, recording, sfreq, interpolation_method, max_deviation)
