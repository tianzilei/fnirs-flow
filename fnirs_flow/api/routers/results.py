"""Generated result workspace endpoints."""

from __future__ import annotations

import csv
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from fnirs_flow.api.models import ProjectResults
from fnirs_flow.api.router_dependencies import bind_router_context, current_store
from fnirs_flow.api.svg_sanitizer import sanitize_svg
from fnirs_flow.infrastructure.filesystem import is_macos_metadata_path

router = APIRouter(dependencies=[Depends(bind_router_context)])


def _store() -> Any:
    return current_store()


@router.get("/api/projects/{project_id}/results/{kind}", response_model=ProjectResults)
async def project_results_endpoint(project_id: str, kind: str) -> dict[str, Any]:
    if kind not in {"qc", "channel", "roi", "group"}:
        raise HTTPException(status_code=404, detail="Unknown result type")
    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    outdir = store.get_output_dir(project_id)
    paths = []
    processed_root = outdir / "derivatives" / "processed_hb_first_level"
    processed_tables = {
        "qc": ["residual_qc.csv", "exclusion_manifest.csv", "design_matrix_manifest.csv"],
        "channel": ["first_level_glm_estimates.csv", "first_level_contrasts.csv"],
    }
    if kind in processed_tables and processed_root.is_dir():
        for name in processed_tables[kind]:
            path = processed_root / name
            if path.exists():
                with path.open(newline="", encoding="utf-8-sig") as stream:
                    data = list(csv.DictReader(stream))
                paths.append(path)
    if kind == "qc":
        paths.extend(outdir.glob("sub-*/**/*_desc-qc_summary.json"))
        paths.extend((outdir / "compiled").glob("sub-*/**/*_desc-qc_summary.json"))
    else:
        for base in (outdir / "derivatives" / kind, outdir / "compiled" / "derivatives" / kind):
            if base.is_dir():
                paths.extend(base.glob("*.json"))
    figure_paths = []
    if kind == "group":
        for base in (outdir / "derivatives" / "group", outdir / "compiled" / "derivatives" / "group"):
            if base.is_dir():
                figure_paths.extend(base.glob("*.svg"))
    files = []
    seen: set[str] = set()
    for path in sorted(paths):
        relative = path.relative_to(outdir).as_posix()
        logical_name = relative.removeprefix("compiled/")
        if is_macos_metadata_path(relative) or logical_name in seen:
            continue
        seen.add(logical_name)
        if path.suffix == ".csv":
            try:
                with path.open(newline="", encoding="utf-8-sig") as stream:
                    data = list(csv.DictReader(stream))
            except OSError:
                continue
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        files.append({"path": logical_name, "data": data})
    figures = []
    seen_figures: set[str] = set()
    for path in sorted(figure_paths):
        relative = path.relative_to(outdir).as_posix()
        logical_name = relative.removeprefix("compiled/")
        if is_macos_metadata_path(relative) or logical_name in seen_figures:
            continue
        seen_figures.add(logical_name)
        try:
            svg = sanitize_svg(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        figures.append({"path": logical_name, "svg": svg})
    return {"kind": kind, "file_count": len(files), "files": files, "figures": figures}
