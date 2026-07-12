"""FastAPI application for fnirs-flow WebUI."""

from __future__ import annotations

import hmac
import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response, StreamingResponse

import fnirs_flow
from fnirs_flow.api.models import (
    CompileResult,
    DiscoverResult,
    DryRunResult,
    ExecuteResult,
    ExportResult,
    FlowUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectSnapshot,
    ValidationResult,
)
from fnirs_flow.api.projects import (
    ProjectStore,
    compile_project_flow,
    create_snapshot,
    discover_project_data,
    dry_run_project,
    execute_project_runs,
    export_project_package,
    validate_project_flow,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Refresh bundled MethodAtom data whenever the API starts."""
    from fnirs_flow.registry.atom_templates import refresh_method_atom_templates

    refresh_method_atom_templates()
    yield


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


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ProjectStore(Path("outputs/api_projects"))
    return _store


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
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


# --- Flow ---


@app.get("/api/projects/{project_id}/flow")
async def get_flow(project_id: str):
    flow = get_store().get_flow(project_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


@app.put("/api/projects/{project_id}/flow")
async def update_flow(project_id: str, data: FlowUpdate):
    if not get_store().update_flow(project_id, data.flow):
        raise HTTPException(status_code=404, detail="Project not found")
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
async def compile_flow_endpoint(project_id: str):
    result = compile_project_flow(get_store(), project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Flow not found or compilation failed")
    return result


# --- Dataset Discovery ---


@app.post("/api/projects/{project_id}/discover-data", response_model=DiscoverResult)
async def discover_data_endpoint(project_id: str, dataset_id: str):
    result = discover_project_data(get_store(), project_id, dataset_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return result


# --- Dry Run ---


@app.post("/api/projects/{project_id}/dry-run", response_model=DryRunResult)
async def dry_run_endpoint(project_id: str):
    result = dry_run_project(get_store(), project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Plan not found. Compile flow first.")
    return result


# --- Execute ---


@app.post("/api/projects/{project_id}/execute", response_model=ExecuteResult)
async def execute_endpoint(project_id: str):
    result = execute_project_runs(get_store(), project_id)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail="Project not found or flow not compiled. Compile and discover data first.",
        )
    return result


# --- Snapshots ---


@app.post("/api/projects/{project_id}/snapshots", response_model=ProjectSnapshot)
async def create_snapshot_endpoint(project_id: str):
    result = create_snapshot(get_store(), project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    return result


# --- Export Package ---


@app.post("/api/projects/{project_id}/export-package", response_model=ExportResult)
async def export_package_endpoint(project_id: str):
    result = export_project_package(get_store(), project_id)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail="Project not found or flow not compiled. Compile first.",
        )
    return result


# --- Package Import/Fork/Trust ---


@app.post("/api/projects/{project_id}/import-package")
async def import_package_endpoint(project_id: str, package_path: str):
    """Import a .fnirsflow.zip package into a project."""
    from fnirs_flow.exporters.package_importer import import_package as do_import

    store = get_store()
    outdir = store.get_output_dir(project_id)
    try:
        result = do_import(package_path, str(outdir))
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/projects/{project_id}/fork")
async def fork_project_endpoint(project_id: str, fork_name: str = ""):
    """Fork an imported project to a new editable copy."""
    from fnirs_flow.exporters.package_importer import fork_package

    store = get_store()
    source_dir = store.get_output_dir(project_id)
    fork_dir = source_dir.parent / (fork_name or f"{project_id}_fork")
    try:
        result = fork_package(str(source_dir), str(fork_dir), unfork=True)
        # Create new project entry
        proj = store.create(fork_name or f"{project_id}_fork", f"Forked from {project_id}")
        return {"fork_project_id": proj.id, **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/projects/{project_id}/trust-atom/{atom_id}")
async def trust_atom_endpoint(project_id: str, atom_id: str):
    """Trust a quarantined atom."""
    from fnirs_flow.exporters.package_importer import trust_atom

    store = get_store()
    outdir = store.get_output_dir(project_id)
    result = trust_atom(str(outdir), atom_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
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
    }


# --- SSE Progress Stream ---

# Store for execution progress events (with memory limits)
_MAX_EVENTS_PER_PROJECT = 1000
_MAX_PROJECTS = 100
_progress_events: dict[str, list[dict]] = {}
_progress_lock = threading.Lock()


def push_progress(project_id: str, event: dict) -> None:
    """Push a progress event for a project, evicting old data if limits exceeded."""
    with _progress_lock:
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
    import asyncio

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

if _DIST_DIR.is_dir():
    _ASSETS_DIR = _DIST_DIR / "assets"
    if _ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA index.html for all non-API routes."""
        # If the path matches a real file, serve it
        file_path = _DIST_DIR / full_path
        if full_path and file_path.is_file():
            return Response(content=file_path.read_bytes(), media_type=_guess_mime(full_path))
        # Otherwise serve index.html (SPA fallback)
        index = _DIST_DIR / "index.html"
        if index.is_file():
            return Response(content=index.read_bytes(), media_type="text/html")
        return JSONResponse(status_code=404, content={"detail": "Frontend not built. Run: cd webui && npm run build"})


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
