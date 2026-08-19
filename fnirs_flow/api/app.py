"""FastAPI application for fnirs-flow WebUI."""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

import fnirs_flow
from fnirs_flow.api.error_responses import register_exception_handlers
from fnirs_flow.api.middleware import configure_http_middleware
from fnirs_flow.api.project_use_cases import APIProjectUseCases
from fnirs_flow.api.routers.ai import router as ai_router
from fnirs_flow.api.routers.dependencies import router as dependencies_router
from fnirs_flow.api.routers.diagnostics import router as diagnostics_router
from fnirs_flow.api.routers.discovery import router as discovery_router
from fnirs_flow.api.routers.execution import router as execution_router
from fnirs_flow.api.routers.history import router as history_router
from fnirs_flow.api.routers.packages import router as packages_router
from fnirs_flow.api.routers.progress import (
    ProgressBuffer,
    _progress_events,  # noqa: F401 - compatibility surface for existing tests/tools
    _progress_sequences,  # noqa: F401 - compatibility surface for existing tests/tools
    push_progress,  # noqa: F401 - compatibility surface for existing tests/tools
)
from fnirs_flow.api.routers.progress import (
    router as progress_router,
)
from fnirs_flow.api.routers.projects import router as projects_router
from fnirs_flow.api.routers.registry import router as registry_router
from fnirs_flow.api.routers.results import router as results_router
from fnirs_flow.api.static import router as static_router
from fnirs_flow.application import ProjectApplicationService
from fnirs_flow.application.project_use_cases import ProjectStore, validate_project_execution
from fnirs_flow.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for startup/shutdown events."""
    # Startup
    from fnirs_flow.registry.atom_templates import refresh_method_atom_templates
    from fnirs_flow.registry.methodatom_library import write_runtime_state

    registry_state = refresh_method_atom_templates()
    write_runtime_state(registry_state, settings.registry_cache_dir)

    # Initialize lock registry
    from fnirs_flow.api.concurrency import get_lock_registry

    store = get_store()
    lock_dir = store._base_dir / ".locks"
    try:
        get_lock_registry(lock_dir=lock_dir)
    except ValueError:
        import logging

        logging.getLogger(__name__).debug("Lock registry already initialized with different lock_dir")

    yield
    # Shutdown (nothing to do)


app = FastAPI(
    title="fnirs-flow API",
    description="fNIRS analysis Flow orchestration framework",
    version=fnirs_flow.__version__,
    lifespan=lifespan,
)
app.state.settings = settings
app.state.progress_buffer = ProgressBuffer(settings.progress_buffer_limit)
configure_http_middleware(app, settings)
register_exception_handlers(app)
app.state.store_provider = lambda: get_store()
app.state.service_provider = lambda: get_project_service()
app.state.job_manager_provider = lambda: get_job_manager()
app.state.validation_provider = lambda store, project_id: validate_project_execution(store, project_id)
app.state.path_resolver = lambda value, project_id, label: _resolve_allowed_local_file(
    value, project_id, label=label
)
app.include_router(registry_router)
app.include_router(progress_router)
app.include_router(diagnostics_router)
app.include_router(dependencies_router)
app.include_router(history_router)
app.include_router(packages_router)
app.include_router(discovery_router)
app.include_router(projects_router)
app.include_router(execution_router)
app.include_router(results_router)
app.include_router(ai_router)


_store: ProjectStore | None = None
_store_lock = threading.Lock()
_job_manager = None
_job_manager_lock = threading.Lock()


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ProjectStore(
                    settings.project_store_dir,
                    bundle_retention=settings.bundle_retention,
                )
    return _store


def get_project_service() -> ProjectApplicationService:
    """Return the application facade for project-level use cases."""
    return ProjectApplicationService(get_store(), APIProjectUseCases())


def get_job_manager():
    """Return the execution manager associated with the active project store."""
    global _job_manager
    store = get_store()
    if _job_manager is None or _job_manager.store is not store:
        with _job_manager_lock:
            if _job_manager is None or _job_manager.store is not store:
                if _job_manager is not None:
                    _job_manager.shutdown(wait=False)
                from fnirs_flow.api.jobs import ExecutionJobManager

                _job_manager = ExecutionJobManager(
                    store,
                    progress_callback=app.state.progress_buffer.push,
                    max_workers=settings.job_workers,
                )
    return _job_manager


def _configured_allowed_roots() -> list[Path]:
    return list(settings.allowed_path_roots)


def _local_path_roots(project_id: str) -> list[Path]:
    """Roots from which API clients may ask the server to read local files."""
    store = get_store()
    roots = [
        store._base_dir.resolve(),  # Project bundles and exported packages.
        store._bundles.workspace_path(project_id).resolve(),
        store.get_output_dir(project_id).resolve(),
    ]
    project_data_root = store.get_project_data_root(project_id)
    if project_data_root:
        roots.append(Path(project_data_root).expanduser().resolve())
    roots.extend(path.resolve() for path in store.list_dataset_bindings().values())
    roots.extend(_configured_allowed_roots())
    return roots


def _resolve_allowed_local_file(value: str, project_id: str, *, label: str) -> Path:
    if not value or not value.strip():
        raise HTTPException(status_code=422, detail=f"{label} is required")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{label} does not exist or is not a file")
    roots = _local_path_roots(project_id)
    if not any(path.is_relative_to(root) for root in roots):
        raise HTTPException(
            status_code=403,
            detail=(
                f"{label} is outside the allowed local roots. "
                "Move it into the project workspace, bind its dataset root, "
                "or set FNIRS_ALLOWED_PATH_ROOTS."
            ),
        )
    return path


# Catch-all static routes must be registered after every API route.
app.include_router(static_router)
