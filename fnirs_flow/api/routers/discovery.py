"""Dataset discovery and participant metadata endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from fnirs_flow.api.error_responses import api_error
from fnirs_flow.api.models import (
    DatasetRead,
    DiscoverResult,
    ExampleFlowSummary,
    ParticipantTableImportRequest,
    ParticipantTableImportResult,
    ProjectDataFolderList,
)
from fnirs_flow.api.router_dependencies import bind_router_context, current_service, current_store
from fnirs_flow.application.project_use_cases import (
    import_project_participant_table,
    list_project_data_folders,
    load_project_discover_result,
    resolve_project_data_path,
)
from fnirs_flow.data.registry import DatasetRegistry

router = APIRouter(dependencies=[Depends(bind_router_context)])


def _store() -> Any:
    return current_store()


def _service() -> Any:
    return current_service()


@router.get("/api/datasets", response_model=list[DatasetRead])
async def list_datasets_endpoint() -> list[DatasetRead]:
    return [DatasetRead(dataset_id=e.dataset_id, name=e.name, source_kind=e.source_kind, url=e.url, doi=e.doi,
                         citation=e.citation, license=e.license, description=e.description, folder_name=e.folder_name)
            for e in DatasetRegistry().all_entries()]


_EXAMPLE_FLOWS: dict[str, dict[str, Any]] = {
    "blank_template": {"label": "Blank Template", "flow": {"schema_version": "0.3.0", "flow_id": "blank-template",
        "name": "Blank Template", "description": "Start with an empty flow canvas.", "nodes": [], "flow_atoms": [],
        "edges": [], "adapter_registry": [], "metadata": {"tags": [], "order_policy": {"allow_order_violations": False,
        "allow_empty_edges": False}, "checklist": {}}}},
    "demo_task_glm_real": {"label": "Demo Task GLM Real Data", "path": Path("configs/demo_task_glm_real.json")},
    "demo_task_flow": {"label": "Demo Task GLM", "path": Path("configs/demo_task_flow.json")},
    "demo_resting_state_flow": {"label": "Demo Resting State", "path": Path("configs/demo_resting_state_flow.json")},
}


@router.get("/api/example-flows", response_model=list[ExampleFlowSummary])
async def list_example_flows_endpoint() -> list[dict[str, str]]:
    return [{"id": i, "label": s["label"]} for i, s in _EXAMPLE_FLOWS.items()]


@router.get("/api/example-flows/{example_id}")
async def get_example_flow_endpoint(example_id: str) -> dict[str, Any]:
    spec = _EXAMPLE_FLOWS.get(example_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Example flow not found")
    if "flow" in spec:
        return cast(dict[str, Any], spec["flow"])
    try:
        return cast(
            dict[str, Any],
            json.loads((Path(__file__).resolve().parents[3] / spec["path"]).read_text(encoding="utf-8")),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Example flow could not be loaded") from exc


@router.post("/api/projects/{project_id}/discover-data", response_model=DiscoverResult)
async def discover_data_endpoint(project_id: str, dataset_id: str,
                                  data_root: str | None = Query(None), data_path: str | None = Query(None),
                                  base_revision: int | None = Query(None)) -> Any:
    if _store().get(project_id) is None:
        raise api_error(404, "PROJECT_NOT_FOUND", "Project not found", "discovery", recoverable=False,
                        suggested_action="Select an existing project")
    try:
        return await run_in_threadpool(_service().discover, project_id, dataset_id, data_root=data_root,
                                       data_path=data_path, base_revision=base_revision)
    except ValueError as exc:
        raise api_error(404, "DATASET_NOT_FOUND", str(exc), "discovery", recoverable=True,
                        suggested_action="Choose a registered dataset ID") from exc
    except (OSError, KeyError, RuntimeError) as exc:
        raise api_error(500, "DATA_DISCOVERY_FAILED", str(exc), "discovery", recoverable=True,
                        suggested_action="Check data access and server logs") from exc


@router.get("/api/projects/{project_id}/data-folders", response_model=ProjectDataFolderList)
async def list_project_data_folders_endpoint(project_id: str, parent: str = Query("")) -> Any:
    if _store().get(project_id) is None:
        raise api_error(404, "PROJECT_NOT_FOUND", "Project not found", "data", recoverable=False,
                        suggested_action="Select an existing project")
    try:
        return await run_in_threadpool(list_project_data_folders, _store(), project_id, parent)
    except (OSError, ValueError) as exc:
        raise api_error(422, "PROJECT_DATA_FOLDER_INVALID", str(exc), "data", recoverable=True,
                        suggested_action="Choose a folder under the project's data directory") from exc


@router.get("/api/projects/{project_id}/discover-data", response_model=DiscoverResult)
async def get_discover_data_endpoint(project_id: str) -> Any:
    result = load_project_discover_result(_store(), project_id)
    if result is None:
        status = 404 if _store().get(project_id) is None else 409
        raise api_error(status, "PROJECT_NOT_FOUND" if status == 404 else "DATA_NOT_DISCOVERED",
                        "Dataset discovery result not found", "discovery", recoverable=status == 409,
                        suggested_action="Discover a dataset first")
    return result


@router.post("/api/projects/{project_id}/participant-table", response_model=ParticipantTableImportResult)
async def import_participant_table_endpoint(project_id: str, data: ParticipantTableImportRequest) -> Any:
    if _store().get(project_id) is None:
        raise api_error(404, "PROJECT_NOT_FOUND", "Project not found", "participant_metadata", recoverable=False,
                        suggested_action="Select an existing project")
    try:
        table_path, _ = resolve_project_data_path(
            _store(), project_id, data.path, label="Participant table path", must_be_file=True
        )
        result = import_project_participant_table(
            _store(),
            project_id,
            str(table_path),
            table_kind=data.table_kind,
            id_column=data.id_column,
            include_column=data.include_column,
            group_column=data.group_column,
            label_column=data.label_column,
            site_column=data.site_column,
            scanner_column=data.scanner_column,
            covariate_columns=data.covariate_columns,
            session_column=data.session_column,
            timepoint_column=data.timepoint_column,
            pair_id_column=data.pair_id_column,
            dyad_id_column=data.dyad_id_column,
            participant_role_column=data.participant_role_column,
            delimiter=data.delimiter,
            encoding=data.encoding,
        )
    except (OSError, ValueError) as exc:
        raise api_error(
            422,
            "PARTICIPANT_TABLE_INVALID",
            str(exc),
            "participant_metadata",
            recoverable=True,
            suggested_action="Check the table path, delimiter, encoding, and participant id column",
        ) from exc
    if result is None:
        raise api_error(404, "PROJECT_NOT_FOUND", "Project not found", "participant_metadata", recoverable=False,
                        suggested_action="Select an existing project")
    return result
