"""Project-level concurrency locks: in-process RWLock and cross-process file lock."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fnirs_flow.api.exceptions import ProjectLockTimeoutError

logger = logging.getLogger(__name__)

_STALE_TIMEOUT = 300.0  # seconds before a cross-process lock is considered stale
_HEARTBEAT_INTERVAL = 30.0  # seconds between heartbeat updates


@dataclass
class LockHolder:
    """Describes who currently holds a project lock."""

    operation: str  # "compile" | "execute" | "save" | "restore" | ...
    holder_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    acquired_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    thread_id: int = field(default_factory=threading.get_ident)


class ProjectLock:
    """In-process read-write lock for a single project.

    Writers are exclusive; readers are shared.  The lock is *not* re-entrant
    (a thread that already holds the write lock and tries to acquire it again
    will deadlock by design — callers must not nest writes).
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._cond = threading.Condition(threading.Lock())
        self._read_count = 0
        self._write_holder: LockHolder | None = None

    # -- write lock ----------------------------------------------------------

    def acquire_write(
        self, operation: str, timeout: float = 30.0
    ) -> LockHolder:
        """Block until the write lock is acquired or *timeout* expires.

        Returns a :class:`LockHolder` on success.
        Raises :class:`ProjectLockTimeoutError` on timeout.
        """
        holder = LockHolder(operation=operation)
        deadline = time.monotonic() + timeout

        with self._cond:
            # Wait until no readers and no writer
            while self._read_count > 0 or self._write_holder is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProjectLockTimeoutError(self.project_id, timeout)
                self._cond.wait(timeout=remaining)

            self._write_holder = holder

        return holder

    def release_write(self) -> None:
        """Release the write lock."""
        with self._cond:
            self._write_holder = None
            self._cond.notify_all()

    # -- query --------------------------------------------------------------

    @property
    def is_write_locked(self) -> bool:
        with self._cond:
            return self._write_holder is not None

    @property
    def write_holder(self) -> LockHolder | None:
        with self._cond:
            return self._write_holder

    @property
    def read_count(self) -> int:
        with self._cond:
            return self._read_count


class CrossProcessLock:
    """Cross-process file lock using atomic file creation.

    Lock file is a JSON document containing the holder metadata.  A
    background heartbeat thread keeps the mtime fresh so that stale
    detection works reliably.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()

    def acquire(self, operation: str, timeout: float = 30.0) -> LockHolder:
        """Acquire the cross-process lock.

        Returns a :class:`LockHolder` on success.
        Raises :class:`ProjectLockTimeoutError` on timeout.
        """
        holder = LockHolder(operation=operation)
        deadline = time.monotonic() + timeout

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProjectLockTimeoutError(
                    self._lock_path.stem, timeout
                )

            try:
                fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                payload = json.dumps(
                    {
                        "pid": os.getpid(),
                        "operation": operation,
                        "holder_id": holder.holder_id,
                        "acquired_at": holder.acquired_at,
                    }
                )
                os.write(fd, payload.encode("utf-8"))
                os.close(fd)
                # Start heartbeat
                self._start_heartbeat()
                return holder
            except FileExistsError:
                if self._is_stale():
                    try:
                        self._lock_path.unlink()
                    except FileNotFoundError:
                        pass
                time.sleep(min(0.2, remaining))

    def release(self) -> None:
        """Release the cross-process lock."""
        self._stop_heartbeat()
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    def read_holder(self) -> dict[str, Any] | None:
        """Read the current lock holder info from the lock file."""
        try:
            data = json.loads(self._lock_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _is_stale(self, stale_timeout: float = _STALE_TIMEOUT) -> bool:
        try:
            mtime = self._lock_path.stat().st_mtime
            return (time.time() - mtime) > stale_timeout
        except FileNotFoundError:
            return True

    def _start_heartbeat(self) -> None:
        self._heartbeat_stop.clear()

        def _beat() -> None:
            while not self._heartbeat_stop.wait(_HEARTBEAT_INTERVAL):
                try:
                    # Touch the file to update mtime
                    os.utime(self._lock_path, None)
                except OSError:
                    break

        self._heartbeat_thread = threading.Thread(
            target=_beat, daemon=True, name="lock-heartbeat"
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2.0)
            self._heartbeat_thread = None

    def __enter__(self) -> CrossProcessLock:
        self.acquire(operation="unknown")
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()


class ProjectLockRegistry:
    """Global registry of per-project locks.

    Provides a single entry-point for acquiring write locks on any project,
    coordinating both in-process and cross-process locking.
    """

    def __init__(self, lock_dir: Path) -> None:
        self._lock_dir = lock_dir
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, ProjectLock] = {}
        self._cross_locks: dict[str, CrossProcessLock] = {}
        self._meta_lock = threading.Lock()  # protects the dicts above

    def _get_in_process_lock(self, project_id: str) -> ProjectLock:
        with self._meta_lock:
            if project_id not in self._locks:
                self._locks[project_id] = ProjectLock(project_id)
            return self._locks[project_id]

    def _get_cross_process_lock(self, project_id: str) -> CrossProcessLock:
        with self._meta_lock:
            if project_id not in self._cross_locks:
                path = self._lock_dir / f"{project_id}.lock"
                self._cross_locks[project_id] = CrossProcessLock(path)
            return self._cross_locks[project_id]

    def acquire_write(
        self,
        project_id: str,
        operation: str,
        timeout: float = 30.0,
    ) -> tuple[LockHolder, CrossProcessLock]:
        """Acquire both in-process and cross-process write locks.

        Returns (LockHolder, CrossProcessLock).  The caller **must** call
        :meth:`release_write` when done, passing both objects.
        """
        in_lock = self._get_in_process_lock(project_id)
        cross_lock = self._get_cross_process_lock(project_id)

        # In-process first (fast, blocks local threads)
        holder = in_lock.acquire_write(operation, timeout=timeout)

        # Then cross-process (best-effort, may fail on NFS etc.)
        try:
            cross_lock.acquire(operation, timeout=max(0.1, timeout - 5))
        except ProjectLockTimeoutError:
            in_lock.release_write()
            raise

        return holder, cross_lock

    def release_write(
        self,
        project_id: str,
        holder: LockHolder,
        cross_lock: CrossProcessLock,
    ) -> None:
        """Release both locks."""
        cross_lock.release()
        in_lock = self._get_in_process_lock(project_id)
        in_lock.release_write()

    def get_lock_info(self, project_id: str) -> dict[str, Any]:
        """Return the current lock status for a project."""
        in_lock = self._get_in_process_lock(project_id)
        cross_lock = self._get_cross_process_lock(project_id)

        holder = in_lock.write_holder
        cross_info = cross_lock.read_holder()

        if holder is not None:
            return {
                "project_id": project_id,
                "locked": True,
                "operation": holder.operation,
                "holder_id": holder.holder_id,
                "acquired_at": holder.acquired_at,
                "cross_process": cross_info is not None,
            }
        if cross_info:
            return {
                "project_id": project_id,
                "locked": True,
                "operation": cross_info.get("operation", "unknown"),
                "holder_id": cross_info.get("holder_id", "unknown"),
                "acquired_at": cross_info.get("acquired_at", ""),
                "cross_process": True,
            }
        return {
            "project_id": project_id,
            "locked": False,
            "operation": "",
            "holder_id": "",
            "acquired_at": "",
            "cross_process": False,
        }


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_registry: ProjectLockRegistry | None = None
_registry_lock = threading.Lock()


def get_lock_registry(lock_dir: Path | None = None) -> ProjectLockRegistry:
    """Return the global :class:`ProjectLockRegistry` singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                if lock_dir is None:
                    raise ValueError("lock_dir required on first call")
                _registry = ProjectLockRegistry(lock_dir)
    return _registry
