"""Read-only backend and service diagnostics endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

import fnirs_flow
from fnirs_flow.api.models import BackendDescription, HealthStatus

router = APIRouter()


@router.get("/api/backends", response_model=list[BackendDescription])
async def list_backends() -> list[BackendDescription]:
    from fnirs_flow.adapters.backend_registry import get_registry

    registry = get_registry()
    return [
        BackendDescription(**description)
        for backend_id in registry.list_all()
        if (description := registry.describe(backend_id)) is not None
    ]


@router.get("/api/health", response_model=HealthStatus)
async def health() -> dict[str, Any]:
    return {"status": "ok", "version": fnirs_flow.__version__}
