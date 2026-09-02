"""Spawn-safe request, response, and entry point for isolated run execution."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fnirs_flow.execution.concurrency import native_thread_limit
from fnirs_flow.execution.engine import RunContext
from fnirs_flow.execution.models import RunExecutionResult


class RunWorkerRequest(BaseModel):
    run_context: dict[str, Any]
    plan: dict[str, Any]
    dag: dict[str, Any]
    outdir: str
    continue_on_failure: bool = True
    blas_threads: int = Field(default=1, ge=1)
    attempt_id: str = ""


class RunWorkerResponse(BaseModel):
    run_id: str
    result: RunExecutionResult
    events: list[dict[str, Any]] = Field(default_factory=list)


def execute_run_worker(request_payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one run without receiving locks, callbacks, adapters, or MNE objects."""
    request = RunWorkerRequest.model_validate(request_payload)
    run_context = RunContext.model_validate(request.run_context)
    service_type = getattr(importlib.import_module("fnirs_flow.execution.service"), "ExecutionService")
    service = service_type(progress_callback=None, cancel_check=None)
    service._active_attempt_id = request.attempt_id
    with native_thread_limit(request.blas_threads):
        result = service.run_executor.execute(
            run_context,
            request.plan,
            request.dag,
            Path(request.outdir),
            continue_on_failure=request.continue_on_failure,
        )
    response = RunWorkerResponse(
        run_id=run_context.run_id,
        result=result,
        events=[{"type": "run_completed", "run_id": run_context.run_id, "status": result.status}],
    )
    return response.model_dump(mode="json")
