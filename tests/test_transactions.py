"""Tests for project transactions, concurrency locks, and revision control."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from fnirs_flow.api.concurrency import (
    CrossProcessLock,
    LockHolder,
    ProjectLock,
    ProjectLockRegistry,
)
from fnirs_flow.api.exceptions import (
    ProjectBusyError,
    ProjectLockTimeoutError,
    ProjectRevisionConflictError,
)
from fnirs_flow.api.projects import ProjectStore
from fnirs_flow.api.transaction import ProjectTransaction, recover_staging_directories

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_base(tmp_path: Path) -> Path:
    return tmp_path / "projects"


@pytest.fixture()
def store(tmp_base: Path) -> ProjectStore:
    return ProjectStore(tmp_base)


@pytest.fixture()
def project(store: ProjectStore):
    return store.create("test-project", "A test project")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_revision_conflict_stores_revisions(self) -> None:
        exc = ProjectRevisionConflictError(current_revision=5, requested_revision=3)
        assert exc.current_revision == 5
        assert exc.requested_revision == 3
        assert "5" in str(exc)
        assert "3" in str(exc)

    def test_lock_timeout_stores_project_id(self) -> None:
        exc = ProjectLockTimeoutError(project_id="abc", timeout=10.0)
        assert exc.project_id == "abc"
        assert exc.timeout == 10.0

    def test_busy_error_stores_operation(self) -> None:
        exc = ProjectBusyError(operation="compile", holder_id="xyz")
        assert exc.operation == "compile"
        assert exc.holder_id == "xyz"


# ---------------------------------------------------------------------------
# In-process ProjectLock
# ---------------------------------------------------------------------------


class TestProjectLock:
    def test_write_lock_basic(self) -> None:
        lock = ProjectLock("p1")
        holder = lock.acquire_write("test", timeout=1.0)
        assert lock.is_write_locked
        assert lock.write_holder is holder
        lock.release_write()
        assert not lock.is_write_locked

    def test_write_lock_blocks_second_acquirer(self) -> None:
        lock = ProjectLock("p1")
        lock.acquire_write("first", timeout=1.0)

        second_acquired = threading.Event()
        second_error = threading.Event()

        def try_second() -> None:
            try:
                lock.acquire_write("second", timeout=0.5)
                second_acquired.set()
            except ProjectLockTimeoutError:
                second_error.set()

        t = threading.Thread(target=try_second)
        t.start()
        t.join(timeout=2.0)

        assert second_error.is_set()
        assert not second_acquired.is_set()
        lock.release_write()

    def test_write_lock_can_be_acquired_after_release(self) -> None:
        lock = ProjectLock("p1")
        lock.acquire_write("first", timeout=1.0)
        lock.release_write()

        holder = lock.acquire_write("second", timeout=1.0)
        assert holder.operation == "second"
        lock.release_write()

    def test_concurrent_writes_on_different_locks(self) -> None:
        lock1 = ProjectLock("p1")
        lock2 = ProjectLock("p2")

        holder1 = lock1.acquire_write("op1", timeout=1.0)
        holder2 = lock2.acquire_write("op2", timeout=1.0)

        assert holder1.operation == "op1"
        assert holder2.operation == "op2"

        lock1.release_write()
        lock2.release_write()


# ---------------------------------------------------------------------------
# CrossProcessLock
# ---------------------------------------------------------------------------


class TestCrossProcessLock:
    def test_acquire_and_release(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        lock = CrossProcessLock(lock_path)
        holder = lock.acquire("test", timeout=1.0)
        assert lock_path.exists()
        assert holder.operation == "test"

        info = lock.read_holder()
        assert info is not None
        assert info["operation"] == "test"

        lock.release()
        assert not lock_path.exists()

    def test_stale_lock_cleanup(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        # Create a stale lock file
        lock_path.write_text('{"operation": "old"}')

        # Modify mtime to be very old
        import os

        old_time = time.time() - 700
        os.utime(lock_path, (old_time, old_time))

        lock = CrossProcessLock(lock_path)
        holder = lock.acquire("new", timeout=2.0)
        assert holder.operation == "new"
        lock.release()

    def test_context_manager(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        lock = CrossProcessLock(lock_path)
        with lock:
            assert lock_path.exists()
        assert not lock_path.exists()


# ---------------------------------------------------------------------------
# ProjectLockRegistry
# ---------------------------------------------------------------------------


class TestProjectLockRegistry:
    def test_acquire_write_returns_holder(self, tmp_path: Path) -> None:
        registry = ProjectLockRegistry(tmp_path / "locks")
        holder, cross_lock = registry.acquire_write("p1", "compile", timeout=1.0)
        assert holder.operation == "compile"
        assert isinstance(holder, LockHolder)
        registry.release_write("p1", holder, cross_lock)

    def test_concurrent_writes_blocked(self, tmp_path: Path) -> None:
        registry = ProjectLockRegistry(tmp_path / "locks")
        holder1, cross1 = registry.acquire_write("p1", "compile", timeout=1.0)

        error_event = threading.Event()

        def try_write() -> None:
            try:
                registry.acquire_write("p1", "execute", timeout=0.5)
            except ProjectLockTimeoutError:
                error_event.set()

        t = threading.Thread(target=try_write)
        t.start()
        t.join(timeout=2.0)
        assert error_event.is_set()

        registry.release_write("p1", holder1, cross1)

    def test_different_projects_parallel(self, tmp_path: Path) -> None:
        registry = ProjectLockRegistry(tmp_path / "locks")
        h1, c1 = registry.acquire_write("p1", "compile", timeout=1.0)
        h2, c2 = registry.acquire_write("p2", "compile", timeout=1.0)
        assert h1.operation == "compile"
        assert h2.operation == "compile"
        registry.release_write("p1", h1, c1)
        registry.release_write("p2", h2, c2)

    def test_get_lock_info_unlocked(self, tmp_path: Path) -> None:
        registry = ProjectLockRegistry(tmp_path / "locks")
        info = registry.get_lock_info("p1")
        assert info["project_id"] == "p1"
        assert not info["locked"]

    def test_get_lock_info_locked(self, tmp_path: Path) -> None:
        registry = ProjectLockRegistry(tmp_path / "locks")
        holder, cross = registry.acquire_write("p1", "compile", timeout=1.0)
        info = registry.get_lock_info("p1")
        assert info["locked"]
        assert info["operation"] == "compile"
        registry.release_write("p1", holder, cross)


# ---------------------------------------------------------------------------
# Staging directory recovery
# ---------------------------------------------------------------------------


class TestStagingRecovery:
    def test_recover_removes_staging_dirs(self, tmp_path: Path) -> None:
        staging_root = tmp_path / ".staging"
        (staging_root / "proj1-abc").mkdir(parents=True)
        (staging_root / "proj2-def").mkdir(parents=True)
        (staging_root / "proj1-abc" / "test.txt").write_text("data")

        count = recover_staging_directories(staging_root)
        assert count == 2
        # Subdirectories should be removed, root may still exist
        assert not (staging_root / "proj1-abc").exists()
        assert not (staging_root / "proj2-def").exists()

    def test_recover_empty_dir(self, tmp_path: Path) -> None:
        staging_root = tmp_path / ".staging"
        staging_root.mkdir()
        count = recover_staging_directories(staging_root)
        assert count == 0

    def test_recover_nonexistent_dir(self, tmp_path: Path) -> None:
        count = recover_staging_directories(tmp_path / "nonexistent")
        assert count == 0


# ---------------------------------------------------------------------------
# ProjectTransaction
# ---------------------------------------------------------------------------


class TestProjectTransaction:
    def test_commit_increments_revision(
        self, store: ProjectStore, project
    ) -> None:
        pid = project.id
        initial_rev = project.revision

        with ProjectTransaction(store, pid, reason="test_commit") as tx:
            # Write something to staging
            (tx.output_dir / "test.txt").mkdir(parents=True, exist_ok=True)
            (tx.output_dir / "test.txt" / "data.txt").write_text("hello")
            tx.commit()

        updated = store.get(pid)
        assert updated is not None
        assert updated.revision == initial_rev + 1

    def test_abort_preserves_original(
        self, store: ProjectStore, project
    ) -> None:
        pid = project.id
        initial_rev = project.revision
        original_dir = store.get_output_dir(pid)

        try:
            with ProjectTransaction(store, pid, reason="test_abort") as tx:
                (tx.output_dir / "should_not_exist.txt").write_text("gone")
                raise RuntimeError("intentional abort")
        except RuntimeError:
            pass

        # Original workspace should be unchanged
        assert not (original_dir / "should_not_exist.txt").exists()
        updated = store.get(pid)
        assert updated is not None
        assert updated.revision == initial_rev

    def test_staging_isolation(self, store: ProjectStore, project) -> None:
        pid = project.id
        original_dir = store.get_output_dir(pid)

        with ProjectTransaction(store, pid, reason="test_isolation") as tx:
            staging_file = tx.output_dir / "staging_only.txt"
            staging_file.write_text("in staging")
            # Should not be visible in original workspace
            assert not (original_dir / "staging_only.txt").exists()
            tx.commit()

        # After commit, the file should be in the workspace
        assert (original_dir / "staging_only.txt").exists()

    def test_revision_conflict_on_stale_write(
        self, store: ProjectStore, project
    ) -> None:
        pid = project.id

        # First transaction increments revision
        with ProjectTransaction(store, pid, reason="first") as tx:
            tx.commit()

        # Second transaction with stale revision should fail
        with pytest.raises(ProjectRevisionConflictError) as exc_info:
            with ProjectTransaction(
                store, pid, reason="stale", base_revision=0
            ) as tx:
                tx.commit()

        assert exc_info.value.current_revision > 0
        assert exc_info.value.requested_revision == 0

    def test_no_revision_check_when_none(
        self, store: ProjectStore, project
    ) -> None:
        pid = project.id

        # Should not raise when base_revision is None
        with ProjectTransaction(store, pid, reason="no_check") as tx:
            tx.commit()

        updated = store.get(pid)
        assert updated is not None
        assert updated.revision > 0

    def test_lock_released_after_exception(
        self, store: ProjectStore, project
    ) -> None:
        pid = project.id

        try:
            with ProjectTransaction(store, pid, reason="fail") as tx:
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        # Should be able to acquire lock again
        with ProjectTransaction(store, pid, reason="after_fail") as tx:
            tx.commit()

    def test_output_dir_proxies_to_staging(
        self, store: ProjectStore, project
    ) -> None:
        pid = project.id

        with ProjectTransaction(store, pid, reason="proxy_test") as tx:
            # store.get_output_dir should return staging dir
            outdir = store.get_output_dir(pid)
            assert str(tx.output_dir) == str(outdir)
            tx.commit()

    def test_persist_skipped_during_transaction(
        self, store: ProjectStore, project
    ) -> None:
        pid = project.id

        with ProjectTransaction(store, pid, reason="persist_skip") as tx:
            # update_state should not trigger bundle save during transaction
            store.update_state(pid, test_key="test_value")
            # The state should be in memory
            assert store._projects[pid]["state"]["test_key"] == "test_value"
            tx.commit()

    def test_concurrent_compile_and_execute_blocked(
        self, store: ProjectStore, project
    ) -> None:
        pid = project.id
        error_event = threading.Event()
        entered = threading.Event()

        def try_compile() -> None:
            entered.wait(timeout=2.0)
            try:
                with ProjectTransaction(
                    store, pid, reason="compile", lock_timeout=0.5
                ) as tx:
                    tx.commit()
            except ProjectLockTimeoutError:
                error_event.set()

        with ProjectTransaction(store, pid, reason="execute") as tx:
            entered.set()
            t = threading.Thread(target=try_compile)
            t.start()
            t.join(timeout=2.0)
            assert error_event.is_set()
            tx.commit()


# ---------------------------------------------------------------------------
# Integration: compile in transaction
# ---------------------------------------------------------------------------


class TestCompileInTransaction:
    def test_compile_creates_compiled_dir(
        self, store: ProjectStore, project
    ) -> None:
        from fnirs_flow.api.projects import compile_project_flow

        pid = project.id
        # Save a minimal flow
        store.update_flow(pid, {
            "schema_version": "0.3.0",
            "flow_id": "test-flow",
            "name": "Test Flow",
            "nodes": [],
            "edges": [],
        })

        result = compile_project_flow(store, pid)
        assert result is not None
        assert result.flow_id == "test-flow"

        # Verify compiled dir exists
        compiled_dir = store.get_output_dir(pid) / "compiled"
        assert compiled_dir.exists()
        assert (compiled_dir / "plan.json").exists()


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_create_non_transactional(self, store: ProjectStore) -> None:
        """create() should work without transactions."""
        proj = store.create("new-project")
        assert proj.name == "new-project"
        assert proj.revision == 1

    def test_update_flow_non_transactional(
        self, store: ProjectStore, project
    ) -> None:
        """update_flow() should work without transactions."""
        pid = project.id
        result = store.update_flow(pid, {"flow_id": "test"})
        assert result

        proj = store.get(pid)
        assert proj is not None
        assert proj.flow_id == "test"

    def test_commit_project_skips_during_transaction(
        self, store: ProjectStore, project
    ) -> None:
        """commit_project() should be a no-op during active transaction."""
        pid = project.id

        with ProjectTransaction(store, pid, reason="test") as tx:
            # This should be a no-op
            store.commit_project(pid, reason="should_be_skipped")
            tx.commit()
