"""Strict parser for vendor processed-Hb ``_RE.TXT`` exports."""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

import numpy as np

from fnirs_flow.data.processed_hb_models import (
    InputProvenance,
    ParserQC,
    ProcessedHbChannel,
    ProcessedHbRecording,
    VendorHeader,
)

PARSER_VERSION = "1.1.0"
_CHANNEL_RE = re.compile(r"(?i)^ch(?:annel)?[ _-]?(\d+)(?:\([^)]*\))?[ _-]*(oxyhb|deoxyhb|totalhb)$")


class ProcessedHbParseError(ValueError):
    """Raised when an input cannot be interpreted unambiguously."""


def _decode(raw: bytes, encoding: str | None) -> tuple[str, str, int, int]:
    candidates = [encoding] if encoding else ["utf-8-sig", "utf-8", "cp932", "gb18030"]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            text = raw.decode(candidate)
        except UnicodeDecodeError:
            continue
        return text, candidate, text.count("\ufffd"), 1 if raw.startswith(b"\xef\xbb\xbf") else 0
    raise ProcessedHbParseError("unable to decode _RE.TXT with configured encodings")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def parse_vendor_processed_hb(
    path: str | Path, *, uri: str = "", encoding: str | None = None
) -> tuple[ProcessedHbRecording, ParserQC]:
    """Parse a complete vendor table and return recording plus auditable QC."""
    source = Path(path)
    raw = source.read_bytes()
    text, used_encoding, replacements, bom = _decode(raw, encoding)
    if "\ufffd" in text:
        raise ProcessedHbParseError("decoded text contains replacement characters")
    lines = text.splitlines()
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    header_names: list[str] = []
    data_start: int | None = None
    header_candidates: list[tuple[int, list[str]]] = []
    # Shimadzu OMM/NIRS-SPM headers contain per-recording electrical settings
    # under [Condition-*].  Keep them as observed metadata; they are not
    # wavelength values and must never be promoted to ``wavelengths_nm``.
    condition_values: dict[str, list[float]] = {}
    condition_kind_hint = ""
    pending_condition_kind = ""
    pending_condition_count = 0
    for idx, line in enumerate(lines):
        stripped = line.strip().strip("\ufeff")
        if stripped.startswith("[") and stripped.endswith("]"):
            name = stripped[1:-1].strip()
            current = sections.setdefault(name, {})
            condition_kind_hint = ""
            pending_condition_kind = ""
            pending_condition_count = 0
            continue
        if current is not None and stripped and data_start is None:
            if "=" in stripped:
                key, val = stripped.split("=", 1)
                current[key.strip()] = val.strip()
            elif "\t" in stripped:
                key, val = stripped.split("\t", 1)
                current[key.strip()] = val.strip()
        if data_start is None and stripped:
            if "gain(" in stripped.casefold():
                condition_kind_hint = "gain"
            elif re.fullmatch(r"R\d+(?:\s*,\s*R\d+)+", stripped, flags=re.IGNORECASE):
                labels = re.findall(r"R\d+", stripped, flags=re.IGNORECASE)
                pending_condition_kind = "gain" if condition_kind_hint == "gain" else "voltage"
                pending_condition_count = len(labels)
                condition_kind_hint = ""
            elif pending_condition_kind and re.fullmatch(
                r"[-+0-9.eE]+(?:\s*,\s*[-+0-9.eE]+){2,}", stripped
            ):
                try:
                    parsed_condition_values = [float(item.strip()) for item in stripped.split(",")]
                except ValueError as exc:
                    raise ProcessedHbParseError("invalid numeric Shimadzu condition row") from exc
                if len(parsed_condition_values) != pending_condition_count:
                    raise ProcessedHbParseError(
                        f"Shimadzu {pending_condition_kind} count does not match its R-channel labels"
                    )
                existing = condition_values.get(pending_condition_kind)
                if existing is not None and existing != parsed_condition_values:
                    raise ProcessedHbParseError(f"ambiguous repeated Shimadzu {pending_condition_kind} rows")
                condition_values[pending_condition_kind] = parsed_condition_values
                pending_condition_kind = ""
                pending_condition_count = 0
        candidate = [part.strip() for part in re.split(r"[\t,]", line.strip())]
        if sum(_norm(part) == "time(sec)" for part in candidate) == 1:
            header_candidates.append((idx, candidate))
    if len(header_candidates) != 1:
        raise ProcessedHbParseError("TIME_HEADER_AMBIGUOUS: unique Time(sec) header row not found")
    header_index, header_names = header_candidates[0]
    data_start = header_index + 1
    canonical = [_norm(v) for v in header_names]
    time_indices = [i for i, v in enumerate(canonical) if v == "time(sec)"]
    if len(time_indices) != 1:
        raise ProcessedHbParseError("Time(sec) must occur exactly once")
    fields: dict[tuple[int, str], int] = {}
    for i, name in enumerate(header_names):
        header_match = _CHANNEL_RE.match(name.strip())
        if not header_match:
            continue
        chrom = {"oxyhb": "hbo", "deoxyhb": "hbr", "totalhb": "hbt"}[header_match.group(2).casefold()]
        field_key = (int(header_match.group(1)), chrom)
        if field_key in fields:
            raise ProcessedHbParseError(f"duplicate channel field: {name}")
        fields[field_key] = i
    # Shimadzu/NIRS-SPM exports put channel labels on the line immediately
    # above the chromophore row (e.g. ``ch- 1`` repeated three times), while
    # the data row contains only oxyHb/deoxyHb/totalHb labels.  Reconstruct
    # the channel/chromophore mapping from those two aligned rows.
    if not fields and header_index > 0:
        channel_labels = [part.strip() for part in re.split(r"[\t,]", lines[header_index - 1].rstrip())]
        if len(channel_labels) == len(header_names):
            for i, chrom_name in enumerate(header_names):
                aligned_chrom = {"oxyhb": "hbo", "deoxyhb": "hbr", "totalhb": "hbt"}.get(
                    _norm(chrom_name)
                )
                channel_match = re.search(
                    r"(?:ch(?:annel)?)[ _-]*(\d+)", channel_labels[i], flags=re.IGNORECASE
                )
                if aligned_chrom and channel_match:
                    fields[(int(channel_match.group(1)), aligned_chrom)] = i
    channels_numbers = sorted({n for n, _ in fields})
    if not channels_numbers:
        raise ProcessedHbParseError("no Hb channel triplets found")
    if channels_numbers != list(range(1, channels_numbers[-1] + 1)):
        raise ProcessedHbParseError("channel numbers must start at 1 and be contiguous")
    missing = [(n, c) for n in channels_numbers for c in ("hbo", "hbr") if (n, c) not in fields]
    if missing:
        raise ProcessedHbParseError(f"missing HbO/HbR fields: {missing}")
    hbt_present = [(n, "hbt") in fields for n in channels_numbers]
    if any(hbt_present) and not all(hbt_present):
        raise ProcessedHbParseError("partial HbT channel triplets are ambiguous")
    rows: list[list[str]] = []
    width = len(header_names)
    for line in lines[data_start:]:
        if not line.strip() or line.lstrip().startswith("["):
            continue
        row = next(csv.reader([line], delimiter="\t" if "\t" in line else ","))
        if len(row) != width:
            raise ProcessedHbParseError(f"data row has {len(row)} columns; expected {width}")
        rows.append([v.strip() for v in row])
    if not rows:
        raise ProcessedHbParseError("data table is empty")
    numeric_indices = {time_indices[0], *fields.values()}
    numeric_values = np.full((len(rows), width), np.nan, dtype=float)
    try:
        for row_idx, row in enumerate(rows):
            for col_idx in numeric_indices:
                numeric_values[row_idx, col_idx] = float(row[col_idx])
    except ValueError as exc:
        raise ProcessedHbParseError(f"non-numeric timestamp/Hb value: {exc}") from exc
    timestamps = numeric_values[:, time_indices[0]]
    if not np.isfinite(timestamps).all():
        raise ProcessedHbParseError("timestamps contain non-finite values")
    dt = np.diff(timestamps)
    duplicate_fraction = float(np.mean(dt == 0)) if dt.size else 0.0
    if dt.size and np.any(dt <= 0):
        raise ProcessedHbParseError("TIME_NON_MONOTONIC: timestamps must be strictly increasing")
    finite_channels = np.isfinite(
        numeric_values[:, [fields[(number, chrom)] for number in channels_numbers for chrom in ("hbo", "hbr")]]
    )
    if not finite_channels.all():
        raise ProcessedHbParseError("NONFINITE_UNRESOLVED: HbO/HbR data contain non-finite values")
    warnings: list[str] = []
    if replacements or bom:
        warnings.append("ENCODING_REPAIRED" if replacements else "UTF8_BOM")
    declared_points = None
    for section in sections.values():
        for key, value in section.items():
            if _norm(key) in {"points", "data points", "number of points"}:
                try:
                    declared_points = int(float(value))
                except ValueError:
                    pass
    if declared_points is not None and declared_points != len(rows):
        warnings.append("HEADER_POINT_COUNT_MISMATCH")
    declared_end_time = None
    for section in sections.values():
        for key, value in section.items():
            if _norm(key) in {"end time", "end time(sec)", "last time(sec)", "duration(sec)"}:
                try:
                    declared_end_time = float(value)
                except ValueError:
                    pass
    if declared_end_time is not None and not np.isclose(declared_end_time, timestamps[-1], rtol=0, atol=1e-9):
        warnings.append("HEADER_END_TIME_MISMATCH")
    hbo = np.vstack([numeric_values[:, fields[(number, "hbo")]] for number in channels_numbers])
    hbr = np.vstack([numeric_values[:, fields[(number, "hbr")]] for number in channels_numbers])
    hbt = (
        np.vstack([numeric_values[:, fields[(number, "hbt")]] for number in channels_numbers])
        if all((number, "hbt") in fields for number in channels_numbers)
        else None
    )
    channels = tuple(ProcessedHbChannel(f"ch{n:03d}", n, header_names[fields[(n, "hbo")]]) for n in channels_numbers)
    if np.any(np.all(np.isclose(hbo, 0.0), axis=1)) or np.any(np.all(np.isclose(hbr, 0.0), axis=1)):
        raise ProcessedHbParseError("ALL_ZERO_CHANNEL: all-zero HbO/HbR channel")
    declared_channels = None
    for section in sections.values():
        for key, value in section.items():
            if _norm(key) in {"channels", "channel count", "number of channels"}:
                try:
                    declared_channels = int(float(value))
                except ValueError:
                    pass
    if declared_channels is not None and declared_channels != len(channels):
        raise ProcessedHbParseError("declared channel count does not match field triplets")
    sha = hashlib.sha256(raw).hexdigest()
    median_dt = float(np.median(dt)) if dt.size else float("nan")
    dt_mad = float(np.median(np.abs(dt - median_dt))) if dt.size else float("nan")
    dt_iqr = float(np.subtract(*np.percentile(dt, [75, 25]))) if dt.size else float("nan")
    jitter = float(np.max(np.abs(dt - median_dt))) if dt.size else float("nan")
    hbt_status = "unavailable"
    hbt_mae: float | None = None
    hbt_rmse: float | None = None
    hbt_max_abs_error: float | None = None
    hbt_error_quantiles: tuple[float, ...] = ()
    hbt_tolerance_exceedance_fraction: float | None = None
    if hbt is not None:
        err = hbt - (hbo + hbr)
        hbt_mae = float(np.mean(np.abs(err)))
        hbt_rmse = float(np.sqrt(np.mean(err**2)))
        hbt_max_abs_error = float(np.max(np.abs(err)))
        hbt_error_quantiles = tuple(float(v) for v in np.quantile(np.abs(err), [0.5, 0.9, 0.95, 0.99]))
        hbt_status = "pass" if np.isfinite(err).all() else "fail"
    provenance = InputProvenance(
        uri or source.as_posix(),
        source.as_posix(),
        sha,
        len(raw),
        "vendor_processed_hb",
        PARSER_VERSION,
        used_encoding,
        declared_points,
        len(rows),
        float(timestamps[0]),
        float(timestamps[-1]),
        float(timestamps[-1] - timestamps[0]),
        1.0 / median_dt if median_dt > 0 else float("nan"),
        float(np.min(dt)) if dt.size else float("nan"),
        median_dt,
        float(np.max(dt)) if dt.size else float("nan"),
        dt_mad,
        dt_iqr,
        jitter,
        int(np.sum(dt == 0)),
        len(channels),
        False,
        False,
        None,
        None,
        None,
        hbt_status,
        hbt_mae,
        hbt_rmse,
        hbt_max_abs_error,
        hbt_error_quantiles,
        hbt_tolerance_exceedance_fraction,
        tuple(warnings),
        "pass",
    )
    # Attach only explicitly identified condition metadata. Gain-only headers
    # must never be promoted to Applied Voltage.
    if "voltage" in condition_values:
        sections.setdefault("Parsed Condition Metadata", {})["Applied Voltage"] = ",".join(
            str(item) for item in condition_values["voltage"]
        )
    if "gain" in condition_values:
        sections.setdefault("Parsed Condition Metadata", {})["Amp. Gain"] = ",".join(
            str(int(item)) if item.is_integer() else str(item) for item in condition_values["gain"]
        )
    qc = ParserQC(
        "warn" if warnings else "pass",
        tuple(warnings),
        (),
        {
            "duplicate_fraction": duplicate_fraction,
            "finite_channel_fraction": float(np.mean(finite_channels)),
            "encoding_replacements": replacements,
        },
    )

    def optional_values(name: str) -> np.ndarray | None:
        indices = [i for i, value in enumerate(canonical) if value == name]
        return np.asarray([row[indices[0]] for row in rows], dtype=object) if len(indices) == 1 else None

    return ProcessedHbRecording(
        timestamps,
        hbo,
        hbr,
        hbt,
        channels,
        optional_values("task"),
        optional_values("mark"),
        optional_values("count"),
        VendorHeader(sections, declared_points, declared_channels or len(channels), tuple(header_names)),
        provenance,
    ), qc
