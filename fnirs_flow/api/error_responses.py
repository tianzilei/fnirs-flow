"""Stable API error envelopes and concurrency exception handlers."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import JSONResponse

from fnirs_flow.api.exceptions import (
    ProjectBusyError,
    ProjectLockTimeoutError,
    ProjectRevisionConflictError,
    ProjectTransactionError,
)


def api_error(
    status_code: int,
    code: str,
    message: str,
    stage: str,
    *,
    recoverable: bool,
    suggested_action: str,
) -> HTTPException:
    """Build the stable error envelope used by workflow endpoints."""
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "stage": stage,
            "recoverable": recoverable,
            "suggested_action": suggested_action,
        },
    )


async def revision_conflict_handler(_request: Request, error: Exception) -> JSONResponse:
    exc = cast(ProjectRevisionConflictError, error)
    return JSONResponse(
        status_code=409,
        content={
            "code": "PROJECT_REVISION_CONFLICT",
            "message": str(exc),
            "stage": "save",
            "recoverable": True,
            "suggested_action": "Reload the project and retry",
            "current_revision": exc.current_revision,
            "requested_revision": exc.requested_revision,
        },
    )


async def project_busy_handler(_request: Request, error: Exception) -> JSONResponse:
    exc = cast(ProjectBusyError, error)
    return JSONResponse(
        status_code=409,
        content={
            "code": "PROJECT_BUSY",
            "message": str(exc),
            "stage": "save",
            "recoverable": True,
            "suggested_action": "Wait for the current operation to complete",
        },
    )


async def lock_timeout_handler(_request: Request, error: Exception) -> JSONResponse:
    exc = cast(ProjectLockTimeoutError, error)
    return JSONResponse(
        status_code=408,
        content={
            "code": "PROJECT_LOCK_TIMEOUT",
            "message": str(exc),
            "stage": "save",
            "recoverable": True,
            "suggested_action": "Retry after the current operation completes",
        },
    )


async def transaction_error_handler(_request: Request, error: Exception) -> JSONResponse:
    exc = cast(ProjectTransactionError, error)
    return JSONResponse(
        status_code=500,
        content={
            "code": "PROJECT_TRANSACTION_FAILED",
            "message": str(exc),
            "stage": "save",
            "recoverable": True,
            "suggested_action": "Retry the operation",
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register stable transaction and concurrency handlers on an app."""
    app.add_exception_handler(ProjectRevisionConflictError, revision_conflict_handler)
    app.add_exception_handler(ProjectBusyError, project_busy_handler)
    app.add_exception_handler(ProjectLockTimeoutError, lock_timeout_handler)
    app.add_exception_handler(ProjectTransactionError, transaction_error_handler)
