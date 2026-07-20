"""Isolated environment manager for dependency installation.

Implements §8.1 of the design document:
- Each dependency profile uses an isolated environment
- Path: <cache_root>/backend-envs/<profile_id>/<lock_fingerprint>/
- Does NOT modify fnirs-flow main Python environment
- Does NOT modify user's base Conda environment
- Does NOT modify system Python
- Environment creation in independent process
- Atomic publish on success, quarantine on failure

§8.4 - Concurrency:
- Keyed by (profile_id, lock_fingerprint)
- Cross-process locking
- Shared installation task for concurrent requests
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EnvironmentStatus(str, Enum):
    """Status of an isolated environment."""

    CREATING = "creating"
    READY = "ready"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    REMOVED = "removed"


class EnvironmentInfo(BaseModel):
    """Information about an isolated environment."""

    environment_id: str
    profile_id: str
    lock_fingerprint: str
    path: str
    status: EnvironmentStatus = EnvironmentStatus.CREATING
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    published_at: str | None = None
    python_version: str = ""
    platform: str = ""
    installed_packages: dict[str, str] = Field(default_factory=dict)
    frozen_requirements: str = ""
    environment_hash: str = ""
    error: str | None = None


class EnvironmentLock:
    """Cross-process lock for environment operations.

    Uses file-based locking to coordinate between processes.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._lock_fd: int | None = None

    def acquire(self, timeout: float = 300.0) -> bool:
        """Acquire the lock with timeout.

        Returns True if lock acquired, False if timeout.
        """
        start = time.time()
        while time.time() - start < timeout:
            try:
                # Atomic lock creation
                fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                os.write(fd, f"{os.getpid()}\n".encode())
                self._lock_fd = fd
                return True
            except FileExistsError:
                # Lock exists, check if stale
                if self._is_stale():
                    try:
                        self._lock_path.unlink()
                    except FileNotFoundError:
                        pass
                time.sleep(0.1)
        return False

    def release(self) -> None:
        """Release the lock."""
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _is_stale(self, stale_timeout: float = 600.0) -> bool:
        """Check if lock is stale (older than timeout)."""
        try:
            mtime = self._lock_path.stat().st_mtime
            return (time.time() - mtime) > stale_timeout
        except FileNotFoundError:
            return True

    def __enter__(self) -> EnvironmentLock:
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()


class EnvironmentManager:
    """Manages isolated environments for dependency installation.

    Implements §8.1:
    - <cache_root>/backend-envs/<profile_id>/<lock_fingerprint>/
    - Atomic publish on success
    - Quarantine on failure

    §8.4 - Concurrency:
    - Cross-process locking via file locks
    """

    def __init__(self, cache_root: Path | str | None = None) -> None:
        if cache_root is None:
            cache_root = Path(tempfile.gettempdir()) / "fnirs-flow" / "backend-envs"
        self._cache_root = Path(cache_root)
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._environments: dict[str, EnvironmentInfo] = {}
        self._load_environments()

    @property
    def cache_root(self) -> Path:
        """Root directory for isolated environments."""
        return self._cache_root

    def _load_environments(self) -> None:
        """Load existing environment info from disk."""
        for env_dir in self._cache_root.iterdir():
            if not env_dir.is_dir():
                continue
            info_path = env_dir / "environment_info.json"
            if info_path.exists():
                try:
                    data = json.loads(info_path.read_text(encoding="utf-8"))
                    info = EnvironmentInfo.model_validate(data)
                    self._environments[info.environment_id] = info
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning("Failed to load environment info from %s: %s", info_path, e)

    def _compute_environment_id(self, profile_id: str, lock_fingerprint: str) -> str:
        """Compute unique environment ID."""
        return f"{profile_id}/{lock_fingerprint}"

    def get_environment_path(self, profile_id: str, lock_fingerprint: str) -> Path:
        """Get the path for an environment."""
        return self._cache_root / profile_id / lock_fingerprint

    def get_quarantine_path(self, profile_id: str, lock_fingerprint: str) -> Path:
        """Get the quarantine path for a failed environment."""
        return self._cache_root / ".quarantine" / profile_id / lock_fingerprint

    def environment_exists(self, profile_id: str, lock_fingerprint: str) -> bool:
        """Check if an environment exists and is ready."""
        env_id = self._compute_environment_id(profile_id, lock_fingerprint)
        info = self._environments.get(env_id)
        return info is not None and info.status == EnvironmentStatus.READY

    def get_environment(self, profile_id: str, lock_fingerprint: str) -> EnvironmentInfo | None:
        """Get environment info."""
        env_id = self._compute_environment_id(profile_id, lock_fingerprint)
        return self._environments.get(env_id)

    def list_environments(self) -> list[EnvironmentInfo]:
        """List all environments."""
        return list(self._environments.values())

    def create_environment(
        self,
        profile_id: str,
        lock_fingerprint: str,
        python_version: str | None = None,
    ) -> EnvironmentInfo:
        """Create a new isolated environment.

        This creates the staging directory. The environment is not published
        until publish_environment() is called.

        §8.1: Environment creation and installation run in a separate process.
        """
        env_id = self._compute_environment_id(profile_id, lock_fingerprint)
        env_path = self.get_environment_path(profile_id, lock_fingerprint)

        # Create staging directory (not yet published)
        staging_path = env_path.parent / f".staging-{lock_fingerprint}"
        staging_path.mkdir(parents=True, exist_ok=True)

        info = EnvironmentInfo(
            environment_id=env_id,
            profile_id=profile_id,
            lock_fingerprint=lock_fingerprint,
            path=str(env_path),
            status=EnvironmentStatus.CREATING,
            python_version=python_version
            or f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            platform=platform.platform(),
        )

        # Write info to staging
        info_path = staging_path / "environment_info.json"
        info_path.write_text(info.model_dump_json(indent=2), encoding="utf-8")

        self._environments[env_id] = info
        return info

    def publish_environment(self, profile_id: str, lock_fingerprint: str) -> bool:
        """Publish an environment by atomic rename.

        §8.1: Successful installations are published by atomic rename.
        """
        env_id = self._compute_environment_id(profile_id, lock_fingerprint)
        env_path = self.get_environment_path(profile_id, lock_fingerprint)
        staging_path = env_path.parent / f".staging-{lock_fingerprint}"

        if not staging_path.exists():
            logger.error("Staging directory not found: %s", staging_path)
            return False

        # Atomic rename
        try:
            # Ensure parent exists
            env_path.parent.mkdir(parents=True, exist_ok=True)
            staging_path.rename(env_path)

            # Update status
            info = self._environments.get(env_id)
            if info:
                info.status = EnvironmentStatus.READY
                info.published_at = datetime.now(timezone.utc).isoformat()
                info_path = env_path / "environment_info.json"
                info_path.write_text(info.model_dump_json(indent=2), encoding="utf-8")

            logger.info("Published environment: %s", env_path)
            return True
        except OSError as e:
            logger.error("Failed to publish environment: %s", e)
            return False

    def quarantine_environment(self, profile_id: str, lock_fingerprint: str, error: str = "") -> bool:
        """Move a failed environment to quarantine.

        §8.1: Failed environments enter quarantine or the cleanup queue.
        """
        env_id = self._compute_environment_id(profile_id, lock_fingerprint)
        env_path = self.get_environment_path(profile_id, lock_fingerprint)
        staging_path = env_path.parent / f".staging-{lock_fingerprint}"
        quarantine_path = self.get_quarantine_path(profile_id, lock_fingerprint)

        # Move staging or env to quarantine
        source = staging_path if staging_path.exists() else env_path
        if not source.exists():
            return False

        try:
            quarantine_path.parent.mkdir(parents=True, exist_ok=True)
            source.rename(quarantine_path)

            # Update status
            info = self._environments.get(env_id)
            if info:
                info.status = EnvironmentStatus.QUARANTINED
                info.error = error
                info_path = quarantine_path / "environment_info.json"
                info_path.write_text(info.model_dump_json(indent=2), encoding="utf-8")

            logger.info("Quarantined environment: %s -> %s", source, quarantine_path)
            return True
        except OSError as e:
            logger.error("Failed to quarantine environment: %s", e)
            return False

    def remove_environment(self, profile_id: str, lock_fingerprint: str) -> bool:
        """Remove an environment.

        §8.2: Cancellability and environment removal.
        """
        env_id = self._compute_environment_id(profile_id, lock_fingerprint)
        env_path = self.get_environment_path(profile_id, lock_fingerprint)
        quarantine_path = self.get_quarantine_path(profile_id, lock_fingerprint)

        removed = False
        for path in [env_path, quarantine_path]:
            if path.exists():
                try:
                    shutil.rmtree(path)
                    removed = True
                    logger.info("Removed environment: %s", path)
                except OSError as e:
                    logger.error("Failed to remove environment %s: %s", path, e)

        if removed:
            self._environments.pop(env_id, None)

        return removed

    def cleanup_stale(self, max_age_hours: float = 24.0) -> int:
        """Clean up stale staging and quarantine directories."""
        cleaned = 0
        cutoff = time.time() - (max_age_hours * 3600)

        # Clean staging directories
        for profile_dir in self._cache_root.iterdir():
            if not profile_dir.is_dir():
                continue
            for item in profile_dir.iterdir():
                if item.name.startswith(".staging-"):
                    if item.stat().st_mtime < cutoff:
                        try:
                            shutil.rmtree(item)
                            cleaned += 1
                            logger.info("Cleaned stale staging: %s", item)
                        except OSError as e:
                            logger.warning("Failed to clean %s: %s", item, e)

        # Clean quarantine
        quarantine_root = self._cache_root / ".quarantine"
        if quarantine_root.exists():
            for profile_dir in quarantine_root.iterdir():
                if not profile_dir.is_dir():
                    continue
                for item in profile_dir.iterdir():
                    if item.stat().st_mtime < cutoff:
                        try:
                            shutil.rmtree(item)
                            cleaned += 1
                            logger.info("Cleaned stale quarantine: %s", item)
                        except OSError as e:
                            logger.warning("Failed to clean %s: %s", item, e)

        return cleaned

    def get_lock(self, profile_id: str, lock_fingerprint: str) -> EnvironmentLock:
        """Get a cross-process lock for an environment."""
        lock_dir = self._cache_root / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_name = f"{profile_id}-{lock_fingerprint}.lock"
        return EnvironmentLock(lock_dir / lock_name)

    def compute_lock_fingerprint(
        self,
        profile_id: str,
        packages: list[dict[str, str]],
    ) -> str:
        """Compute a stable fingerprint for lock file.

        §8.4: Keyed by (profile_id, lock_fingerprint).
        """
        data = {
            "profile_id": profile_id,
            "packages": sorted(packages, key=lambda p: p.get("distribution", "")),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "platform": platform.platform(),
        }
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()[:16]


# Global environment manager
_manager: EnvironmentManager | None = None


def get_environment_manager(cache_root: Path | str | None = None) -> EnvironmentManager:
    """Get the global environment manager."""
    global _manager
    if _manager is None:
        _manager = EnvironmentManager(cache_root)
    return _manager
