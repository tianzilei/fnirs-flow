"""Project management endpoints."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fnirs_flow.api.project_bundle import ProjectBundleError, ProjectBundleManager
from fnirs_flow.api.uri import URIBindingStore
from fnirs_flow.filesystem import is_visible_data_file, remove_macos_metadata_paths
from fnirs_flow.history.service import HistoryService
from fnirs_flow.history.zip_json_store import ZipJsonHistoryStore

if TYPE_CHECKING:
    from fnirs_flow.api.transaction import ProjectTransaction

logger = logging.getLogger(__name__)


class StaleCompiledPlanError(ValueError):
    """Raised when persisted compiled artifacts do not match the current Flow."""


class ProjectReadOnlyError(ValueError):
    """Raised when an imported read-only project's Flow is mutated."""


class ProjectQuarantineError(ValueError):
    """Raised when execution is attempted with quarantined imported atoms."""


class ProjectDataNotReadyError(ValueError):
    """Raised when no usable dataset run is available for execution."""


def get_import_metadata(store: ProjectStore, project_id: str) -> dict[str, Any]:
    metadata_path = store.get_output_dir(project_id) / "import_metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        result: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def assert_project_editable(store: ProjectStore, project_id: str) -> None:
    if get_import_metadata(store, project_id).get("read_only", False):
        raise ProjectReadOnlyError("IMPORTED_PROJECT_READ_ONLY: fork the imported package before editing or compiling")


def load_flow_from_compiled_package(compiled_dir: Path) -> dict[str, Any]:
    """Load the original Flow, or reconstruct an editable approximation for legacy packages."""
    flow_path = compiled_dir / "flow.json"
    if flow_path.exists():
        result: dict[str, Any] = json.loads(flow_path.read_text(encoding="utf-8"))
        return result

    plan = json.loads((compiled_dir / "plan.json").read_text(encoding="utf-8"))
    dag = json.loads((compiled_dir / "execution_dag.json").read_text(encoding="utf-8"))
    nodes = []
    for index, atom in enumerate(dag.get("atoms", dag.get("nodes", []))):
        atom_id = atom.get("atom_id") or atom.get("step_id")
        atom_type = atom.get("atom_type") or atom.get("node_type") or "unknown"
        node: dict[str, Any] = {
            "id": atom_id,
            "type": atom_type,
            "atom_type": atom_type,
            "template_id": atom.get("template_id"),
            "operation": atom.get("operation") or atom_type,
            "category": atom.get("category") or "analysis",
            "config": atom.get("parameters", {}),
            "position": {"x": index * 180, "y": 0},
            "evidence_refs": atom.get("evidence_refs", []),
        }
        if atom.get("backend_id"):
            node["backend_binding"] = {
                "backend_id": atom["backend_id"],
                "operation": atom.get("backend_operation") or atom.get("operation", ""),
                "version_spec": atom.get("backend_version_spec") or "",
            }
        nodes.append(node)
    edges = [
        {
            "id": f"imported-edge-{index + 1}",
            "source": edge.get("source", ""),
            "target": edge.get("target", ""),
            "source_handle": edge.get("source_handle", "output"),
            "target_handle": edge.get("target_handle", "input"),
        }
        for index, edge in enumerate(dag.get("edges", []))
    ]
    return {
        "schema_version": "0.3.0",
        "flow_id": plan.get("flow_id", "imported-flow"),
        "name": plan.get("name", "Imported Flow"),
        "description": plan.get("description", "Reconstructed from a legacy package"),
        "metadata": plan.get("metadata", {}),
        "nodes": nodes,
        "edges": edges,
    }


def _assert_compiled_plan_current(store: ProjectStore, project_id: str) -> None:
    """Fail closed when a run/export action targets an obsolete compiled plan."""
    from fnirs_flow.compiler.hashing import compute_flow_hash

    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return
    plan_path = store.get_output_dir(project_id) / "compiled" / "plan.json"
    if not plan_path.exists():
        return
    if get_import_metadata(store, project_id).get("read_only", False):
        # Imported plans are immutable at the service boundary and retain the
        # source package's authoritative hash, including for legacy packages
        # that did not include flow.json.
        return
    try:
        compiled_hash = json.loads(plan_path.read_text(encoding="utf-8")).get("flow_hash", "")
    except (json.JSONDecodeError, OSError) as exc:
        raise StaleCompiledPlanError("Compiled plan is unreadable; compile the Flow again") from exc
    current_hash = compute_flow_hash(flow)
    if not compiled_hash or compiled_hash != current_hash:
        raise StaleCompiledPlanError("STALE_COMPILED_PLAN: the Flow changed after compilation; compile it again")


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
    ProjectStatus,
    RunSummary,
    ValidationResult,
)
from fnirs_flow.compiler.compiler import compile_flow  # noqa: E402
from fnirs_flow.data.discovery import discover_dataset  # noqa: E402
from fnirs_flow.data.manifest import DataManifest  # noqa: E402
from fnirs_flow.data.participants import (  # noqa: E402
    ColumnRoleMap,
    read_participant_table,
    write_participant_table_artifacts,
)
from fnirs_flow.execution.engine import dry_run  # noqa: E402
from fnirs_flow.flow.snapshots import ProjectSnapshot as Snapshot  # noqa: E402
from fnirs_flow.validation.api import validate_flow  # noqa: E402


class ProjectStore:
    """Persistent project store backed by canonical single-file bundles."""

    def __init__(self, base_dir: Path):
        self._base_dir = Path(base_dir)
        self._bundles = ProjectBundleManager(self._base_dir)
        self._projects: dict[str, dict[str, Any]] = {}
        self._materialized_projects: set[str] = set()
        self._lock = threading.RLock()
        self._active_transactions: dict[str, ProjectTransaction] = {}
        self._uri_bindings = URIBindingStore(self._base_dir)
        self._debounce_timers: dict[str, threading.Timer] = {}
        self._debounce_delay: float = 1.0  # 1 second debounce
        self._load_all()
        self._recover_staging()

    def _load_all(self, *, lazy: bool = True) -> None:
        """Verify bundles and materialize their disposable working copies.

        If lazy=True, only read bundle headers without full extraction.
        If lazy=False, extract and verify all bundles.
        """
        self._projects = self._bundles.load_all(lazy=lazy)
        self._materialized_projects = set() if lazy else set(self._projects)

    def _recover_staging(self) -> None:
        """Clean up leftover staging directories from crashed transactions."""
        from fnirs_flow.api.transaction import recover_staging_directories

        staging_root = self._base_dir / ".staging"
        count = recover_staging_directories(staging_root)
        if count:
            logger.info("Recovered %d stale staging directory(ies)", count)

    def _persist(self, project_id: str, *, reason: str = "metadata_updated") -> None:
        """Atomically write metadata and replace the canonical project bundle."""
        # Skip if a transaction is active — the transaction will persist on commit
        if project_id in self._active_transactions:
            return
        proj_dir = self._bundles.workspace_path(project_id)
        proj_dir.mkdir(parents=True, exist_ok=True)
        meta_file = proj_dir / "project.json"
        temporary = proj_dir / ".project.json.tmp"
        temporary.write_text(json.dumps(self._projects[project_id], indent=2), encoding="utf-8")
        temporary.replace(meta_file)
        manifest = self._bundles.save(project_id, reason=reason)
        project = self._projects[project_id]
        project["revision"] = int(manifest.get("revision", 0))
        project["integrity_status"] = "verified"
        project["last_verified_at"] = manifest.get("saved_at")
        project["verification_scope"] = "full"
        project.pop("integrity_error", None)
        self._materialized_projects.add(project_id)

    def ensure_project_loaded(self, project_id: str) -> bool:
        """Ensure a project is fully loaded (extracted and verified).

        Returns True if the project was already loaded or was successfully loaded.
        Returns False if the project doesn't exist or couldn't be loaded.
        """
        with self._lock:
            if project_id not in self._projects:
                return False

            if project_id in self._materialized_projects:
                return True

            # Try to extract and verify the project. This replaces the
            # disposable workspace, so it must be serialized per store.
            try:
                self._bundles.extract_verified(project_id)
                workspace = self._bundles.workspace_path(project_id)
                metadata_path = workspace / "project.json"
                if not metadata_path.exists():
                    return False
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("id") != project_id:
                    return False
                metadata["integrity_status"] = "verified"
                metadata["last_verified_at"] = datetime.now(timezone.utc).isoformat()
                metadata["verification_scope"] = "full"
                self._projects[project_id] = metadata
                self._materialized_projects.add(project_id)
                return True
            except (ProjectBundleError, json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load project '%s': %s", project_id, exc)
                return False

    def register_transaction(self, project_id: str, tx: ProjectTransaction) -> None:
        """Register an active transaction for a project."""
        self._active_transactions[project_id] = tx

    def unregister_transaction(self, project_id: str) -> None:
        """Unregister an active transaction."""
        self._active_transactions.pop(project_id, None)

    def get_active_transaction(self, project_id: str) -> ProjectTransaction | None:
        """Return the active transaction for a project, if any."""
        return self._active_transactions.get(project_id)

    def bind_dataset(self, dataset_id: str, local_path: Path) -> None:
        """Bind a dataset ID to a local path for external-data:// URIs."""
        self._uri_bindings.bind(dataset_id, local_path)

    def unbind_dataset(self, dataset_id: str) -> None:
        """Remove a dataset binding."""
        self._uri_bindings.unbind(dataset_id)

    def get_dataset_binding(self, dataset_id: str) -> Path | None:
        """Get the local path for a dataset ID."""
        return self._uri_bindings.get_binding(dataset_id)

    def list_dataset_bindings(self) -> dict[str, Path]:
        """List all dataset bindings."""
        return self._uri_bindings.list_bindings()

    def _debounced_persist(self, project_id: str, reason: str = "metadata_updated") -> None:
        """Persist project with debounce to avoid excessive saves."""
        with self._lock:
            # Cancel existing timer for this project
            if project_id in self._debounce_timers:
                self._debounce_timers[project_id].cancel()

            # Create new timer
            def do_persist():
                with self._lock:
                    self._debounce_timers.pop(project_id, None)
                    self._persist(project_id, reason=reason)

            timer = threading.Timer(self._debounce_delay, do_persist)
            self._debounce_timers[project_id] = timer
            timer.start()

    def cancel_debounce(self, project_id: str) -> None:
        """Cancel any pending debounced persist for a project."""
        with self._lock:
            if project_id in self._debounce_timers:
                self._debounce_timers[project_id].cancel()
                del self._debounce_timers[project_id]

    def create(self, name: str, description: str = "") -> ProjectRead:
        if not name or not name.strip():
            raise ValueError("Project name cannot be empty")
        if len(name) > 256:
            raise ValueError("Project name too long (max 256 characters)")
        # Sanitize: project IDs are UUIDs, so no path traversal risk
        project_id = uuid.uuid4().hex[:12]
        project_dir = self._bundles.workspace_path(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self._projects[project_id] = {
                "id": project_id,
                "name": name,
                "description": description,
                "flow": {},
                "snapshots": [],
                "attempts": [],
                "state": {},
                "pending_draft": None,
            }
            self._persist(project_id, reason="project_created")

        created = self.get(project_id)
        if created is None:  # pragma: no cover - guarded by the insertion above
            raise RuntimeError("Newly created project could not be loaded")
        return created

    def _project_read(self, project_id: str, *, verify_bundle: bool) -> ProjectRead | None:
        proj = self._projects.get(project_id)
        if proj is None:
            return None
        bundle_path = self._bundles.bundle_path(project_id)
        manifest: dict[str, Any] = {
            "revision": proj.get("revision", 0),
            "saved_at": proj.get("last_verified_at"),
        }

        busy_op: str | None = None
        tx = self._active_transactions.get(project_id)
        if tx is not None:
            busy_op = tx._reason

        integrity_status = str(proj.get("integrity_status", "unknown"))
        last_verified_at = proj.get("last_verified_at")
        verification_scope = proj.get("verification_scope", "header")
        integrity_error = proj.get("integrity_error")

        if verify_bundle and bundle_path.exists():
            try:
                manifest = self._bundles.verify(bundle_path, expected_project_id=project_id)
                integrity_status = "verified"
                last_verified_at = datetime.now(timezone.utc).isoformat()
                verification_scope = "full"
                integrity_error = None
            except (ProjectBundleError, OSError) as exc:
                integrity_status = "failed"
                last_verified_at = datetime.now(timezone.utc).isoformat()
                verification_scope = "full"
                integrity_error = str(exc)

            proj["revision"] = int(manifest.get("revision", proj.get("revision", 0)))
            proj["integrity_status"] = integrity_status
            proj["last_verified_at"] = last_verified_at
            proj["verification_scope"] = verification_scope
            if integrity_error is None:
                proj.pop("integrity_error", None)
            else:
                proj["integrity_error"] = integrity_error

        return ProjectRead(
            id=proj["id"],
            name=proj["name"],
            description=proj["description"],
            flow_id=proj.get("flow", {}).get("flow_id", ""),
            package_path=str(bundle_path.resolve()),
            revision=int(manifest.get("revision", 0)),
            integrity_status=integrity_status,
            last_verified_at=last_verified_at,
            verification_scope=verification_scope,
            integrity_error=integrity_error,
            busy_operation=busy_op,
        )

    def get(self, project_id: str) -> ProjectRead | None:
        """Return a project after fully verifying its canonical bundle."""
        return self._project_read(project_id, verify_bundle=True)

    def list_all(self) -> list[ProjectRead]:
        """List projects from bounded cached headers without extracting or hashing payloads."""
        return [
            project
            for project_id in self._projects
            if (project := self._project_read(project_id, verify_bundle=False)) is not None
        ]

    def get_flow(self, project_id: str) -> dict[str, Any] | None:
        proj = self._projects.get(project_id)
        if proj is None:
            return None
        if project_id not in self._materialized_projects:
            if not self.ensure_project_loaded(project_id):
                return None
            proj = self._projects.get(project_id)
            if proj is None:
                return None
        result: dict[str, Any] = proj.get("flow", {})
        return result

    def update_flow(self, project_id: str, flow: dict[str, Any], *, debounce: bool = False) -> bool:
        if project_id not in self._materialized_projects and not self.ensure_project_loaded(project_id):
            return False
        from fnirs_flow.flow.empty_markers import normalize_empty_markers, remove_unconnected_auto_empty_markers

        metadata = flow.get("metadata") if isinstance(flow.get("metadata"), dict) else {}
        policy = metadata.get("order_policy") if isinstance(metadata.get("order_policy"), dict) else {}
        normalized_flow = (
            normalize_empty_markers(flow)
            if policy.get("allow_empty_edges") is True
            else remove_unconnected_auto_empty_markers(flow)
        )
        with self._lock:
            if project_id not in self._projects:
                return False
            self._projects[project_id]["flow"] = normalized_flow
            self._projects[project_id]["state"] = {}
            if debounce:
                self._debounced_persist(project_id, reason="flow_saved")
            else:
                self._persist(project_id, reason="flow_saved")
            return True

    def update_state(self, project_id: str, **values: Any) -> None:
        """Persist workflow state while keeping disk artifacts authoritative."""
        with self._lock:
            if project_id not in self._projects:
                return
            self._projects[project_id].setdefault("state", {}).update(values)
            self._persist(project_id, reason="project_state_updated")

    def save_draft(self, project_id: str, draft_flow: dict[str, Any]) -> bool:
        """Save a draft flow without overwriting the current project flow.

        The draft is stored as pending_draft until confirmed or discarded.
        """
        with self._lock:
            if project_id not in self._projects:
                return False
            self._projects[project_id]["pending_draft"] = draft_flow
            self._persist(project_id, reason="draft_saved")
            return True

    def get_draft(self, project_id: str) -> dict[str, Any] | None:
        """Return the pending draft flow, or None if no draft exists."""
        proj = self._projects.get(project_id)
        if proj is None:
            return None
        return proj.get("pending_draft")

    def confirm_draft(self, project_id: str) -> dict[str, Any] | None:
        """Accept the pending draft as the current project flow.

        Returns the confirmed flow, or None if no draft exists.
        """
        with self._lock:
            if project_id not in self._projects:
                return None
            draft: dict[str, Any] | None = self._projects[project_id].get("pending_draft")
            if draft is None:
                return None
            self._projects[project_id]["flow"] = draft
            self._projects[project_id]["pending_draft"] = None
            self._projects[project_id]["state"] = {}
            self._persist(project_id, reason="draft_confirmed")
            return draft

    def discard_draft(self, project_id: str) -> bool:
        """Discard the pending draft without applying it."""
        with self._lock:
            if project_id not in self._projects:
                return False
            if self._projects[project_id].get("pending_draft") is None:
                return False
            self._projects[project_id]["pending_draft"] = None
            self._persist(project_id, reason="draft_discarded")
            return True

    def commit_project(self, project_id: str, *, reason: str) -> None:
        """Save direct output-file mutations into the canonical bundle."""
        # Skip if a transaction is active — the transaction will persist on commit
        if project_id in self._active_transactions:
            return
        with self._lock:
            if project_id not in self._projects:
                return
            self._bundles.save(project_id, reason=reason)

    def get_package_path(self, project_id: str) -> Path:
        return self._bundles.bundle_path(project_id)

    def get_bundle_status(self, project_id: str) -> dict[str, Any] | None:
        if project_id not in self._projects:
            return None
        bundle = self._bundles.bundle_path(project_id)
        versions = self._bundles.list_versions(project_id)

        busy_op: str | None = None
        lock_owner: str | None = None
        tx = self._active_transactions.get(project_id)
        if tx is not None:
            busy_op = tx._reason
            lock_owner = tx.tx_id

        # Perform actual integrity verification
        integrity_status = "unknown"
        last_verified_at = None
        verification_scope = None
        integrity_error = None
        manifest: dict[str, Any] = {}

        try:
            # Verify bundle integrity
            manifest = self._bundles.verify(bundle, expected_project_id=project_id)
            integrity_status = "verified"
            last_verified_at = datetime.now(timezone.utc).isoformat()
            verification_scope = "full"
        except Exception as e:
            integrity_status = "failed"
            integrity_error = str(e)

        return {
            "project_id": project_id,
            "package_path": str(bundle.resolve()),
            "storage_format": "fnirsflow_bundle",
            "revision": int(manifest.get("revision", 0)),
            "saved_at": manifest.get("saved_at", ""),
            "save_reason": manifest.get("reason", ""),
            "size_bytes": bundle.stat().st_size,
            "integrity_status": integrity_status,
            "last_verified_at": last_verified_at,
            "verification_scope": verification_scope,
            "integrity_error": integrity_error,
            "versions": versions,
            "busy_operation": busy_op,
            "lock_owner": lock_owner,
        }

    def restore_bundle_revision(self, project_id: str, revision: int) -> ProjectRead | None:
        from fnirs_flow.api.transaction import ProjectTransaction

        if project_id not in self._projects:
            return None

        with ProjectTransaction(self, project_id, reason=f"restored_revision_{revision}") as tx:
            # Extract retained version to staging instead of workspace
            self._bundles.extract_retained_to(project_id, revision, tx.staging_dir)
            # Reload in-memory metadata from the extracted version
            meta_path = tx.staging_dir / "project.json"
            if meta_path.exists():
                self._projects[project_id] = json.loads(
                    meta_path.read_text(encoding="utf-8")
                )
            tx.commit()

        return self.get(project_id)

    def get_version_history(self, project_id: str) -> list[dict[str, Any]]:
        """Get version history for a project."""
        if project_id not in self._projects:
            return []
        return self._bundles.list_versions(project_id)

    def get_output_dir(self, project_id: str) -> Path:
        tx = self._active_transactions.get(project_id)
        if tx is not None:
            return tx.output_dir
        return self._bundles.workspace_path(project_id) / "outputs"

    def create_snapshot(self, project_id: str) -> ProjectSnapshot | None:
        """Create an immutable snapshot of the current flow."""
        flow = self.get_flow(project_id)
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

        with self._lock:
            self._projects[project_id]["snapshots"].append(snapshot.model_dump())
            self._persist(project_id, reason="flow_snapshot_created")

        return ProjectSnapshot(
            snapshot_id=snapshot_id,
            flow_hash=flow_hash,
            created_at=snapshot.created_at,
        )

    # -- Design History (FlowVCS) --

    def _history_service(self, project_id: str) -> HistoryService:
        """Return a HistoryService backed by the project's workspace."""
        self.ensure_project_loaded(project_id)
        workspace = self._bundles.workspace_path(project_id)
        return HistoryService(ZipJsonHistoryStore(workspace))

    def initialize_design_history(self, project_id: str) -> str:
        """Initialize design history for a project. Returns root commit_id."""
        self.ensure_project_loaded(project_id)
        flow = self._projects[project_id].get("flow", {})
        svc = self._history_service(project_id)
        commit_id = svc.initialize(flow)
        self._persist(project_id, reason="design_history_initialized")
        return commit_id

    def commit_design(
        self,
        project_id: str,
        message: str = "",
        *,
        reason: str = "manual_design_commit",
    ) -> str:
        """Create a new design commit from the current flow."""
        self.ensure_project_loaded(project_id)
        flow = self._projects[project_id].get("flow", {})
        svc = self._history_service(project_id)
        commit_id = svc.commit(flow, message, reason=reason)
        self._persist(project_id, reason="design_commit")
        return commit_id

    def create_design_branch(
        self, project_id: str, name: str, from_commit_id: str | None = None
    ) -> dict[str, Any]:
        """Create a new design branch."""
        svc = self._history_service(project_id)
        branch = svc.create_branch(name, from_commit_id)
        return branch.model_dump()

    def delete_design_branch(self, project_id: str, name: str) -> None:
        """Delete a design branch."""
        svc = self._history_service(project_id)
        svc.delete_branch(name)

    def list_design_branches(self, project_id: str) -> list[dict[str, Any]]:
        """List all design branches."""
        svc = self._history_service(project_id)
        return [b.model_dump() for b in svc.list_branches()]

    def switch_design_branch(self, project_id: str, target: str) -> dict[str, Any]:
        """Switch to a branch or commit. Returns the target flow."""
        svc = self._history_service(project_id)
        flow = svc.checkout(target)
        # Update the working copy
        with self._lock:
            self._projects[project_id]["flow"] = flow
            self._projects[project_id]["state"] = {}
        self._persist(project_id, reason="design_checkout")
        return flow

    def list_design_commits(
        self,
        project_id: str,
        branch: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List design commits."""
        svc = self._history_service(project_id)
        return [c.model_dump() for c in svc.list_commits(branch, limit=limit, offset=offset)]

    def get_design_diff(
        self, project_id: str, from_commit: str, to_commit: str
    ) -> dict[str, Any]:
        """Get structured diff between two design commits."""
        svc = self._history_service(project_id)
        return svc.diff(from_commit, to_commit).model_dump()

    def is_design_dirty(self, project_id: str) -> bool:
        """Check if the current flow differs from design HEAD."""
        self.ensure_project_loaded(project_id)
        flow = self._projects[project_id].get("flow", {})
        svc = self._history_service(project_id)
        if not svc.store.is_initialized():
            return False
        return svc.check_dirty(flow)

    def get_design_head(self, project_id: str) -> dict[str, Any] | None:
        """Get the HEAD design commit info."""
        svc = self._history_service(project_id)
        if not svc.store.is_initialized():
            return None
        return svc.get_head_commit().model_dump()

    def migrate_snapshots_to_history(self, project_id: str) -> dict[str, Any]:
        """Import legacy snapshots into design history. Returns migration report."""
        self.ensure_project_loaded(project_id)
        proj = self._projects[project_id]
        snapshots = proj.get("snapshots", [])
        current_flow = proj.get("flow", {})
        svc = self._history_service(project_id)
        # Initialize history if not already done
        if not svc.store.is_initialized():
            svc.initialize(current_flow)
        from fnirs_flow.history.migration import migrate_snapshots_to_history
        report = migrate_snapshots_to_history(svc, snapshots, current_flow=current_flow)
        if report.success:
            self._persist(project_id, reason="history_migration")
        return report.model_dump()

    def get_lock_info(self, project_id: str) -> dict[str, Any]:
        """Return the current lock status for a project."""
        from fnirs_flow.api.concurrency import get_lock_registry

        lock_dir = self._base_dir / ".locks"
        registry = get_lock_registry(lock_dir=lock_dir)
        return registry.get_lock_info(project_id)


def validate_project_flow(store: ProjectStore, project_id: str) -> ValidationResult:
    """Validate a project's flow."""
    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return ValidationResult(is_valid=False, errors=["No flow found for project"])

    report = validate_flow(flow)
    result = ValidationResult(
        is_valid=report.is_valid and not report.has_fatal_risks,
        errors=report.errors,
        warnings=report.warnings,
        risks=[r.model_dump() for r in report.risks],
    )
    from fnirs_flow.compiler.hashing import compute_flow_hash

    store.update_state(
        project_id,
        validated_flow_hash=compute_flow_hash(flow) if result.is_valid else "",
    )
    return result


def compile_project_flow(
    store: ProjectStore,
    project_id: str,
    *,
    base_revision: int | None = None,
) -> CompileResult | None:
    """Compile a project's flow to plan/dag.

    Outputs are written to ``<project>/outputs/compiled/``.
    """
    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return None

    from fnirs_flow.api.transaction import ProjectTransaction

    with ProjectTransaction(
        store, project_id, reason="compile", base_revision=base_revision
    ) as tx:
        outdir = tx.output_dir
        result = compile_flow(flow, outdir)
        store.update_state(project_id, compiled_flow_hash=result.flow_hash)
        tx.commit()

    compiled_dir = store.get_output_dir(project_id) / "compiled"
    atom_types = list({n.atom_type or n.node_type for n in result.execution_dag.nodes})
    node_by_id = {n.atom_id or n.step_id: n for n in result.execution_dag.nodes}
    dag_layers = [
        [
            {
                "id": node.atom_id or node.step_id,
                "atom_type": node.atom_type or node.node_type,
                "node_type": node.node_type,
                "operation": node.operation or "",
            }
            for atom_id in layer
            if (node := node_by_id.get(atom_id)) is not None
        ]
        for layer in result.execution_dag.execution_layers
    ]

    return CompileResult(
        flow_id=result.flow_graph.flow_id,
        flow_hash=result.flow_hash,
        steps=len(result.execution_dag.nodes),
        layers=len(result.execution_dag.execution_layers),
        output_files=[f.name for f in sorted(compiled_dir.iterdir()) if is_visible_data_file(f, root=compiled_dir)],
        dag_layers=dag_layers,
        atoms=len(result.execution_dag.nodes),
        atom_types=sorted(atom_types),
    )


def discover_project_data(
    store: ProjectStore,
    project_id: str,
    dataset_id: str,
    *,
    base_revision: int | None = None,
) -> DiscoverResult:
    """Discover a dataset for a project."""
    from fnirs_flow.api.transaction import ProjectTransaction

    with ProjectTransaction(
        store, project_id, reason="discover_data", base_revision=base_revision
    ) as tx:
        outdir = tx.output_dir
        manifest = discover_dataset(dataset_id, outdir)
        if manifest.runtime_local_root:
            store.bind_dataset(manifest.dataset_id, Path(manifest.runtime_local_root))
        result = DiscoverResult(
            dataset_id=manifest.dataset_id,
            files=len(manifest.files),
            runs=len(manifest.subject_session_runs),
            local_root=manifest.runtime_local_root,
            source_url=manifest.source.url,
            metadata_tables=len(manifest.metadata_tables),
        )
        store.update_state(project_id, dataset_id=manifest.dataset_id, discovered_runs=result.runs)
        tx.commit()

    return result


def import_project_participant_table(
    store: ProjectStore,
    project_id: str,
    path: str,
    *,
    table_kind: str = "participant",
    id_column: str = "participant_id",
    include_column: str = "include",
    group_column: str = "group",
    label_column: str = "",
    site_column: str = "site",
    scanner_column: str = "scanner_id",
    covariate_columns: list[str] | None = None,
    session_column: str = "session",
    timepoint_column: str = "timepoint",
    pair_id_column: str = "pair_id",
    dyad_id_column: str = "dyad_id",
    participant_role_column: str = "participant_role",
    delimiter: str = "auto",
    encoding: str = "utf-8-sig",
    base_revision: int | None = None,
) -> dict[str, Any] | None:
    if store.get(project_id) is None:
        return None

    from fnirs_flow.api.transaction import ProjectTransaction

    with ProjectTransaction(
        store, project_id, reason="participant_metadata_imported", base_revision=base_revision
    ) as tx:
        outdir = tx.output_dir
        compiled_dir = outdir / "compiled"
        manifest_path = compiled_dir / "data_manifest.json"
        manifest: DataManifest | None = None
        if manifest_path.exists():
            try:
                manifest = DataManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                manifest = None
        column_role_map = ColumnRoleMap(
            id_column=id_column,
            include_column=include_column,
            group_column=group_column,
            label_column=label_column,
            site_column=site_column,
            scanner_column=scanner_column,
            covariate_columns=covariate_columns or [],
            session_column=session_column,
            timepoint_column=timepoint_column,
            pair_id_column=pair_id_column,
            dyad_id_column=dyad_id_column,
            participant_role_column=participant_role_column,
        )
        table = read_participant_table(
            path,
            table_kind="observation" if table_kind == "observation" else "participant",
            id_column=id_column,
            include_column=include_column,
            delimiter=delimiter,
            encoding=encoding,
            column_role_map=column_role_map,
        )
        bundle = write_participant_table_artifacts(table, compiled_dir, manifest=manifest)
        tx.commit()

    return {
        "table_kind": table.table_kind,
        "rows": len(table.rows),
        "columns": [column.model_dump() for column in table.columns],
        "manifest": bundle.participant_table_manifest.model_dump(),
        "column_role_map": bundle.column_role_map.model_dump(),
        "validation_report": bundle.validation_report.model_dump(),
        "preview_rows": bundle.preview_rows,
    }


def dry_run_project(store: ProjectStore, project_id: str) -> DryRunResult | None:
    """Execute a dry-run for a project."""
    outdir = store.get_output_dir(project_id)
    _assert_compiled_plan_current(store, project_id)
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
    except (OSError, KeyError, ValueError):
        raise


def create_snapshot(store: ProjectStore, project_id: str) -> ProjectSnapshot | None:
    """Create an immutable snapshot of the current flow."""
    return store.create_snapshot(project_id)


def validate_project_execution(store: ProjectStore, project_id: str) -> bool:
    """Validate execution prerequisites without starting scientific work."""
    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return False

    outdir = store.get_output_dir(project_id)
    compiled_dir = outdir / "compiled"

    # Check that compiled plan exists
    dag_path = compiled_dir / "execution_dag.json"
    if not dag_path.exists():
        return False
    _assert_compiled_plan_current(store, project_id)
    manifest = _load_data_manifest(compiled_dir) or {}
    dataset_id = str(manifest.get("dataset_id", ""))
    binding = store.get_dataset_binding(dataset_id) if dataset_id else None
    _assert_project_data_ready(compiled_dir, binding)
    quarantined = get_import_metadata(store, project_id).get("quarantined_atoms", [])
    if quarantined:
        raise ProjectQuarantineError(
            "QUARANTINED_ATOMS: explicitly trust these atoms before execution: " + ", ".join(quarantined)
        )
    return True


def execute_project_runs(
    store: ProjectStore,
    project_id: str,
    *,
    attempt_id: str = "",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> ExecuteResult | None:
    """Execute runs for a project using the unified ExecutionService."""
    if not validate_project_execution(store, project_id):
        return None

    outdir = store.get_output_dir(project_id)

    try:
        from fnirs_flow.execution.service import (
            ExecutionCancelledError,
            ExecutionRequest,
            ExecutionService,
        )

        # Auto-create ProjectSnapshot before execute if flow has changed
        snap = create_snapshot(store, project_id)

        # Capture design commit_id for provenance anchoring
        design_head = store.get_design_head(project_id)
        design_commit_id = design_head["commit_id"] if design_head else ""
        snapshot_id = snap.snapshot_id if snap else ""

        # Create execution request
        manifest = _load_data_manifest(outdir / "compiled") or {}
        dataset_id = str(manifest.get("dataset_id", ""))
        binding = store.get_dataset_binding(dataset_id) if dataset_id else None
        request = ExecutionRequest(
            project_dir=str(outdir),
            data_root=str(binding) if binding else None,
            outdir=str(outdir),
            attempt_id=attempt_id,
            commit_id=design_commit_id,
            snapshot_id=snapshot_id,
        )

        # Execute via ExecutionService
        service = ExecutionService(
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        result = service.execute(request)

        response = ExecuteResult(
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
                            output_handles=ar.output_handles,
                            artifacts=[
                                ArtifactSummary(
                                    artifact_id=art.get("artifact_id", ""),
                                    type=art.get("type", ""),
                                    uri=art.get("uri", art.get("path", "")),
                                    path=art.get("path", ""),
                                    resolved_path=art.get("resolved_path", ""),
                                    relative_path=art.get("relative_path", ""),
                                    checksum=art.get("checksum", ""),
                                    exists=art.get("exists", False),
                                    atom_id=art.get("atom_id", ar.atom_id),
                                    step_id=art.get("step_id", ""),
                                )
                                for art in ar.artifacts
                            ],
                            warnings=ar.warnings,
                            error=ar.error,
                        )
                        for ar in rr.atom_results
                    ],
                    artifacts=[
                        ArtifactSummary(
                            artifact_id=art.get("artifact_id", ""),
                            type=art.get("type", ""),
                            uri=art.get("uri", art.get("path", "")),
                            path=art.get("path", ""),
                            resolved_path=art.get("resolved_path", ""),
                            relative_path=art.get("relative_path", ""),
                            checksum=art.get("checksum", ""),
                            exists=art.get("exists", False),
                            atom_id=art.get("atom_id", ""),
                            step_id=art.get("step_id", ""),
                        )
                        for art in rr.artifacts
                    ],
                )
                for rr in result.run_results
            ],
            failure_ids=result.failure_ids,
        )
        store.update_state(
            project_id,
            last_attempt_id=result.attempt_id,
            last_execution_status="failed" if result.failed_runs else "completed",
        )
        return response
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        if isinstance(e, ProjectDataNotReadyError):
            raise
        if isinstance(e, ExecutionCancelledError):
            store.update_state(
                project_id,
                last_attempt_id=attempt_id,
                last_execution_status="cancelled",
            )
            logger.info("Execution cancelled for project %s", project_id)
            raise
        logger.exception("Execute failed for project %s: %s", project_id, e)
        raise


def _load_data_manifest(compiled_dir: Path) -> dict[str, Any] | None:
    for path in (compiled_dir / "data_manifest.json", compiled_dir.parent / "data_manifest.json"):
        if path.exists():
            try:
                result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
                return result
            except (json.JSONDecodeError, OSError):
                return None
    return None


def _runnable_manifest_runs(compiled_dir: Path, data_root: Path | None = None) -> int:
    manifest = _load_data_manifest(compiled_dir)
    if not manifest:
        return 0
    from fnirs_flow.api.uri import ProjectURI

    local_root = data_root
    runnable = 0
    for run in manifest.get("subject_session_runs", []):
        value = str(run.get("uri") or run.get("path", ""))
        if value.startswith("external-data://") and local_root is not None:
            try:
                candidate = local_root / Path(*ProjectURI(value).path.parts)
            except ValueError:
                continue
        else:
            candidate = Path(value) if value else Path()
        if value and candidate.is_file():
            runnable += 1
    return runnable


def _assert_project_data_ready(compiled_dir: Path, data_root: Path | None = None) -> None:
    if _runnable_manifest_runs(compiled_dir, data_root) == 0:
        raise ProjectDataNotReadyError(
            "DATA_NOT_READY: discover or relink at least one existing data run before execution"
        )


def get_project_status(store: ProjectStore, project_id: str) -> ProjectStatus | None:
    """Derive readiness from persisted Flow and artifacts so reloads are stable."""
    project = store.get(project_id)
    if project is None:
        return None
    flow = store.get_flow(project_id) or {}
    from fnirs_flow.compiler.hashing import compute_flow_hash

    flow_hash = compute_flow_hash(flow) if flow else ""
    state = store._projects.get(project_id, {}).get("state", {})
    compiled_dir = store.get_output_dir(project_id) / "compiled"
    plan_path = compiled_dir / "plan.json"
    compiled_hash = ""
    if plan_path.exists():
        try:
            compiled_hash = json.loads(plan_path.read_text(encoding="utf-8")).get("flow_hash", "")
        except (json.JSONDecodeError, OSError):
            compiled_hash = ""
    metadata = get_import_metadata(store, project_id)
    read_only = bool(metadata.get("read_only", False))
    # Imported immutable packages may not contain a source Flow with the exact
    # original hash; their verified compiled plan remains authoritative.
    compiled = bool(compiled_hash and (read_only or compiled_hash == flow_hash))
    manifest = _load_data_manifest(compiled_dir) or {}
    dataset_id = str(manifest.get("dataset_id", ""))
    binding = store.get_dataset_binding(dataset_id) if dataset_id else None
    runnable_runs = _runnable_manifest_runs(compiled_dir, binding) if compiled else 0
    validated = bool(flow_hash and (state.get("validated_flow_hash") == flow_hash or (read_only and compiled)))
    return ProjectStatus(
        flow_saved=bool(flow),
        validated=validated,
        compiled=compiled,
        data_discovered=runnable_runs > 0,
        runnable_runs=runnable_runs,
        executed=bool(state.get("last_attempt_id")),
        flow_hash=flow_hash,
        compiled_flow_hash=compiled_hash,
        last_attempt_id=state.get("last_attempt_id", ""),
        last_execution_status=state.get("last_execution_status", ""),
        read_only=read_only,
        quarantined_atoms=list(metadata.get("quarantined_atoms", [])),
    )


def export_project_package(
    store: ProjectStore,
    project_id: str,
    profile_id: str = "reproducibility_package",
) -> ExportResult | None:
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
    _assert_compiled_plan_current(store, project_id)

    import shutil
    import tempfile

    from fnirs_flow.exporters.package_exporter import export_package, get_package_contents

    pkg_path = None
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_pkg = Path(tmp_dir) / f"{project_id}.fnirsflow.zip"
            export_package(compiled_dir, tmp_pkg, profile_id=profile_id)
            # Copy to final location in export/
            final_dir = outdir / "export"
            final_dir.mkdir(parents=True, exist_ok=True)
            pkg_path = final_dir / tmp_pkg.name
            shutil.copy2(tmp_pkg, pkg_path)
            remove_macos_metadata_paths(outdir.parent)
        return ExportResult(
            package_path=str(pkg_path),
            size_bytes=pkg_path.stat().st_size,
            profile=profile_id,
            contents=get_package_contents(pkg_path),
        )
    except Exception as e:
        logger.error("Package export failed: %s", e)
        if pkg_path and pkg_path.exists():
            pkg_path.unlink(missing_ok=True)
        raise
