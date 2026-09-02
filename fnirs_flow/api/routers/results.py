"""Generated result workspace endpoints."""

from __future__ import annotations

import csv
import itertools
import json
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from fnirs_flow.api.models import ProjectResults
from fnirs_flow.api.router_dependencies import bind_router_context, current_store
from fnirs_flow.api.svg_sanitizer import sanitize_svg
from fnirs_flow.infrastructure.filesystem import is_macos_metadata_path

router = APIRouter(dependencies=[Depends(bind_router_context)])

MAX_RESULT_FILE_BYTES = 2 * 1024**2
MAX_RESULT_FIGURE_BYTES = 1024**2


def _store() -> Any:
    return current_store()


def _read_result_file(path: Path, logical_name: str, row_limit: int) -> dict[str, Any]:
    size_bytes = path.stat().st_size
    if size_bytes > MAX_RESULT_FILE_BYTES:
        return {
            "path": logical_name,
            "data": None,
            "size_bytes": size_bytes,
            "rows_truncated": True,
        }
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as stream:
            rows = list(itertools.islice(csv.DictReader(stream), row_limit + 1))
        truncated = len(rows) > row_limit
        data = rows[:row_limit]
        return {
            "path": logical_name,
            "data": data,
            "size_bytes": size_bytes,
            "returned_rows": len(data),
            "rows_truncated": truncated,
        }
    return {
        "path": logical_name,
        "data": json.loads(path.read_text(encoding="utf-8")),
        "size_bytes": size_bytes,
    }


def _load_project_results(
    store: Any,
    project_id: str,
    kind: str,
    *,
    row_limit: int,
    file_limit: int,
) -> dict[str, Any]:
    outdir = store.get_output_dir(project_id)
    paths: list[Path] = []
    processed_root = outdir / "derivatives" / "processed_hb_first_level"
    processed_tables = {
        "qc": ["residual_qc.csv", "exclusion_manifest.csv", "design_matrix_manifest.csv"],
        "channel": ["first_level_glm_estimates.csv", "first_level_contrasts.csv"],
    }
    if kind in processed_tables and processed_root.is_dir():
        for name in processed_tables[kind]:
            path = processed_root / name
            if path.exists():
                paths.append(path)
    if kind == "qc":
        paths.extend(outdir.glob("sub-*/**/*_desc-qc_summary.json"))
        paths.extend((outdir / "compiled").glob("sub-*/**/*_desc-qc_summary.json"))
    else:
        for base in (outdir / "derivatives" / kind, outdir / "compiled" / "derivatives" / kind):
            if base.is_dir():
                paths.extend(base.glob("*.json"))
    figure_paths: list[Path] = []
    if kind == "group":
        for base in (outdir / "derivatives" / "group", outdir / "compiled" / "derivatives" / "group"):
            if base.is_dir():
                figure_paths.extend(base.glob("*.svg"))
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(paths):
        relative = path.relative_to(outdir).as_posix()
        logical_name = relative.removeprefix("compiled/")
        if is_macos_metadata_path(relative) or logical_name in seen:
            continue
        seen.add(logical_name)
        if len(files) >= file_limit:
            continue
        try:
            files.append(_read_result_file(path, logical_name, row_limit))
        except (OSError, json.JSONDecodeError):
            continue
    figures: list[dict[str, str]] = []
    seen_figures: set[str] = set()
    for path in sorted(figure_paths):
        relative = path.relative_to(outdir).as_posix()
        logical_name = relative.removeprefix("compiled/")
        if is_macos_metadata_path(relative) or logical_name in seen_figures:
            continue
        seen_figures.add(logical_name)
        if len(figures) >= file_limit:
            continue
        try:
            if path.stat().st_size > MAX_RESULT_FIGURE_BYTES:
                continue
            svg = sanitize_svg(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        figures.append({"path": logical_name, "svg": svg})
    total_files = len(seen)
    truncated = total_files > len(files) or len(seen_figures) > len(figures)
    return {
        "kind": kind,
        "file_count": total_files,
        "returned_file_count": len(files),
        "truncated": truncated,
        "files": files,
        "figures": figures,
    }


@router.get("/api/projects/{project_id}/results/{kind}", response_model=ProjectResults)
async def project_results_endpoint(
    project_id: str,
    kind: str,
    row_limit: int = Query(default=100, ge=1, le=1000),
    file_limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    if kind not in {"qc", "channel", "roi", "group"}:
        raise HTTPException(status_code=404, detail="Unknown result type")
    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return cast(
        dict[str, Any],
        await run_in_threadpool(
            _load_project_results,
            store,
            project_id,
            kind,
            row_limit=row_limit,
            file_limit=file_limit,
        ),
    )
