"""Stable artifact representations and finite result-table persistence."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Protocol

from fnirs_flow.infrastructure.uri import create_project_uri


class RunResultLike(Protocol):
    run_id: str
    channel_results: list[dict[str, Any]]
    roi_results: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    atom_results: list[Any]


def path_artifact_summary(
    path: Path,
    outdir: Path,
    *,
    artifact_type: str,
    artifact_id: str,
    atom_id: str = "",
    step_id: str = "",
) -> dict[str, Any]:
    """Return the stable API/UI representation of a derivative file."""
    resolved_path = path.resolve()
    try:
        relative_path = str(resolved_path.relative_to(outdir.resolve()))
    except ValueError:
        relative_path = ""
    uri = create_project_uri(f"outputs/{relative_path}") if relative_path else None
    return {
        "artifact_id": artifact_id,
        "type": artifact_type,
        "uri": str(uri) if uri else "",
        "path": str(uri) if uri else "",
        "resolved_path": str(resolved_path),
        "relative_path": relative_path,
        "checksum": hashlib.sha256(resolved_path.read_bytes()).hexdigest(),
        "exists": resolved_path.is_file(),
        "atom_id": atom_id,
        "step_id": step_id,
    }


def write_run_result_tables(run_result: RunResultLike, outdir: Path) -> None:
    """Persist finite channel and ROI tables for one completed run."""
    for kind, rows in (("channel", run_result.channel_results), ("roi", run_result.roi_results)):
        if not rows:
            continue
        for row_index, row in enumerate(rows):
            for key, value in row.items():
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"Non-finite {kind} result at row {row_index}, field '{key}'")
        result_dir = outdir / "derivatives" / kind
        result_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{run_result.run_id}_{kind}_results"
        json_path = result_dir / f"{stem}.json"
        csv_path = result_dir / f"{stem}.csv"
        json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
        with csv_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        for path in (json_path, csv_path):
            source_atom_ids = sorted({str(row.get("source_atom_id", "")) for row in rows if row.get("source_atom_id")})
            artifact = path_artifact_summary(
                path, outdir, artifact_type=f"{kind.title()}Results",
                artifact_id=f"{run_result.run_id}-{kind}-{path.suffix.lstrip('.')}",
                atom_id=",".join(source_atom_ids), step_id=f"{kind}_output",
            )
            run_result.artifacts.append(artifact)
            for atom_id in source_atom_ids:
                atom_result = next((item for item in run_result.atom_results if item.atom_id == atom_id), None)
                if atom_result is not None:
                    atom_result.artifacts.append({**artifact, "atom_id": atom_id})


def collect_group_result_artifacts(outdir: Path) -> list[dict[str, Any]]:
    """Collect the bounded set of supported group result artifacts."""
    group_dir = outdir / "derivatives" / "group"
    if not group_dir.is_dir():
        return []
    specs = {
        "analysis_table.csv": ("GroupAnalysisTable", "group_design_matrix"),
        "group_design_matrix.csv": ("GroupDesignMatrix", "group_design_matrix"),
        "group_design_spec.json": ("GroupDesignSpec", "group_design_matrix"),
        "group_summary.csv": ("GroupSummaryTable", "group_summary"),
        "group_summary.json": ("GroupSummaryJson", "group_summary"),
        "group_glm_results.csv": ("GroupGLMResultsTable", "group_level_glm"),
        "group_glm_results.json": ("GroupGLMResultsJson", "group_level_glm"),
        "contrast_matrix.csv": ("ContrastMatrixTable", "group_contrast"),
        "contrast_results.csv": ("ContrastResultsTable", "group_contrast"),
        "contrast_results.json": ("ContrastResultsJson", "group_contrast"),
        "effect_sizes.csv": ("ContrastEffectSizesTable", "group_contrast"),
        "effect_sizes.json": ("ContrastEffectSizesJson", "group_contrast"),
        "multiple_comparison_results.csv": ("MultipleComparisonResultsTable", "group_contrast"),
        "multiple_comparison_results.json": ("MultipleComparisonResultsJson", "group_contrast"),
        "group_contrasts.json": ("GroupContrastSpec", "group_contrast"),
        "contrast_effects.svg": ("ContrastEffectFigure", "group_contrast"),
    }
    return [
        path_artifact_summary(
            group_dir / filename,
            outdir,
            artifact_type=artifact_type,
            artifact_id=f"group-{Path(filename).stem}-{Path(filename).suffix.lstrip('.')}",
            atom_id=atom_id,
            step_id=atom_id,
        )
        for filename, (artifact_type, atom_id) in specs.items()
        if (group_dir / filename).exists()
    ]
