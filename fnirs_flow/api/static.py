"""WebUI static asset and SPA fallback routes."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, Response

router = APIRouter()


def _dist_dir(request: Request):
    """Return packaged WebUI resources without assuming a repository layout."""
    settings = request.app.state.settings
    return files(settings.webui_resource_package).joinpath(settings.webui_resource_path)


def guess_mime(path: str) -> str:
    suffixes = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".html": "text/html",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }
    return suffixes.get(Path(path).suffix.lower(), "application/octet-stream")


@router.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str) -> Response:
    dist_dir = _dist_dir(request)
    requested = PurePosixPath(full_path)
    if requested.is_absolute() or ".." in requested.parts:
        return JSONResponse(status_code=403, content={"detail": "Access denied"})
    file_path = dist_dir.joinpath(*requested.parts) if requested.parts else dist_dir
    if full_path and file_path.is_file():
        return Response(content=file_path.read_bytes(), media_type=guess_mime(full_path))
    index = dist_dir.joinpath("index.html")
    if index.is_file():
        return Response(content=index.read_bytes(), media_type="text/html")
    return JSONResponse(
        status_code=503,
        content={"detail": "Packaged WebUI assets are missing; reinstall fnirs-flow"},
    )
