"""Managed NIRS-SPM data and probe-layout utility adapters.

The source utilities live in ``tianzilei/MainCodeRepo`` (Apache-2.0). These
adapters keep the useful NIRS-SPM parsing and related data-management logic
while removing GUI automation, hard-coded paths, destructive moves, and
hard-coded participant attributes.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from fnirs_flow.infrastructure.filesystem import is_visible_data_file

DEFAULT_FILENAME_PATTERN = r"(\d{8})(\d{3})([A-Za-z]{4})(N|E|A|C|P|B|T)"


def inventory_fnirs_filenames(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    base_dir: str | Path | None = None,
    filename_pattern: str = DEFAULT_FILENAME_PATTERN,
    extensions: Iterable[str] | None = None,
    recursive: bool = True,
    atom_id: str = "fnirs_filename_inventory",
) -> dict[str, Any]:
    """Inventory fNIRS filenames and split them into valid/invalid tables."""
    source = _resolve_source_path(source_path, base_dir)
    if not source.is_dir():
        raise ValueError(f"FNIRS_INVENTORY_SOURCE_INVALID: directory not found: {source}")
    try:
        pattern = re.compile(filename_pattern)
    except re.error as exc:
        raise ValueError(f"FNIRS_INVENTORY_PATTERN_INVALID: {exc}") from exc

    normalized_extensions = {
        value.lower() if value.startswith(".") else f".{value.lower()}"
        for value in (extensions or [])
        if str(value).strip()
    }
    candidates = source.rglob("*") if recursive else source.glob("*")
    paths = sorted(
        (
            path
            for path in candidates
            if is_visible_data_file(path, root=source)
            and (not normalized_extensions or path.suffix.lower() in normalized_extensions)
        ),
        key=lambda path: path.relative_to(source).as_posix().lower(),
    )

    valid_rows: list[dict[str, str]] = []
    invalid_rows: list[dict[str, str]] = []
    unique_stems: set[str] = set()
    for path in paths:
        relative_path = path.relative_to(source).as_posix()
        stem = path.stem
        unique_stems.add(stem)
        match = pattern.match(stem)
        if match and len(match.groups()) >= 4:
            valid_rows.append(
                {
                    "relative_path": relative_path,
                    "filename": path.name,
                    "stem": stem,
                    "date": match.group(1),
                    "code": match.group(2),
                    "letter": match.group(3),
                    "status": match.group(4),
                }
            )
        else:
            invalid_rows.append({"relative_path": relative_path, "filename": path.name, "stem": stem})

    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = _safe_stem(atom_id)
    unique_path = outdir / f"{prefix}_unique_filenames.csv"
    valid_path = outdir / f"{prefix}_valid_filenames.csv"
    invalid_path = outdir / f"{prefix}_invalid_filenames.csv"
    manifest_path = outdir / f"{prefix}_filename_inventory.json"
    _write_csv(unique_path, [{"stem": stem} for stem in sorted(unique_stems)])
    _write_csv(
        valid_path,
        valid_rows,
        fieldnames=["relative_path", "filename", "stem", "date", "code", "letter", "status"],
    )
    _write_csv(
        invalid_path,
        invalid_rows,
        fieldnames=["relative_path", "filename", "stem"],
    )
    summary = {
        "type": "FnirsFilenameInventory",
        "source": str(source),
        "recursive": recursive,
        "filename_pattern": filename_pattern,
        "extensions": sorted(normalized_extensions),
        "files": len(paths),
        "unique_stems": len(unique_stems),
        "valid": len(valid_rows),
        "invalid": len(invalid_rows),
    }
    manifest_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"output": summary, "artifact_paths": [unique_path, valid_path, invalid_path, manifest_path]}


def inspect_nirs_spm_headers(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    base_dir: str | Path | None = None,
    glob_pattern: str = "*.TXT",
    recursive: bool = True,
    encoding: str = "utf-8-sig",
    include_subject_id: bool = False,
    atom_id: str = "nirs_spm_header_inspection",
) -> dict[str, Any]:
    """Inspect NIRS-SPM-style text headers without loading signal values."""
    source = _resolve_source_path(source_path, base_dir)
    if source.is_file():
        paths = [source]
        source_root = source.parent
    elif source.is_dir():
        candidates = source.rglob(glob_pattern) if recursive else source.glob(glob_pattern)
        paths = sorted(
            (path for path in candidates if is_visible_data_file(path, root=source)),
            key=lambda path: path.as_posix().lower(),
        )
        source_root = source
    else:
        raise ValueError(f"NIRS_SPM_HEADER_SOURCE_INVALID: path not found: {source}")
    if not paths:
        raise ValueError(f"NIRS_SPM_HEADER_EMPTY: no files matched {glob_pattern!r} under {source}")

    reports = [
        _inspect_nirs_spm_header(path, source_root, encoding=encoding, include_subject_id=include_subject_id)
        for path in paths
    ]
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = _safe_stem(atom_id)
    csv_path = outdir / f"{prefix}_headers.csv"
    json_path = outdir / f"{prefix}_headers.json"
    csv_rows = [
        {
            **row,
            "wavelengths": ";".join(str(value) for value in row["wavelengths"]),
        }
        for row in reports
    ]
    _write_csv(csv_path, csv_rows)
    summary = {
        "type": "NirsspmHeaderInspection",
        "files": len(reports),
        "valid_headers": sum(1 for row in reports if not row["issues"]),
        "include_subject_id": include_subject_id,
        "reports": reports,
    }
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"output": summary, "artifact_paths": [csv_path, json_path]}


def split_probe_layout_csv(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    base_dir: str | Path | None = None,
    label_column: str = "layout",
    coordinate_columns: Iterable[str] = ("x", "y", "z"),
    source_prefixes: Iterable[str] = ("T", "S"),
    detector_prefixes: Iterable[str] = ("R", "D"),
    channel_prefixes: Iterable[str] = ("CH",),
    coordinate_set_id: str = "probe_layout",
    atom_id: str = "probe_layout_split",
) -> dict[str, Any]:
    """Split a probe layout CSV into source, detector, and channel tables."""
    source = _resolve_source_path(source_path, base_dir)
    if not source.is_file():
        raise ValueError(f"PROBE_LAYOUT_SOURCE_INVALID: file not found: {source}")
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        headers = reader.fieldnames or []
    if not rows:
        raise ValueError("PROBE_LAYOUT_EMPTY: layout CSV has no data rows")

    header_map = {header.casefold(): header for header in headers}
    resolved_label = header_map.get(label_column.casefold())
    coords = list(coordinate_columns)
    resolved_coords = [header_map.get(column.casefold()) for column in coords]
    if resolved_label is None or any(column is None for column in resolved_coords):
        required = [label_column, *coords]
        raise ValueError(f"PROBE_LAYOUT_COLUMNS_MISSING: required columns {required}; found {headers}")

    prefixes = {
        "channel": tuple(value.upper() for value in channel_prefixes),
        "source": tuple(value.upper() for value in source_prefixes),
        "detector": tuple(value.upper() for value in detector_prefixes),
    }
    split_rows: dict[str, list[dict[str, str]]] = {"source": [], "detector": [], "channel": []}
    unclassified: list[str] = []
    for row in rows:
        label = str(row.get(resolved_label, "")).strip()
        normalized = label.upper()
        kind = next((name for name in ("channel", "source", "detector") if normalized.startswith(prefixes[name])), None)
        if kind is None:
            unclassified.append(label)
            continue
        split_rows[kind].append(
            {
                "Label": label,
                "X": str(row.get(resolved_coords[0], "")).strip(),
                "Y": str(row.get(resolved_coords[1], "")).strip(),
                "Z": str(row.get(resolved_coords[2], "")).strip(),
            }
        )

    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = _safe_stem(coordinate_set_id or atom_id)
    artifact_paths: list[Path] = []
    for kind in ("source", "detector", "channel"):
        path = outdir / f"{prefix}_{kind}_coordinates.csv"
        _write_csv(path, split_rows[kind], fieldnames=["Label", "X", "Y", "Z"])
        artifact_paths.append(path)
    manifest_path = outdir / f"{prefix}_probe_layout_manifest.json"
    summary = {
        "type": "ProbeLayoutSplit",
        "coordinate_set_id": coordinate_set_id,
        "source_file_size": source.stat().st_size,
        "source_file_modified": source.stat().st_mtime_ns,
        "rows": len(rows),
        "sources": len(split_rows["source"]),
        "detectors": len(split_rows["detector"]),
        "channels": len(split_rows["channel"]),
        "unclassified_labels": unclassified,
    }
    manifest_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    artifact_paths.append(manifest_path)
    return {"output": summary, "artifact_paths": artifact_paths}


def _inspect_nirs_spm_header(
    path: Path,
    source_root: Path,
    *,
    encoding: str,
    include_subject_id: bool,
) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding=encoding).splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"NIRS_SPM_HEADER_ENCODING_ERROR: {path}: {exc}") from exc
    if not lines:
        raise ValueError(f"NIRS_SPM_HEADER_EMPTY_FILE: {path}")

    data_line_number: int | None = None
    match = re.search(r"\[Data Line\]\s*(\d+)", lines[0])
    if match:
        data_line_number = int(match.group(1))
    if data_line_number is None:
        for index, line in enumerate(lines, start=1):
            if line.strip().startswith("Time("):
                data_line_number = index + 1
                break

    measured = next((line for line in lines if line.startswith("Measured Date")), "")
    measured_value = measured.split(None, 2)[2].strip() if len(measured.split(None, 2)) >= 3 else ""
    subject_values: list[str] = []
    for key in ("ID", "Name"):
        value = next((line.split("\t", 1)[1].strip() for line in lines if line.startswith(key + "\t")), "")
        if value:
            subject_values.append(value)
    subject_id = max(subject_values, key=len, default="")

    header_end = max((data_line_number or len(lines) + 1) - 1, 0)
    header_lines = lines[:header_end]
    pair_pattern = re.compile(r"\((\d+),(\d+)\)")
    channel_pairs = [match.groups() for line in header_lines for match in pair_pattern.finditer(line)]
    wavelengths: list[float] = []
    in_condition = False
    for line in header_lines:
        stripped = line.strip()
        if stripped.startswith("[Condition"):
            in_condition = True
            continue
        if in_condition and (stripped.startswith("[") or "Gain" in stripped):
            break
        if in_condition:
            wavelengths.extend(float(value) for value in re.findall(r"\d+\.\d+", line))

    sample_line = next((line for line in lines[header_end:] if len(line.split()) >= 5), "")
    column_count = len(sample_line.split()) if sample_line else 0
    measurement_columns = max(column_count - 4, 0)
    inferred_channels = 0
    if measurement_columns:
        inferred_channels = measurement_columns // (3 if measurement_columns % 3 == 0 else 2)
    issues: list[str] = []
    if data_line_number is None:
        issues.append("data_line_not_found")
    if not sample_line:
        issues.append("data_preview_not_found")
    if not channel_pairs:
        issues.append("channel_pairs_not_found")
    report: dict[str, Any] = {
        "relative_path": path.relative_to(source_root).as_posix(),
        "measurement_datetime": measured_value,
        "subject_id_present": bool(subject_id),
        "data_line_number": data_line_number,
        "column_count": column_count,
        "measurement_columns": measurement_columns,
        "inferred_channels": inferred_channels,
        "channel_pairs": len(channel_pairs),
        "wavelengths": sorted(set(wavelengths)),
        "issues": ";".join(issues),
    }
    if include_subject_id:
        report["subject_id"] = subject_id
    return report


def _resolve_source_path(source_path: str | Path, base_dir: str | Path | None) -> Path:
    path = Path(source_path).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir) / path
    return path.resolve()


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    columns = fieldnames or list(dict.fromkeys(key for row in rows for key in row)) or ["value"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._-")
    return cleaned or "fnirs"
