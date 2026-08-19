"""Dry-run and asynchronous execution endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from fnirs_flow.api.error_responses import api_error
from fnirs_flow.api.models import DryRunResult, ExecutionJobRead
from fnirs_flow.api.router_dependencies import (
    bind_router_context,
    current_job_manager,
    current_service,
    current_store,
    validate_current_project,
)
from fnirs_flow.application.project_use_cases import (
    ProjectDataNotReadyError,
    ProjectQuarantineError,
    StaleCompiledPlanError,
)

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(bind_router_context)])


def _store() -> Any:
    return current_store()


def _service() -> Any:
    return current_service()


def _jobs() -> Any:
    return current_job_manager()


def _validate_execution(store: Any, project_id: str) -> bool:
    return validate_current_project(store, project_id)


@router.post("/api/projects/{project_id}/dry-run", response_model=DryRunResult)
async def dry_run_endpoint(project_id: str) -> Any:
    try:
        result = await run_in_threadpool(_service().dry_run, project_id)
    except StaleCompiledPlanError as exc:
        raise api_error(409, "STALE_COMPILED_PLAN", str(exc), "dry_run", recoverable=True,
                        suggested_action="Compile the current Flow again") from exc
    except (OSError, KeyError, ValueError) as exc:
        raise api_error(422, "DRY_RUN_FAILED", str(exc), "dry_run", recoverable=True,
                        suggested_action="Check the compiled plan and data manifest") from exc
    if result is None:
        status = 404 if _store().get(project_id) is None else 409
        raise api_error(status, "PROJECT_NOT_FOUND" if status == 404 else "PLAN_NOT_COMPILED",
                        "Compiled plan not found", "dry_run", recoverable=status == 409,
                        suggested_action="Compile the Flow first")
    return result


@router.post("/api/projects/{project_id}/execute", response_model=ExecutionJobRead, status_code=202)
async def execute_endpoint(project_id: str) -> Any:
    try:
        ready = _validate_execution(_store(), project_id)
    except StaleCompiledPlanError as exc:
        raise api_error(409, "STALE_COMPILED_PLAN", str(exc), "execute", recoverable=True,
                        suggested_action="Compile the current Flow again") from exc
    except ProjectQuarantineError as exc:
        raise api_error(409, "QUARANTINED_ATOMS", str(exc), "execute", recoverable=True,
                        suggested_action="Review and explicitly trust quarantined atoms") from exc
    except ProjectDataNotReadyError as exc:
        raise api_error(409, "DATA_NOT_READY", str(exc), "execute", recoverable=True,
                        suggested_action="Discover or relink at least one existing data run") from exc
    except ImportError as exc:
        raise api_error(503, "BACKEND_UNAVAILABLE", str(exc), "execute", recoverable=True,
                        suggested_action="Install or repair the required backend") from exc
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        logger.exception("Execution request failed for project %s", project_id)
        raise api_error(500, "EXECUTION_FAILED", str(exc), "execute", recoverable=True,
                        suggested_action="Inspect execution logs and retry") from exc
    if not ready:
        status = 404 if _store().get(project_id) is None else 409
        raise api_error(status, "PROJECT_NOT_FOUND" if status == 404 else "PLAN_NOT_COMPILED",
                        "Project or compiled plan not found", "execute", recoverable=status == 409,
                        suggested_action="Compile the Flow and discover data first")
    return _jobs().create(project_id)


@router.get("/api/projects/{project_id}/attempts", response_model=list[ExecutionJobRead])
async def list_execution_attempts(project_id: str) -> Any:
    if _store().get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _jobs().list(project_id)


@router.get("/api/projects/{project_id}/attempts/{attempt_id}", response_model=ExecutionJobRead)
async def get_execution_attempt(project_id: str, attempt_id: str) -> Any:
    job = _jobs().get(project_id, attempt_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Execution attempt not found")
    return job


@router.post("/api/projects/{project_id}/attempts/{attempt_id}/cancel", response_model=ExecutionJobRead)
async def cancel_execution_attempt(project_id: str, attempt_id: str) -> Any:
    job = _jobs().cancel(project_id, attempt_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Execution attempt not found")
    return job
