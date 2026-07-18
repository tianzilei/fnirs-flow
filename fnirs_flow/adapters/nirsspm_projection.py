"""NIRS-SPM v4 r1 spatial projection rewrite helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REFERENCE_DIR = Path("References") / "NIRS_SPM_v4_r1"
DEFAULT_STAGE = "head_surface_mni_to_cortical_surface_mni"


def run_nirsspm_surface_projection_csv(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    reference_dir: str | Path | None = None,
    base_dir: str | Path | None = None,
    atom_id: str = "nirs_spm_surface_projection",
    coordinate_set_id: str = "",
    label_column: str = "",
    head_coordinate_columns: dict[str, str] | None = None,
    reference_coordinate_columns: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a Python rewrite of NIRS-SPM ``projection_CS.m`` on CSV coordinates.

    The implemented stage is the NIRS-SPM cortical surface projection from MNI
    head-surface coordinates to MNI cortical-surface coordinates. It does not
    silently import already projected MNI columns as output.
    """
    source = _resolve_source_path(source_path, base_dir)
    if not source.exists():
        raise FileNotFoundError(f"NIRS-SPM projection input CSV not found: {source}")

    rows = _read_csv_rows(source)
    if not rows:
        raise ValueError(f"NIRS-SPM projection input CSV has no data rows: {source}")

    headers = set(rows[0].keys())
    label_col = _select_first_existing(headers, [label_column] if label_column else [
        "projection_label",
        "label",
        "channel",
        "channel_name",
        "raw_label",
        "optode_name",
    ])
    head_cols = _select_xyz_columns(
        headers,
        head_coordinate_columns,
        [
            ("projected_head_x", "projected_head_y", "projected_head_z"),
            ("head_x", "head_y", "head_z"),
            ("mni_head_x", "mni_head_y", "mni_head_z"),
        ],
        "head-surface",
    )
    ref_cols = None
    if reference_coordinate_columns is not None:
        ref_cols = _select_xyz_columns(headers, reference_coordinate_columns, [], "reference MNI")
    elif {"projected_mni_x", "projected_mni_y", "projected_mni_z"}.issubset(headers):
        ref_cols = ("projected_mni_x", "projected_mni_y", "projected_mni_z")

    input_points: list[list[float]] = []
    source_row_indexes: list[int] = []
    input_metadata: list[dict[str, str]] = []
    skipped_missing_head = 0
    for source_row_index, row in enumerate(rows, start=1):
        head_xyz = [_parse_float(row.get(column, "")) for column in head_cols]
        if any(value is None for value in head_xyz):
            skipped_missing_head += 1
            continue
        input_points.append([float(value) for value in head_xyz])
        source_row_indexes.append(source_row_index)
        input_metadata.append(row)

    if not input_points:
        raise ValueError(f"No rows contained complete head-surface coordinates in columns {head_cols}")

    projector = NirsspmSurfaceProjector.from_reference_dir(reference_dir or DEFAULT_REFERENCE_DIR)
    projected_points = projector.project_head_to_cortex(input_points)

    source_sha256 = _sha256(source)
    coordinate_set = coordinate_set_id or _first_nonempty(rows, "group_id") or source.stem
    normalized_rows: list[dict[str, Any]] = []
    distances: list[float] = []
    for row_index, (source_row_index, source_row, projected_xyz) in enumerate(
        zip(source_row_indexes, input_metadata, projected_points, strict=True),
        start=1,
    ):
        label = str(source_row.get(label_col, "")).strip() if label_col else ""
        output_row: dict[str, Any] = {
            "coordinate_set_id": coordinate_set,
            "row_index": row_index,
            "source_row_index": source_row_index,
            "label": label,
            "point_type": _infer_point_type(source_row, label),
            "head_x": float(input_points[row_index - 1][0]),
            "head_y": float(input_points[row_index - 1][1]),
            "head_z": float(input_points[row_index - 1][2]),
            "projected_mni_x": float(projected_xyz[0]),
            "projected_mni_y": float(projected_xyz[1]),
            "projected_mni_z": float(projected_xyz[2]),
            "projection_algorithm": "NIRS-SPM_v4_r1_projection_CS_python_rewrite",
            "projection_stage": DEFAULT_STAGE,
            "source_file_sha256": source_sha256,
        }
        if ref_cols is not None:
            ref_xyz = [_parse_float(source_row.get(column, "")) for column in ref_cols]
            if not any(value is None for value in ref_xyz):
                diff = [float(projected_xyz[i]) - float(ref_xyz[i]) for i in range(3)]
                distance = math.sqrt(sum(value * value for value in diff))
                distances.append(distance)
                output_row.update(
                    {
                        "reference_mni_x": float(ref_xyz[0]),
                        "reference_mni_y": float(ref_xyz[1]),
                        "reference_mni_z": float(ref_xyz[2]),
                        "diff_x_atom_minus_reference": diff[0],
                        "diff_y_atom_minus_reference": diff[1],
                        "diff_z_atom_minus_reference": diff[2],
                        "euclidean_distance_mm": distance,
                    }
                )
        normalized_rows.append(output_row)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    safe_stem = _safe_stem(coordinate_set)
    csv_path = output_path / f"{safe_stem}_nirsspm_surface_projection.csv"
    json_path = output_path / f"{safe_stem}_nirsspm_surface_projection.json"
    manifest_path = output_path / f"{safe_stem}_nirsspm_surface_projection_manifest.json"

    _write_rows(csv_path, normalized_rows)
    validation = _summarize_distances(distances)
    manifest = {
        "type": "NirsspmSurfaceProjection",
        "coordinate_set_id": coordinate_set,
        "atom_id": atom_id,
        "source_file": str(source),
        "source_file_sha256": source_sha256,
        "reference_dir": str(projector.reference_dir),
        "source_rows": len(rows),
        "projected_rows": len(normalized_rows),
        "skipped_missing_head": skipped_missing_head,
        "head_coordinate_columns": list(head_cols),
        "reference_coordinate_columns": list(ref_cols) if ref_cols is not None else [],
        "label_column": label_col,
        "projection_algorithm": "NIRS-SPM_v4_r1_projection_CS_python_rewrite",
        "projection_stage": DEFAULT_STAGE,
        "surface_reference_count": projector.surface_reference_count,
        "validation": validation,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "projection_csv": str(csv_path),
            "projection_json": str(json_path),
            "manifest": str(manifest_path),
        },
    }
    json_path.write_text(
        json.dumps({**manifest, "rows": normalized_rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    warnings = []
    if skipped_missing_head:
        warnings.append(f"Skipped {skipped_missing_head} rows without complete head-surface coordinates")
    if validation.get("matched_reference_rows", 0) and validation.get("max_distance_mm", 0) > 5:
        warnings.append(
            "Projection rewrite differs from provided reference coordinates; inspect validation metrics before use"
        )

    return {
        "output": {**manifest, "rows": normalized_rows},
        "output_handles": {
            "type": "NirsspmSurfaceProjection",
            "coordinate_set_id": coordinate_set,
            "rows": len(normalized_rows),
            "projection_csv": str(csv_path),
            "projection_json": str(json_path),
            "manifest": str(manifest_path),
            "projection_algorithm": "NIRS-SPM_v4_r1_projection_CS_python_rewrite",
            "projection_stage": DEFAULT_STAGE,
            "validation": validation,
        },
        "artifact_paths": [csv_path, json_path, manifest_path],
        "warnings": warnings,
        "provenance": {
            "source_file": str(source),
            "source_file_sha256": source_sha256,
            "reference_dir": str(projector.reference_dir),
            "projection_algorithm": "NIRS-SPM_v4_r1_projection_CS_python_rewrite",
            "projection_stage": DEFAULT_STAGE,
        },
    }


class NirsspmSurfaceProjector:
    """Python rewrite of NIRS-SPM v4 r1 ``projection_CS.m``."""

    def __init__(self, cortical_surfaces: list[Any], brain_surface_edge: Any, reference_dir: Path) -> None:
        self.cortical_surfaces = cortical_surfaces
        self.brain_surface_edge = brain_surface_edge
        self.reference_dir = reference_dir
        self.surface_reference_count = len(cortical_surfaces)

    @classmethod
    def from_reference_dir(cls, reference_dir: str | Path) -> NirsspmSurfaceProjector:
        np = _require_numpy()
        loadmat = _require_loadmat()
        ref_dir = _resolve_reference_dir(reference_dir)
        mat_dir = ref_dir / "nfri_functions" / "mat" / "nfri_mni_estimation"
        if not mat_dir.exists():
            raise FileNotFoundError(f"NIRS-SPM surface reference directory not found: {mat_dir}")

        cortical_surfaces = []
        for index in range(1, 18):
            mat_path = mat_dir / f"CrtSrfMNISm{index:04d}.mat"
            mat = loadmat(mat_path)
            cortical_surfaces.append(
                np.column_stack([mat["xallM"].ravel(), mat["yallM"].ravel(), mat["zallM"].ravel()]).astype(float)
            )
        brain_mat = loadmat(mat_dir / "BrainSurfEdgeMNI.mat")
        brain_surface_edge = np.column_stack(
            [brain_mat["xallBEM"].ravel(), brain_mat["yallBEM"].ravel(), brain_mat["zallBEM"].ravel()]
        ).astype(float)
        return cls(cortical_surfaces, brain_surface_edge, ref_dir)

    def project_head_to_cortex(self, points: list[list[float]]) -> Any:
        np = _require_numpy()
        points_array = np.asarray(points, dtype=float)
        projected_by_reference = []
        for surface in self.cortical_surfaces:
            projected_by_reference.append(
                np.asarray([projection_bs(surface, point) for point in points_array], dtype=float)
            )
        averaged = np.stack(projected_by_reference, axis=0).mean(axis=0)
        return np.asarray([back_projection(self.brain_surface_edge, point) for point in averaged], dtype=float)


def projection_bs(surface_xyz: Any, point: Any) -> Any:
    """Rewrite of NIRS-SPM ``ProjectionBS_f``."""
    np = _require_numpy()
    point_array = np.asarray(point, dtype=float)
    distances = np.sqrt(np.sum((surface_xyz - point_array) ** 2, axis=1))
    sorted_indexes = np.argsort(distances)
    top_count = max(1, round(surface_xyz.shape[0] * 0.05))
    close_count = min(200, surface_xyz.shape[0])
    xyz_top = surface_xyz[sorted_indexes[:top_count], :]
    xyz_close = surface_xyz[sorted_indexes[:close_count], :]
    point_near = xyz_close.mean(axis=0)
    point_vector = point_array - point_near
    denominator = float(np.dot(point_vector, point_vector))
    if denominator == 0:
        foot_points = np.repeat(point_array[None, :], xyz_top.shape[0], axis=0)
    else:
        t_values = ((xyz_top - point_array) @ point_vector) / denominator
        foot_points = point_array + t_values[:, None] * point_vector
    rod_distances = np.sqrt(np.sum((xyz_top - foot_points) ** 2, axis=1))

    rod = np.empty((0, 3), dtype=float)
    rod_radius = 0
    while rod.size == 0:
        rod_radius += 1
        rod = xyz_top[rod_distances <= rod_radius, :]

    vicinity_distances = np.sqrt(np.sum((rod - point_array) ** 2, axis=1))
    vicinity_indexes = np.argsort(vicinity_distances)
    vicinity_count = min(3, rod.shape[0])
    return rod[vicinity_indexes[:vicinity_count], :].mean(axis=0)


def back_projection(surface_edge_xyz: Any, point: Any) -> Any:
    """Rewrite of NIRS-SPM ``BackProjectionf``."""
    np = _require_numpy()
    point_array = np.asarray(point, dtype=float)
    distances = np.sqrt(np.sum((surface_edge_xyz - point_array) ** 2, axis=1))
    indexes = np.argsort(distances)[:3]
    return surface_edge_xyz[indexes, :].mean(axis=0)


def _resolve_reference_dir(reference_dir: str | Path) -> Path:
    path = Path(reference_dir)
    if path.exists():
        return path
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / path
    if candidate.exists():
        return candidate
    return path


def _require_numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError("NIRS-SPM projection rewrite requires numpy") from exc
    return np


def _require_loadmat() -> Any:
    try:
        from scipy.io import loadmat
    except ImportError as exc:
        raise ImportError("NIRS-SPM projection rewrite requires scipy to read NIRS-SPM .mat surfaces") from exc
    return loadmat


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
            raise ValueError(f"NIRS-SPM projection CSV has no header: {path}")
        return [{str(key): value for key, value in row.items()} for row in reader]


def _select_xyz_columns(
    headers: set[str],
    configured: dict[str, str] | None,
    candidates: list[tuple[str, str, str]],
    label: str,
) -> tuple[str, str, str]:
    if configured:
        selected = (str(configured.get("x", "")), str(configured.get("y", "")), str(configured.get("z", "")))
        missing = [column for column in selected if column not in headers]
        if missing:
            raise ValueError(f"Configured {label} coordinate columns not found: {missing}")
        return selected
    for candidate in candidates:
        if all(column in headers for column in candidate):
            return candidate
    raise ValueError(f"NIRS-SPM projection CSV is missing recognized {label} coordinate columns")


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
    if "fiducial" in kind or "reference" in kind:
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


def _summarize_distances(distances: list[float]) -> dict[str, Any]:
    if not distances:
        return {"matched_reference_rows": 0}
    sorted_distances = sorted(distances)
    count = len(sorted_distances)
    median = (
        sorted_distances[count // 2]
        if count % 2
        else (sorted_distances[count // 2 - 1] + sorted_distances[count // 2]) / 2
    )
    return {
        "matched_reference_rows": count,
        "mean_distance_mm": sum(sorted_distances) / count,
        "median_distance_mm": median,
        "rmse_distance_mm": math.sqrt(sum(value * value for value in sorted_distances) / count),
        "max_distance_mm": max(sorted_distances),
        "within_5mm_count": sum(value <= 5 for value in sorted_distances),
        "within_10mm_count": sum(value <= 10 for value in sorted_distances),
        "within_15mm_count": sum(value <= 15 for value in sorted_distances),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_stem(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe.strip("._") or "nirsspm_surface_projection"
