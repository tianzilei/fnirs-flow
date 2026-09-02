"""Project repository and application use-case implementations."""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

from fnirs_flow.history.service import HistoryService
from fnirs_flow.history.zip_json_store import ZipJsonHistoryStore
from fnirs_flow.infrastructure.filesystem import is_visible_data_file, remove_macos_metadata_paths
from fnirs_flow.infrastructure.portability import is_absolute_local_path
from fnirs_flow.infrastructure.project_bundle import ProjectBundleError, ProjectBundleManager
from fnirs_flow.infrastructure.project_data_roots import ProjectDataRootStore as _ProjectDataRootStore
from fnirs_flow.infrastructure.uri import URIBindingStore

if TYPE_CHECKING:
    from fnirs_flow.infrastructure.transaction import ProjectTransaction

logger = logging.getLogger(__name__)

# Compatibility export for callers that historically imported this store here.
ProjectDataRootStore = _ProjectDataRootStore

_PATH_FIELD_PATTERN = re.compile(
    r"(^|_)(path|paths|file|files|dir|dirs|folder|folders|directory|csv|tsv|snirf|bids_dir|reference_dir)$"
)


def normalize_project_relative_path(value: str, *, label: str = "Project data path", allow_empty: bool = False) -> str:
    """Normalize a project-data-root relative path, rejecting absolute or escaping paths."""
    raw = str(value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise ValueError(f"{label} must be a non-empty project-relative path")
    normalized = raw.replace("\\", "/").strip("/")
    if is_absolute_local_path(raw) or raw.startswith("~") or "://" in raw:
        raise ValueError(f"{label} must be project-relative; absolute paths are not allowed")
    if not normalized:
        if allow_empty:
            return ""
        raise ValueError(f"{label} must be a non-empty project-relative path")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} contains an unsafe path segment")
    if any(":" in part for part in parts):
        raise ValueError(f"{label} cannot contain ':'")
    return PurePosixPath(*parts).as_posix()


def resolve_project_data_path(
    store: ProjectStore,
    project_id: str,
    relative_path: str,
    *,
    label: str = "Project data path",
    must_exist: bool = True,
    must_be_file: bool = False,
    must_be_dir: bool = False,
    allow_empty: bool = False,
) -> tuple[Path, str]:
    """Resolve a project-relative data path inside the project's configured data root."""
    root_value = store.get_project_data_root(project_id)
    if not root_value:
        raise ValueError("Project data folder is not configured")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError("Project data folder does not exist or is not a directory")
    rel = normalize_project_relative_path(relative_path, label=label, allow_empty=allow_empty)
    candidate = root if not rel else (root / Path(*PurePosixPath(rel).parts)).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"{label} must stay inside the project data folder")
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"{label} does not exist")
    if must_be_file and not candidate.is_file():
        raise FileNotFoundError(f"{label} does not exist or is not a file")
    if must_be_dir and not candidate.is_dir():
        raise FileNotFoundError(f"{label} does not exist or is not a directory")
    return candidate, rel


def _is_import_path_atom(atom: dict[str, Any]) -> bool:
    fields = [
        str(atom.get("category", "")),
        str(atom.get("atom_type", "")),
        str(atom.get("operation", "")),
        str(atom.get("template_id", "")),
    ]
    lowered = " ".join(fields).lower()
    return "data_import" in lowered or "import" in lowered or "reader" in lowered or "input" in lowered


def _iter_path_field_values(value: Any, location: str = "$"):
    if isinstance(value, dict):
        for key, item in value.items():
            child_location = f"{location}.{key}"
            key_text = str(key)
            if isinstance(item, str) and _PATH_FIELD_PATTERN.search(key_text):
                yield child_location, item
            elif isinstance(item, (dict, list)):
                yield from _iter_path_field_values(item, child_location)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child_location = f"{location}[{index}]"
            if isinstance(item, str) and _PATH_FIELD_PATTERN.search(location.rsplit(".", 1)[-1]):
                yield child_location, item
            elif isinstance(item, (dict, list)):
                yield from _iter_path_field_values(item, child_location)


def _validate_import_atom_project_paths(flow: dict[str, Any]) -> None:
    from fnirs_flow.flow.serialization import normalize_flow_payload

    atoms = normalize_flow_payload(flow).get("flow_atoms", [])
    for atom_index, atom in enumerate(atoms):
        if not isinstance(atom, dict) or not _is_import_path_atom(atom):
            continue
        atom_id = str(atom.get("id") or atom.get("atom_id") or atom_index)
        for field, path_value in _iter_path_field_values(atom):
            if not path_value.strip():
                continue
            try:
                normalize_project_relative_path(path_value, label=f"Atom {atom_id} {field}")
            except ValueError as exc:
                raise ProjectBundleError(f"Import atom paths must be project-relative; {exc}") from exc


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
    atoms = []
    for index, atom in enumerate(execution_atoms(dag)):
        atom_id = atom.get("atom_id")
        atom_type = atom.get("atom_type") or "unknown"
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
        atoms.append(node)
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
        "schema_version": "0.4.0",
        "flow_id": plan.get("flow_id", "imported-flow"),
        "name": plan.get("name", "Imported Flow"),
        "description": plan.get("description", "Reconstructed from a legacy package"),
        "metadata": plan.get("metadata", {}),
        "flow_atoms": atoms,
        "edges": edges,
    }


def _assert_compiled_plan_current(store: ProjectStore, project_id: str) -> None:
    """Fail closed when a run/export action targets an obsolete compiled plan."""
    from fnirs_flow.compiler.matching import flows_match

    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return
    plan_path = store.get_output_dir(project_id) / "compiled" / "plan.json"
    if not plan_path.exists():
        return
    if get_import_metadata(store, project_id).get("read_only", False):
        # Imported plans are immutable at the service boundary.
        return
    try:
        compiled_flow = json.loads((plan_path.parent / "flow.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise StaleCompiledPlanError("Compiled plan is unreadable; compile the Flow again") from exc
    if not flows_match(compiled_flow, flow):
        raise StaleCompiledPlanError("STALE_COMPILED_PLAN: the Flow changed after compilation; compile it again")


from fnirs_flow.application.execution_use_cases import dry_run_compiled_project  # noqa: E402
from fnirs_flow.application.flow_use_cases import (  # noqa: E402
    compile_flow_payload,
    validate_flow_payload,
)
from fnirs_flow.application.models import (  # noqa: E402
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
from fnirs_flow.compiler.execution_dag import ExecutionDag  # noqa: E402
from fnirs_flow.execution.dag_payload import execution_atoms, normalize_execution_dag_payload  # noqa: E402
from fnirs_flow.flow.snapshots import ProjectSnapshot as Snapshot  # noqa: E402


class ProjectStore:
    """Persistent project store backed by canonical single-file bundles."""

    def __init__(self, base_dir: Path, *, bundle_retention: int = 10):
        self._base_dir = Path(base_dir)
        self._bundles = ProjectBundleManager(
            self._base_dir,
            retained_versions=bundle_retention,
        )
        self._projects: dict[str, dict[str, Any]] = {}
        self._materialized_projects: set[str] = set()
        self._lock = threading.RLock()
        self._active_transactions: dict[str, ProjectTransaction] = {}
        self._uri_bindings = URIBindingStore(self._base_dir)
        self._project_data_roots = ProjectDataRootStore(self._base_dir)
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
        from fnirs_flow.infrastructure.transaction import recover_staging_directories

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
            last_error: Exception | None = None
            for attempt in range(2):
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
                    last_error = exc
                    if attempt == 0:
                        continue
            logger.warning("Failed to load project '%s': %s", project_id, last_error)
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

    def set_project_data_root(self, project_id: str, data_root: str) -> None:
        """Set a machine-local default data root for a project."""
        self._project_data_roots.set(project_id, data_root)

    def get_project_data_root(self, project_id: str) -> str:
        """Get the machine-local default data root for a project."""
        return self._project_data_roots.get(project_id)

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

    def create(self, name: str, description: str = "", *, data_root: str = "") -> ProjectRead:
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
                "recommendation_decisions": [],
                "current_recommendation_decision_id": None,
                "state": {},
                "pending_draft": None,
            }
            self._persist(project_id, reason="project_created")
            self.set_project_data_root(project_id, data_root)

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
            data_root=self.get_project_data_root(project_id),
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

        raw_metadata = flow.get("metadata")
        metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
        raw_policy = metadata.get("order_policy")
        policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
        normalized_flow = (
            normalize_empty_markers(flow)
            if policy.get("allow_empty_edges") is True
            else remove_unconnected_auto_empty_markers(flow)
        )
        _validate_import_atom_project_paths(normalized_flow)
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
        from fnirs_flow.infrastructure.transaction import ProjectTransaction

        if project_id not in self._projects:
            return None

        with ProjectTransaction(self, project_id, reason=f"restored_revision_{revision}") as tx:
            # Extract retained version to staging instead of workspace
            self._bundles.extract_retained_to(project_id, revision, tx.staging_dir)
            # Reload in-memory metadata from the extracted version
            meta_path = tx.staging_dir / "project.json"
            if meta_path.exists():
                self._projects[project_id] = json.loads(meta_path.read_text(encoding="utf-8"))
            tx.commit()

        return self.get(project_id)

    def get_version_history(self, project_id: str) -> list[dict[str, Any]]:
        """Get version history for a project."""
        if project_id not in self._projects:
            return []
        return self._bundles.list_versions(project_id)

    def get_project_snapshots(self, project_id: str) -> list[dict[str, Any]]:
        """Return detached snapshot records in creation order."""
        if not self.ensure_project_loaded(project_id):
            return []
        with self._lock:
            return cast(
                list[dict[str, Any]],
                json.loads(json.dumps(self._projects[project_id].get("snapshots", []))),
            )

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

        revision = int(self._projects[project_id].get("revision", 0))
        snapshot_id = f"snap-{revision}-{len(self._projects[project_id]['snapshots']) + 1}"

        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            flow=flow,
            revision=revision,
            created_at=datetime.now(timezone.utc).isoformat(),
            recommendation_decision_id=self._projects[project_id].get("current_recommendation_decision_id"),
            recommendation_rules_version=(
                self._projects[project_id].get("current_recommendation_rules_version")
            ),
        )

        with self._lock:
            self._projects[project_id]["snapshots"].append(snapshot.model_dump())
            try:
                self._persist(project_id, reason="flow_snapshot_created")
            except Exception:
                stored_snapshots = self._projects[project_id]["snapshots"]
                if stored_snapshots and stored_snapshots[-1].get("snapshot_id") == snapshot_id:
                    stored_snapshots.pop()
                raise

        return ProjectSnapshot(
            snapshot_id=snapshot_id,
            revision=revision,
            created_at=snapshot.created_at,
            recommendation_decision_id=snapshot.recommendation_decision_id,
            recommendation_rules_version=snapshot.recommendation_rules_version,
        )

    def save_recommendation_decision(self, project_id: str, decision: Any) -> Any:
        """Persist an immutable recommendation decision in the project bundle."""
        from fnirs_flow.recommendation.contracts import RecommendationDecision

        self.ensure_project_loaded(project_id)
        if project_id not in self._projects:
            raise KeyError(project_id)
        validated = (
            decision
            if isinstance(decision, RecommendationDecision)
            else RecommendationDecision.model_validate(decision)
        )
        with self._lock:
            records = self._projects[project_id].setdefault("recommendation_decisions", [])
            if any(item.get("decision_id") == validated.decision_id for item in records):
                raise ValueError(f"Recommendation decision already exists: {validated.decision_id}")
            records.append(validated.model_dump(mode="json"))
            self._projects[project_id]["current_recommendation_decision_id"] = validated.decision_id
            self._projects[project_id]["current_recommendation_rules_version"] = validated.rules_version
            # Materialize the selected decision for package/report consumers.
            output_dir = self.get_output_dir(project_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "recommendation_decision.json").write_text(
                json.dumps(validated.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self._persist(project_id, reason="recommendation_decision_saved")
        return validated

    def get_recommendation_decision(self, project_id: str, decision_id: str | None = None) -> Any | None:
        from fnirs_flow.recommendation.contracts import RecommendationDecision

        self.ensure_project_loaded(project_id)
        project = self._projects.get(project_id)
        if project is None:
            return None
        target = decision_id or project.get("current_recommendation_decision_id")
        for raw in project.get("recommendation_decisions", []):
            if raw.get("decision_id") == target:
                return RecommendationDecision.model_validate(raw)
        return None

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

    def create_design_branch(self, project_id: str, name: str, from_commit_id: str | None = None) -> dict[str, Any]:
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

    def get_design_diff(self, project_id: str, from_commit: str, to_commit: str) -> dict[str, Any]:
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
        from fnirs_flow.infrastructure.concurrency import get_lock_registry

        lock_dir = self._base_dir / ".locks"
        registry = get_lock_registry(lock_dir=lock_dir)
        return registry.get_lock_info(project_id)


def validate_project_flow(store: ProjectStore, project_id: str) -> ValidationResult:
    """Validate a project's flow."""
    flow = store.get_flow(project_id)
    if flow is None or not flow:
        return ValidationResult(is_valid=False, errors=["No flow found for project"])

    report = validate_flow_payload(flow)
    result = ValidationResult(
        is_valid=report.is_valid and not report.has_fatal_risks,
        errors=report.errors,
        warnings=report.warnings,
        risks=[r.model_dump() for r in report.risks],
    )
    store.update_state(
        project_id,
        validated_flow=flow if result.is_valid else {},
        validated_revision=(int(getattr(store.get(project_id), "revision", 0)) if result.is_valid else 0),
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

    from fnirs_flow.infrastructure.transaction import ProjectTransaction

    with ProjectTransaction(store, project_id, reason="compile", base_revision=base_revision) as tx:
        outdir = tx.output_dir
        result = compile_flow_payload(flow, outdir)
        store.update_state(
            project_id,
            compiled_revision=int(store._projects[project_id].get("revision", 0)),
        )
        tx.commit()

    compiled_dir = store.get_output_dir(project_id) / "compiled"
    atom_types = list({atom.atom_type for atom in result.execution_dag.atoms})
    node_by_id = {atom.atom_id: atom for atom in result.execution_dag.atoms}
    dag_layers = [
        [
            {
                "id": node.atom_id,
                "atom_type": node.atom_type,
                "operation": node.operation or "",
            }
            for atom_id in layer
            if (node := node_by_id.get(atom_id)) is not None
        ]
        for layer in result.execution_dag.execution_layers
    ]

    return CompileResult(
        flow_id=result.flow_graph.flow_id,
        revision=int(store._projects[project_id].get("revision", 0)),
        steps=len(result.execution_dag.atoms),
        layers=len(result.execution_dag.execution_layers),
        output_files=[f.name for f in sorted(compiled_dir.iterdir()) if is_visible_data_file(f, root=compiled_dir)],
        dag_layers=dag_layers,
        atoms=len(result.execution_dag.atoms),
        atom_types=sorted(atom_types),
    )


def load_project_compile_result(store: ProjectStore, project_id: str) -> CompileResult | None:
    """Rehydrate the last compiled summary from persisted plan/DAG artifacts."""
    if store.get(project_id) is None:
        return None
    compiled_dir = store.get_output_dir(project_id) / "compiled"
    plan_path = compiled_dir / "plan.json"
    dag_path = compiled_dir / "execution_dag.json"
    if not plan_path.exists() or not dag_path.exists():
        return None
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        dag = json.loads(dag_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    execution_dag = ExecutionDag.model_validate(normalize_execution_dag_payload(dag))
    nodes = [atom.model_dump(mode="json", exclude_none=True) for atom in execution_dag.atoms]
    layers = execution_dag.execution_layers
    node_by_id = {str(node.get("atom_id") or node.get("id")): node for node in nodes}
    dag_layers = [
        [
            {
                "id": str(node.get("atom_id") or atom_id),
                "atom_type": str(node.get("atom_type") or ""),
                "operation": str(node.get("operation") or ""),
            }
            for atom_id in layer
            if (node := node_by_id.get(str(atom_id))) is not None
        ]
        for layer in layers
    ]
    atom_types = sorted({str(node.get("atom_type") or "") for node in nodes if node.get("atom_type")})
    return CompileResult(
        flow_id=str(plan.get("flow_id") or dag.get("flow_id") or ""),
        revision=int(store._projects[project_id].get("state", {}).get("compiled_revision", 0)),
        steps=len(nodes),
        layers=len(layers),
        output_files=[f.name for f in sorted(compiled_dir.iterdir()) if is_visible_data_file(f, root=compiled_dir)],
        dag_layers=dag_layers,
        atoms=len(nodes),
        atom_types=atom_types,
    )


def discover_project_data(
    store: ProjectStore,
    project_id: str,
    dataset_id: str,
    *,
    data_root: str | Path | None = None,
    data_path: str | None = None,
    base_revision: int | None = None,
) -> DiscoverResult:
    """Discover a dataset for a project."""
    from fnirs_flow.infrastructure.transaction import ProjectTransaction

    if dataset_id == "vendor-processed-hb":
        from fnirs_flow.data.frozen_manifest import discover_frozen_processed_hb
        from fnirs_flow.execution.processed_hb_pipeline import dry_run_processed_hb

        with ProjectTransaction(store, project_id, reason="discover_processed_hb", base_revision=base_revision) as tx:
            root_value = data_root or store.get_project_data_root(project_id) or None
            if data_path is not None:
                root = resolve_project_data_path(
                    store, project_id, data_path, label="Frozen manifest folder", must_be_dir=True, allow_empty=True
                )[0]
            elif root_value is not None:
                root = Path(root_value)
            else:
                raise ValueError("Vendor processed-Hb discovery requires the project data folder or dataset folder")
            required = (
                "fnirs_signal_provenance.csv",
                "analysis_population_manifest.csv",
                "fnirs_events.tsv",
                "contrast_matrix.csv",
            )
            missing = [name for name in required if not (root / name).is_file()]
            if missing:
                raise ValueError(f"Missing frozen processed-Hb inputs: {missing}")
            processed_manifest = discover_frozen_processed_hb(
                root / required[0],
                root / required[1],
                runtime_root=root,
                events_uri=str(root / required[2]),
                contrast_matrix_uri=str(root / required[3]),
            )
            manifest_payload = processed_manifest.model_dump(mode="json")
            manifest_payload["dataset_id"] = dataset_id
            compiled_dir = tx.output_dir / "compiled"
            compiled_dir.mkdir(parents=True, exist_ok=True)
            (compiled_dir / "data_manifest.json").write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
            from importlib.resources import files

            preset = files("fnirs_flow.resources.presets").joinpath("vendor_processed_hb_v1.json")
            (compiled_dir / "processed_hb_preset.json").write_text(preset.read_text(encoding="utf-8"), encoding="utf-8")
            store.bind_dataset(dataset_id, root)
            preview = dry_run_processed_hb(compiled_dir, data_root=root)
            result = DiscoverResult(
                dataset_id=dataset_id,
                files=sum(record["discovery_status"] == "available" for record in preview["records"]),
                runs=len(processed_manifest.runs),
                local_root=str(root),
                metadata_tables=4,
                processed_hb=preview,
            )
            store.update_state(project_id, dataset_id=dataset_id, discovered_runs=result.runs)
            tx.commit()
        return result

    from fnirs_flow.data.discovery import discover_dataset

    with ProjectTransaction(store, project_id, reason="discover_data", base_revision=base_revision) as tx:
        outdir = tx.output_dir
        effective_data_root: Path | None
        if data_path is not None:
            effective_data_root = resolve_project_data_path(
                store,
                project_id,
                data_path,
                label="Dataset folder",
                must_be_dir=True,
                allow_empty=True,
            )[0]
        else:
            root_value = data_root or store.get_project_data_root(project_id) or None
            effective_data_root = Path(root_value) if root_value is not None else None
        discovered_manifest = discover_dataset(dataset_id, outdir, local_root=effective_data_root)
        if discovered_manifest.runtime_local_root:
            store.bind_dataset(discovered_manifest.dataset_id, Path(discovered_manifest.runtime_local_root))
        result = DiscoverResult(
            dataset_id=discovered_manifest.dataset_id,
            files=len(discovered_manifest.files),
            runs=len(discovered_manifest.subject_session_runs),
            local_root=discovered_manifest.runtime_local_root,
            source_url=discovered_manifest.source.url,
            metadata_tables=len(discovered_manifest.metadata_tables),
        )
        store.update_state(project_id, dataset_id=discovered_manifest.dataset_id, discovered_runs=result.runs)
        tx.commit()

    return result


def list_project_data_folders(store: ProjectStore, project_id: str, parent: str = "") -> dict[str, Any]:
    """List immediate child folders under a project-relative data folder."""
    if store.get(project_id) is None:
        return {}
    parent_path, parent_rel = resolve_project_data_path(
        store,
        project_id,
        parent,
        label="Parent folder",
        must_be_dir=True,
        allow_empty=True,
    )
    folders: list[dict[str, Any]] = []
    for child in sorted(parent_path.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        relative = PurePosixPath(parent_rel, child.name).as_posix() if parent_rel else child.name
        try:
            has_children = any(
                grandchild.is_dir() and not grandchild.name.startswith(".") for grandchild in child.iterdir()
            )
        except OSError:
            has_children = False
        folders.append({"name": child.name, "path": relative, "has_children": has_children})
    return {"parent": parent_rel, "folders": folders}


def load_project_discover_result(store: ProjectStore, project_id: str) -> DiscoverResult | None:
    """Rehydrate the last dataset discovery summary from data_manifest.json."""
    if store.get(project_id) is None:
        return None
    compiled_dir = store.get_output_dir(project_id) / "compiled"
    manifest = _load_data_manifest(compiled_dir)
    if not manifest:
        return None
    dataset_id = str(manifest.get("dataset_id", ""))
    binding = store.get_dataset_binding(dataset_id) if dataset_id else None
    if manifest.get("data_branch") == "vendor_processed_hb":
        from fnirs_flow.execution.processed_hb_pipeline import dry_run_processed_hb

        preview = dry_run_processed_hb(compiled_dir, data_root=binding)
        return DiscoverResult(
            dataset_id=dataset_id or "vendor-processed-hb",
            files=sum(record["discovery_status"] == "available" for record in preview["records"]),
            runs=len(manifest.get("runs", []) or []),
            local_root=str(binding or ""),
            metadata_tables=4,
            processed_hb=preview,
        )
    return DiscoverResult(
        dataset_id=dataset_id,
        files=len(manifest.get("files", []) or []),
        runs=len(manifest.get("subject_session_runs", []) or []),
        local_root=str(binding or manifest.get("runtime_local_root", "") or manifest.get("local_root", "")),
        source_url=str((manifest.get("source") or {}).get("url", "")),
        metadata_tables=len(manifest.get("metadata_tables", []) or []),
    )


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

    from fnirs_flow.data.manifest import DataManifest
    from fnirs_flow.data.participant_tables import (
        ColumnRoleMap,
        read_participant_table,
        write_participant_table_artifacts,
    )
    from fnirs_flow.infrastructure.transaction import ProjectTransaction

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
    compiled_dir = outdir / "compiled"
    manifest = _load_data_manifest(compiled_dir) or {}
    if manifest.get("data_branch") == "vendor_processed_hb":
        from fnirs_flow.execution.processed_hb_pipeline import dry_run_processed_hb

        dataset_id = str(manifest.get("dataset_id") or "vendor-processed-hb")
        binding = store.get_dataset_binding(dataset_id)
        result = dry_run_processed_hb(compiled_dir, data_root=binding)
        planned = [
            {
                "run_id": row["fnirs_record_id"],
                "status": "planned" if row["eligible"] else "skipped",
                "subject": "",
                "session": "",
                "run": row["record_pair_id"],
                "started_at": "",
                "completed_at": "",
            }
            for row in result["records"]
        ]
        return DryRunResult(total_runs=len(planned), planned_runs=planned, summary={"processed_hb": result})
    try:
        result = dry_run_compiled_project(outdir)
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
    from fnirs_flow.execution.dag_payload import assert_atom_security

    assert_atom_security(json.loads(dag_path.read_text(encoding="utf-8")))
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
    compiled_dir = outdir / "compiled"
    manifest = _load_data_manifest(compiled_dir) or {}

    if manifest.get("data_branch") == "vendor_processed_hb":
        from fnirs_flow.execution.processed_hb_pipeline import run_processed_hb

        snap = create_snapshot(store, project_id)
        dataset_id = str(manifest.get("dataset_id") or "vendor-processed-hb")
        binding = store.get_dataset_binding(dataset_id)
        result = run_processed_hb(compiled_dir, outdir, data_root=binding)
        run_rows = []
        processed_root = outdir / "derivatives" / "processed_hb_first_level"
        run_manifest_path = processed_root / "run_manifest.csv"
        exclusion_path = processed_root / "exclusion_manifest.csv"
        import csv

        with run_manifest_path.open(newline="", encoding="utf-8-sig") as stream:
            discovered_runs = list(csv.DictReader(stream))
        with exclusion_path.open(newline="", encoding="utf-8-sig") as stream:
            failed_ids = {row["fnirs_record_id"] for row in csv.DictReader(stream) if row.get("status") == "fail"}
        artifacts = [
            ArtifactSummary(
                artifact_id=name,
                type="processed_hb_derivative",
                path=path,
                relative_path=Path(path).relative_to(outdir).as_posix(),
                exists=True,
            )
            for name, path in result["artifacts"].items()
        ]
        for row in discovered_runs:
            record_id = row["fnirs_record_id"]
            status = (
                "failed"
                if record_id in failed_ids
                else ("completed" if row.get("analysis_included") == "true" else "skipped")
            )
            run_rows.append(
                RunSummary(
                    run_id=record_id,
                    status=status,
                    run=row.get("record_pair_id", ""),
                    atom_results=[],
                    artifacts=artifacts if status == "completed" else [],
                )
            )
        attempt = attempt_id or f"processed-hb-{uuid.uuid4().hex[:12]}"
        response = ExecuteResult(
            attempt_id=attempt,
            total_runs=len(run_rows),
            successful=result["successful_record_pairs"],
            failed=result["exclusions"],
            runs=run_rows,
            failure_ids=sorted(failed_ids),
        )
        store.update_state(
            project_id,
            last_attempt_id=attempt,
            last_execution_status="failed" if result["exclusions"] else "completed",
            snapshot_id=snap.snapshot_id if snap else "",
        )
        return response

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
        recommendation = store.get_recommendation_decision(project_id)

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
            recommendation_decision_id=(recommendation.decision_id if recommendation else ""),
            recommendation_rules_version=(recommendation.rules_version if recommendation else ""),
        )

        # Execute via ExecutionService
        service = ExecutionService(
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        execution_result = service.execute(request)

        response = ExecuteResult(
            attempt_id=execution_result.attempt_id,
            total_runs=execution_result.total_runs,
            successful=execution_result.successful_runs,
            failed=execution_result.failed_runs,
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
                for rr in execution_result.run_results
            ],
            failure_ids=execution_result.failure_ids,
        )
        store.update_state(
            project_id,
            last_attempt_id=execution_result.attempt_id,
            last_execution_status=(
                "failed" if execution_result.failed_runs or execution_result.skipped_runs else "completed"
            ),
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
    from fnirs_flow.infrastructure.uri import ProjectURI

    local_root = data_root
    runnable = 0
    if manifest.get("data_branch") == "vendor_processed_hb":
        for run in manifest.get("runs", []):
            value = str(run.get("signal_uri", ""))
            if value.startswith("external-data://") and local_root is not None:
                relative = value.split("external-data://", 1)[1]
                relative = relative.split("/", 1)[1] if "/" in relative else relative
                candidate = local_root / relative
                if not candidate.is_file():
                    candidate = local_root / Path(relative).name
            else:
                candidate = Path(value) if value else Path()
            if value and candidate.is_file():
                runnable += 1
        return runnable
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
    from fnirs_flow.compiler.matching import flows_match

    flow_revision = int(project.revision)
    state = store._projects.get(project_id, {}).get("state", {})
    compiled_dir = store.get_output_dir(project_id) / "compiled"
    compiled_flow_path = compiled_dir / "flow.json"
    compiled_flow: dict[str, Any] = {}
    if compiled_flow_path.exists():
        try:
            compiled_flow = json.loads(compiled_flow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            compiled_flow = {}
    metadata = get_import_metadata(store, project_id)
    quarantined_atoms = list(metadata.get("quarantined_atoms", []))
    dag_path = compiled_dir / "execution_dag.json"
    if dag_path.exists():
        try:
            dag = json.loads(dag_path.read_text(encoding="utf-8"))
            from fnirs_flow.execution.dag_payload import execution_atoms

            quarantined_atoms.extend(
                str(atom.get("atom_id") or atom.get("atom_type") or "<unknown>")
                for atom in execution_atoms(dag)
                if str(atom.get("security_status", "trusted")) in {"quarantined", "blocked"}
            )
        except (json.JSONDecodeError, OSError):
            pass
    quarantined_atoms = list(dict.fromkeys(quarantined_atoms))
    read_only = bool(metadata.get("read_only", False))
    compiled = bool(compiled_flow and (read_only or flows_match(compiled_flow, flow)))
    manifest = _load_data_manifest(compiled_dir) or {}
    dataset_id = str(manifest.get("dataset_id", ""))
    binding = store.get_dataset_binding(dataset_id) if dataset_id else None
    runnable_runs = _runnable_manifest_runs(compiled_dir, binding) if compiled else 0
    validated_flow = state.get("validated_flow")
    validated = bool(
        flow and ((isinstance(validated_flow, dict) and flows_match(validated_flow, flow)) or (read_only and compiled))
    )
    return ProjectStatus(
        flow_saved=bool(flow),
        validated=validated,
        compiled=compiled,
        data_discovered=runnable_runs > 0,
        runnable_runs=runnable_runs,
        executed=bool(state.get("last_attempt_id")),
        flow_revision=flow_revision,
        compiled_revision=int(state.get("compiled_revision", 0)) if compiled else 0,
        last_attempt_id=state.get("last_attempt_id", ""),
        last_execution_status=state.get("last_execution_status", ""),
        read_only=read_only,
        quarantined_atoms=quarantined_atoms,
    )


def export_project_package(
    store: ProjectStore,
    project_id: str,
    profile_id: str = "reproducibility_package",
    *,
    snapshot_id: str | None = None,
    attempt_id: str | None = None,
    include_history: bool = False,
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

    snapshots = store.get_project_snapshots(project_id)
    if snapshot_id is None:
        current_flow = store.get_flow(project_id) or {}
        selected_snapshot = next(
            (snapshot for snapshot in reversed(snapshots) if snapshot.get("flow") == current_flow),
            None,
        )
        if selected_snapshot is None:
            selected_snapshot = Snapshot(
                snapshot_id=f"snap-export-{uuid.uuid4().hex[:12]}",
                flow=current_flow,
                revision=int(project.revision),
                created_at=datetime.now(timezone.utc).isoformat(),
                description="Package export snapshot",
            ).model_dump()
    else:
        selected_snapshot = next(
            (snapshot for snapshot in snapshots if snapshot.get("snapshot_id") == snapshot_id),
            None,
        )
        if selected_snapshot is None:
            raise ValueError(f"Unknown project snapshot: {snapshot_id}")

    from fnirs_flow.compiler.matching import flows_match

    try:
        compiled_flow = json.loads((compiled_dir / "flow.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise StaleCompiledPlanError("Compiled Flow is unreadable; compile the Flow again") from exc
    snapshot_flow = selected_snapshot.get("flow")
    if not isinstance(snapshot_flow, dict) or not flows_match(snapshot_flow, compiled_flow):
        raise ValueError(
            f"Project snapshot {selected_snapshot.get('snapshot_id', '<unknown>')} "
            "does not match the compiled Flow"
        )

    attempts: list[dict[str, Any]] = []
    attempts_root = store.get_output_dir(project_id) / "attempts"
    if attempts_root.is_dir():
        for job_path in sorted(attempts_root.glob("*/job.json")):
            try:
                attempts.append(json.loads(job_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                logger.warning("Skipping invalid execution attempt record: %s", job_path)
    selected_attempt = None
    if attempt_id is not None:
        selected_attempt = next(
            (attempt for attempt in attempts if attempt.get("attempt_id") == attempt_id),
            None,
        )
        if selected_attempt is None:
            raise ValueError(f"Unknown project execution attempt: {attempt_id}")
        attempt_snapshot_id = selected_attempt.get("snapshot_id")
        if not attempt_snapshot_id:
            raise ValueError(f"Project execution attempt {attempt_id} has no snapshot anchor")
        if attempt_snapshot_id != selected_snapshot.get("snapshot_id"):
            raise ValueError(
                f"Project execution attempt {attempt_id} references snapshot {attempt_snapshot_id}, "
                f"not {selected_snapshot.get('snapshot_id')}"
            )

    import shutil
    import tempfile

    from fnirs_flow.exporters.package_exporter import export_package, get_package_contents

    pkg_path = None
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            tmp_pkg = Path(tmp_dir) / f"{project_id}.fnirsflow.zip"
            export_package(
                compiled_dir,
                tmp_pkg,
                profile_id=profile_id,
                selected_snapshot=selected_snapshot,
                selected_attempt=selected_attempt,
                snapshot_history=snapshots if include_history else (),
                attempt_history=attempts if include_history else (),
            )
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
