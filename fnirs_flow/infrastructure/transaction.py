"""Project-level write transaction with staging directory and rollback."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Protocol, cast

from fnirs_flow.application.errors import (
    ProjectRevisionConflictError,
    ProjectTransactionError,
)
from fnirs_flow.infrastructure.concurrency import CrossProcessLock, LockHolder, get_lock_registry
from fnirs_flow.infrastructure.filesystem import macos_metadata_ignore


class ProjectStoreProtocol(Protocol):
    _bundles: Any
    _projects: dict[str, Any]

    def ensure_project_loaded(self, project_id: str) -> bool: ...

    def register_transaction(self, project_id: str, transaction: ProjectTransaction) -> None: ...

    def unregister_transaction(self, project_id: str) -> None: ...

logger = logging.getLogger(__name__)


def recover_staging_directories(staging_root: Path) -> int:
    """Delete all leftover staging directories on startup.

    Staging dirs are ephemeral — a crash mid-transaction means the staging
    data is incomplete and must not be used.  Returns the number of dirs
    cleaned up.
    """
    count = 0
    if not staging_root.exists():
        return 0
    for entry in sorted(staging_root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            shutil.rmtree(entry, ignore_errors=True)
            count += 1
        except OSError as exc:
            logger.warning("Could not remove stale staging dir %s: %s", entry, exc)
    return count


class ProjectTransaction:
    """Context manager that wraps a project modification in a staging workflow.

    Usage::

        with ProjectTransaction(store, project_id, reason="compile") as tx:
            compile_flow(flow, tx.output_dir)
            tx.commit()

    Inside the ``with`` block, ``tx.output_dir`` points to a *staging copy* of
    the project workspace.  All file writes go there.  On ``commit()``, the
    staging is validated, bundled, and atomically swapped into the real
    workspace.  If the block exits without calling ``commit()`` (e.g. due to an
    exception), the staging directory is discarded and the original project is
    untouched.
    """

    def __init__(
        self,
        store: ProjectStoreProtocol,
        project_id: str,
        reason: str,
        *,
        base_revision: int | None = None,
        expected_head_commit_id: str | None = None,
        lock_timeout: float = 30.0,
    ) -> None:
        self._store = store
        self._project_id = project_id
        self._reason = reason
        self._base_revision = base_revision
        self._expected_head_commit_id = expected_head_commit_id
        self._lock_timeout = lock_timeout

        self._staging_dir: Path | None = None
        self._tx_id = uuid.uuid4().hex[:10]
        self._holder: LockHolder | None = None
        self._cross_lock: CrossProcessLock | None = None
        self._committed = False

    @property
    def output_dir(self) -> Path:
        """Return the staging ``outputs/`` directory."""
        if self._staging_dir is None:
            raise ProjectTransactionError("Transaction not started")
        return self._staging_dir / "outputs"

    @property
    def staging_dir(self) -> Path:
        """Return the root staging directory."""
        if self._staging_dir is None:
            raise ProjectTransactionError("Transaction not started")
        return self._staging_dir

    @property
    def tx_id(self) -> str:
        return self._tx_id

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> ProjectTransaction:
        bundles = self._store._bundles
        staging_root = self._base_dir / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        self._staging_dir = staging_root / f"{self._project_id}-{self._tx_id}"

        # 1. Acquire write lock (in-process + cross-process)
        lock_dir = self._base_dir / ".locks"
        registry = get_lock_registry(lock_dir=lock_dir)
        self._holder, self._cross_lock = registry.acquire_write(
            self._project_id,
            operation=self._reason,
            timeout=self._lock_timeout,
        )

        try:
            # 2. Check base_revision
            if self._base_revision is not None:
                current = bundles.read_current_revision(self._project_id)
                if current != self._base_revision:
                    raise ProjectRevisionConflictError(
                        current_revision=current,
                        requested_revision=self._base_revision,
                    )

            # 2b. Check expected HEAD commit (FlowVCS branch concurrency)
            if self._expected_head_commit_id is not None:
                self._check_expected_head()

            # 3. Ensure the disposable workspace has been materialized, then
            # copy workspace → staging. Materialization replaces the workspace,
            # so it must happen before copytree starts.
            self._store.ensure_project_loaded(self._project_id)
            workspace = bundles.workspace_path(self._project_id)
            if workspace.exists():
                shutil.copytree(
                    workspace,
                    self._staging_dir,
                    dirs_exist_ok=True,
                    ignore=macos_metadata_ignore,
                )
            else:
                self._staging_dir.mkdir(parents=True, exist_ok=True)

            # Ensure outputs directory exists in staging
            (self._staging_dir / "outputs").mkdir(parents=True, exist_ok=True)

            # 4. Register transaction so that store.get_output_dir() proxies
            self._store.register_transaction(self._project_id, self)

        except Exception:
            # Rollback: release locks and clean up staging
            self._cleanup_staging()
            self._release_locks()
            raise

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        try:
            if not self._committed:
                # Transaction exited without commit — discard staging
                self._cleanup_staging()
        finally:
            self._store.unregister_transaction(self._project_id)
            self._release_locks()

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    def commit(self) -> dict[str, Any]:
        """Validate, bundle, and atomically swap staging into the workspace.

        Returns the new bundle manifest.
        """
        if self._staging_dir is None or not self._staging_dir.exists():
            raise ProjectTransactionError("No staging directory to commit")

        bundles = self._store._bundles

        # 1. Defense-in-depth revision check
        if self._base_revision is not None:
            current = bundles.read_current_revision(self._project_id)
            if current != self._base_revision:
                raise ProjectRevisionConflictError(
                    current_revision=current,
                    requested_revision=self._base_revision,
                )

        # 1b. Defense-in-depth expected HEAD check
        if self._expected_head_commit_id is not None:
            self._check_expected_head()

        # 2. Flush in-memory metadata to staging
        proj_meta = self._store._projects.get(self._project_id)
        if proj_meta is not None:
            meta_file = self._staging_dir / "project.json"
            meta_file.write_text(
                json.dumps(proj_meta, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        # 3. Save bundle from staging (atomic zip + replace)
        manifest = bundles.save_from_staging(
            self._project_id,
            self._staging_dir,
            reason=self._reason,
        )

        # 4. Reload in-memory metadata from the new workspace
        workspace = bundles.workspace_path(self._project_id)
        metadata_path = workspace / "project.json"
        if metadata_path.exists():
            self._store._projects[self._project_id] = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )

        self._committed = True
        return cast(dict[str, Any], manifest)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _base_dir(self) -> Path:
        return cast(Path, self._store._bundles.base_dir)

    def _check_expected_head(self) -> None:
        """Verify the design history HEAD matches the expected commit."""
        from fnirs_flow.history.errors import BranchHeadConflict
        from fnirs_flow.history.zip_json_store import ZipJsonHistoryStore

        if self._expected_head_commit_id is None:
            raise ProjectTransactionError(
                "Cannot check HEAD: no expected commit ID set"
            )
        workspace = self._store._bundles.workspace_path(self._project_id)
        store = ZipJsonHistoryStore(workspace)
        if not store.is_initialized():
            return  # no history yet — no conflict possible
        state = store.get_state()
        actual_head = state.head.commit_id
        if actual_head != self._expected_head_commit_id:
            raise BranchHeadConflict(
                f"Design HEAD changed concurrently: expected "
                f"{self._expected_head_commit_id[:16]}, got {actual_head[:16]}"
            )

    def _cleanup_staging(self) -> None:
        if self._staging_dir is not None and self._staging_dir.exists():
            try:
                shutil.rmtree(self._staging_dir, ignore_errors=True)
            except OSError as exc:
                logger.warning(
                    "Could not clean up staging dir %s: %s",
                    self._staging_dir,
                    exc,
                )

    def _release_locks(self) -> None:
        try:
            lock_dir = self._base_dir / ".locks"
            registry = get_lock_registry(lock_dir=lock_dir)
            registry.release_write(
                self._project_id,
                self._holder,  # type: ignore[arg-type]
                self._cross_lock,  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.warning("Error releasing lock for %s: %s", self._project_id, exc)
