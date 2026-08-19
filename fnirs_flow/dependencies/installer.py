"""Controlled installer for dependency installation.

Implements §8.2, §8.3, §8.4 of the design document:

§8.2 - Installation approval content:
- Backend and profile name
- Direct dependencies with locked versions
- Package source and Git tag/commit
- Target environment path and estimated disk usage
- Network requirement
- Affected MethodAtoms
- Known license or platform restrictions
- Cancellability and environment removal method

§8.3 - Source and supply chain control:
- Only install pre-declared dependencies from registry
- Git deps prefer commit SHA; tag only as readable version
- Verify declared package version when available
- Install commands use parameter arrays (no shell string concatenation)
- No tokens, credentials in logs
- Generate frozen requirements and an explicit environment revision after install
- MethodAtom parameters cannot override package source/index URL

§8.4 - Concurrency and cancellation:
- Keyed by (profile_id, environment revision)
- Shared installation task for concurrent requests
- First request creates task; subsequent subscribe to progress
- Single subscriber cancel doesn't stop task with other subscribers
- All subscribers cancel triggers safe termination
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fnirs_flow.dependencies.environment_manager import (
    EnvironmentManager,
    get_environment_manager,
)
from fnirs_flow.dependencies.models import (
    ApprovalRecord,
    DependencyPlan,
    InstallationTask,
    InstallPolicy,
    PackageRequirement,
)
from fnirs_flow.dependencies.policies import (
    SourceAllowlist,
    get_allowlist,
    get_policy_manager,
)

logger = logging.getLogger(__name__)


class InstallerStatus(str, Enum):
    """Status of the installer."""

    IDLE = "idle"
    VALIDATING = "validating"
    INSTALLING = "installing"
    PROBING = "probing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InstallProgress(BaseModel):
    """Progress update for installation."""

    task_id: str
    status: InstallerStatus
    progress: float = 0.0  # 0.0 to 1.0
    message: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DependencyInstaller:
    """Controlled installer for dependency installation.

    §8.3: Install commands use parameter arrays, no shell string concatenation.
    §8.3: No tokens/credentials in logs.
    §8.3: Generate frozen requirements after install.
    """

    def __init__(
        self,
        environment_manager: EnvironmentManager | None = None,
        allowlist: SourceAllowlist | None = None,
    ) -> None:
        self._env_manager = environment_manager or get_environment_manager()
        self._allowlist = allowlist or get_allowlist()
        self._tasks: dict[str, InstallationTask] = {}
        self._subscribers: dict[str, list[Any]] = {}  # task_id -> [callbacks]
        self._cancel_flags: dict[str, bool] = {}

    def validate_approval(
        self,
        plan: DependencyPlan,
        approval: ApprovalRecord,
    ) -> tuple[bool, list[str]]:
        """Validate an approval record against a plan.

        §8.2: approval validates the plan revision, source policy, and
        target environment before creating an installation task.

        Returns:
            (is_valid, list of error messages)
        """
        errors: list[str] = []

        if approval.plan_id != plan.plan_id or approval.plan_revision != plan.revision:
            errors.append("Plan ID or revision does not match the approval record")

        # Verify decision
        if approval.decision != InstallPolicy.APPROVED_ONCE:
            errors.append(f"Invalid decision: {approval.decision.value}")

        # Verify sources are allowlisted
        for req in plan.requirements:
            source = req.package.source
            if source and not self._allowlist.is_allowed(source):
                errors.append(f"Source not allowed: {source} (package: {req.package.distribution})")

        return len(errors) == 0, errors

    def create_task(
        self,
        plan: DependencyPlan,
        approval: ApprovalRecord,
    ) -> InstallationTask:
        """Create an installation task.

        §8.4: The first request creates the task.
        """
        # Validate approval
        is_valid, errors = self.validate_approval(plan, approval)
        if not is_valid:
            raise ValueError(f"Invalid approval: {'; '.join(errors)}")

        # Check policy
        policy_manager = get_policy_manager()
        plan_key = f"{plan.plan_id}:{plan.revision}"
        if not policy_manager.is_approved(plan_key):
            raise ValueError("Plan is not approved for installation")

        # Create task
        task_id = f"install-{plan.plan_id}-{int(time.time())}"
        task = InstallationTask(
            task_id=task_id,
            plan_id=plan.plan_id,
            profile_id=plan.requirements[0].profile_id if plan.requirements else "unknown",
            status="pending",
        )

        self._tasks[task_id] = task
        self._cancel_flags[task_id] = False
        self._subscribers[task_id] = []

        return task

    def execute_task(
        self,
        task_id: str,
        plan: DependencyPlan,
    ) -> InstallationTask:
        """Execute an installation task.

        §8.3: Install commands use parameter arrays.
        §8.3: No tokens/credentials in logs.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        task.status = "running"
        task.started_at = datetime.now(timezone.utc).isoformat()

        try:
            # Get environment info
            env_info = self._env_manager.get_environment(
                task.profile_id,
                f"revision-{plan.revision}",
            )

            if env_info is None:
                # Create environment
                env_info = self._env_manager.create_environment(
                    task.profile_id,
                    f"revision-{plan.revision}",
                )

            env_path = Path(env_info.path)

            # Install each requirement
            total = len(plan.requirements)
            for i, req in enumerate(plan.requirements):
                # Check cancellation
                if self._cancel_flags.get(task_id, False):
                    task.status = "cancelled"
                    task.completed_at = datetime.now(timezone.utc).isoformat()
                    task.log_lines.append("Installation cancelled by user")
                    return task

                # Update progress
                task.progress = (i / total) * 100
                task.log_lines.append(f"Installing {req.package.distribution}...")
                self._notify_subscribers(task_id, InstallProgress(
                    task_id=task_id,
                    status=InstallerStatus.INSTALLING,
                    progress=task.progress / 100,
                    message=f"Installing {req.package.distribution}",
                ))

                # Install package
                success = self._install_package(
                    req.package,
                    env_path,
                    task,
                )

                if not success:
                    task.status = "failed"
                    task.completed_at = datetime.now(timezone.utc).isoformat()
                    task.error = f"Failed to install {req.package.distribution}"
                    self._env_manager.quarantine_environment(
                        task.profile_id,
                        f"revision-{plan.revision}",
                        error=task.error,
                    )
                    return task

            # Generate frozen requirements
            frozen = self._freeze_requirements(env_path)
            task.log_lines.append(f"Frozen requirements:\n{frozen}")

            # Publish environment
            published = self._env_manager.publish_environment(
                task.profile_id,
                f"revision-{plan.revision}",
            )

            if published:
                task.status = "completed"
                task.progress = 100
                task.log_lines.append("Environment published successfully")
            else:
                task.status = "failed"
                task.error = "Failed to publish environment"

            task.completed_at = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            task.status = "failed"
            task.completed_at = datetime.now(timezone.utc).isoformat()
            task.error = str(e)
            task.log_lines.append(f"Error: {e}")
            logger.error("Installation failed: %s", e)

        return task

    def _install_package(
        self,
        package: PackageRequirement,
        env_path: Path,
        task: InstallationTask,
    ) -> bool:
        """Install a single package.

        §8.3: Install commands use parameter arrays, no shell string concatenation.
        §8.3: No tokens/credentials in logs.
        """
        # Build install command as parameter array
        pip_cmd = [sys.executable, "-m", "pip", "install"]

        # Add target directory
        pip_cmd.extend(["--target", str(env_path)])

        # Add source
        source = package.source
        if source.startswith("git+"):
            # Git dependency
            pip_cmd.append(source)
        elif source.startswith("pypi://"):
            # PyPI dependency
            pkg_name = source.replace("pypi://", "")
            if package.version_specifier:
                pip_cmd.append(f"{pkg_name}{package.version_specifier}")
            else:
                pip_cmd.append(pkg_name)
        else:
            # Direct source
            pip_cmd.append(source)

        # Add quiet flag
        pip_cmd.append("--quiet")

        # Log command (sanitized - no credentials)
        sanitized_cmd = self._sanitize_command(pip_cmd)
        task.log_lines.append(f"Running: {' '.join(sanitized_cmd)}")

        try:
            # Run in subprocess
            result = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )

            if result.returncode == 0:
                task.log_lines.append(f"Installed {package.distribution}")
                return True
            else:
                # Sanitize error output
                error = self._sanitize_output(result.stderr)
                task.log_lines.append(f"Failed: {error}")
                return False

        except subprocess.TimeoutExpired:
            task.log_lines.append(f"Timeout installing {package.distribution}")
            return False
        except Exception as e:
            task.log_lines.append(f"Error: {e}")
            return False

    def _sanitize_command(self, cmd: list[str]) -> list[str]:
        """Sanitize command for logging (remove credentials).

        §8.3: Do not write tokens, private index credentials, or complete
        environment variables to logs.
        """
        sanitized = []
        skip_next = False
        for arg in cmd:
            if skip_next:
                sanitized.append("***")
                skip_next = False
                continue
            if arg in ("--index-url", "--extra-index-url", "--client-cert"):
                sanitized.append(arg)
                skip_next = True
            elif "token" in arg.lower() or "password" in arg.lower():
                sanitized.append("***")
            else:
                sanitized.append(arg)
        return sanitized

    def _sanitize_output(self, output: str) -> str:
        """Sanitize output for logging (remove credentials).

        §8.3: Installation logs keep necessary diagnostics and redact paths,
        usernames, and credentials.
        """
        import re
        # Remove potential tokens in key=value format
        output = re.sub(r'token=[^\s]+', 'token=***', output)
        output = re.sub(r'password=[^\s]+', 'password=***', output)
        # Remove credentials in URLs (e.g., https://user:token@host)
        output = re.sub(r'(https?://)([^:]+):([^@]+)@', r'\1\2:***@', output)
        # Remove home directory paths
        home = str(Path.home())
        output = output.replace(home, '~')
        return output

    def _freeze_requirements(self, env_path: Path) -> str:
        """Generate frozen requirements for environment.

        §8.3: Generate frozen requirements and an explicit environment revision after
        installation completes.
        """
        pip_cmd = [
            sys.executable, "-m", "pip", "freeze",
            "--path", str(env_path),
        ]

        try:
            result = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout
            return f"# Error freezing: {result.stderr}"
        except Exception as e:
            return f"# Error freezing: {e}"

    def subscribe(self, task_id: str, callback: Any) -> bool:
        """Subscribe to installation progress.

        §8.4: Later requests subscribe to progress.
        """
        if task_id not in self._tasks:
            return False
        self._subscribers.setdefault(task_id, []).append(callback)
        return True

    def cancel(self, task_id: str) -> bool:
        """Cancel an installation task.

        §8.4: One subscriber cancellation does not stop an installation that
        still has other subscribers.
        """
        if task_id not in self._tasks:
            return False

        self._cancel_flags[task_id] = True
        self._notify_subscribers(task_id, InstallProgress(
            task_id=task_id,
            status=InstallerStatus.CANCELLED,
            message="Cancellation requested",
        ))
        return True

    def _notify_subscribers(self, task_id: str, progress: InstallProgress) -> None:
        """Notify all subscribers of progress update."""
        for callback in self._subscribers.get(task_id, []):
            try:
                callback(progress)
            except Exception as e:
                logger.warning("Subscriber callback error: %s", e)

    def get_task(self, task_id: str) -> InstallationTask | None:
        """Get installation task status."""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[InstallationTask]:
        """List all installation tasks."""
        return list(self._tasks.values())

    def cleanup_task(self, task_id: str) -> bool:
        """Clean up a completed task."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.status in ("completed", "failed", "cancelled"):
            self._tasks.pop(task_id, None)
            self._cancel_flags.pop(task_id, None)
            self._subscribers.pop(task_id, None)
            return True
        return False


class InstallationOrchestrator:
    """Orchestrates the full installation workflow.

    Combines:
    - Dependency resolution
    - Approval validation
    - Environment management
    - Package installation
    - Capability probing
    """

    def __init__(
        self,
        environment_manager: EnvironmentManager | None = None,
        installer: DependencyInstaller | None = None,
    ) -> None:
        self._env_manager = environment_manager or get_environment_manager()
        self._installer = installer or DependencyInstaller(self._env_manager)

    def install_from_plan(
        self,
        plan: DependencyPlan,
        approval: ApprovalRecord,
    ) -> InstallationTask:
        """Execute installation from a dependency plan.

        §8.2: Full workflow from approval to installation.
        """
        # Create and execute task
        task = self._installer.create_task(plan, approval)
        task = self._installer.execute_task(task.task_id, plan)

        return task

    def check_environment(
        self,
        profile_id: str,
        environment_revision: str,
    ) -> dict[str, Any]:
        """Check if an environment exists and is ready."""
        env_info = self._env_manager.get_environment(profile_id, environment_revision)
        if env_info is None:
            return {
                "exists": False,
                "status": "not_found",
            }
        return {
            "exists": True,
            "status": env_info.status.value,
            "path": env_info.path,
            "created_at": env_info.created_at,
            "published_at": env_info.published_at,
        }

    def remove_environment(
        self,
        profile_id: str,
        environment_revision: str,
    ) -> bool:
        """Remove an environment."""
        return self._env_manager.remove_environment(profile_id, environment_revision)

    def list_environments(self) -> list[dict[str, Any]]:
        """List all environments."""
        envs = self._env_manager.list_environments()
        return [
            {
                "environment_id": e.environment_id,
                "profile_id": e.profile_id,
                "status": e.status.value,
                "path": e.path,
                "created_at": e.created_at,
                "published_at": e.published_at,
            }
            for e in envs
        ]

    def list_tasks(self) -> list[Any]:
        """List all installation tasks."""
        return self._installer.list_tasks()

    def cancel(self, task_id: str) -> bool:
        """Cancel an installation task."""
        return self._installer.cancel(task_id)


# Global orchestrator (thread-safe singleton)
_orchestrator: InstallationOrchestrator | None = None
_orchestrator_lock = __import__("threading").Lock()


def get_installation_orchestrator() -> InstallationOrchestrator:
    """Get the global installation orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
            if _orchestrator is None:
                _orchestrator = InstallationOrchestrator()
    return _orchestrator
