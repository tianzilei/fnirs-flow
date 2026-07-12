"""Project management endpoints."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fnirs_flow.api.models import (  # noqa: E402
    ArtifactSummary,
    AtomResultSummary,
    CompileResult,
    DiscoverResult,
    DryRunResult,
    ExecuteResult,
    ExportResult,
    ProjectRead,
    ProjectSnapshot,
    RunSummary,
    ValidationResult,
)
from fnirs_flow.compiler.compiler import compile_flow  # noqa: E402
from fnirs_flow.data.discovery import discover_dataset  # noqa: E402
from fnirs_flow.execution.engine import dry_run  # noqa: E402
from fnirs_flow.flow.snapshots import ProjectSnapshot as Snapshot  # noqa: E402
from fnirs_flow.validation.api import validate_flow  # noqa: E402


class ProjectStore:
    """Persistent project store backed by JSON files on disk."""

    def __init__(self, base_dir: Path):
        self._base_dir = Path(base_dir)
        self._projects: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load_all()

    def _load_all(self) -> None:
        """Load all projects from disk on startup."""
        if not self._base_dir.exists():
            return
        for proj_dir in self._base_dir.iterdir():
            meta_file = proj_dir / "project.json"
            if proj_dir.is_dir() and meta_file.exists():
                try:
                    with open(meta_file, encoding="utf-8") as f:
                        self._projects[proj_dir.name] = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Skipping corrupt project '%s': %s", proj_dir.name, e)
                    continue

    def _persist(self, project_id: str) -> None:
        """Write project metadata to disk."""
        proj_dir = self._base_dir / project_id
        proj_dir.mkdir(parents=True, exist_ok=True)
        with open(proj_dir / "project.json", "w", encoding="utf-8") as f:
            json.dump(self._projects[project_id], f, indent=2)

    def create(self, name: str, description: str = "") -> ProjectRead:
        if not name or not name.strip():
            raise ValueError("Project name cannot be empty")
        if len(name) > 256:
            raise ValueError("Project name too long (max 256 characters)")
        # Sanitize: project IDs are UUIDs, so no path traversal risk
        project_id = str(uuid.uuid4())[:8]
        project_dir = self._base_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self._projects[project_id] = {
                "id": project_id,
                "name": name,
                "description": description,
                "flow": {},
                "snapshots": [],
                "attempts": [],
            }
            self._persist(project_id)

        return ProjectRead(id=project_id, name=name, description=description)

    def get(self, project_id: str) -> ProjectRead | None:
        proj = self._projects.get(project_id)
        if proj is None:
            return None
        return ProjectRead(
            id=proj["id"],
            name=proj["name"],
            description=proj["description"],
            flow_id=proj.get("flow", {}).get("flow_id", ""),
        )

    def list_all(self) -> list[ProjectRead]:
        return [
            ProjectRead(
                id=p["id"],
                name=p["name"],
                description=p["description"],
                flow_id=p.get("flow", {}).get("flow_id", ""),
            )
            for p in self._projects.values()
        ]

    def get_flow(self, project_id: str) -> dict[str, Any] | None:
        proj = self._projects.get(project_id)
        if proj is None:
            return None
        result: dict[str, Any] = proj.get("flow", {})
        return result

    def update_flow(self, project_id: str, flow: dict[str, Any]) -> bool:
        with self._lock:
            if project_id not in self._projects:
                return False
            self._projects[project_id]["flow"] = flow
            self._persist(project_id)
            return True

    def get_output_dir(self, project_id: str) -> Path:
        return self._base_dir / project_id / "outputs"


def validate_project_flow(store: ProjectStore, project_id: str) -> ValidationResult:
    """Validate a project's flow."""
    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return ValidationResult(is_valid=False, errors=["No flow found for project"])

    report = validate_flow(flow)
    return ValidationResult(
        is_valid=report.is_valid and not report.has_fatal_risks,
        errors=report.errors,
        warnings=report.warnings,
        risks=[r.model_dump() for r in report.risks],
    )


def compile_project_flow(store: ProjectStore, project_id: str) -> CompileResult | None:
    """Compile a project's flow to plan/dag.

    Outputs are written to ``<project>/outputs/compiled/``.
    """
    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return None

    outdir = store.get_output_dir(project_id)
    result = compile_flow(flow, outdir)

    # result.outdir now points to compiled/ subdirectory
    compiled_dir = result.outdir

    # Collect atom types from execution DAG
    atom_types = list({n.atom_type or n.node_type for n in result.execution_dag.nodes})

    return CompileResult(
        flow_id=result.flow_graph.flow_id,
        flow_hash=result.flow_hash,
        steps=len(result.execution_dag.nodes),
        layers=len(result.execution_dag.execution_layers),
        output_files=[f.name for f in sorted(compiled_dir.iterdir()) if f.is_file()],
        atoms=len(result.execution_dag.nodes),
        atom_types=sorted(atom_types),
    )


def discover_project_data(store: ProjectStore, project_id: str, dataset_id: str) -> DiscoverResult | None:
    """Discover a dataset for a project."""
    outdir = store.get_output_dir(project_id)
    try:
        manifest = discover_dataset(dataset_id, outdir)
        return DiscoverResult(
            dataset_id=manifest.dataset_id,
            files=len(manifest.files),
            runs=len(manifest.subject_session_runs),
            local_root=manifest.local_root,
            source_url=manifest.source.url,
        )
    except ValueError as e:
        logger.warning("Dataset discovery failed: %s", e)
        return None
    except (OSError, KeyError, RuntimeError) as e:
        logger.exception("Unexpected error during dataset discovery: %s", e)
        return None


def dry_run_project(store: ProjectStore, project_id: str) -> DryRunResult | None:
    """Execute a dry-run for a project."""
    outdir = store.get_output_dir(project_id)
    try:
        result = dry_run(outdir)
        return DryRunResult(
            total_runs=result.total_runs,
            planned_runs=[r.model_dump() for r in result.planned_runs],
            summary=result.summary,
        )
    except FileNotFoundError:
        logger.warning("Dry run failed — plan not found for project %s", project_id)
        return None
    except (OSError, KeyError, ValueError) as e:
        logger.exception("Unexpected error during dry run for project %s: %s", project_id, e)
        return None


def create_snapshot(store: ProjectStore, project_id: str) -> ProjectSnapshot | None:
    """Create an immutable snapshot of the current flow."""
    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return None

    from fnirs_flow.compiler.hashing import compute_flow_hash

    flow_hash = compute_flow_hash(flow)
    snapshot_id = f"snap-{flow_hash[:8]}"

    snapshot = Snapshot(
        snapshot_id=snapshot_id,
        flow=flow,
        flow_hash=flow_hash,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    with store._lock:
        store._projects[project_id]["snapshots"].append(snapshot.model_dump())
        store._persist(project_id)

    return ProjectSnapshot(
        snapshot_id=snapshot_id,
        flow_hash=flow_hash,
        created_at=snapshot.created_at,
    )


def execute_project_runs(store: ProjectStore, project_id: str) -> ExecuteResult | None:
    """Execute runs for a project using the unified ExecutionService."""
    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return None

    outdir = store.get_output_dir(project_id)
    compiled_dir = outdir / "compiled"

    # Check that compiled plan exists
    dag_path = compiled_dir / "execution_dag.json"
    if not dag_path.exists():
        return None

    try:
        from fnirs_flow.execution.service import ExecutionRequest, ExecutionService

        # Auto-create ProjectSnapshot before execute if flow has changed
        create_snapshot(store, project_id)

        # Push progress: starting
        from fnirs_flow.api.app import push_progress

        push_progress(
            project_id,
            {
                "type": "execution_started",
                "project_id": project_id,
            },
        )

        # Create execution request
        request = ExecutionRequest(
            project_dir=str(outdir),
            outdir=str(outdir),
        )

        # Execute via ExecutionService
        service = ExecutionService()
        result = service.execute(request)

        # Push progress: completed
        push_progress(
            project_id,
            {
                "type": "execution_completed",
                "project_id": project_id,
                "successful": result.successful_runs,
                "failed": result.failed_runs,
            },
        )

        return ExecuteResult(
            attempt_id=result.attempt_id,
            total_runs=result.total_runs,
            successful=result.successful_runs,
            failed=result.failed_runs,
            runs=[
                RunSummary(
                    run_id=rr.run_id,
                    status=rr.status,
                    subject="",
                    session="",
                    run="",
                    started_at=rr.started_at,
                    completed_at=rr.completed_at,
                    atom_results=[
                        AtomResultSummary(
                            atom_id=ar.atom_id,
                            status=ar.status,
                            error=ar.error,
                        )
                        for ar in rr.atom_results
                    ],
                    artifacts=[
                        ArtifactSummary(
                            type=art.get("type", ""),
                            path=art.get("path", ""),
                            checksum=art.get("checksum", ""),
                        )
                        for art in rr.artifacts
                    ],
                )
                for rr in result.run_results
            ],
            failure_ids=result.failure_ids,
        )
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        logger.exception("Execute failed for project %s: %s", project_id, e)
        return None


def export_project_package(store: ProjectStore, project_id: str) -> ExportResult | None:
    """Export a compiled project as a .fnirsflow.zip package.

    Reads compiled outputs from ``<project>/outputs/compiled/`` and writes
    the package to ``<project>/outputs/export/``.
    """
    project = store.get(project_id)
    if project is None:
        return None

    outdir = store.get_output_dir(project_id)
    compiled_dir = outdir / "compiled"
    if not (compiled_dir / "plan.json").exists():
        return None

    import shutil
    import tempfile

    from fnirs_flow.exporters.package_exporter import export_package

    pkg_path = None
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_pkg = Path(tmp_dir) / f"{project_id}.fnirsflow.zip"
            export_package(compiled_dir, tmp_pkg)
            # Copy to final location in export/
            final_dir = outdir / "export"
            final_dir.mkdir(parents=True, exist_ok=True)
            pkg_path = final_dir / tmp_pkg.name
            shutil.copy2(tmp_pkg, pkg_path)
        return ExportResult(
            package_path=str(pkg_path),
            size_bytes=pkg_path.stat().st_size,
        )
    except Exception as e:
        logger.error("Package export failed: %s", e)
        if pkg_path and pkg_path.exists():
            pkg_path.unlink(missing_ok=True)
        return None
