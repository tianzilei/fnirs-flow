"""Import prepared localization projection CSV files as executable artifacts."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATUS_ALLOWLIST = {"matched", "complete_ready_to_use"}
DEFAULT_ACCURACY_CAVEAT = "not_claimed_to_reproduce_nirsspm_accuracy"

COORDINATE_COLUMN_CANDIDATES = [
    ("adjusted_projected_mni_x", "adjusted_projected_mni_y", "adjusted_projected_mni_z"),
    ("actual_projected_mni_x", "actual_projected_mni_y", "actual_projected_mni_z"),
    ("projected_mni_x", "projected_mni_y", "projected_mni_z"),
    ("mni_x", "mni_y", "mni_z"),
    ("x", "y", "z"),
]

LABEL_COLUMN_CANDIDATES = [
    "channel",
    "channel_name",
    "projection_label",
    "optode_name",
    "raw_label",
    "label",
    "name",
]

INDEX_COLUMN_CANDIDATES = ["point_index", "raw_index", "channel_index", "index"]


def import_projection_coordinate_csv(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    base_dir: str | Path | None = None,
    atom_id: str = "localization_projection_import",
    coordinate_set_id: str = "",
    coordinate_columns: dict[str, str] | None = None,
    label_column: str = "",
    include_match_statuses: list[str] | None = None,
    accuracy_caveat: str = DEFAULT_ACCURACY_CAVEAT,
    method_id: str = "localization_projection_import",
) -> dict[str, Any]:
    """Validate and standardize a prepared MNI projection coordinate CSV.

    This imports already prepared coordinate tables. It does not implement
    NIRS-SPM/NFRI spatial registration or claim NIRS-SPM-equivalent precision.
    """
    source = _resolve_source_path(source_path, base_dir)
    if not source.exists():
        raise FileNotFoundError(f"Projection coordinate CSV not found: {source}")
    if source.suffix.lower() != ".csv":
        raise ValueError(f"Projection coordinate input must be a CSV file: {source}")

    rows = _read_csv_rows(source)
    if not rows:
        raise ValueError(f"Projection coordinate CSV has no data rows: {source}")

    headers = set(rows[0].keys())
    selected_coordinate_columns = _select_coordinate_columns(headers, coordinate_columns)
    selected_label_column = _select_first_existing(headers, [label_column] if label_column else LABEL_COLUMN_CANDIDATES)
    selected_index_column = _select_first_existing(headers, INDEX_COLUMN_CANDIDATES)
    status_allowlist = set(include_match_statuses or DEFAULT_STATUS_ALLOWLIST)
    source_stat = source.stat()
    coordinate_set = coordinate_set_id or _first_nonempty(rows, "group_id") or source.stem

    normalized_rows: list[dict[str, Any]] = []
    skipped_missing_mni = 0
    skipped_status = 0
    for source_row_index, row in enumerate(rows, start=1):
        if "match_status" in row and status_allowlist:
            status = str(row.get("match_status", "")).strip()
            if status and status not in status_allowlist:
                skipped_status += 1
                continue

        x_value = _parse_float(row.get(selected_coordinate_columns[0], ""))
        y_value = _parse_float(row.get(selected_coordinate_columns[1], ""))
        z_value = _parse_float(row.get(selected_coordinate_columns[2], ""))
        if x_value is None or y_value is None or z_value is None:
            skipped_missing_mni += 1
            continue

        label = str(row.get(selected_label_column, "")).strip() if selected_label_column else ""
        point_type = _infer_point_type(row, label)
        normalized_rows.append(
            {
                "coordinate_set_id": coordinate_set,
                "row_index": len(normalized_rows) + 1,
                "source_row_index": source_row_index,
                "point_type": point_type,
                "label": label,
                "mni_x": x_value,
                "mni_y": y_value,
                "mni_z": z_value,
                "coordinate_columns": ";".join(selected_coordinate_columns),
                "group_id": str(row.get("group_id", "")).strip(),
                "canonical_file": str(row.get("canonical_file", "")).strip(),
                "source_point_index": str(row.get(selected_index_column, "")).strip() if selected_index_column else "",
                "coordinate_method": str(row.get("coordinate_method", "")).strip(),
                "match_status": str(row.get("match_status", "")).strip(),
                "accuracy_caveat": str(row.get("accuracy_caveat", "")).strip() or accuracy_caveat,
                "source_file_size": source_stat.st_size,
            }
        )

    if not normalized_rows:
        raise ValueError(
            "Projection coordinate CSV did not contain usable MNI rows "
            f"with columns {selected_coordinate_columns}"
        )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    safe_stem = _safe_stem(coordinate_set)
    csv_path = output_path / f"{safe_stem}_projected_mni_channels.csv"
    json_path = output_path / f"{safe_stem}_projected_mni_channels.json"
    manifest_path = output_path / f"{safe_stem}_projection_import_manifest.json"

    _write_rows(csv_path, normalized_rows)
    point_type_counts = dict(Counter(str(row["point_type"]) for row in normalized_rows))
    manifest = {
        "type": "ProjectedMNIChannels",
        "coordinate_set_id": coordinate_set,
        "atom_id": atom_id,
        "method_id": method_id,
        "source_file": str(source),
        "source_file_size": source_stat.st_size,
        "source_file_modified": source_stat.st_mtime_ns,
        "source_rows": len(rows),
        "imported_rows": len(normalized_rows),
        "skipped_missing_mni": skipped_missing_mni,
        "skipped_status": skipped_status,
        "coordinate_columns": list(selected_coordinate_columns),
        "label_column": selected_label_column,
        "index_column": selected_index_column,
        "point_type_counts": point_type_counts,
        "accuracy_caveat": accuracy_caveat,
        "not_nirsspm_equivalent": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "standardized_csv": str(csv_path),
            "standardized_json": str(json_path),
            "manifest": str(manifest_path),
        },
    }
    json_path.write_text(
        json.dumps({**manifest, "rows": normalized_rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    warnings = []
    if skipped_missing_mni:
        warnings.append(f"Skipped {skipped_missing_mni} rows without complete MNI coordinates")
    if skipped_status:
        warnings.append(f"Skipped {skipped_status} rows outside allowed match_status values")

    return {
        "output": {**manifest, "rows": normalized_rows},
        "output_handles": {
            "type": "ProjectedMNIChannels",
            "coordinate_set_id": coordinate_set,
            "rows": len(normalized_rows),
            "channels": point_type_counts.get("channel", 0),
            "optodes": point_type_counts.get("optode", 0),
            "fiducials": point_type_counts.get("fiducial", 0),
            "standardized_csv": str(csv_path),
            "standardized_json": str(json_path),
            "manifest": str(manifest_path),
            "accuracy_caveat": accuracy_caveat,
            "not_nirsspm_equivalent": True,
        },
        "artifact_paths": [csv_path, json_path, manifest_path],
        "warnings": warnings,
        "provenance": {
            "source_file": str(source),
            "source_file_size": source_stat.st_size,
            "source_file_modified": source_stat.st_mtime_ns,
            "coordinate_columns": list(selected_coordinate_columns),
            "method_id": method_id,
            "accuracy_caveat": accuracy_caveat,
        },
    }


def _resolve_source_path(source_path: str | Path, base_dir: str | Path | None) -> Path:
    source = Path(source_path)
    if source.is_absolute():
        return source
    if base_dir is not None:
        candidate = Path(base_dir) / source
        if candidate.exists():
            return candidate
    return source


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"Projection coordinate CSV has no header: {path}")
        return [{str(key): value for key, value in row.items()} for row in reader]


def _select_coordinate_columns(
    headers: set[str],
    coordinate_columns: dict[str, str] | None,
) -> tuple[str, str, str]:
    if coordinate_columns:
        selected = (
            str(coordinate_columns.get("x", "")),
            str(coordinate_columns.get("y", "")),
            str(coordinate_columns.get("z", "")),
        )
        missing = [column for column in selected if column not in headers]
        if missing:
            raise ValueError(f"Configured coordinate columns not found: {missing}")
        return selected

    for candidate in COORDINATE_COLUMN_CANDIDATES:
        if all(column in headers for column in candidate):
            return candidate
    raise ValueError(
        "Projection coordinate CSV is missing recognized MNI coordinate columns. "
        f"Tried: {COORDINATE_COLUMN_CANDIDATES}"
    )


def _select_first_existing(headers: set[str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate and candidate in headers:
            return candidate
    return ""


def _first_nonempty(rows: list[dict[str, str]], column: str) -> str:
    for row in rows:
        value = str(row.get(column, "")).strip()
        if value:
            return value
    return ""


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _infer_point_type(row: dict[str, str], label: str) -> str:
    kind = str(row.get("projection_kind", "")).lower()
    label_lower = label.lower()
    if "fiducial" in kind or "reference" in kind or label_lower in {"nz", "iz", "ar", "al", "nasion", "inion"}:
        return "fiducial"
    if (
        label_lower.startswith("nz")
        or label_lower.startswith("iz")
        or label_lower.startswith("ar")
        or label_lower.startswith("al")
    ):
        return "fiducial"
    if "channel" in kind or re.match(r"^ch\d+", label_lower):
        return "channel"
    return "optode"


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _safe_stem(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe.strip("._") or "projected_mni_channels"
