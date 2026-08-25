"""Project package export, import, and dataset binding endpoints."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from fnirs_flow.api.error_responses import api_error
from fnirs_flow.api.models import (
    BundleStatus,
    ExportRequest,
    ExportResult,
    ImportStatus,
    PackageProfile,
    ProjectRead,
    VersionHistoryEntry,
)
from fnirs_flow.api.router_dependencies import bind_router_context, current_store, resolve_current_path
from fnirs_flow.application.project_use_cases import (
    StaleCompiledPlanError,
    export_project_package,
    load_flow_from_compiled_package,
)

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(bind_router_context)])


def _store() -> Any:
    return current_store()


def _resolve_package_path(value: str, project_id: str) -> Path:
    return resolve_current_path(value, project_id, "Package path")


@router.get("/api/projects/{project_id}/bundle", response_model=BundleStatus)
async def project_bundle_status_endpoint(project_id: str) -> Any:
    from fnirs_flow.infrastructure.project_bundle import ProjectBundleError

    try:
        result = _store().get_bundle_status(project_id)
    except ProjectBundleError as exc:
        raise api_error(409, "PROJECT_BUNDLE_CORRUPT", str(exc), "project_open", recoverable=True,
                        suggested_action="Restore a retained revision or reopen the last valid project bundle") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.post("/api/projects/{project_id}/bundle/restore/{revision}", response_model=ProjectRead)
async def restore_project_bundle_endpoint(project_id: str, revision: int) -> Any:
    from fnirs_flow.infrastructure.project_bundle import ProjectBundleError

    try:
        result = _store().restore_bundle_revision(project_id, revision)
    except ProjectBundleError as exc:
        raise api_error(404, "PROJECT_REVISION_NOT_FOUND", str(exc), "project_restore", recoverable=True,
                        suggested_action="Choose a revision listed by the project bundle status endpoint") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.get("/api/projects/{project_id}/version-history", response_model=list[VersionHistoryEntry])
async def get_version_history_endpoint(project_id: str) -> Any:
    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return store.get_version_history(project_id)


@router.post("/api/projects/{project_id}/export-package", response_model=ExportResult)
async def export_package_endpoint(project_id: str, data: ExportRequest | None = None) -> Any:
    request = data or ExportRequest()
    try:
        result = await run_in_threadpool(export_project_package, _store(), project_id, profile_id=request.profile)
    except StaleCompiledPlanError as exc:
        raise api_error(409, "STALE_COMPILED_PLAN", str(exc), "export", recoverable=True,
                        suggested_action="Compile the current Flow again") from exc
    except ValueError as exc:
        raise api_error(422, "EXPORT_PROFILE_INVALID", str(exc), "export", recoverable=True,
                        suggested_action="Choose a supported package profile") from exc
    except (OSError, RuntimeError) as exc:
        logger.exception("Package export failed for project %s", project_id)
        raise api_error(500, "EXPORT_FAILED", str(exc), "export", recoverable=True,
                        suggested_action="Check output permissions and server logs") from exc
    if result is None:
        status = 404 if _store().get(project_id) is None else 409
        raise api_error(status, "PROJECT_NOT_FOUND" if status == 404 else "PLAN_NOT_COMPILED",
                        "Project or compiled plan not found", "export", recoverable=status == 409,
                        suggested_action="Compile the Flow first")
    return result


@router.get("/api/package-profiles", response_model=list[PackageProfile])
async def list_package_profiles_endpoint() -> list[dict[str, Any]]:
    from fnirs_flow.exporters.package_exporter import list_package_profiles
    return [profile.model_dump() for profile in list_package_profiles()]


@router.post("/api/projects/{project_id}/import-package")
async def import_package_endpoint(project_id: str, package_path: str, data_root: str | None = None) -> Any:
    from fnirs_flow.exporters.package_importer import import_package as do_import

    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_package_path = _resolve_package_path(package_path, project_id)
    outdir = store.get_output_dir(project_id)
    try:
        result = do_import(resolved_package_path, str(outdir), relink_data=data_root is not None,
                           data_root=data_root, project_layout=True, persist_binding=False)
        imported_flow = load_flow_from_compiled_package(outdir / "compiled")
        if data_root is not None:
            manifest_path = outdir / "compiled" / "data_manifest.json"
            if manifest_path.exists():
                dataset_id = str(json.loads(manifest_path.read_text(encoding="utf-8")).get("dataset_id", ""))
                if dataset_id:
                    store.bind_dataset(dataset_id, Path(data_root).expanduser().resolve())
        store.update_flow(project_id, imported_flow)
        return result
    except (ValueError, KeyError) as exc:
        logger.warning("Import validation error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("Import IO error: %s", exc)
        raise HTTPException(status_code=500, detail="File system error during import") from exc
    except Exception as exc:
        logger.exception("Unexpected error during import")
        raise HTTPException(status_code=500, detail="Import failed due to an internal error") from exc


@router.post("/api/projects/{project_id}/fork")
async def fork_project_endpoint(project_id: str, fork_name: str = "") -> dict[str, Any]:
    from fnirs_flow.exporters.package_importer import fork_package

    store = _store()
    source_dir = store.get_output_dir(project_id)
    try:
        proj = store.create(fork_name or f"{project_id}_fork", f"Forked from {project_id}")
        fork_dir = store.get_output_dir(proj.id)
        result = fork_package(str(source_dir), str(fork_dir), unfork=True)
        store.update_flow(proj.id, load_flow_from_compiled_package(fork_dir / "compiled"))
        return {"fork_project_id": proj.id, **result}
    except (ValueError, KeyError) as exc:
        logger.warning("Fork validation error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("Fork IO error: %s", exc)
        raise HTTPException(status_code=500, detail="File system error during fork") from exc
    except Exception as exc:
        logger.exception("Unexpected error during fork")
        raise HTTPException(status_code=500, detail="Fork failed due to an internal error") from exc


@router.post("/api/projects/{project_id}/trust-atom/{atom_id}")
async def trust_atom_endpoint(project_id: str, atom_id: str) -> Any:
    from fnirs_flow.api.transaction import ProjectTransaction
    from fnirs_flow.exporters.package_importer import trust_atom

    store = _store()
    with ProjectTransaction(store, project_id, reason="atom_trust_updated") as tx:
        result = trust_atom(str(tx.output_dir), atom_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        flow = store.get_flow(project_id)
        if flow:
            for atom in flow.get("flow_atoms", flow.get("nodes", [])):
                if atom.get("id") == atom_id or atom.get("atom_id") == atom_id:
                    atom["security_status"] = "trusted"
                    atom.setdefault("metadata", {})["trusted_at"] = result["trusted_at"]
            store.update_flow(project_id, flow)
        tx.commit()
    return result


@router.get("/api/projects/{project_id}/import-status", response_model=ImportStatus)
async def import_status_endpoint(project_id: str) -> dict[str, Any]:
    store = _store()
    outdir = store.get_output_dir(project_id)
    metadata_path = outdir / "import_metadata.json"
    if not metadata_path.exists():
        return {"imported": False, "read_only": False, "quarantined_atoms": []}
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    dataset_id = str(metadata.get("dataset_id") or "")
    bound_root = store.get_dataset_binding(dataset_id) if dataset_id else None
    return {"imported": True, "read_only": metadata.get("read_only", False),
            "quarantined_atoms": metadata.get("quarantined_atoms", []), "relinked": metadata.get("relinked", False),
            "data_root": str(bound_root) if bound_root else "", "dataset_id": dataset_id}


@router.post("/api/projects/{project_id}/relink-data")
async def relink_project_data_endpoint(project_id: str, data_root: str) -> dict[str, str]:
    from fnirs_flow.exporters.package_importer import relink_package_data

    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    root = Path(data_root).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=422, detail="Data root does not exist or is not a directory")
    try:
        relink_result = relink_package_data(store.get_output_dir(project_id), root, persist_binding=False)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Imported package has no data_manifest.json") from exc
    manifest = json.loads(Path(relink_result["manifest_path"]).read_text(encoding="utf-8"))
    dataset_id = str(manifest.get("dataset_id") or "dataset")
    store.bind_dataset(dataset_id, root)
    store.update_state(project_id, relinked_dataset_id=dataset_id, relinked_data_uri=f"external-data://{dataset_id}/")
    return {"status": "relinked", "data_root": str(root), "dataset_id": dataset_id, "data_uri": f"external-data://{dataset_id}/"}


@router.post("/api/projects/{project_id}/bind-dataset")
async def bind_project_dataset_endpoint(project_id: str, dataset_id: str, data_root: str) -> dict[str, str]:
    from fnirs_flow.data.registry import DatasetRegistry

    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    root = Path(data_root).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=422, detail="Data root does not exist or is not a directory")
    if DatasetRegistry().get(dataset_id) is None:
        raise HTTPException(status_code=404, detail="Unknown dataset")
    store.bind_dataset(dataset_id, root)
    return {"status": "bound", "dataset_id": dataset_id, "data_root": str(root), "data_uri": f"external-data://{dataset_id}/"}
