"""Request-scoped dependencies shared by API routers.

The composition root stores providers on ``FastAPI.state``.  A router-level
dependency resolves them once per request and exposes the resulting objects
through context variables, avoiding mutable provider globals in router
modules while preserving compact endpoint signatures.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from fastapi import Request

_store_context: ContextVar[Any] = ContextVar("fnirs_flow_api_store")
_service_context: ContextVar[Any] = ContextVar("fnirs_flow_api_service")
_jobs_context: ContextVar[Any] = ContextVar("fnirs_flow_api_jobs")
_validation_context: ContextVar[Callable[[Any, str], bool]] = ContextVar("fnirs_flow_api_validation")
_path_resolver_context: ContextVar[Callable[[str, str, str], Path]] = ContextVar("fnirs_flow_api_path_resolver")


async def bind_router_context(request: Request) -> AsyncIterator[None]:
    """Bind application dependencies to the lifetime of one HTTP request."""
    state = request.app.state
    tokens = [
        (_store_context, _store_context.set(state.store_provider())),
        (_service_context, _service_context.set(state.service_provider())),
        (_jobs_context, _jobs_context.set(state.job_manager_provider())),
        (_validation_context, _validation_context.set(state.validation_provider)),
        (_path_resolver_context, _path_resolver_context.set(state.path_resolver)),
    ]
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


def current_store() -> Any:
    return _store_context.get()


def current_service() -> Any:
    return _service_context.get()


def current_job_manager() -> Any:
    return _jobs_context.get()


def validate_current_project(store: Any, project_id: str) -> bool:
    return _validation_context.get()(store, project_id)


def resolve_current_path(value: str, project_id: str, label: str) -> Path:
    return _path_resolver_context.get()(value, project_id, label)
