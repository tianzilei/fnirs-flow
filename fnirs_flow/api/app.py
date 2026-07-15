"""FastAPI application for fnirs-flow WebUI."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
    load_flow_from_compiled_package,
    validate_project_execution,
    validate_project_flow,
)

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
        pass  # Already initialized with different lock_dir

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


@app.get("/api/projects", response_model=list[ProjectRead])
async def list_projects():
    return get_store().list_all()


@app.post("/api/projects", response_model=ProjectRead)
async def create_project(data: ProjectCreate):
    return get_store().create(data.name, data.description)


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
    if not get_store().update_flow(project_id, data.flow, debounce=data.debounce):
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
    result = validate_project_flow(get_store(), project_id)
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
        result = compile_project_flow(get_store(), project_id, base_revision=base_revision)
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


# --- Dataset Discovery ---


@app.post("/api/projects/{project_id}/discover-data", response_model=DiscoverResult)
async def discover_data_endpoint(
    project_id: str,
    dataset_id: str,
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
        result = discover_project_data(get_store(), project_id, dataset_id, base_revision=base_revision)
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
        result = import_project_participant_table(
            get_store(),
            project_id,
            data.path,
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
        result = dry_run_project(get_store(), project_id)
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
        result = export_project_package(get_store(), project_id, profile_id=request.profile)
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
    outdir = store.get_output_dir(project_id)
    try:
        result = do_import(
            package_path,
            str(outdir),
            relink_data=data_root is not None,
            data_root=data_root,
            project_layout=True,
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
        raise HTTPException(status_code=500, detail=f"File system error: {e}") from e
    except Exception as e:
        logger.exception("Unexpected error during import")
        raise HTTPException(status_code=500, detail=f"Import failed: {e}") from e


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
        raise HTTPException(status_code=500, detail=f"File system error: {e}") from e
    except Exception as e:
        logger.exception("Unexpected error during fork")
        raise HTTPException(status_code=500, detail=f"Fork failed: {e}") from e


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
    import json as json_mod

    store = get_store()
    outdir = store.get_output_dir(project_id)
    metadata_path = outdir / "import_metadata.json"
    if not metadata_path.exists():
        return {"imported": False, "read_only": False, "quarantined_atoms": []}
    metadata = json_mod.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        "imported": True,
        "read_only": metadata.get("read_only", False),
        "quarantined_atoms": metadata.get("quarantined_atoms", []),
        "relinked": metadata.get("relinked", False),
        "data_root": "",
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
        relink_result = relink_package_data(outdir, root)
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
    files = []
    seen: set[str] = set()
    for path in sorted(paths):
        if path.name.startswith("._"):
            continue
        relative = path.relative_to(outdir).as_posix()
        logical_name = relative.removeprefix("compiled/")
        if logical_name in seen:
            continue
        seen.add(logical_name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        files.append({"path": logical_name, "data": data})
    return {"kind": kind, "file_count": len(files), "files": files}


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

        import json as json_mod

        dag = json_mod.loads(dag_path.read_text(encoding="utf-8"))

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
            import json as json_mod

            plan = json_mod.loads(plan_path.read_text(encoding="utf-8"))
            if plan.get("plan_id") == plan_id:
                return plan

    raise HTTPException(status_code=404, detail="Plan not found")


@app.post("/api/dependencies/plans/{plan_id}/approve")
async def approve_dependency_plan(plan_id: str):
    """Approve a dependency plan for installation.

    §9.1: approve 校验计划指纹、来源策略和目标环境后，才创建安装任务
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
            import json as json_mod

            plan = json_mod.loads(plan_path.read_text(encoding="utf-8"))
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

    return {"status": "approved", "plan_id": plan_id, "fingerprint": plan.plan_fingerprint}


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
            import json as json_mod

            plan_data = json_mod.loads(plan_path.read_text(encoding="utf-8"))
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
    for task in orchestrator._installer.list_tasks():
        if task.task_id == task_id:
            return task.model_dump()

    raise HTTPException(status_code=404, detail="Installation task not found")


@app.post("/api/dependencies/installations/{task_id}/cancel")
async def cancel_installation(task_id: str):
    """Cancel an installation task."""
    from fnirs_flow.dependencies.installer import get_installation_orchestrator

    orchestrator = get_installation_orchestrator()
    success = orchestrator._installer.cancel(task_id)
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
        try:
            while True:
                await asyncio.sleep(0.5)
                with _progress_lock:
                    events = _progress_events.get(project_id, [])
                    if len(events) > last_idx:
                        for event in events[last_idx:]:
                            yield f"data: {json.dumps(event)}\n\n"
                        last_idx = len(events)
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


@app.get("/api/atom-templates")
async def list_atom_templates():
    """List all available MethodAtom templates from the backend registry."""
    from fnirs_flow.registry.atom_templates import ALL_ATOM_TEMPLATES

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


# Register the SPA fallback last. Starlette resolves routes in declaration order,
# so a catch-all registered before API routes would return index.html for them.
if _DIST_DIR.is_dir():
    _ASSETS_DIR = _DIST_DIR / "assets"
    if _ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA index.html for all non-API routes."""
        file_path = (_DIST_DIR / full_path).resolve()
        if not file_path.is_relative_to(_DIST_DIR.resolve()):
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
