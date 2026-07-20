"""FastAPI application for fnirs-flow WebUI."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import os
import string
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response, StreamingResponse

import fnirs_flow
from fnirs_flow.api.exceptions import (
    ProjectBusyError,
    ProjectLockTimeoutError,
    ProjectRevisionConflictError,
    ProjectTransactionError,
)
from fnirs_flow.api.models import (
    BackendDescription,
    CompileResult,
    DatasetRead,
    DiscoverResult,
    DryRunResult,
    ExecutionJobRead,
    ExportRequest,
    ExportResult,
    FlowUpdate,
    ParticipantTableImportRequest,
    ParticipantTableImportResult,
    ProjectCreate,
    ProjectLockInfo,
    ProjectRead,
    ProjectSnapshot,
    ProjectStatus,
    ValidationResult,
)
from fnirs_flow.api.project_bundle import ProjectBundleError
from fnirs_flow.api.projects import (
    ProjectDataNotReadyError,
    ProjectQuarantineError,
    ProjectReadOnlyError,
    ProjectStore,
    StaleCompiledPlanError,
    assert_project_editable,
    compile_project_flow,
    create_snapshot,
    discover_project_data,
    dry_run_project,
    export_project_package,
    get_project_status,
    import_project_participant_table,
    list_project_data_folders,
    load_flow_from_compiled_package,
    load_project_compile_result,
    load_project_discover_result,
    resolve_project_data_path,
    validate_project_execution,
    validate_project_flow,
)
from fnirs_flow.api.svg_sanitizer import sanitize_svg
from fnirs_flow.data.registry import DatasetRegistry
from fnirs_flow.filesystem import is_macos_metadata_path

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for startup/shutdown events."""
    # Startup
    from fnirs_flow.registry.atom_templates import refresh_method_atom_templates

    refresh_method_atom_templates()

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


# --- Request size limit middleware (10MB) ---
_MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                body_size = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"},
                )
            if body_size > _MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large (max 10MB)"},
                )
        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)


# --- API key authentication (optional, enabled via FNIRS_API_KEY env var) ---
_API_KEY = os.environ.get("FNIRS_API_KEY", "")
_PUBLIC_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}


def _is_loopback_host(host: str | None) -> bool:
    """Return True for local clients, including FastAPI's in-process test client."""
    if not host:
        return True
    normalized = host.strip().lower()
    if normalized in {"localhost", "testclient"} or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class LocalOnlyWithoutAPIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _API_KEY:
            return await call_next(request)
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)
        client_host = request.client.host if request.client else None
        if not _is_loopback_host(client_host):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Remote API access requires FNIRS_API_KEY. "
                        "Bind to localhost or set FNIRS_API_KEY before exposing the server."
                    )
                },
            )
        return await call_next(request)


app.add_middleware(LocalOnlyWithoutAPIKeyMiddleware)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not _API_KEY:
            return await call_next(request)
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)
        key = request.headers.get("x-api-key", "")
        if not hmac.compare_digest(key, _API_KEY):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)


app.add_middleware(APIKeyAuthMiddleware)


def _validate_cors_origin(origin: str) -> bool:
    """Validate a CORS origin: must be http/https localhost or 127.0.0.1."""
    if origin == "*":
        return False
    try:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        return hostname in ("localhost", "127.0.0.1", "::1") or hostname.endswith(".localhost")
    except (ValueError, AttributeError):
        return False


_raw_cors = os.environ.get(
    "FNIRS_CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://localhost:8000",
).split(",")
_cors_origins = [o.strip() for o in _raw_cors if o.strip() and _validate_cors_origin(o.strip())]
if not _cors_origins:
    _cors_origins = ["http://localhost:3000", "http://localhost:5173", "http://localhost:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


_store: ProjectStore | None = None
_store_lock = threading.Lock()
_job_manager = None
_job_manager_lock = threading.Lock()


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ProjectStore(Path("outputs/api_projects"))
    return _store


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

                _job_manager = ExecutionJobManager(store, progress_callback=push_progress)
    return _job_manager


def _configured_allowed_roots() -> list[Path]:
    roots: list[Path] = []
    raw = os.environ.get("FNIRS_ALLOWED_PATH_ROOTS", "")
    for item in raw.split(os.pathsep):
        if not item.strip():
            continue
        roots.append(Path(item).expanduser().resolve())
    return roots


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


def _api_error(
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


# --- Transaction & concurrency error handlers ---


@app.exception_handler(ProjectRevisionConflictError)
async def revision_conflict_handler(request: Request, exc: ProjectRevisionConflictError) -> JSONResponse:
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


@app.exception_handler(ProjectBusyError)
async def project_busy_handler(request: Request, exc: ProjectBusyError) -> JSONResponse:
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


@app.exception_handler(ProjectLockTimeoutError)
async def lock_timeout_handler(request: Request, exc: ProjectLockTimeoutError) -> JSONResponse:
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


@app.exception_handler(ProjectTransactionError)
async def transaction_error_handler(request: Request, exc: ProjectTransactionError) -> JSONResponse:
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


# --- Projects ---


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


@app.get("/api/local-folders")
async def list_local_folders(path: str = Query("", description="Absolute local folder path to browse")):
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
            parent_path = current_path.parent
            parent = str(parent_path) if parent_path != current_path else ""
            folders = []
            for child in sorted(current_path.iterdir(), key=lambda item: item.name.lower()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                folders.append(_folder_entry(child))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Permission denied while listing this folder") from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"current": current, "parent": parent, "folders": folders}


@app.get("/api/projects", response_model=list[ProjectRead])
async def list_projects():
    return get_store().list_all()


@app.post("/api/projects", response_model=ProjectRead)
async def create_project(data: ProjectCreate):
    return get_store().create(data.name, data.description, data_root=data.data_root)


@app.get("/api/projects/{project_id}", response_model=ProjectRead)
async def get_project(project_id: str):
    proj = get_store().get(project_id)
    if proj is None:
        raise _api_error(
            404,
            "PROJECT_NOT_FOUND",
            "Project not found",
            "project",
            recoverable=False,
            suggested_action="Select an existing project",
        )
    return proj


@app.get("/api/projects/{project_id}/status", response_model=ProjectStatus)
async def get_project_status_endpoint(project_id: str):
    result = get_project_status(get_store(), project_id)
    if result is None:
        raise _api_error(
            404,
            "PROJECT_NOT_FOUND",
            "Project not found",
            "project",
            recoverable=False,
            suggested_action="Select an existing project",
        )
    return result


# --- Flow ---


@app.get("/api/projects/{project_id}/flow")
async def get_flow(project_id: str):
    flow = get_store().get_flow(project_id)
    if flow is None:
        raise _api_error(
            404,
            "PROJECT_NOT_FOUND",
            "Project not found",
            "flow",
            recoverable=False,
            suggested_action="Select an existing project",
        )
    return flow


@app.put("/api/projects/{project_id}/flow")
async def update_flow(project_id: str, data: FlowUpdate):
    try:
        assert_project_editable(get_store(), project_id)
    except ProjectReadOnlyError as exc:
        raise _api_error(
            409,
            "PROJECT_READ_ONLY",
            str(exc),
            "flow",
            recoverable=True,
            suggested_action="Fork the imported project before editing",
        ) from exc
    try:
        updated = get_store().update_flow(project_id, data.flow, debounce=data.debounce)
    except ProjectBundleError as exc:
        raise _api_error(
            422,
            "FLOW_PATH_INVALID",
            str(exc),
            "flow",
            recoverable=True,
            suggested_action="Use a project-relative path under the project's data folder",
        ) from exc
    if not updated:
        raise _api_error(
            404,
            "PROJECT_NOT_FOUND",
            "Project not found",
            "flow",
            recoverable=False,
            suggested_action="Select an existing project",
        )
    return {"status": "updated"}


# --- Validation ---


@app.post("/api/projects/{project_id}/validate", response_model=ValidationResult)
async def validate_flow_endpoint(project_id: str):
    result = await run_in_threadpool(validate_project_flow, get_store(), project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


# --- Compile ---


@app.post("/api/projects/{project_id}/compile", response_model=CompileResult)
async def compile_flow_endpoint(
    project_id: str,
    base_revision: int | None = Query(None, description="Expected current revision for optimistic concurrency"),
):
    try:
        assert_project_editable(get_store(), project_id)
    except ProjectReadOnlyError as exc:
        raise _api_error(
            409,
            "PROJECT_READ_ONLY",
            str(exc),
            "compile",
            recoverable=True,
            suggested_action="Fork the imported project before compiling",
        ) from exc
    try:
        result = await run_in_threadpool(
            compile_project_flow,
            get_store(),
            project_id,
            base_revision=base_revision,
        )
    except (ValueError, KeyError) as exc:
        raise _api_error(
            422,
            "COMPILE_VALIDATION_FAILED",
            str(exc),
            "compile",
            recoverable=True,
            suggested_action="Fix validation errors and compile again",
        ) from exc
    except (OSError, RuntimeError) as exc:
        logger.exception("Compilation failed for project %s", project_id)
        raise _api_error(
            500,
            "COMPILE_FAILED",
            str(exc),
            "compile",
            recoverable=True,
            suggested_action="Check output permissions and server logs",
        ) from exc
    if result is None:
        code = "PROJECT_NOT_FOUND" if get_store().get(project_id) is None else "FLOW_NOT_FOUND"
        raise _api_error(
            404,
            code,
            "Project or Flow not found",
            "compile",
            recoverable=False,
            suggested_action="Create or save a Flow before compiling",
        )
    return result


@app.get("/api/projects/{project_id}/compile", response_model=CompileResult)
async def get_compile_result_endpoint(project_id: str):
    result = load_project_compile_result(get_store(), project_id)
    if result is None:
        status = 404 if get_store().get(project_id) is None else 409
        raise _api_error(
            status,
            "PROJECT_NOT_FOUND" if status == 404 else "PLAN_NOT_COMPILED",
            "Compiled plan not found",
            "compile",
            recoverable=status == 409,
            suggested_action="Compile the Flow first",
        )
    return result


# --- Dataset Discovery ---


@app.get("/api/datasets", response_model=list[DatasetRead])
async def list_datasets_endpoint():
    """List datasets available to the no-code data workspace."""
    return [
        DatasetRead(
            dataset_id=entry.dataset_id,
            name=entry.name,
            source_kind=entry.source_kind,
            url=entry.url,
            doi=entry.doi,
            citation=entry.citation,
            license=entry.license,
            description=entry.description,
            folder_name=entry.folder_name,
        )
        for entry in DatasetRegistry().all_entries()
    ]


_EXAMPLE_FLOWS = {
    "blank_template": {
        "label": "Blank Template",
        "flow": {
            "schema_version": "0.3.0",
            "flow_id": "blank-template",
            "name": "Blank Template",
            "description": "Start with an empty flow canvas.",
            "nodes": [],
            "flow_atoms": [],
            "edges": [],
            "adapter_registry": [],
            "metadata": {
                "tags": [],
                "order_policy": {
                    "allow_order_violations": False,
                    "allow_empty_edges": False,
                },
                "checklist": {},
            },
        },
    },
    "demo_task_glm_real": {
        "label": "Demo Task GLM Real Data",
        "path": Path("configs/demo_task_glm_real.json"),
    },
    "demo_task_flow": {
        "label": "Demo Task GLM",
        "path": Path("configs/demo_task_flow.json"),
    },
    "demo_resting_state_flow": {
        "label": "Demo Resting State",
        "path": Path("configs/demo_resting_state_flow.json"),
    },
}


@app.get("/api/example-flows")
async def list_example_flows_endpoint():
    return [
        {"id": example_id, "label": spec["label"]}
        for example_id, spec in _EXAMPLE_FLOWS.items()
    ]


@app.get("/api/example-flows/{example_id}")
async def get_example_flow_endpoint(example_id: str):
    spec = _EXAMPLE_FLOWS.get(example_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Example flow not found")
    if "flow" in spec:
        return spec["flow"]
    path = Path(__file__).resolve().parents[2] / spec["path"]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Example flow could not be loaded") from exc


@app.post("/api/projects/{project_id}/discover-data", response_model=DiscoverResult)
async def discover_data_endpoint(
    project_id: str,
    dataset_id: str,
    data_root: str | None = Query(None, description="Optional local dataset root for local BIDS-NIRS datasets"),
    data_path: str | None = Query(None, description="Project-relative dataset folder under the project data root"),
    base_revision: int | None = Query(None, description="Expected current revision for optimistic concurrency"),
):
    if get_store().get(project_id) is None:
        raise _api_error(
            404,
            "PROJECT_NOT_FOUND",
            "Project not found",
            "discovery",
            recoverable=False,
            suggested_action="Select an existing project",
        )
    try:
        result = await run_in_threadpool(
            discover_project_data,
            get_store(),
            project_id,
            dataset_id,
            data_root=data_root,
            data_path=data_path,
            base_revision=base_revision,
        )
    except ValueError as exc:
        raise _api_error(
            404,
            "DATASET_NOT_FOUND",
            str(exc),
            "discovery",
            recoverable=True,
            suggested_action="Choose a registered dataset ID",
        ) from exc
    except (OSError, KeyError, RuntimeError) as exc:
        logger.exception("Dataset discovery failed for project %s", project_id)
        raise _api_error(
            500,
            "DATA_DISCOVERY_FAILED",
            str(exc),
            "discovery",
            recoverable=True,
            suggested_action="Check data access and server logs",
        ) from exc
    return result


@app.get("/api/projects/{project_id}/data-folders")
async def list_project_data_folders_endpoint(
    project_id: str,
    parent: str = Query("", description="Project-relative parent folder"),
):
    if get_store().get(project_id) is None:
        raise _api_error(
            404,
            "PROJECT_NOT_FOUND",
            "Project not found",
            "data",
            recoverable=False,
            suggested_action="Select an existing project",
        )
    try:
        result = await run_in_threadpool(list_project_data_folders, get_store(), project_id, parent)
    except (OSError, ValueError) as exc:
        raise _api_error(
            422,
            "PROJECT_DATA_FOLDER_INVALID",
            str(exc),
            "data",
            recoverable=True,
            suggested_action="Choose a folder under the project's data directory",
        ) from exc
    return result


@app.get("/api/projects/{project_id}/discover-data", response_model=DiscoverResult)
async def get_discover_data_endpoint(project_id: str):
    result = load_project_discover_result(get_store(), project_id)
    if result is None:
        status = 404 if get_store().get(project_id) is None else 409
        raise _api_error(
            status,
            "PROJECT_NOT_FOUND" if status == 404 else "DATA_NOT_DISCOVERED",
            "Dataset discovery result not found",
            "discovery",
            recoverable=status == 409,
            suggested_action="Discover a dataset first",
        )
    return result


@app.post("/api/projects/{project_id}/participant-table", response_model=ParticipantTableImportResult)
async def import_participant_table_endpoint(project_id: str, data: ParticipantTableImportRequest):
    if get_store().get(project_id) is None:
        raise _api_error(
            404,
            "PROJECT_NOT_FOUND",
            "Project not found",
            "participant_metadata",
            recoverable=False,
            suggested_action="Select an existing project",
        )
    try:
        table_path, _relative_path = resolve_project_data_path(
            get_store(),
            project_id,
            data.path,
            label="Participant table path",
            must_be_file=True,
        )
        result = import_project_participant_table(
            get_store(),
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
        raise _api_error(
            422,
            "PARTICIPANT_TABLE_INVALID",
            str(exc),
            "participant_metadata",
            recoverable=True,
            suggested_action="Check the table path, delimiter, encoding, and participant id column",
        ) from exc
    if result is None:
        raise _api_error(
            404,
            "PROJECT_NOT_FOUND",
            "Project not found",
            "participant_metadata",
            recoverable=False,
            suggested_action="Select an existing project",
        )
    return result


# --- Dry Run ---


@app.post("/api/projects/{project_id}/dry-run", response_model=DryRunResult)
async def dry_run_endpoint(project_id: str):
    try:
        result = await run_in_threadpool(dry_run_project, get_store(), project_id)
    except StaleCompiledPlanError as exc:
        raise _api_error(
            409,
            "STALE_COMPILED_PLAN",
            str(exc),
            "dry_run",
            recoverable=True,
            suggested_action="Compile the current Flow again",
        ) from exc
    except (OSError, KeyError, ValueError) as exc:
        raise _api_error(
            422,
            "DRY_RUN_FAILED",
            str(exc),
            "dry_run",
            recoverable=True,
            suggested_action="Check the compiled plan and data manifest",
        ) from exc
    if result is None:
        status = 404 if get_store().get(project_id) is None else 409
        code = "PROJECT_NOT_FOUND" if status == 404 else "PLAN_NOT_COMPILED"
        raise _api_error(
            status,
            code,
            "Compiled plan not found",
            "dry_run",
            recoverable=status == 409,
            suggested_action="Compile the Flow first",
        )
    return result


# --- Execute ---


@app.post(
    "/api/projects/{project_id}/execute",
    response_model=ExecutionJobRead,
    status_code=202,
)
async def execute_endpoint(project_id: str):
    try:
        ready = validate_project_execution(get_store(), project_id)
    except StaleCompiledPlanError as exc:
        raise _api_error(
            409,
            "STALE_COMPILED_PLAN",
            str(exc),
            "execute",
            recoverable=True,
            suggested_action="Compile the current Flow again",
        ) from exc
    except ProjectQuarantineError as exc:
        raise _api_error(
            409,
            "QUARANTINED_ATOMS",
            str(exc),
            "execute",
            recoverable=True,
            suggested_action="Review and explicitly trust quarantined atoms",
        ) from exc
    except ProjectDataNotReadyError as exc:
        raise _api_error(
            409,
            "DATA_NOT_READY",
            str(exc),
            "execute",
            recoverable=True,
            suggested_action="Discover or relink at least one existing data run",
        ) from exc
    except ImportError as exc:
        raise _api_error(
            503,
            "BACKEND_UNAVAILABLE",
            str(exc),
            "execute",
            recoverable=True,
            suggested_action="Install or repair the required backend",
        ) from exc
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        logger.exception("Execution request failed for project %s", project_id)
        raise _api_error(
            500,
            "EXECUTION_FAILED",
            str(exc),
            "execute",
            recoverable=True,
            suggested_action="Inspect execution logs and retry",
        ) from exc
    if not ready:
        status = 404 if get_store().get(project_id) is None else 409
        code = "PROJECT_NOT_FOUND" if status == 404 else "PLAN_NOT_COMPILED"
        raise _api_error(
            status,
            code,
            "Project or compiled plan not found",
            "execute",
            recoverable=status == 409,
            suggested_action="Compile the Flow and discover data first",
        )
    return get_job_manager().create(project_id)


@app.get("/api/projects/{project_id}/attempts", response_model=list[ExecutionJobRead])
async def list_execution_attempts(project_id: str):
    if get_store().get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return get_job_manager().list(project_id)


@app.get("/api/projects/{project_id}/attempts/{attempt_id}", response_model=ExecutionJobRead)
async def get_execution_attempt(project_id: str, attempt_id: str):
    job = get_job_manager().get(project_id, attempt_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Execution attempt not found")
    return job


@app.post("/api/projects/{project_id}/attempts/{attempt_id}/cancel", response_model=ExecutionJobRead)
async def cancel_execution_attempt(project_id: str, attempt_id: str):
    job = get_job_manager().cancel(project_id, attempt_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Execution attempt not found")
    return job


# --- Snapshots ---


@app.post("/api/projects/{project_id}/snapshots", response_model=ProjectSnapshot)
async def create_snapshot_endpoint(project_id: str):
    result = create_snapshot(get_store(), project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    return result


@app.get("/api/projects/{project_id}/bundle")
async def project_bundle_status_endpoint(project_id: str):
    """Return the verified editable bundle and its retained revisions."""
    from fnirs_flow.api.project_bundle import ProjectBundleError

    try:
        result = get_store().get_bundle_status(project_id)
    except ProjectBundleError as exc:
        raise _api_error(
            409,
            "PROJECT_BUNDLE_CORRUPT",
            str(exc),
            "project_open",
            recoverable=True,
            suggested_action="Restore a retained revision or reopen the last valid project bundle",
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


# --- Design History (FlowVCS) ---


@app.post("/api/projects/{project_id}/history/initialize")
async def initialize_design_history_endpoint(project_id: str):
    """Initialize design history for a project."""
    try:
        commit_id = get_store().initialize_design_history(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"commit_id": commit_id}


@app.get("/api/projects/{project_id}/history")
async def get_design_history_endpoint(project_id: str):
    """Get design history status (HEAD, branches, dirty)."""
    store = get_store()
    head = store.get_design_head(project_id)
    if head is None:
        return {
            "head": None,
            "branches": [],
            "dirty": False,
        }
    branches = store.list_design_branches(project_id)
    dirty = store.is_design_dirty(project_id)
    return {
        "head": head,
        "branches": branches,
        "dirty": dirty,
    }


@app.get("/api/projects/{project_id}/history/commits")
async def list_design_commits_endpoint(
    project_id: str,
    branch: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List design commits."""
    return get_store().list_design_commits(project_id, branch, limit=limit, offset=offset)


@app.get("/api/projects/{project_id}/history/commits/{commit_id}")
async def get_design_commit_endpoint(project_id: str, commit_id: str):
    """Get a specific design commit."""
    from fnirs_flow.history.errors import CommitNotFound

    try:
        svc = get_store()._history_service(project_id)
        commit = svc.get_commit(commit_id)
        return commit.model_dump()
    except CommitNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/projects/{project_id}/history/commits")
async def create_design_commit_endpoint(project_id: str, body: dict[str, Any]):
    """Create a new design commit."""
    message = body.get("message", "")
    reason = body.get("reason", "manual_design_commit")
    try:
        commit_id = get_store().commit_design(project_id, message, reason=reason)
        return {"commit_id": commit_id}
    except Exception as exc:
        from fnirs_flow.history.errors import NoChanges

        if isinstance(exc, NoChanges):
            raise _api_error(
                409,
                "NO_CHANGES",
                str(exc),
                "design_commit",
                recoverable=True,
                suggested_action="Modify the flow before committing",
            ) from exc
        raise


@app.get("/api/projects/{project_id}/history/diff")
async def design_diff_endpoint(
    project_id: str,
    from_commit: str = "",
    to_commit: str = "",
):
    """Get structured diff between two design commits."""
    if not from_commit or not to_commit:
        raise HTTPException(status_code=422, detail="Both from_commit and to_commit are required")
    try:
        return get_store().get_design_diff(project_id, from_commit, to_commit)
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/projects/{project_id}/history/branches")
async def create_design_branch_endpoint(project_id: str, body: dict[str, Any]):
    """Create a new design branch."""
    name = body.get("name", "")
    from_commit = body.get("from_commit_id")
    try:
        branch = get_store().create_design_branch(project_id, name, from_commit)
        return branch
    except Exception as exc:
        from fnirs_flow.history.errors import BranchAlreadyExists, BranchNameInvalid

        if isinstance(exc, BranchNameInvalid):
            raise _api_error(
                422,
                "BRANCH_NAME_INVALID",
                str(exc),
                "branch_create",
                recoverable=True,
                suggested_action="Use a valid branch name",
            ) from exc
        if isinstance(exc, BranchAlreadyExists):
            raise _api_error(
                409,
                "BRANCH_ALREADY_EXISTS",
                str(exc),
                "branch_create",
                recoverable=True,
                suggested_action="Use a different branch name",
            ) from exc
        raise


@app.delete("/api/projects/{project_id}/history/branches/{name}")
async def delete_design_branch_endpoint(project_id: str, name: str):
    """Delete a design branch."""
    try:
        get_store().delete_design_branch(project_id, name)
        return {"status": "deleted"}
    except Exception as exc:
        from fnirs_flow.history.errors import BranchNotFound

        if isinstance(exc, BranchNotFound):
            raise HTTPException(status_code=404, detail=str(exc))
        raise


@app.post("/api/projects/{project_id}/history/checkout")
async def checkout_design_branch_endpoint(project_id: str, body: dict[str, Any]):
    """Switch to a design branch or commit."""
    target = body.get("target", "")
    try:
        flow = get_store().switch_design_branch(project_id, target)
        return {"flow": flow, "target": target}
    except Exception as exc:
        from fnirs_flow.history.errors import BranchNotFound

        if isinstance(exc, BranchNotFound):
            raise HTTPException(status_code=404, detail=str(exc))
        raise


@app.post("/api/projects/{project_id}/history/migrate")
async def migrate_design_history_endpoint(project_id: str):
    """Migrate legacy snapshots into design history."""
    try:
        report = get_store().migrate_snapshots_to_history(project_id)
        return report
    except Exception as exc:
        raise _api_error(
            500,
            "MIGRATION_FAILED",
            str(exc),
            "history_migration",
            recoverable=True,
            suggested_action="Check project snapshots and retry",
        ) from exc


# --- AI Draft Flow Generation ---


def _sanitize_ai_settings(body: dict[str, Any]) -> dict[str, Any]:
    settings = body.get("ai_settings")
    if not isinstance(settings, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key in ("provider", "base_url", "model", "organization", "project"):
        value = str(settings.get(key, "")).strip()
        if value:
            sanitized[key] = value
    for key in ("temperature", "max_tokens", "timeout_seconds"):
        value = settings.get(key)
        if isinstance(value, int | float):
            sanitized[key] = value
    sanitized["api_key_present"] = bool(settings.get("api_key_present")) or bool(
        str(settings.get("api_key", "")).strip()
    )
    sanitized["mode"] = str(settings.get("mode", "template")).strip() or "template"
    return sanitized


def _draft_generation_inputs(body: dict[str, Any], ai_settings: dict[str, Any]) -> dict[str, Any]:
    assumptions = list(body.get("assumptions") or [])
    user_confirmations = list(body.get("user_confirmations") or [])
    model_name = str(ai_settings.get("model") or body.get("model", "api_template"))
    external_flow: dict[str, Any] | None = None

    if ai_settings.get("mode") == "openai-compatible":
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("FNIRS_FLOW_ALLOW_EXTERNAL_AI_IN_TESTS"):
            ai_settings["provider_status"] = "disabled_in_tests"
            return {
                "assumptions": assumptions,
                "user_confirmations": user_confirmations,
                "model_name": model_name,
                "ai_settings": ai_settings,
                "external_flow": external_flow,
            }

        from fnirs_flow.ai.openai_compatible import (
            AIProviderError,
            AIProviderNotConfigured,
            generate_openai_compatible_flow,
        )

        try:
            generated = generate_openai_compatible_flow(
                scenario=str(body.get("scenario", "task")),
                study_name=str(body.get("study_name", "")),
                data_format=str(body.get("data_format", "snirf")),
                conditions=[str(item) for item in body.get("conditions") or []],
                settings=ai_settings,
            )
        except AIProviderNotConfigured:
            ai_settings["provider_status"] = "not_configured"
        except AIProviderError as exc:
            raise _api_error(
                502,
                "AI_PROVIDER_REQUEST_FAILED",
                str(exc),
                "ai_draft",
                recoverable=True,
                suggested_action=(
                    "Check OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_API_KEY, "
                    "and provider chat/completions support."
                ),
            ) from exc
        else:
            external_flow = generated.get("flow") if isinstance(generated.get("flow"), dict) else None
            ai_settings.update(generated.get("settings") or {})
            if generated.get("usage"):
                ai_settings["usage"] = generated["usage"]
            model_name = str(ai_settings.get("model") or model_name)

    return {
        "assumptions": assumptions,
        "user_confirmations": user_confirmations,
        "model_name": model_name,
        "ai_settings": ai_settings,
        "external_flow": external_flow,
    }


@app.post("/api/ai/draft-flow")
async def generate_ai_draft_endpoint(body: dict[str, Any]):
    """Generate a candidate flow from a scenario template."""
    from fnirs_flow.ai.draft_generator import generate_draft_flow

    scenario = body.get("scenario", "task")
    ai_settings = _sanitize_ai_settings(body)
    draft_inputs = _draft_generation_inputs(body, ai_settings)
    if draft_inputs["external_flow"] is not None:
        return draft_inputs["external_flow"]
    try:
        flow = generate_draft_flow(
            scenario,
            study_name=body.get("study_name", ""),
            data_format=body.get("data_format", "snirf"),
            conditions=body.get("conditions"),
            model_name=draft_inputs["model_name"],
            assumptions=draft_inputs["assumptions"],
            user_confirmations=draft_inputs["user_confirmations"],
        )
        if draft_inputs["ai_settings"]:
            flow.setdefault("metadata", {}).setdefault("ai_generation", {})["settings"] = draft_inputs["ai_settings"]
        return flow
    except ValueError as exc:
        raise _api_error(
            422,
            "INVALID_SCENARIO",
            str(exc),
            "ai_draft",
            recoverable=True,
            suggested_action="Use task or resting_state, or add the missing MethodAtom templates and input bindings.",
        ) from exc


@app.post("/api/projects/{project_id}/ai/draft-flow")
async def generate_ai_draft_for_project_endpoint(project_id: str, body: dict[str, Any]):
    """Generate a candidate flow and save it as a pending draft.

    The draft does NOT overwrite the current project flow.
    Use POST /api/projects/{id}/ai/confirm-draft to accept it,
    or DELETE /api/projects/{id}/ai/draft to discard it.
    """
    from fnirs_flow.ai.draft_generator import generate_draft_flow

    scenario = body.get("scenario", "task")
    ai_settings = _sanitize_ai_settings(body)
    draft_inputs = _draft_generation_inputs(body, ai_settings)
    if draft_inputs["external_flow"] is not None:
        flow = draft_inputs["external_flow"]
        flow.setdefault("metadata", {}).setdefault("ai_generation", {})["settings"] = draft_inputs["ai_settings"]
    else:
        try:
            flow = generate_draft_flow(
                scenario,
                study_name=body.get("study_name", ""),
                data_format=body.get("data_format", "snirf"),
                conditions=body.get("conditions"),
                model_name=draft_inputs["model_name"],
                assumptions=draft_inputs["assumptions"],
                user_confirmations=draft_inputs["user_confirmations"],
            )
            if draft_inputs["ai_settings"]:
                flow.setdefault("metadata", {}).setdefault("ai_generation", {})["settings"] = draft_inputs[
                    "ai_settings"
                ]
        except ValueError as exc:
            raise _api_error(
                422,
                "INVALID_SCENARIO",
                str(exc),
                "ai_draft",
                recoverable=True,
                suggested_action=(
                    "Use task or resting_state, or add the missing MethodAtom templates and input bindings."
                ),
            ) from exc

    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    store.save_draft(project_id, flow)
    if draft_inputs["external_flow"] is not None:
        store.update_flow(project_id, flow)
    return {
        "status": "draft_pending",
        "flow_id": flow.get("flow_id"),
        "ai_generation": flow.get("metadata", {}).get("ai_generation"),
        "imported_to_flow": draft_inputs["external_flow"] is not None,
        "message": (
            "Draft saved. Confirm with POST /api/projects/{id}/ai/confirm-draft"
            " or discard with DELETE /api/projects/{id}/ai/draft"
        ),
    }


@app.get("/api/projects/{project_id}/ai/draft")
async def get_ai_draft_endpoint(project_id: str):
    """Get the pending AI draft for a project, if any."""
    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    draft = store.get_draft(project_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No pending draft")
    return {"status": "draft_exists", "draft": draft}


@app.post("/api/projects/{project_id}/ai/validate-draft")
async def validate_ai_draft_endpoint(project_id: str):
    """Validate the pending AI draft without confirming it.

    Returns validation errors, risks, warnings, and readiness assessment.
    Does not modify the draft or project flow.
    """
    from fnirs_flow.validation.api import validate_flow

    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    draft = store.get_draft(project_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No pending draft to validate")

    report = validate_flow(draft)
    return {
        "status": "draft_validated",
        "flow_id": draft.get("flow_id"),
        "valid": len(report.errors) == 0,
        "errors": report.errors,
        "warnings": report.warnings,
        "risks": [
            {
                "risk_id": r.risk_id,
                "code": r.code,
                "severity": r.severity,
                "domain": r.domain,
                "message": r.message,
                "suggested_action": r.suggested_action,
            }
            for r in report.risks
        ],
        "readiness": report.readiness,
    }


@app.post("/api/projects/{project_id}/ai/confirm-draft")
async def confirm_ai_draft_endpoint(project_id: str, body: dict[str, Any] | None = None):
    """Accept the pending AI draft as the current project flow.

    Review-aware clients may submit the exact confirmation strings plus a
    human reviewer. Calls without a body retain the original API behavior.
    """
    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    draft = store.get_draft(project_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No pending draft to confirm")

    if body:
        ai_generation = draft.get("metadata", {}).get("ai_generation", {})
        required = [str(item) for item in ai_generation.get("requires_user_confirmation", [])]
        reviewed_parameters = list(dict.fromkeys(str(item) for item in body.get("confirmed_parameters", [])))
        confirmed_by = str(body.get("confirmed_by", "")).strip()
        missing = [item for item in required if item not in set(reviewed_parameters)]
        if missing or (required and not confirmed_by):
            detail = "All AI confirmation items and a human reviewer are required"
            if missing:
                detail += f"; missing: {'; '.join(missing)}"
            raise _api_error(
                422,
                "AI_CONFIRMATIONS_INCOMPLETE",
                detail,
                "ai_draft_review",
                recoverable=True,
                suggested_action="Review every listed item and identify the human reviewer",
            )
        ai_generation["confirmed_parameters"] = reviewed_parameters
        ai_generation["confirmed_by"] = confirmed_by
        ai_generation["confirmed_at"] = datetime.now(timezone.utc).isoformat()
        ai_generation["not_used_for_execution"] = False

    confirmed = store.confirm_draft(project_id)
    if confirmed is None:
        raise HTTPException(status_code=404, detail="No pending draft to confirm")
    ai_generation = confirmed.get("metadata", {}).get("ai_generation", {})
    return {
        "status": "draft_confirmed",
        "flow_id": confirmed.get("flow_id"),
        "confirmed_by": ai_generation.get("confirmed_by", ""),
        "confirmed_count": len(ai_generation.get("confirmed_parameters", [])),
    }


@app.delete("/api/projects/{project_id}/ai/draft")
async def discard_ai_draft_endpoint(project_id: str):
    """Discard the pending AI draft without applying it."""
    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    discarded = store.discard_draft(project_id)
    if not discarded:
        raise HTTPException(status_code=404, detail="No pending draft to discard")
    return {"status": "draft_discarded"}


@app.post("/api/projects/{project_id}/bundle/restore/{revision}", response_model=ProjectRead)
async def restore_project_bundle_endpoint(project_id: str, revision: int):
    """Restore a retained full-project version as a new revision."""
    from fnirs_flow.api.project_bundle import ProjectBundleError

    try:
        result = get_store().restore_bundle_revision(project_id, revision)
    except ProjectBundleError as exc:
        raise _api_error(
            404,
            "PROJECT_REVISION_NOT_FOUND",
            str(exc),
            "project_restore",
            recoverable=True,
            suggested_action="Choose a revision listed by the project bundle status endpoint",
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@app.get("/api/projects/{project_id}/version-history")
async def get_version_history_endpoint(project_id: str):
    """Return the version history for a project."""
    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    history = store.get_version_history(project_id)
    return history


@app.get("/api/projects/{project_id}/lock", response_model=ProjectLockInfo)
async def get_project_lock_status(project_id: str):
    """Return the current lock status for a project."""
    if get_store().get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    info = get_store().get_lock_info(project_id)
    return ProjectLockInfo(**info)


# --- Export Package ---


@app.post("/api/projects/{project_id}/export-package", response_model=ExportResult)
async def export_package_endpoint(project_id: str, data: ExportRequest | None = None):
    request = data or ExportRequest()
    try:
        result = await run_in_threadpool(
            export_project_package,
            get_store(),
            project_id,
            profile_id=request.profile,
        )
    except StaleCompiledPlanError as exc:
        raise _api_error(
            409,
            "STALE_COMPILED_PLAN",
            str(exc),
            "export",
            recoverable=True,
            suggested_action="Compile the current Flow again",
        ) from exc
    except ValueError as exc:
        raise _api_error(
            422,
            "EXPORT_PROFILE_INVALID",
            str(exc),
            "export",
            recoverable=True,
            suggested_action="Choose a supported package profile",
        ) from exc
    except (OSError, RuntimeError) as exc:
        logger.exception("Package export failed for project %s", project_id)
        raise _api_error(
            500,
            "EXPORT_FAILED",
            str(exc),
            "export",
            recoverable=True,
            suggested_action="Check output permissions and server logs",
        ) from exc
    if result is None:
        status = 404 if get_store().get(project_id) is None else 409
        code = "PROJECT_NOT_FOUND" if status == 404 else "PLAN_NOT_COMPILED"
        raise _api_error(
            status,
            code,
            "Project or compiled plan not found",
            "export",
            recoverable=status == 409,
            suggested_action="Compile the Flow first",
        )
    return result


@app.get("/api/package-profiles")
async def list_package_profiles_endpoint():
    from fnirs_flow.exporters.package_exporter import list_package_profiles

    return [profile.model_dump() for profile in list_package_profiles()]


# --- Package Import/Fork/Trust ---


@app.post("/api/projects/{project_id}/import-package")
async def import_package_endpoint(project_id: str, package_path: str, data_root: str | None = None):
    """Import a .fnirsflow.zip package into a project."""
    from fnirs_flow.exporters.package_importer import import_package as do_import

    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_package_path = _resolve_allowed_local_file(package_path, project_id, label="Package path")
    outdir = store.get_output_dir(project_id)
    try:
        result = do_import(
            resolved_package_path,
            str(outdir),
            relink_data=data_root is not None,
            data_root=data_root,
            project_layout=True,
            persist_binding=False,
        )
        imported_flow = load_flow_from_compiled_package(outdir / "compiled")
        if data_root is not None:
            manifest_path = outdir / "compiled" / "data_manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                dataset_id = str(manifest.get("dataset_id", ""))
                if dataset_id:
                    store.bind_dataset(dataset_id, Path(data_root).expanduser().resolve())
        store.update_flow(project_id, imported_flow)
        return result
    except (ValueError, KeyError) as e:
        logger.warning("Import validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        logger.error("Import IO error: %s", e)
        raise HTTPException(status_code=500, detail="File system error during import") from e
    except Exception as e:
        logger.exception("Unexpected error during import")
        raise HTTPException(status_code=500, detail="Import failed due to an internal error") from e


@app.post("/api/projects/{project_id}/fork")
async def fork_project_endpoint(project_id: str, fork_name: str = ""):
    """Fork an imported project to a new editable copy."""
    from fnirs_flow.exporters.package_importer import fork_package

    store = get_store()
    source_dir = store.get_output_dir(project_id)
    try:
        proj = store.create(fork_name or f"{project_id}_fork", f"Forked from {project_id}")
        fork_dir = store.get_output_dir(proj.id)
        result = fork_package(str(source_dir), str(fork_dir), unfork=True)
        flow = load_flow_from_compiled_package(fork_dir / "compiled")
        store.update_flow(proj.id, flow)
        return {"fork_project_id": proj.id, **result}
    except (ValueError, KeyError) as e:
        logger.warning("Fork validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        logger.error("Fork IO error: %s", e)
        raise HTTPException(status_code=500, detail="File system error during fork") from e
    except Exception as e:
        logger.exception("Unexpected error during fork")
        raise HTTPException(status_code=500, detail="Fork failed due to an internal error") from e


@app.post("/api/projects/{project_id}/trust-atom/{atom_id}")
async def trust_atom_endpoint(project_id: str, atom_id: str):
    """Trust a quarantined atom."""
    from fnirs_flow.api.transaction import ProjectTransaction
    from fnirs_flow.exporters.package_importer import trust_atom

    store = get_store()
    with ProjectTransaction(store, project_id, reason="atom_trust_updated") as tx:
        outdir = tx.output_dir
        result = trust_atom(str(outdir), atom_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        tx.commit()
    return result


@app.get("/api/projects/{project_id}/import-status")
async def import_status_endpoint(project_id: str):
    """Check if a project was imported and its restrictions."""
    store = get_store()
    outdir = store.get_output_dir(project_id)
    metadata_path = outdir / "import_metadata.json"
    if not metadata_path.exists():
        return {"imported": False, "read_only": False, "quarantined_atoms": []}
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    dataset_id = str(metadata.get("dataset_id") or "")
    bound_root = store.get_dataset_binding(dataset_id) if dataset_id else None
    return {
        "imported": True,
        "read_only": metadata.get("read_only", False),
        "quarantined_atoms": metadata.get("quarantined_atoms", []),
        "relinked": metadata.get("relinked", False),
        "data_root": str(bound_root) if bound_root else "",
        "dataset_id": dataset_id,
    }


@app.post("/api/projects/{project_id}/relink-data")
async def relink_project_data_endpoint(project_id: str, data_root: str):
    """Relink an imported package's data manifest to a local directory."""
    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    root = Path(data_root).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=422, detail="Data root does not exist or is not a directory")
    outdir = store.get_output_dir(project_id)
    from fnirs_flow.exporters.package_importer import relink_package_data

    try:
        relink_result = relink_package_data(outdir, root, persist_binding=False)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Imported package has no data_manifest.json") from exc
    manifest_path = Path(relink_result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_id = str(manifest.get("dataset_id") or "dataset")
    store.bind_dataset(dataset_id, root)
    store.update_state(
        project_id,
        relinked_dataset_id=dataset_id,
        relinked_data_uri=f"external-data://{dataset_id}/",
    )
    return {
        "status": "relinked",
        "data_root": str(root),
        "dataset_id": dataset_id,
        "data_uri": f"external-data://{dataset_id}/",
    }


@app.post("/api/projects/{project_id}/bind-dataset")
async def bind_project_dataset_endpoint(project_id: str, dataset_id: str, data_root: str):
    """Bind a registered dataset ID to a local directory for later discovery/execution."""
    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    root = Path(data_root).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=422, detail="Data root does not exist or is not a directory")
    if DatasetRegistry().get(dataset_id) is None:
        raise HTTPException(status_code=404, detail="Unknown dataset")
    store.bind_dataset(dataset_id, root)
    return {
        "status": "bound",
        "dataset_id": dataset_id,
        "data_root": str(root),
        "data_uri": f"external-data://{dataset_id}/",
    }


@app.get("/api/projects/{project_id}/results/{kind}")
async def project_results_endpoint(project_id: str, kind: str):
    """Read bounded, generated result JSON for the Results Workspace."""
    if kind not in {"qc", "channel", "roi", "group"}:
        raise HTTPException(status_code=404, detail="Unknown result type")
    store = get_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    outdir = store.get_output_dir(project_id)
    paths: list[Path] = []
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
    files = []
    seen: set[str] = set()
    for path in sorted(paths):
        relative = path.relative_to(outdir).as_posix()
        if is_macos_metadata_path(relative):
            continue
        logical_name = relative.removeprefix("compiled/")
        if logical_name in seen:
            continue
        seen.add(logical_name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        files.append({"path": logical_name, "data": data})
    figures = []
    seen_figures: set[str] = set()
    for path in sorted(figure_paths):
        relative = path.relative_to(outdir).as_posix()
        if is_macos_metadata_path(relative):
            continue
        logical_name = relative.removeprefix("compiled/")
        if logical_name in seen_figures:
            continue
        seen_figures.add(logical_name)
        try:
            svg = sanitize_svg(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        figures.append({"path": logical_name, "svg": svg})
    return {"kind": kind, "file_count": len(files), "files": files, "figures": figures}


# --- Dependency Management (§9.1) ---


@app.get("/api/backends", response_model=list[BackendDescription])
async def list_backends():
    """List all registered backends without importing them.

    §9.1: /api/backends uses registry.describe(), must not instantiate backends
    """
    from fnirs_flow.adapters.backend_registry import get_registry

    registry = get_registry()
    backends = []
    for backend_id in registry.list_all():
        desc = registry.describe(backend_id)
        if desc:
            backends.append(desc)
    return backends


@app.post("/api/dependencies/resolve")
async def resolve_dependencies_endpoint(project_id: str):
    """Resolve dependencies for a project's compiled flow.

    §9.1: resolve 永远是只读操作
    """
    from fnirs_flow.api.transaction import ProjectTransaction

    store = get_store()

    with ProjectTransaction(store, project_id, reason="dependency_plan_resolved") as tx:
        outdir = tx.output_dir
        compiled_dir = outdir / "compiled"

        if not compiled_dir.exists():
            raise HTTPException(status_code=404, detail="Project not compiled yet")

        dag_path = compiled_dir / "execution_dag.json"
        if not dag_path.exists():
            raise HTTPException(status_code=404, detail="execution_dag.json not found")

        dag = json.loads(dag_path.read_text(encoding="utf-8"))

        from fnirs_flow.dependencies.resolver import resolve_dependencies

        plan = resolve_dependencies(dag, flow_id=project_id)

        # Save plan
        plan_path = compiled_dir / "dependency_plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        tx.commit()

    return plan.model_dump()


@app.get("/api/dependencies/plans/{plan_id}")
async def get_dependency_plan(plan_id: str):
    """Get a dependency plan by ID."""
    # Search for plan in all projects
    store = get_store()
    for proj in store.list_all():
        compiled_dir = store.get_output_dir(proj.id) / "compiled"
        plan_path = compiled_dir / "dependency_plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan.get("plan_id") == plan_id:
                return plan

    raise HTTPException(status_code=404, detail="Plan not found")


async def _record_dependency_plan_approval(plan_id: str):
    """Record human approval for a dependency plan without starting installation.

    §9.1: approval records are separated from any future network install action.
    """
    from fnirs_flow.api.transaction import ProjectTransaction

    # Find the plan
    store = get_store()
    plan_data = None
    owner_project_id = None

    for proj in store.list_all():
        cd = store.get_output_dir(proj.id) / "compiled"
        plan_path = cd / "dependency_plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan.get("plan_id") == plan_id:
                plan_data = plan
                owner_project_id = proj.id
                break

    if plan_data is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    from fnirs_flow.dependencies.models import DependencyPlan, InstallPolicy
    from fnirs_flow.dependencies.policies import get_policy_manager

    plan = DependencyPlan.model_validate(plan_data)

    # Approve the plan
    policy_manager = get_policy_manager()
    policy_manager.approve_plan(plan.plan_fingerprint)

    # Create approval record
    from datetime import datetime, timezone

    from fnirs_flow.dependencies.models import ApprovalRecord

    approval = ApprovalRecord(
        plan_id=plan.plan_id,
        plan_fingerprint=plan.plan_fingerprint,
        decision=InstallPolicy.APPROVED_ONCE,
        approved_at=datetime.now(timezone.utc).isoformat(),
    )

    # Save approval in transaction
    if owner_project_id:
        with ProjectTransaction(store, owner_project_id, reason="dependency_plan_approved") as tx:
            approval_path = tx.output_dir / "compiled" / "approval_record.json"
            approval_path.write_text(approval.model_dump_json(indent=2), encoding="utf-8")
            tx.commit()

    return {
        "status": "approval_recorded",
        "plan_id": plan_id,
        "fingerprint": plan.plan_fingerprint,
        "installation_started": False,
        "message": "Approval was recorded; no download or installation was started.",
    }


@app.post("/api/dependencies/plans/{plan_id}/record-approval")
async def record_dependency_plan_approval(plan_id: str):
    return await _record_dependency_plan_approval(plan_id)


@app.post("/api/dependencies/plans/{plan_id}/approve")
async def approve_dependency_plan(plan_id: str):
    return await _record_dependency_plan_approval(plan_id)


@app.post("/api/dependencies/plans/{plan_id}/reject")
async def reject_dependency_plan(plan_id: str):
    """Reject a dependency plan."""
    from fnirs_flow.dependencies.models import DependencyPlan
    from fnirs_flow.dependencies.policies import get_policy_manager

    store = get_store()
    for proj in store.list_all():
        compiled_dir = store.get_output_dir(proj.id) / "compiled"
        plan_path = compiled_dir / "dependency_plan.json"
        if plan_path.exists():
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan_data.get("plan_id") == plan_id:
                plan = DependencyPlan.model_validate(plan_data)
                policy_manager = get_policy_manager()
                policy_manager.reject_plan(plan.plan_fingerprint)
                return {"status": "rejected", "plan_id": plan_id}

    raise HTTPException(status_code=404, detail="Plan not found")


@app.get("/api/dependencies/installations/{task_id}")
async def get_installation_status(task_id: str):
    """Get installation task status."""
    from fnirs_flow.dependencies.installer import get_installation_orchestrator

    orchestrator = get_installation_orchestrator()
    # Search for task in orchestrator
    for task in orchestrator.list_tasks():
        if task.task_id == task_id:
            return task.model_dump()

    raise HTTPException(status_code=404, detail="Installation task not found")


@app.post("/api/dependencies/installations/{task_id}/cancel")
async def cancel_installation(task_id: str):
    """Cancel an installation task."""
    from fnirs_flow.dependencies.installer import get_installation_orchestrator

    orchestrator = get_installation_orchestrator()
    success = orchestrator.cancel(task_id)
    if success:
        return {"status": "cancelled", "task_id": task_id}
    raise HTTPException(status_code=404, detail="Task not found or already completed")


@app.get("/api/dependency-environments")
async def list_dependency_environments():
    """List all dependency environments."""
    from fnirs_flow.dependencies.installer import get_installation_orchestrator

    orchestrator = get_installation_orchestrator()
    return orchestrator.list_environments()


@app.delete("/api/dependency-environments/{environment_id:path}")
async def delete_dependency_environment(environment_id: str):
    """Delete a dependency environment."""
    from fnirs_flow.dependencies.installer import get_installation_orchestrator

    orchestrator = get_installation_orchestrator()
    # Parse environment_id as profile_id/lock_fingerprint
    parts = environment_id.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid environment_id format")

    success = orchestrator.remove_environment(parts[0], parts[1])
    if success:
        return {"status": "removed", "environment_id": environment_id}
    raise HTTPException(status_code=404, detail="Environment not found")


# --- SSE Progress Stream ---

# Store for execution progress events (with memory limits)
_MAX_EVENTS_PER_PROJECT = 1000
_MAX_PROJECTS = 100
_progress_events: dict[str, list[dict]] = {}
_progress_sequences: dict[tuple[str, str], int] = {}
_progress_lock = threading.Lock()


def push_progress(project_id: str, event: dict) -> None:
    """Push a progress event for a project, evicting old data if limits exceeded."""
    with _progress_lock:
        attempt_id = str(event.get("attempt_id", ""))
        sequence_key = (project_id, attempt_id)
        sequence = _progress_sequences.get(sequence_key, 0) + 1
        _progress_sequences[sequence_key] = sequence
        event = {
            "project_id": project_id,
            "attempt_id": attempt_id,
            "sequence": sequence,
            **event,
        }
        if project_id not in _progress_events:
            _progress_events[project_id] = []
        _progress_events[project_id].append(event)
        # Trim to max events per project
        if len(_progress_events[project_id]) > _MAX_EVENTS_PER_PROJECT:
            _progress_events[project_id] = _progress_events[project_id][-_MAX_EVENTS_PER_PROJECT:]
        # Evict oldest projects if too many
        if len(_progress_events) > _MAX_PROJECTS:
            oldest = next(iter(_progress_events))
            del _progress_events[oldest]
            # Clean up associated sequence counters
            stale = [k for k in _progress_sequences if k[0] == oldest]
            for k in stale:
                del _progress_sequences[k]


@app.get("/api/projects/{project_id}/progress")
async def progress_stream(project_id: str):
    """SSE endpoint for real-time execution progress."""

    async def generate():
        # Send existing events
        with _progress_lock:
            initial_events = list(_progress_events.get(project_id, []))
        for event in initial_events:
            yield f"data: {json.dumps(event)}\n\n"

        # Wait for new events; stop cleanly on client disconnect
        last_idx = len(initial_events)
        idle_ticks = 0
        MAX_IDLE_TICKS = 600  # 5 minutes at 0.5s intervals
        try:
            while True:
                await asyncio.sleep(0.5)
                with _progress_lock:
                    events = _progress_events.get(project_id, [])
                    if len(events) > last_idx:
                        for event in events[last_idx:]:
                            yield f"data: {json.dumps(event)}\n\n"
                        last_idx = len(events)
                        idle_ticks = 0
                    else:
                        idle_ticks += 1

                # Send heartbeat comment every 15s
                if idle_ticks % 30 == 0:
                    yield ": heartbeat\n\n"

                # Terminate after prolonged inactivity
                if idle_ticks >= MAX_IDLE_TICKS:
                    yield f"data: {json.dumps({'type': 'stream_closed', 'reason': 'idle_timeout'})}\n\n"
                    break
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Health ---


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": fnirs_flow.__version__}


# --- Serve frontend static files ---
# The built frontend lives in webui/dist relative to the project root.
_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "webui" / "dist"

def _guess_mime(path: str) -> str:
    """Minimal MIME type guesser for static assets."""
    if path.endswith(".js"):
        return "application/javascript"
    if path.endswith(".css"):
        return "text/css"
    if path.endswith(".html"):
        return "text/html"
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".svg"):
        return "image/svg+xml"
    if path.endswith(".png"):
        return "image/png"
    if path.endswith(".ico"):
        return "image/x-icon"
    return "application/octet-stream"


# --- Atom Templates (registry-driven palette) ---


def _is_parameter_option_value(value: Any) -> bool:
    return isinstance(value, str | int | float) and not isinstance(value, bool)


def _unique_parameter_options(values: list[Any]) -> list[Any]:
    seen: set[tuple[str, str]] = set()
    options: list[Any] = []
    for value in values:
        if not _is_parameter_option_value(value):
            continue
        key = (type(value).__name__, str(value))
        if key in seen:
            continue
        seen.add(key)
        options.append(value)
    return options


def _template_parameter_options(template: Any, templates: list[Any]) -> dict[str, list[Any]]:
    default_config = dict(getattr(template, "default_config", {}) or {})
    explicit = dict(getattr(template, "parameter_options", {}) or {})
    atom_type = getattr(template, "atom_type", "")
    peer_templates = [item for item in templates if getattr(item, "atom_type", "") == atom_type]
    options: dict[str, list[Any]] = {}

    for name, value in default_config.items():
        values = list(explicit.get(name, []))
        values.extend(
            dict(getattr(peer, "default_config", {}) or {}).get(name)
            for peer in peer_templates
        )
        merged = _unique_parameter_options(values)
        if len(merged) > 1 or explicit.get(name):
            current_included = any(str(item) == str(value) for item in merged)
            options[name] = merged if current_included or not _is_parameter_option_value(value) else [value, *merged]

    return options


@app.get("/api/atom-templates")
async def list_atom_templates():
    """List all available MethodAtom templates from the backend registry."""
    from fnirs_flow.registry.atom_templates import ALL_ATOM_TEMPLATES
    from fnirs_flow.registry.node_templates import attach_common_parameter_options

    attach_common_parameter_options(ALL_ATOM_TEMPLATES)
    templates = []
    for t in ALL_ATOM_TEMPLATES:
        templates.append(
            {
                "id": t.node_id,
                "atom_type": t.atom_type,
                "display_name": t.display_name,
                "category": t.category.value if hasattr(t.category, "value") else str(t.category),
                "operation": t.operation or t.atom_type,
                "description": getattr(t, "description", ""),
                "default_config": dict(getattr(t, "default_config", {}) or {}),
                "parameter_options": _template_parameter_options(t, ALL_ATOM_TEMPLATES),
                "parameter_specs": dict(getattr(t, "parameter_specs", {}) or {}),
                "default_readiness_status": (
                    t.default_readiness_status.value
                    if getattr(t, "default_readiness_status", None) is not None
                    else "not_configured"
                ),
                "default_execution_scope": getattr(t, "default_execution_scope", None) or "run",
                "input_ports": [
                    {"name": p.name, "schema": p.port_schema, "required": p.required}
                    for p in getattr(t, "input_ports", [])
                ],
                "output_ports": [
                    {"name": p.name, "schema": p.port_schema, "required": p.required}
                    for p in getattr(t, "output_ports", [])
                ],
                "evidence_refs": list(getattr(t, "evidence_refs", [])),
            }
        )
    return templates


@app.get("/api/empty-marker-specs")
async def list_empty_marker_specs():
    """List schema-preserving no-op marker specs used by Empty risk handling."""
    from fnirs_flow.flow.empty_markers import empty_marker_specs_json

    return empty_marker_specs_json()


@app.get("/api/flow-checklists")
async def list_checklists():
    """List available guided flow checklists."""
    from fnirs_flow.flow.checklists import list_flow_checklists

    return list_flow_checklists()


@app.get("/api/flow-checklists/{scenario_id}")
async def get_checklist(scenario_id: str):
    """Return one guided flow checklist contract."""
    from fnirs_flow.flow.checklists import checklist_to_dict, get_flow_checklist

    checklist = get_flow_checklist(scenario_id)
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")
    return checklist_to_dict(checklist)


# Register the SPA fallback last. Starlette resolves routes in declaration order,
# so a catch-all registered before API routes would return index.html for them.
_ASSETS_DIR = _DIST_DIR / "assets"
if _ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="static-assets")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve the SPA index.html for all non-API routes.

    The route is always registered because ``fnirs-flow webui`` may build the
    frontend after importing this module on a fresh checkout.
    """
    dist_root = _DIST_DIR.resolve()
    file_path = (_DIST_DIR / full_path).resolve()
    if not file_path.is_relative_to(dist_root):
        return JSONResponse(status_code=403, content={"detail": "Access denied"})
    if full_path and file_path.is_file():
        return Response(content=file_path.read_bytes(), media_type=_guess_mime(full_path))
    index = _DIST_DIR / "index.html"
    if index.is_file():
        return Response(content=index.read_bytes(), media_type="text/html")
    return JSONResponse(
        status_code=404,
        content={"detail": "Frontend not built. Run: cd webui && npm run build"},
    )
