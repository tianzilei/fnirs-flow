"""Tests for Phase 3: Controlled isolated installation.

Tests for:
- EnvironmentManager (§8.1, §8.4)
- DependencyInstaller (§8.2, §8.3, §8.4)
- InstallationOrchestrator
"""

from __future__ import annotations

import pytest


@pytest.mark.core
class TestEnvironmentManager:
    """Test isolated environment manager (§8.1, §8.4)."""

    def test_create_environment(self, tmp_path):
        """Verify environment creation."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "envs")
        info = manager.create_environment("test-1.0", "abc123")

        assert info.profile_id == "test-1.0"
        assert info.lock_fingerprint == "abc123"
        assert info.status.value == "creating"

    def test_publish_environment(self, tmp_path):
        """Verify atomic publish (§8.1)."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "envs")
        manager.create_environment("test-1.0", "abc123")

        # Create staging directory
        env_path = manager.get_environment_path("test-1.0", "abc123")
        staging_path = env_path.parent / ".staging-abc123"
        staging_path.mkdir(parents=True, exist_ok=True)

        # Publish
        success = manager.publish_environment("test-1.0", "abc123")
        assert success

        # Check environment exists
        assert manager.environment_exists("test-1.0", "abc123")
        info = manager.get_environment("test-1.0", "abc123")
        assert info is not None
        assert info.status.value == "ready"
        assert info.published_at is not None

    def test_quarantine_environment(self, tmp_path):
        """Verify quarantine on failure (§8.1)."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "envs")
        manager.create_environment("test-1.0", "abc123")

        # Create staging directory
        env_path = manager.get_environment_path("test-1.0", "abc123")
        staging_path = env_path.parent / ".staging-abc123"
        staging_path.mkdir(parents=True, exist_ok=True)

        # Quarantine
        success = manager.quarantine_environment("test-1.0", "abc123", error="test error")
        assert success

        # Check quarantine
        info = manager.get_environment("test-1.0", "abc123")
        assert info is not None
        assert info.status.value == "quarantined"
        assert info.error == "test error"

    def test_remove_environment(self, tmp_path):
        """Verify environment removal (§8.2)."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "envs")
        manager.create_environment("test-1.0", "abc123")

        # Create and publish
        env_path = manager.get_environment_path("test-1.0", "abc123")
        staging_path = env_path.parent / ".staging-abc123"
        staging_path.mkdir(parents=True, exist_ok=True)
        manager.publish_environment("test-1.0", "abc123")

        # Remove
        success = manager.remove_environment("test-1.0", "abc123")
        assert success

        # Check removed
        assert not manager.environment_exists("test-1.0", "abc123")

    def test_list_environments(self, tmp_path):
        """Verify environment listing."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "envs")
        manager.create_environment("test-1.0", "abc123")
        manager.create_environment("test-2.0", "def456")

        envs = manager.list_environments()
        assert len(envs) == 2

    def test_lock_fingerprint_stable(self, tmp_path):
        """Verify lock fingerprint is deterministic (§8.4)."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "envs")
        packages = [
            {"distribution": "pkg-a", "version": "1.0"},
            {"distribution": "pkg-b", "version": "2.0"},
        ]

        fp1 = manager.compute_lock_fingerprint("test-1.0", packages)
        fp2 = manager.compute_lock_fingerprint("test-1.0", packages)
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_lock_acquisition(self, tmp_path):
        """Verify cross-process locking (§8.4)."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "envs")
        lock = manager.get_lock("test-1.0", "abc123")

        # Acquire lock
        acquired = lock.acquire(timeout=1.0)
        assert acquired

        # Release lock
        lock.release()

    def test_stale_cleanup(self, tmp_path):
        """Verify stale staging cleanup."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "envs")
        manager.create_environment("test-1.0", "abc123")

        # Create staging directory
        env_path = manager.get_environment_path("test-1.0", "abc123")
        staging_path = env_path.parent / ".staging-abc123"
        staging_path.mkdir(parents=True, exist_ok=True)

        # Cleanup (should not clean fresh staging)
        cleaned = manager.cleanup_stale(max_age_hours=24.0)
        assert cleaned == 0


@pytest.mark.core
class TestDependencyInstaller:
    """Test dependency installer (§8.2, §8.3, §8.4)."""

    def test_validate_approval_fingerprint(self, tmp_path):
        """Verify approval fingerprint validation (§8.2)."""
        from fnirs_flow.dependencies.installer import DependencyInstaller
        from fnirs_flow.dependencies.models import (
            ApprovalRecord,
            DependencyPlan,
            InstallPolicy,
            PackageRequirement,
            RequirementStatus,
            ResolvedRequirement,
        )

        installer = DependencyInstaller()

        plan = DependencyPlan(
            plan_id="test-plan",
            flow_id="test-flow",
            requirements=[
                ResolvedRequirement(
                    package=PackageRequirement(
                        distribution="test",
                        import_name="test",
                        version_specifier="==1.0",
                        source="pypi://test",
                    ),
                    profile_id="test-1.0",
                    status=RequirementStatus.SATISFIED,
                )
            ],
        )
        plan.plan_fingerprint = plan.compute_fingerprint()

        # Matching fingerprint
        approval_ok = ApprovalRecord(
            plan_id="test-plan",
            plan_fingerprint=plan.plan_fingerprint,
            decision=InstallPolicy.APPROVED_ONCE,
        )
        is_valid, errors = installer.validate_approval(plan, approval_ok)
        assert is_valid
        assert len(errors) == 0

        # Mismatched fingerprint
        approval_bad = ApprovalRecord(
            plan_id="test-plan",
            plan_fingerprint="wrong-fingerprint",
            decision=InstallPolicy.APPROVED_ONCE,
        )
        is_valid, errors = installer.validate_approval(plan, approval_bad)
        assert not is_valid
        assert any("fingerprint" in e.lower() for e in errors)

    def test_validate_approval_source(self, tmp_path):
        """Verify source allowlist validation (§8.3)."""
        from fnirs_flow.dependencies.installer import DependencyInstaller
        from fnirs_flow.dependencies.models import (
            ApprovalRecord,
            DependencyPlan,
            InstallPolicy,
            PackageRequirement,
            RequirementStatus,
            ResolvedRequirement,
        )

        installer = DependencyInstaller()

        # Plan with allowed source
        plan_ok = DependencyPlan(
            plan_id="test",
            flow_id="f",
            requirements=[
                ResolvedRequirement(
                    package=PackageRequirement(
                        distribution="test",
                        import_name="test",
                        version_specifier="",
                        source="pypi://test",
                    ),
                    profile_id="p",
                    status=RequirementStatus.SATISFIED,
                )
            ],
        )
        plan_ok.plan_fingerprint = plan_ok.compute_fingerprint()

        approval = ApprovalRecord(
            plan_id="test",
            plan_fingerprint=plan_ok.plan_fingerprint,
            decision=InstallPolicy.APPROVED_ONCE,
        )

        is_valid, errors = installer.validate_approval(plan_ok, approval)
        assert is_valid

    def test_validate_approval_rejects_bad_source(self, tmp_path):
        """Verify bad source is rejected (§8.3)."""
        from fnirs_flow.dependencies.installer import DependencyInstaller
        from fnirs_flow.dependencies.models import (
            ApprovalRecord,
            DependencyPlan,
            InstallPolicy,
            PackageRequirement,
            RequirementStatus,
            ResolvedRequirement,
        )

        installer = DependencyInstaller()

        # Plan with disallowed source
        plan_bad = DependencyPlan(
            plan_id="test",
            flow_id="f",
            requirements=[
                ResolvedRequirement(
                    package=PackageRequirement(
                        distribution="malicious",
                        import_name="malicious",
                        version_specifier="",
                        source="git+https://evil.com/malicious.git",
                    ),
                    profile_id="p",
                    status=RequirementStatus.MISSING,
                )
            ],
        )
        plan_bad.plan_fingerprint = plan_bad.compute_fingerprint()

        approval = ApprovalRecord(
            plan_id="test",
            plan_fingerprint=plan_bad.plan_fingerprint,
            decision=InstallPolicy.APPROVED_ONCE,
        )

        is_valid, errors = installer.validate_approval(plan_bad, approval)
        assert not is_valid
        assert any("not allowed" in e.lower() for e in errors)

    def test_create_task(self, tmp_path):
        """Verify task creation (§8.4)."""
        from fnirs_flow.dependencies.installer import DependencyInstaller
        from fnirs_flow.dependencies.models import (
            ApprovalRecord,
            DependencyPlan,
            InstallPolicy,
            PackageRequirement,
            RequirementStatus,
            ResolvedRequirement,
        )

        installer = DependencyInstaller()

        plan = DependencyPlan(
            plan_id="test",
            flow_id="f",
            requirements=[
                ResolvedRequirement(
                    package=PackageRequirement(
                        distribution="test",
                        import_name="test",
                        version_specifier="",
                        source="pypi://test",
                    ),
                    profile_id="p",
                    status=RequirementStatus.MISSING,
                )
            ],
        )
        plan.plan_fingerprint = plan.compute_fingerprint()

        # Approve plan
        from fnirs_flow.dependencies.policies import get_policy_manager
        policy_manager = get_policy_manager()
        policy_manager.approve_plan(plan.plan_fingerprint)

        approval = ApprovalRecord(
            plan_id="test",
            plan_fingerprint=plan.plan_fingerprint,
            decision=InstallPolicy.APPROVED_ONCE,
        )

        task = installer.create_task(plan, approval)
        assert task is not None
        assert task.status == "pending"
        assert task.plan_id == "test"

    def test_cancel_task(self, tmp_path):
        """Verify task cancellation (§8.4)."""
        from fnirs_flow.dependencies.installer import DependencyInstaller

        installer = DependencyInstaller()

        # Create a mock task
        from fnirs_flow.dependencies.models import InstallationTask
        task = InstallationTask(
            task_id="test-task",
            plan_id="test-plan",
            profile_id="test-1.0",
            status="pending",
        )
        installer._tasks["test-task"] = task
        installer._cancel_flags["test-task"] = False
        installer._subscribers["test-task"] = []

        # Cancel
        success = installer.cancel("test-task")
        assert success
        assert installer._cancel_flags["test-task"] is True

    def test_sanitize_command(self, tmp_path):
        """Verify command sanitization (§8.3)."""
        from fnirs_flow.dependencies.installer import DependencyInstaller

        installer = DependencyInstaller()

        # Command with potential credentials
        cmd = [
            "pip", "install",
            "--index-url", "https://user:token@private.pypi.com/simple",
            "package",
        ]

        sanitized = installer._sanitize_command(cmd)
        # Should not contain raw credentials
        assert "token" not in " ".join(sanitized)

    def test_sanitize_output(self, tmp_path):
        """Verify output sanitization (§8.3)."""
        from fnirs_flow.dependencies.installer import DependencyInstaller

        installer = DependencyInstaller()

        output = "Installing from https://user:token@private.pypi.com/simple"
        sanitized = installer._sanitize_output(output)
        assert "token" not in sanitized or "***" in sanitized


@pytest.mark.core
class TestInstallationOrchestrator:
    """Test installation orchestrator."""

    def test_check_environment_not_found(self, tmp_path):
        """Verify check for non-existent environment."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager
        from fnirs_flow.dependencies.installer import InstallationOrchestrator

        env_manager = EnvironmentManager(tmp_path / "envs")
        orchestrator = InstallationOrchestrator(env_manager)

        result = orchestrator.check_environment("test-1.0", "nonexistent")
        assert result["exists"] is False
        assert result["status"] == "not_found"

    def test_list_environments_empty(self, tmp_path):
        """Verify empty environment listing."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager
        from fnirs_flow.dependencies.installer import InstallationOrchestrator

        env_manager = EnvironmentManager(tmp_path / "envs")
        orchestrator = InstallationOrchestrator(env_manager)

        envs = orchestrator.list_environments()
        assert len(envs) == 0


@pytest.mark.core
class TestPhase3Integration:
    """Integration tests for Phase 3 components."""

    def test_full_workflow_mock(self, tmp_path):
        """Test full workflow with mock installation."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager
        from fnirs_flow.dependencies.installer import DependencyInstaller
        from fnirs_flow.dependencies.models import (
            ApprovalRecord,
            DependencyPlan,
            InstallPolicy,
            PackageRequirement,
            RequirementStatus,
            ResolvedRequirement,
        )

        env_manager = EnvironmentManager(tmp_path / "envs")
        installer = DependencyInstaller(env_manager)

        # Create plan
        plan = DependencyPlan(
            plan_id="integration-test",
            flow_id="test-flow",
            requirements=[
                ResolvedRequirement(
                    package=PackageRequirement(
                        distribution="pydantic",
                        import_name="pydantic",
                        version_specifier=">=2.0",
                        source="pypi://pydantic",
                    ),
                    profile_id="test-1.0",
                    status=RequirementStatus.MISSING,
                )
            ],
        )
        plan.plan_fingerprint = plan.compute_fingerprint()

        # Approve plan
        from fnirs_flow.dependencies.policies import get_policy_manager
        policy_manager = get_policy_manager()
        policy_manager.approve_plan(plan.plan_fingerprint)

        approval = ApprovalRecord(
            plan_id="integration-test",
            plan_fingerprint=plan.plan_fingerprint,
            decision=InstallPolicy.APPROVED_ONCE,
        )

        # Create task
        task = installer.create_task(plan, approval)
        assert task.status == "pending"

        # Task should be in list
        tasks = installer.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_id == task.task_id


@pytest.mark.core
class TestDesignDocumentCompliance:
    """Verify compliance with design document requirements."""

    def test_environment_path_format(self, tmp_path):
        """§8.1: <cache_root>/backend-envs/<profile_id>/<lock_fingerprint>/"""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "backend-envs")
        path = manager.get_environment_path("cedalion-26.5", "abc123def456")

        assert "cedalion-26.5" in str(path)
        assert "abc123def456" in str(path)

    def test_quarantine_path_format(self, tmp_path):
        """§8.1: Failed environments go to quarantine."""
        from fnirs_flow.dependencies.environment_manager import EnvironmentManager

        manager = EnvironmentManager(tmp_path / "backend-envs")
        path = manager.get_quarantine_path("cedalion-26.5", "abc123def456")

        assert ".quarantine" in str(path)
        assert "cedalion-26.5" in str(path)

    def test_no_shell_string_concatenation(self, tmp_path):
        """§8.3: Install commands use parameter arrays."""
        from fnirs_flow.dependencies.installer import DependencyInstaller

        installer = DependencyInstaller()

        # Verify _install_package builds command as array
        # (This is a structural test - the actual method uses subprocess.run with list)
        import inspect
        source = inspect.getsource(installer._install_package)
        assert "pip_cmd" in source
        assert "subprocess.run" in source

    def test_approval_record_structure(self):
        """§8.2: Approval record contains required fields."""
        from fnirs_flow.dependencies.models import ApprovalRecord, InstallPolicy

        approval = ApprovalRecord(
            plan_id="depplan-test",
            plan_fingerprint="sha256:abc123",
            decision=InstallPolicy.APPROVED_ONCE,
            approved_by="local-user",
            allowed_sources=["github.com/ibs-lab/cedalion"],
            target_environment="backend-envs/cedalion-26.5/...",
        )

        assert approval.plan_id == "depplan-test"
        assert approval.decision == InstallPolicy.APPROVED_ONCE
        assert approval.approved_by == "local-user"
        assert len(approval.allowed_sources) > 0

    def test_installation_task_structure(self):
        """§8.4: Installation task tracks progress."""
        from fnirs_flow.dependencies.models import InstallationTask

        task = InstallationTask(
            task_id="install-test-123",
            plan_id="depplan-test",
            profile_id="cedalion-26.5",
        )

        assert task.task_id == "install-test-123"
        assert task.status == "pending"
        assert task.progress == 0.0
        assert isinstance(task.log_lines, list)
