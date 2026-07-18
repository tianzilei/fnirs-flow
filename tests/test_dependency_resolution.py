"""Regression tests for dependency resolution and lazy backend loading.

Implements §15.3 of the design document:
- Core tests don't require Cedalion
- MethodAtom Library API works without Cedalion installed
- /api/backends doesn't import Cedalion
- Non-Cedalion Flow compilation/execution not slowed by Cedalion profile

Key assertion: assert "cedalion" not in sys.modules
"""

from __future__ import annotations

import json
import sys

import pytest


@pytest.mark.core
class TestDependencyModels:
    """Test dependency data models (§15.1)."""

    def test_requirement_status_enum(self):
        """Verify all required status values exist."""
        from fnirs_flow.dependencies.models import RequirementStatus

        assert RequirementStatus.SATISFIED.value == "satisfied"
        assert RequirementStatus.MISSING.value == "missing"
        assert RequirementStatus.INCOMPATIBLE_VERSION.value == "incompatible_version"
        assert RequirementStatus.INCOMPATIBLE_PYTHON.value == "incompatible_python"
        assert RequirementStatus.CAPABILITY_MISSING.value == "capability_missing"
        assert RequirementStatus.BROKEN_IMPORT.value == "broken_import"
        assert RequirementStatus.SOURCE_NOT_ALLOWED.value == "source_not_allowed"
        assert RequirementStatus.INTEGRITY_UNVERIFIED.value == "integrity_unverified"
        assert RequirementStatus.PROBE_FAILED.value == "probe_failed"

    def test_plan_status_enum(self):
        """Verify all plan status values exist."""
        from fnirs_flow.dependencies.models import PlanStatus

        assert PlanStatus.UNRESOLVED.value == "unresolved"
        assert PlanStatus.RESOLVING.value == "resolving"
        assert PlanStatus.SATISFIED.value == "satisfied"
        assert PlanStatus.APPROVAL_REQUIRED.value == "approval_required"
        assert PlanStatus.BLOCKED.value == "blocked"

    def test_dependency_profile_fingerprint_stable(self):
        """Verify profile fingerprint is deterministic."""
        from fnirs_flow.dependencies.models import DependencyProfile, PackageRequirement

        profile = DependencyProfile(
            profile_id="test-1.0",
            backend_id="test",
            display_name="Test",
            python_requires=">=3.10",
            packages=[
                PackageRequirement(
                    distribution="test-pkg",
                    import_name="test_pkg",
                    version_specifier="==1.0.0",
                    source="pypi://test-pkg",
                )
            ],
            capabilities={"cap1", "cap2"},
            install_source_policy="pypi",
            environment_strategy="main",
            probe_module="test.probe",
        )

        fp1 = profile.fingerprint()
        fp2 = profile.fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex

    def test_dependency_plan_fingerprint_stable(self):
        """Verify plan fingerprint is deterministic."""
        from fnirs_flow.dependencies.models import (
            DependencyPlan,
            PackageRequirement,
            RequirementStatus,
            ResolvedRequirement,
        )

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
            affected_atoms={"test-1.0": ["atom1"]},
        )

        fp1 = plan.compute_fingerprint()
        fp2 = plan.compute_fingerprint()
        assert fp1 == fp2

    def test_dependency_plan_is_satisfied(self):
        """Verify is_satisfied() correctly checks all requirements."""
        from fnirs_flow.dependencies.models import (
            DependencyPlan,
            PackageRequirement,
            RequirementStatus,
            ResolvedRequirement,
        )

        # All satisfied
        plan_ok = DependencyPlan(
            plan_id="ok",
            flow_id="f",
            requirements=[
                ResolvedRequirement(
                    package=PackageRequirement(
                        distribution="t", import_name="t", version_specifier="", source=""
                    ),
                    profile_id="p",
                    status=RequirementStatus.SATISFIED,
                )
            ],
        )
        assert plan_ok.is_satisfied()

        # One missing
        plan_missing = DependencyPlan(
            plan_id="missing",
            flow_id="f",
            requirements=[
                ResolvedRequirement(
                    package=PackageRequirement(
                        distribution="t", import_name="t", version_specifier="", source=""
                    ),
                    profile_id="p",
                    status=RequirementStatus.SATISFIED,
                ),
                ResolvedRequirement(
                    package=PackageRequirement(
                        distribution="x", import_name="x", version_specifier="", source=""
                    ),
                    profile_id="p",
                    status=RequirementStatus.MISSING,
                ),
            ],
        )
        assert not plan_missing.is_satisfied()
        assert len(plan_missing.blocked_requirements()) == 1


@pytest.mark.core
class TestDependencyProfileRegistry:
    """Test dependency profile registry (§15.1)."""

    def test_known_profiles_registered(self):
        """Verify Cedalion and MNE-NIRS profiles are registered."""
        from fnirs_flow.registry.dependency_profiles import get_profile_registry

        registry = get_profile_registry()
        profiles = registry.list_all()
        profile_ids = [p.profile_id for p in profiles]

        assert "cedalion-26.5" in profile_ids
        assert "mne-nirs-1.0" in profile_ids

    def test_cedalion_profile_correct(self):
        """Verify Cedalion profile matches design document."""
        from fnirs_flow.registry.dependency_profiles import get_profile_registry

        registry = get_profile_registry()
        profile = registry.get("cedalion-26.5")

        assert profile is not None
        assert profile.backend_id == "cedalion"
        assert profile.python_requires == ">=3.11,<3.13"
        assert len(profile.packages) == 1
        assert profile.packages[0].distribution == "cedalion"
        assert profile.packages[0].version_specifier == "==26.5.1"
        assert "snirf_read" in profile.capabilities
        assert "int2od" in profile.capabilities

    def test_list_for_backend(self):
        """Verify listing profiles by backend."""
        from fnirs_flow.registry.dependency_profiles import get_profile_registry

        registry = get_profile_registry()
        cedalion_profiles = registry.list_for_backend("cedalion")
        assert len(cedalion_profiles) >= 1
        assert all(p.backend_id == "cedalion" for p in cedalion_profiles)


@pytest.mark.core
class TestLazyBackendRegistry:
    """Test lazy backend registry (§15.1).

    Key: describe(), list_all(), is_available() must NOT import backends.
    """

    def test_list_all_without_import(self):
        """Verify list_all() works without importing backends."""
        from fnirs_flow.adapters.backend_registry import get_registry

        registry = get_registry()
        all_backends = registry.list_all()

        assert "mne_nirs" in all_backends
        assert "cedalion" in all_backends

    def test_describe_without_import(self):
        """Verify describe() returns metadata without importing."""
        from fnirs_flow.adapters.backend_registry import get_registry

        registry = get_registry()
        desc = registry.describe("cedalion")

        assert desc is not None
        assert desc["backend_id"] == "cedalion"
        assert desc["class_path"] == "fnirs_flow.adapters.cedalion_adapter:CedalionAdapter"
        assert desc["dependency_profile_id"] == "cedalion-26.5"
        assert "is_available" in desc
        assert "is_loaded" in desc

    def test_describe_nonexistent(self):
        """Verify describe() returns None for unknown backend."""
        from fnirs_flow.adapters.backend_registry import get_registry

        registry = get_registry()
        assert registry.describe("nonexistent") is None

    def test_is_available_uses_detector(self):
        """Verify is_available() uses lightweight detector."""
        from fnirs_flow.adapters.backend_registry import get_registry

        registry = get_registry()
        # This should use find_spec, not import
        result = registry.is_available("cedalion")
        # Result depends on whether cedalion is installed, but should not raise
        assert isinstance(result, bool)


@pytest.mark.core
class TestDependencyResolver:
    """Test dependency resolver (§15.1, §15.2)."""

    def test_resolve_empty_dag(self):
        """Verify resolver handles empty DAG."""
        from fnirs_flow.dependencies.resolver import resolve_dependencies

        dag = {"atoms": [], "nodes": [], "edges": []}
        plan = resolve_dependencies(dag, flow_id="test-empty")

        assert plan.is_satisfied()
        assert len(plan.requirements) == 0
        assert plan.status.value == "satisfied"

    def test_resolve_no_backend_atoms(self):
        """Verify resolver handles atoms without backend."""
        from fnirs_flow.dependencies.resolver import resolve_dependencies

        dag = {
            "atoms": [
                {
                    "atom_id": "atom1",
                    "atom_type": "test",
                    "category": "preprocessing",
                    "backend_id": None,
                }
            ],
            "edges": [],
        }
        plan = resolve_dependencies(dag, flow_id="test-no-backend")

        assert plan.is_satisfied()
        assert len(plan.requirements) == 0

    def test_resolve_with_backend(self):
        """Verify resolver checks backend dependencies."""
        from fnirs_flow.dependencies.resolver import resolve_dependencies

        dag = {
            "atoms": [
                {
                    "atom_id": "atom-od",
                    "atom_type": "optical_density",
                    "operation": "intensity_to_od",
                    "category": "preprocessing",
                    "backend_id": "mne_nirs",
                }
            ],
            "edges": [],
        }
        plan = resolve_dependencies(dag, flow_id="test-mne")

        # Should have requirements for mne and mne-nirs
        assert len(plan.requirements) > 0
        # Plan should have fingerprint
        assert len(plan.plan_fingerprint) == 64

    def test_resolve_cedalion_flow_without_cedalion(self):
        """Verify Cedalion Flow returns approval_required when Cedalion missing.

        §15.2: Resolving a Cedalion Flow without a Cedalion environment returns approval_required
        """
        from fnirs_flow.dependencies.resolver import resolve_dependencies

        dag = {
            "atoms": [
                {
                    "atom_id": "ced-od",
                    "atom_type": "optical_density",
                    "operation": "intensity_to_od",
                    "category": "preprocessing",
                    "backend_id": "cedalion",
                    "dependency_profile_id": "cedalion-26.5",
                }
            ],
            "edges": [],
        }
        plan = resolve_dependencies(dag, flow_id="test-cedalion")

        # If cedalion is not installed, should require approval
        if not plan.is_satisfied():
            assert plan.status.value == "approval_required"
            assert plan.requires_user_approval
            assert len(plan.affected_atoms) > 0

    def test_resolver_never_imports_cedalion(self):
        """Verify resolver never imports cedalion.

        §6: resolving must not access the network or import large scientific backends
        §15.3: assert "cedalion" not in sys.modules
        """
        # Remove cedalion from sys.modules if present
        cedalion_keys = [k for k in sys.modules if k.startswith("cedalion")]
        for k in cedalion_keys:
            del sys.modules[k]

        from fnirs_flow.dependencies.resolver import resolve_dependencies

        dag = {
            "atoms": [
                {
                    "atom_id": "ced-od",
                    "atom_type": "optical_density",
                    "backend_id": "cedalion",
                    "dependency_profile_id": "cedalion-26.5",
                }
            ],
            "edges": [],
        }
        # Run resolver
        resolve_dependencies(dag, flow_id="test-no-import")

        # Verify cedalion was NOT imported
        assert "cedalion" not in sys.modules


@pytest.mark.core
class TestSourceAllowlist:
    """Test source allowlist (§15.1)."""

    def test_default_allowlist_includes_pypi(self):
        """Verify PyPI is in default allowlist."""
        from fnirs_flow.dependencies.policies import get_allowlist

        allowlist = get_allowlist()
        assert allowlist.is_allowed("pypi://mne")

    def test_default_allowlist_includes_cedalion_git(self):
        """Verify Cedalion git source is in default allowlist."""
        from fnirs_flow.dependencies.policies import get_allowlist

        allowlist = get_allowlist()
        assert allowlist.is_allowed("git+https://github.com/ibs-lab/cedalion.git@v26.5.1")

    def test_unknown_source_rejected(self):
        """Verify unknown sources are rejected."""
        from fnirs_flow.dependencies.policies import get_allowlist

        allowlist = get_allowlist()
        assert not allowlist.is_allowed("git+https://evil.com/malicious.git")


@pytest.mark.core
class TestInstallPolicyManager:
    """Test installation policy manager (§15.1)."""

    def test_default_policy_is_never(self):
        """Verify default policy is 'never' (§3.2)."""
        from fnirs_flow.dependencies.policies import InstallPolicyManager

        manager = InstallPolicyManager()
        assert manager.get_policy("any-fingerprint") == "never"

    def test_approve_plan(self):
        """Verify plan approval changes policy."""
        from fnirs_flow.dependencies.policies import InstallPolicyManager

        manager = InstallPolicyManager()
        manager.approve_plan("fp-123")
        assert manager.get_policy("fp-123") == "approved_once"
        assert manager.is_approved("fp-123")

    def test_reject_plan(self):
        """Verify plan rejection."""
        from fnirs_flow.dependencies.policies import InstallPolicyManager

        manager = InstallPolicyManager()
        manager.reject_plan("fp-456")
        assert manager.get_policy("fp-456") == "rejected"
        assert not manager.is_approved("fp-456")


@pytest.mark.core
class TestProbes:
    """Test capability probes (§15.1)."""

    def test_probe_package_availability(self):
        """Verify package probing without import."""
        from fnirs_flow.dependencies.probes import probe_package_availability

        # pydantic should be installed
        result = probe_package_availability("pydantic", "pydantic")
        assert result["installed"]
        assert result["version"] is not None
        assert result["importable"]

    def test_probe_nonexistent_package(self):
        """Verify probing nonexistent package."""
        from fnirs_flow.dependencies.probes import probe_package_availability

        result = probe_package_availability("nonexistent-pkg-xyz", "nonexistent_pkg_xyz")
        assert not result["installed"]
        assert not result["importable"]


@pytest.mark.core
class TestProvenance:
    """Test provenance tracking (§15.1)."""

    def test_provenance_tracker_write_plan(self, tmp_path):
        """Verify plan writing."""
        from fnirs_flow.dependencies.models import DependencyPlan
        from fnirs_flow.dependencies.provenance import ProvenanceTracker

        tracker = ProvenanceTracker(tmp_path)
        plan = DependencyPlan(plan_id="test", flow_id="f")
        path = tracker.write_plan(plan)

        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["plan_id"] == "test"

    def test_provenance_tracker_roundtrip(self, tmp_path):
        """Verify plan write/load roundtrip."""
        from fnirs_flow.dependencies.models import DependencyPlan
        from fnirs_flow.dependencies.provenance import ProvenanceTracker

        tracker = ProvenanceTracker(tmp_path)
        plan = DependencyPlan(plan_id="roundtrip", flow_id="f")
        tracker.write_plan(plan)

        loaded = tracker.load_plan()
        assert loaded is not None
        assert loaded.plan_id == "roundtrip"


@pytest.mark.core
class TestNoBackendImportOnModuleLoad:
    """Verify that importing fnirs_flow modules does not import backends.

    §15.3: Core tests do not require Cedalion
    §15.3: assert "cedalion" not in sys.modules
    """

    def test_backend_registry_no_eager_import(self):
        """Verify backend registry doesn't eagerly import adapter classes.

        §7.1: The registry stores string entry points and does not call import_module() during registration
        """
        # Remove cedalion from sys.modules if present
        cedalion_keys = [k for k in sys.modules if k.startswith("cedalion")]
        for k in cedalion_keys:
            del sys.modules[k]

        # Re-import the registry
        import importlib

        import fnirs_flow.adapters.backend_registry
        importlib.reload(fnirs_flow.adapters.backend_registry)

        # Verify cedalion was NOT imported during registration
        assert "cedalion" not in sys.modules

    def test_dependency_profiles_no_backend_import(self):
        """Verify dependency profile registration doesn't import backends."""
        # Remove cedalion from sys.modules if present
        cedalion_keys = [k for k in sys.modules if k.startswith("cedalion")]
        for k in cedalion_keys:
            del sys.modules[k]

        import importlib

        import fnirs_flow.registry.dependency_profiles
        importlib.reload(fnirs_flow.registry.dependency_profiles)

        # Verify cedalion was NOT imported
        assert "cedalion" not in sys.modules

    def test_compiler_no_cedalion_import(self, tmp_path):
        """Verify compiler doesn't import cedalion.

        §15.3: Compiling a non-Cedalion Flow must not slow down meaningfully because a Cedalion profile exists
        """
        # Remove cedalion from sys.modules if present
        cedalion_keys = [k for k in sys.modules if k.startswith("cedalion")]
        for k in cedalion_keys:
            del sys.modules[k]

        from fnirs_flow.compiler.compiler import compile_flow

        # A simple flow without cedalion (with required fields)
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test",
            "name": "Test",
            "nodes": [
                {
                    "id": "node1",
                    "type": "optical_density",
                    "atom_type": "optical_density",
                    "category": "preprocessing",
                    "config": {"operation": "optical_density"},
                    "position": {"x": 0, "y": 0},
                    "readiness_status": "ready",
                }
            ],
            "edges": [],
        }

        compile_flow(flow, tmp_path)

        # Verify cedalion was NOT imported
        assert "cedalion" not in sys.modules
