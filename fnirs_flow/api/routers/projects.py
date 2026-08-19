"""Project, Flow, validation, compilation, and snapshot endpoints."""

from __future__ import annotations

import logging
import os
import string
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from fnirs_flow.api.error_responses import api_error
from fnirs_flow.api.models import (
    CompileResult,
    FlowUpdate,
    LocalFolderList,
    ProjectCreate,
    ProjectLockInfo,
    ProjectRead,
    ProjectSnapshot,
    ProjectStatus,
    ValidationResult,
)
from fnirs_flow.api.router_dependencies import bind_router_context, current_service, current_store
from fnirs_flow.application.project_use_cases import (
    ProjectReadOnlyError,
    assert_project_editable,
    create_snapshot,
    get_project_status,
    load_project_compile_result,
)
from fnirs_flow.infrastructure.project_bundle import ProjectBundleError

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(bind_router_context)])


def _store() -> Any:
    return current_store()


def _service() -> Any:
    return current_service()


def _local_folder_roots() -> list[Path]:
    roots: list[Path] = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:/")
            if drive.exists():
                roots.append(drive)
    roots.extend([Path.home(), Path.cwd()])
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key not in seen and resolved.is_dir():
            seen.add(key)
            unique.append(resolved)
    return unique


def _folder_entry(path: Path) -> dict[str, Any]:
    try:
        has_children = any(child.is_dir() and not child.name.startswith(".") for child in path.iterdir())
    except OSError:
        has_children = False
    return {"name": path.name or str(path), "path": str(path), "has_children": has_children}


@router.get("/api/local-folders", response_model=LocalFolderList)
async def list_local_folders(
    path: str = Query("", description="Absolute local folder path to browse"),
) -> dict[str, Any]:
    try:
        if not path.strip():
            current = ""
            parent = ""
            folders = [_folder_entry(root) for root in _local_folder_roots()]
        else:
            current_path = Path(path).expanduser().resolve()
            if not current_path.is_dir():
                raise HTTPException(status_code=422, detail="Folder does not exist or is not a directory")
            current = str(current_path)
            parent = str(current_path.parent) if current_path.parent != current_path else ""
            folders = [
                _folder_entry(child)
                for child in sorted(current_path.iterdir(), key=lambda item: item.name.lower())
                if child.is_dir() and not child.name.startswith(".")
            ]
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Permission denied while listing this folder") from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"current": current, "parent": parent, "folders": folders}


@router.get("/api/projects", response_model=list[ProjectRead])
async def list_projects() -> Any:
    return _store().list_all()


@router.post("/api/projects", response_model=ProjectRead)
async def create_project(data: ProjectCreate) -> Any:
    return _store().create(data.name, data.description, data_root=data.data_root)


@router.get("/api/projects/{project_id}", response_model=ProjectRead)
async def get_project(project_id: str) -> Any:
    project = _store().get(project_id)
    if project is None:
        raise api_error(404, "PROJECT_NOT_FOUND", "Project not found", "project", recoverable=False,
                        suggested_action="Select an existing project")
    return project


@router.get("/api/projects/{project_id}/status", response_model=ProjectStatus)
async def get_project_status_endpoint(project_id: str) -> Any:
    result = get_project_status(_store(), project_id)
    if result is None:
        raise api_error(404, "PROJECT_NOT_FOUND", "Project not found", "project", recoverable=False,
                        suggested_action="Select an existing project")
    return result


@router.get("/api/projects/{project_id}/flow")
async def get_flow(project_id: str) -> dict[str, Any]:
    flow = _store().get_flow(project_id)
    if flow is None:
        raise api_error(404, "PROJECT_NOT_FOUND", "Project not found", "flow", recoverable=False,
                        suggested_action="Select an existing project")
    return cast(dict[str, Any], flow)


@router.put("/api/projects/{project_id}/flow")
async def update_flow(project_id: str, data: FlowUpdate) -> dict[str, str]:
    try:
        assert_project_editable(_store(), project_id)
    except ProjectReadOnlyError as exc:
        raise api_error(409, "PROJECT_READ_ONLY", str(exc), "flow", recoverable=True,
                        suggested_action="Fork the imported project before editing") from exc
    try:
        updated = _store().update_flow(project_id, data.flow, debounce=data.debounce)
    except ProjectBundleError as exc:
        raise api_error(422, "FLOW_PATH_INVALID", str(exc), "flow", recoverable=True,
                        suggested_action="Use a project-relative path under the project's data folder") from exc
    if not updated:
        raise api_error(404, "PROJECT_NOT_FOUND", "Project not found", "flow", recoverable=False,
                        suggested_action="Select an existing project")
    return {"status": "updated"}


@router.post("/api/projects/{project_id}/validate", response_model=ValidationResult)
async def validate_flow_endpoint(project_id: str) -> Any:
    result = await run_in_threadpool(_service().validate, project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.post("/api/projects/{project_id}/compile", response_model=CompileResult)
async def compile_flow_endpoint(project_id: str, base_revision: int | None = Query(None)) -> Any:
    try:
        assert_project_editable(_store(), project_id)
    except ProjectReadOnlyError as exc:
        raise api_error(409, "PROJECT_READ_ONLY", str(exc), "compile", recoverable=True,
                        suggested_action="Fork the imported project before compiling") from exc
    try:
        result = await run_in_threadpool(_service().compile, project_id, base_revision=base_revision)
    except (ValueError, KeyError) as exc:
        raise api_error(422, "COMPILE_VALIDATION_FAILED", str(exc), "compile", recoverable=True,
                        suggested_action="Fix validation errors and compile again") from exc
    except (OSError, RuntimeError) as exc:
        logger.exception("Compilation failed for project %s", project_id)
        raise api_error(500, "COMPILE_FAILED", str(exc), "compile", recoverable=True,
                        suggested_action="Check output permissions and server logs") from exc
    if result is None:
        code = "PROJECT_NOT_FOUND" if _store().get(project_id) is None else "FLOW_NOT_FOUND"
        raise api_error(404, code, "Project or Flow not found", "compile", recoverable=False,
                        suggested_action="Create or save a Flow before compiling")
    return result


@router.get("/api/projects/{project_id}/compile", response_model=CompileResult)
async def get_compile_result_endpoint(project_id: str) -> Any:
    result = load_project_compile_result(_store(), project_id)
    if result is None:
        status = 404 if _store().get(project_id) is None else 409
        raise api_error(status, "PROJECT_NOT_FOUND" if status == 404 else "PLAN_NOT_COMPILED",
                        "Compiled plan not found", "compile", recoverable=status == 409,
                        suggested_action="Compile the Flow first")
    return result


@router.post("/api/projects/{project_id}/snapshots", response_model=ProjectSnapshot)
async def create_snapshot_endpoint(project_id: str) -> Any:
    result = create_snapshot(_store(), project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    return result


@router.get("/api/projects/{project_id}/lock", response_model=ProjectLockInfo)
async def get_project_lock_status(project_id: str) -> ProjectLockInfo:
    if _store().get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectLockInfo(**_store().get_lock_info(project_id))
