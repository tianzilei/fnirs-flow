"""Streaming reader and provenance checks for vendor ``*_RE.TXT`` Hb exports."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ProcessedHbParseError(ValueError):
    """Raised when a processed-Hb export violates the input contract."""


@dataclass
class ProcessedHbData:
    path: Path
    time_s: Any
    hbo: Any
    hbr: Any
    hbt: Any
    channel_names: list[str]
    task: list[str]
    mark: list[str]
    count: list[str]
    provenance: dict[str, Any] = field(default_factory=dict)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_float(value: str, *, row: int, column: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ProcessedHbParseError(f"row {row}: invalid {column} value {value!r}") from exc
    if not math.isfinite(parsed):
        raise ProcessedHbParseError(f"row {row}: non-finite {column} value")
    return parsed


def read_vendor_processed_hb(
    path: str | Path,
    *,
    expected_sha256: str = "",
    expected_channels: int | None = None,
    total_hb_atol: float = 5e-6,
    sampling_jitter_fraction_limit: float = 0.05,
    fail_on_irregular_sampling: bool = True,
) -> ProcessedHbData:
    """Read a vendor processed-Hb text export without changing its samples.

    The parser is intentionally fail-closed for malformed rows, non-finite
    signal values, non-monotonic timestamps, and structural inconsistencies.
    The first all-zero row is retained and reported rather than silently
    removed.
    """

    import numpy as np

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    digest = _sha256(source)
    if expected_sha256 and digest.lower() != expected_sha256.strip().lower():
        raise ProcessedHbParseError(
            f"SHA-256 mismatch for {source.name}: expected {expected_sha256}, observed {digest}"
        )

    metadata: dict[str, str] = {}
    channel_header: list[str] = []
    chromophore_header: list[str] = []
    time_values: list[float] = []
    tasks: list[str] = []
    marks: list[str] = []
    counts: list[str] = []
    signal_rows: list[list[float]] = []
    header_found = False
    line_before_header = ""

    # Exports observed in this project are ASCII-compatible. utf-8-sig keeps
    # the parser deterministic while accepting a possible BOM.
    with source.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.rstrip("\r\n")
            fields = line.split("\t")
            if not header_found:
                if fields and fields[0].strip() == "Time(sec)":
                    header_found = True
                    chromophore_header = [value.strip() for value in fields[4:]]
                    channel_header = [value.strip() for value in line_before_header.split("\t")[4:]]
                    if len(chromophore_header) == 0 or len(chromophore_header) % 3:
                        raise ProcessedHbParseError(
                            "signal header must contain HbO/HbR/HbT triples after four metadata columns"
                        )
                    continue
                stripped = line.strip()
                if stripped:
                    # Preserve useful scalar header facts without relying on
                    # localized spacing.
                    tokens = [token.strip() for token in fields if token.strip()]
                    if len(tokens) >= 2:
                        metadata.setdefault(tokens[0], tokens[1])
                    match = re.search(r"Time Range\s+([-+0-9.]+)\s+([-+0-9.]+)", stripped)
                    if match:
                        metadata["declared_start_time_s"] = match.group(1)
                        metadata["declared_end_time_s"] = match.group(2)
                    points_match = re.search(r"Total Points\s+([0-9]+)", stripped)
                    if points_match:
                        metadata["declared_total_points"] = points_match.group(1)
                line_before_header = line
                continue

            if not line.strip():
                continue
            if len(fields) != 4 + len(chromophore_header):
                raise ProcessedHbParseError(
                    f"row {line_number}: expected {4 + len(chromophore_header)} columns, got {len(fields)}"
                )
            time_values.append(_as_float(fields[0].strip(), row=line_number, column="Time(sec)"))
            tasks.append(fields[1].strip())
            marks.append(fields[2].strip())
            counts.append(fields[3].strip())
            signal_rows.append(
                [
                    _as_float(value.strip(), row=line_number, column=f"signal_{idx + 1}")
                    for idx, value in enumerate(fields[4:])
                ]
            )

    if not header_found:
        raise ProcessedHbParseError("Time(sec) data header was not found")
    if len(time_values) < 3:
        raise ProcessedHbParseError("at least three data rows are required")

    signals = np.asarray(signal_rows, dtype=float)
    times = np.asarray(time_values, dtype=float)
    diffs = np.diff(times)
    if not np.all(diffs > 0):
        duplicate_count = int(np.sum(diffs == 0))
        decreasing_count = int(np.sum(diffs < 0))
        raise ProcessedHbParseError(
            f"timestamps must be strictly increasing (duplicates={duplicate_count}, decreases={decreasing_count})"
        )

    n_channels = signals.shape[1] // 3
    if expected_channels is not None and n_channels != expected_channels:
        raise ProcessedHbParseError(f"expected {expected_channels} channels, observed {n_channels}")

    expected_chromophores = ["oxyhb", "deoxyhb", "totalhb"] * n_channels
    normalized_chromophores = [value.lower() for value in chromophore_header]
    if normalized_chromophores != expected_chromophores:
        raise ProcessedHbParseError("chromophore columns are not ordered as oxyHb/deoxyHb/totalHb triples")

    if len(channel_header) != signals.shape[1] or any(not value for value in channel_header):
        channel_names = [f"ch-{idx + 1}" for idx in range(n_channels)]
        channel_header_status = "reconstructed"
    else:
        channel_names = []
        for idx in range(n_channels):
            triple = channel_header[idx * 3 : idx * 3 + 3]
            if len(set(triple)) != 1:
                raise ProcessedHbParseError(f"channel header triple {idx + 1} is inconsistent: {triple}")
            channel_names.append(triple[0])
        channel_header_status = "observed"
    if len(set(channel_names)) != len(channel_names):
        raise ProcessedHbParseError("channel names are not unique")

    hbo = signals[:, 0::3]
    hbr = signals[:, 1::3]
    hbt = signals[:, 2::3]
    all_zero_hbo = [channel_names[index] for index in range(n_channels) if np.all(hbo[:, index] == 0.0)]
    all_zero_hbr = [channel_names[index] for index in range(n_channels) if np.all(hbr[:, index] == 0.0)]
    if all_zero_hbo or all_zero_hbr:
        raise ProcessedHbParseError(
            f"all-zero chromophore channels are not analysable (HbO={all_zero_hbo}, HbR={all_zero_hbr})"
        )
    total_errors = np.abs(hbt - (hbo + hbr))
    total_error_max = float(np.max(total_errors))
    total_error_p99 = float(np.quantile(total_errors, 0.99))
    total_consistent = total_error_max <= total_hb_atol

    median_dt = float(np.median(diffs))
    sampling_rate = 1.0 / median_dt
    jitter_abs = np.abs(diffs - median_dt)
    jitter_fraction_max = float(np.max(jitter_abs) / median_dt)
    jitter_fraction_p99 = float(np.quantile(jitter_abs, 0.99) / median_dt)
    sampling_grid_status = "pass" if jitter_fraction_max <= sampling_jitter_fraction_limit else "warn"
    if sampling_grid_status != "pass" and fail_on_irregular_sampling:
        raise ProcessedHbParseError(
            "sampling jitter exceeds the uniform-grid model limit "
            f"({jitter_fraction_max:.6g} > {sampling_jitter_fraction_limit:.6g}); "
            "explicit resampling is required before analysis"
        )

    declared_start = metadata.get("declared_start_time_s", "")
    declared_end = metadata.get("declared_end_time_s", "")
    declared_points_text = metadata.get("declared_total_points", "")
    declared_points = int(declared_points_text) if declared_points_text else None
    declared_points_match = declared_points is None or declared_points == len(time_values)
    end_tolerance = max(0.5 * median_dt, 1e-6)
    declared_start_match = True if not declared_start else abs(float(declared_start) - float(times[0])) <= end_tolerance
    declared_end_match = True if not declared_end else abs(float(declared_end) - float(times[-1])) <= end_tolerance
    warnings: list[str] = []
    if not total_consistent:
        warnings.append("total_hb_inconsistent")
    if not declared_points_match:
        warnings.append("declared_points_mismatch")
    if not declared_start_match:
        warnings.append("declared_start_mismatch")
    if not declared_end_match:
        warnings.append("declared_end_mismatch")
    if sampling_grid_status != "pass":
        warnings.append("sampling_grid_irregular")
    first_row_all_zero = bool(np.all(signals[0] == 0.0))
    provenance: dict[str, Any] = {
        "source_path": str(source),
        "source_file": source.name,
        "source_file_role": "vendor_processed_hb_composite",
        "sha256": digest,
        "size_bytes": source.stat().st_size,
        "parser_version": "vendor-processed-hb-v1",
        "absolute_unit_verified": False,
        "unit_status": "NOT_DECLARED_IN_EXPORT",
        "raw_intensity_pipeline_applied": False,
        "short_channel_separation_applied": False,
        "cortical_specific_separation_applied": False,
        "data_rows": len(time_values),
        "channel_count": n_channels,
        "signal_column_count": signals.shape[1],
        "first_time_s": float(times[0]),
        "last_time_s": float(times[-1]),
        "duration_s": float(times[-1] - times[0]),
        "median_dt_s": median_dt,
        "sampling_rate_hz": sampling_rate,
        "sampling_jitter_fraction_max": jitter_fraction_max,
        "sampling_jitter_fraction_p99": jitter_fraction_p99,
        "sampling_grid_status": sampling_grid_status,
        "sampling_jitter_fraction_limit": sampling_jitter_fraction_limit,
        "irregular_sampling_fail_closed": fail_on_irregular_sampling,
        "timestamps_strictly_increasing": True,
        "resampled": False,
        "first_row_all_zero": first_row_all_zero,
        "first_row_retained": True,
        "channel_header_status": channel_header_status,
        "total_hb_consistent": total_consistent,
        "all_zero_hbo_channel_count": 0,
        "all_zero_hbr_channel_count": 0,
        "total_hb_error_max": total_error_max,
        "total_hb_error_p99": total_error_p99,
        "total_hb_atol": total_hb_atol,
        "declared_start_time_s": declared_start,
        "declared_end_time_s": declared_end,
        "declared_total_points": declared_points if declared_points is not None else "",
        "declared_points_match_data_rows": declared_points_match,
        "declared_start_matches_head": declared_start_match,
        "declared_end_matches_tail": declared_end_match,
        "warning_count": len(warnings),
        "warnings": ";".join(warnings),
        "qc_status": "pass" if not warnings else "warn",
    }
    return ProcessedHbData(
        path=source,
        time_s=times,
        hbo=hbo,
        hbr=hbr,
        hbt=hbt,
        channel_names=channel_names,
        task=tasks,
        mark=marks,
        count=counts,
        provenance=provenance,
    )
