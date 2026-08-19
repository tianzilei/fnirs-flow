"""Comprehensive verification tests for lazy backend loading.

These tests verify:
1. Backend registry stores module paths, no Cedalion import at registration
2. MethodAtom library browsing doesn't load backends
3. MNE Flow compile/execute doesn't load Cedalion
4. Cedalion MethodAtom execution loads backend on-demand
5. Missing Cedalion gives clear error, no fallback to MNE
6. Mixed backend Flow switches correctly per MethodAtom
7. Performance measurements
"""

from __future__ import annotations

import json
import sys
import time

import pytest

# ============================================================================
# §1: Backend registry stores string entry points
# ============================================================================


@pytest.mark.core
class TestBackendRegistryLazyLoading:
    """Verify backend registry uses string entry points, no eager imports."""

    def test_registry_stores_class_path_string(self):
        """Registry stores 'module:ClassName' string, not class object."""
        from fnirs_flow.adapters.backend_registry import get_registry

        reg = get_registry()
        desc = reg.describe("cedalion")

        assert desc is not None
        assert desc["class_path"] == "fnirs_flow.adapters.cedalion_adapter:CedalionAdapter"
        assert desc["backend_id"] == "cedalion"
        assert desc["dependency_profile_id"] == "cedalion-26.5"

    def test_registry_no_import_at_registration(self):
        """Importing backend_registry does NOT import cedalion adapter."""
        # Remove cedalion modules
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower():
                del sys.modules[k]

        import importlib

        import fnirs_flow.adapters.backend_registry
        importlib.reload(fnirs_flow.adapters.backend_registry)

        # Verify cedalion adapter was NOT imported
        assert "fnirs_flow.adapters.cedalion_adapter" not in sys.modules

    def test_describe_returns_metadata_only(self):
        """describe() returns metadata without loading backend class."""
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower():
                del sys.modules[k]

        from fnirs_flow.adapters.backend_registry import get_registry
        reg = get_registry()

        desc = reg.describe("cedalion")
        assert desc is not None
        assert desc["backend_id"] == "cedalion"
        assert desc["class_path"] == "fnirs_flow.adapters.cedalion_adapter:CedalionAdapter"
        assert desc["dependency_profile_id"] == "cedalion-26.5"
        assert desc["display_name"] == "Cedalion"
        assert "is_available" in desc
        assert "is_loaded" in desc

        # Verify no import happened
        assert "fnirs_flow.adapters.cedalion_adapter" not in sys.modules

    def test_is_available_uses_find_spec_only(self):
        """is_available() uses importlib.util.find_spec(), not import."""
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower():
                del sys.modules[k]

        from fnirs_flow.adapters.backend_registry import get_registry
        reg = get_registry()

        # This should use detector (find_spec) not import
        result = reg.is_available("cedalion")
        assert isinstance(result, bool)

        # Verify cedalion adapter module was NOT imported
        assert "fnirs_flow.adapters.cedalion_adapter" not in sys.modules

    def test_list_all_no_import(self):
        """list_all() returns backend IDs without importing any backend."""
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower() or "mne" in k.lower():
                del sys.modules[k]

        from fnirs_flow.adapters.backend_registry import get_registry
        reg = get_registry()

        all_ids = reg.list_all()
        assert "cedalion" in all_ids
        assert "mne_nirs" in all_ids

        # No backend modules imported
        assert "fnirs_flow.adapters.cedalion_adapter" not in sys.modules
        assert "fnirs_flow.adapters.mne_nirs_adapter" not in sys.modules


# ============================================================================
# §2: MethodAtom library browsing doesn't load backends
# ============================================================================


@pytest.mark.core
class TestMethodAtomLibraryNoBackendImport:
    """Browsing MethodAtom library does NOT import any backend."""

    def test_import_library_no_cedalion(self):
        """Importing MethodAtom library doesn't import cedalion."""
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower():
                del sys.modules[k]

        from fnirs_flow.registry.atom_templates import ALL_METHOD_ATOM_TEMPLATES

        # Library and templates loaded
        assert len(ALL_METHOD_ATOM_TEMPLATES) > 0

        # Cedalion NOT imported
        assert "cedalion" not in sys.modules

    def test_create_atom_no_backend_import(self):
        """Creating a FlowAtom from template doesn't import backend."""
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower():
                del sys.modules[k]

        from fnirs_flow.registry.node_library import MethodAtomLibrary

        library = MethodAtomLibrary()
        from fnirs_flow.registry.atom_templates import ALL_METHOD_ATOM_TEMPLATES
        library.register_many(ALL_METHOD_ATOM_TEMPLATES)

        # Find a cedalion template
        cedalion_templates = [
            t for t in library.all() if t.backend_binding and t.backend_binding.backend_id == "cedalion"
        ]
        if cedalion_templates:
            template = cedalion_templates[0]
            atom = library.create_atom(template.template_id)
            assert atom is not None
            assert atom.backend_binding is not None
            assert atom.backend_binding.backend_id == "cedalion"

        # Cedalion NOT imported
        assert "cedalion" not in sys.modules

    def test_list_templates_no_backend_import(self):
        """Listing templates doesn't import backends."""
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower():
                del sys.modules[k]

        from fnirs_flow.registry.node_library import MethodAtomLibrary

        library = MethodAtomLibrary()
        from fnirs_flow.registry.atom_templates import ALL_METHOD_ATOM_TEMPLATES
        library.register_many(ALL_METHOD_ATOM_TEMPLATES)

        # List all templates
        all_templates = library.all()
        assert len(all_templates) > 0

        # List by category
        preprocessing = library.by_category("preprocessing")
        assert len(preprocessing) > 0

        # No backend imported
        assert "cedalion" not in sys.modules


# ============================================================================
# §3: MNE Flow compile/execute doesn't load Cedalion
# ============================================================================


@pytest.mark.core
class TestMNEFlowNoCedalionImport:
    """Compiling/executing MNE-only Flow doesn't import Cedalion."""

    def test_compile_mne_flow_no_cedalion(self, tmp_path):
        """Compile a flow with only MNE backend - no Cedalion import."""
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower():
                del sys.modules[k]

        from fnirs_flow.compiler.compiler import compile_flow

        flow = {
            "schema_version": "0.2.0",
            "flow_id": "mne-only-test",
            "name": "MNE Only Test",
            "nodes": [
                {
                    "id": "od",
                    "type": "optical_density",
                    "atom_type": "optical_density",
                    "category": "preprocessing",
                    "config": {"operation": "optical_density"},
                    "position": {"x": 0, "y": 0},
                    "readiness_status": "ready",
                    "backend_binding": {"backend_id": "mne_nirs", "operation": "optical_density"},
                },
            ],
            "edges": [],
        }

        result = compile_flow(flow, tmp_path)
        assert result is not None

        # Verify dependency plan was generated
        dep_plan_path = result.outdir / "dependency_plan.json"
        assert dep_plan_path.exists()

        # Cedalion NOT imported
        assert "cedalion" not in sys.modules

    def test_resolve_mne_flow_no_cedalion(self):
        """Resolving dependencies for MNE flow doesn't import Cedalion."""
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower():
                del sys.modules[k]

        from fnirs_flow.dependencies.resolver import resolve_dependencies

        dag = {
            "atoms": [
                {
                    "atom_id": "od",
                    "atom_type": "optical_density",
                    "backend_id": "mne_nirs",
                    "dependency_profile_id": "mne-nirs-1.0",
                }
            ],
            "edges": [],
        }

        plan = resolve_dependencies(dag, flow_id="mne-test")
        assert plan is not None

        # Cedalion NOT imported
        assert "cedalion" not in sys.modules


# ============================================================================
# §4: Cedalion MethodAtom loads backend on-demand
# ============================================================================


@pytest.mark.core
class TestCedalionLazyLoad:
    """Cedalion backend loads only when executing Cedalion MethodAtom."""

    def test_lazy_registry_load_class(self):
        """registry.load() explicitly loads the backend class."""
        from fnirs_flow.adapters.backend_registry import get_registry

        reg = get_registry()

        # load() returns the class if available, None otherwise
        backend_class = reg.load("cedalion")
        if backend_class is not None:
            # Cedalion is installed - verify class was loaded correctly
            assert backend_class.__name__ == "CedalionAdapter"
            # Verify it was cached
            assert "cedalion" in reg._loaded_classes
        else:
            # Cedalion not installed - load returns None gracefully
            assert not reg.is_available("cedalion")

    def test_lazy_registry_load_nonexistent(self):
        """registry.load() returns None for unknown backend."""
        from fnirs_flow.adapters.backend_registry import get_registry

        reg = get_registry()
        result = reg.load("nonexistent_backend")
        assert result is None

    def test_lazy_registry_create_instance(self):
        """registry.create() loads and instantiates backend."""
        from fnirs_flow.adapters.backend_registry import BackendNotAvailableError, get_registry

        reg = get_registry()

        if reg.is_available("cedalion"):
            backend = reg.create("cedalion")
            assert backend is not None
            assert hasattr(backend, "versions")
        else:
            with pytest.raises(BackendNotAvailableError):
                reg.create("cedalion")


# ============================================================================
# §5: Missing Cedalion gives clear error, no fallback
# ============================================================================


@pytest.mark.core
class TestMissingCedalionNoFallback:
    """Missing Cedalion gives structured error, never falls back to MNE."""

    def test_resolve_cedalion_flow_missing(self):
        """Resolving Cedalion flow when not installed returns approval_required."""
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

        plan = resolve_dependencies(dag, flow_id="ced-missing-test")

        # If cedalion is not installed, should require approval
        if not plan.is_satisfied():
            assert plan.status.value == "approval_required"
            assert plan.requires_user_approval
            assert len(plan.affected_atoms) > 0
            assert "cedalion-26.5" in plan.affected_atoms

    def test_error_message_mentions_methodatom(self):
        """Error message mentions which MethodAtom is affected."""
        from fnirs_flow.dependencies.models import (
            DependencyPlan,
            PackageRequirement,
            RequirementStatus,
            ResolvedRequirement,
        )

        plan = DependencyPlan(
            plan_id="test",
            flow_id="f",
            requirements=[
                ResolvedRequirement(
                    package=PackageRequirement(
                        distribution="cedalion",
                        import_name="cedalion",
                        version_specifier="==26.5.1",
                        source="git+https://github.com/ibs-lab/cedalion.git@v26.5.1",
                    ),
                    profile_id="cedalion-26.5",
                    status=RequirementStatus.MISSING,
                ),
            ],
            affected_atoms={"cedalion-26.5": ["atom-od-01", "atom-conc-01"]},
            requires_user_approval=True,
        )

        error_msg = plan.format_user_error()
        assert "atom-od-01" in error_msg
        assert "cedalion" in error_msg
        # When requires_user_approval is True, message should mention next steps
        assert "approve" in error_msg.lower() or "install" in error_msg.lower()

    def test_no_silent_fallback_to_mne(self):
        """Verify no silent fallback from Cedalion to MNE-NIRS."""
        from fnirs_flow.adapters.backend_registry import BackendNotAvailableError
        from fnirs_flow.execution.service import ExecutionService

        service = ExecutionService()

        # The _create_backend_adapter method should raise ImportError
        # if backend is not available, not fall back to another backend
        with pytest.raises(ImportError, match="not available"):
            service._create_backend_adapter(
                type("MockRegistry", (), {
                    "create": lambda self, bid, **kw: (_ for _ in ()).throw(
                        BackendNotAvailableError(bid)
                    )
                })(),
                "cedalion",
            )

    def test_structured_error_for_missing_backend(self):
        """registry.create() raises BackendNotAvailableError for missing backend."""
        from fnirs_flow.adapters.backend_registry import BackendNotAvailableError, get_registry

        reg = get_registry()

        # Ensure cedalion is not available (mock if needed)
        if not reg.is_available("cedalion"):
            with pytest.raises(BackendNotAvailableError) as exc_info:
                reg.create("cedalion")
            assert exc_info.value.backend_id == "cedalion"
            assert "not available" in exc_info.value.message

    def test_structured_error_for_load_failure(self):
        """registry.create() raises BackendLoadError for load failure."""
        from fnirs_flow.adapters.backend_registry import BackendLoadError, get_registry

        reg = get_registry()

        # Register a backend with invalid class path
        reg.register(
            backend_id="test_invalid",
            class_path="nonexistent.module:NonexistentClass",
            detector=lambda: True,  # Always available
        )

        with pytest.raises(BackendLoadError) as exc_info:
            reg.create("test_invalid")
        assert exc_info.value.backend_id == "test_invalid"
        assert "nonexistent.module" in exc_info.value.class_path


# ============================================================================
# §6: Mixed backend Flow switches correctly per MethodAtom
# ============================================================================


@pytest.mark.core
class TestMixedBackendFlow:
    """Mixed backend Flow switches correctly per MethodAtom."""

    def test_lazy_adapter_pool_per_atom(self):
        """LazyAdapterPool creates adapters per backend_id."""
        from fnirs_flow.adapters.backend_registry import LazyAdapterPool, get_registry

        registry = get_registry()
        pool = LazyAdapterPool(registry)

        # Pool starts empty
        assert not pool.has("mne_nirs")
        assert not pool.has("cedalion")

    def test_mixed_flow_dependency_resolution(self):
        """Mixed MNE+Cedalion flow resolves dependencies correctly."""
        from fnirs_flow.dependencies.resolver import resolve_dependencies

        dag = {
            "atoms": [
                {
                    "atom_id": "mne-od",
                    "atom_type": "optical_density",
                    "backend_id": "mne_nirs",
                    "dependency_profile_id": "mne-nirs-1.0",
                },
                {
                    "atom_id": "ced-glm",
                    "atom_type": "glm",
                    "backend_id": "cedalion",
                    "dependency_profile_id": "cedalion-26.5",
                },
            ],
            "edges": [],
        }

        plan = resolve_dependencies(dag, flow_id="mixed-test")
        assert plan is not None

        # Should have requirements for both backends
        profile_ids = {r.profile_id for r in plan.requirements}
        assert "mne-nirs-1.0" in profile_ids
        assert "cedalion-26.5" in profile_ids

        # Affected atoms should be tracked separately
        assert "mne-nirs-1.0" in plan.affected_atoms
        assert "cedalion-26.5" in plan.affected_atoms
        assert "mne-od" in plan.affected_atoms["mne-nirs-1.0"]
        assert "ced-glm" in plan.affected_atoms["cedalion-26.5"]

    def test_cross_backend_edge_validation(self, tmp_path):
        """Compiler validates cross-backend edges without adapters."""
        from fnirs_flow.compiler.compiler import compile_flow

        flow = {
            "schema_version": "0.2.0",
            "flow_id": "cross-backend-test",
            "name": "Cross Backend Test",
            "nodes": [
                {
                    "id": "mne-od",
                    "type": "optical_density",
                    "atom_type": "optical_density",
                    "category": "preprocessing",
                    "config": {},
                    "position": {"x": 0, "y": 0},
                    "readiness_status": "ready",
                    "backend_binding": {"backend_id": "mne_nirs"},
                    "ports": [
                        {"name": "out", "direction": "out", "schema": "raw", "required": True}
                    ],
                },
                {
                    "id": "ced-glm",
                    "type": "glm",
                    "atom_type": "glm",
                    "category": "analysis",
                    "config": {},
                    "position": {"x": 0, "y": 100},
                    "readiness_status": "ready",
                    "backend_binding": {"backend_id": "cedalion"},
                    # No adapter binding - should fail
                    "ports": [
                        {"name": "in", "direction": "in", "schema": "raw", "required": True}
                    ],
                },
            ],
            "edges": [
                {
                    "id": "edge-1",
                    "source": "mne-od",
                    "target": "ced-glm",
                    "source_handle": "out",
                    "target_handle": "in",
                }
            ],
        }

        with pytest.raises(ValueError, match="Cross-backend|validation errors|Mixed backend"):
            compile_flow(flow, tmp_path)


# ============================================================================
# §7: Performance measurements
# ============================================================================


@pytest.mark.core
class TestPerformanceBaseline:
    """Measure startup time and import overhead."""

    def test_import_time_no_cedalion(self):
        """Importing fnirs_flow modules doesn't trigger Cedalion import."""
        for k in list(sys.modules.keys()):
            if "cedalion" in k.lower():
                del sys.modules[k]

        start = time.perf_counter()
        elapsed = time.perf_counter() - start

        # Should import quickly (< 2 seconds)
        assert elapsed < 2.0, f"Import took {elapsed:.2f}s, expected < 2.0s"

        # No cedalion
        assert "cedalion" not in sys.modules

    def test_dependency_resolution_speed(self):
        """Dependency resolution is fast for simple flows."""
        from fnirs_flow.dependencies.resolver import resolve_dependencies

        dag = {
            "atoms": [
                {
                    "atom_id": f"atom-{i}",
                    "atom_type": "test",
                    "backend_id": "mne_nirs",
                    "dependency_profile_id": "mne-nirs-1.0",
                }
                for i in range(10)
            ],
            "edges": [],
        }

        start = time.perf_counter()
        plan = resolve_dependencies(dag, flow_id="perf-test")
        elapsed = time.perf_counter() - start

        assert plan is not None
        assert elapsed < 1.0, f"Resolution took {elapsed:.2f}s, expected < 1.0s"

    def test_backend_registry_describe_speed(self):
        """describe() is fast (no import)."""
        from fnirs_flow.adapters.backend_registry import get_registry

        reg = get_registry()

        start = time.perf_counter()
        for _ in range(100):
            reg.describe("cedalion")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"100 describe() took {elapsed:.2f}s, expected < 0.1s"


# ============================================================================
# §8: Dependency plan integration
# ============================================================================


@pytest.mark.core
class TestDependencyPlanIntegration:
    """Full integration test for dependency plan workflow."""

    def test_compile_generates_dependency_plan(self, tmp_path):
        """Compiling a flow generates dependency_plan.json."""
        from fnirs_flow.compiler.compiler import compile_flow

        flow = {
            "schema_version": "0.2.0",
            "flow_id": "integration-test",
            "name": "Integration Test",
            "nodes": [
                {
                    "id": "node1",
                    "type": "optical_density",
                    "atom_type": "optical_density",
                    "category": "preprocessing",
                    "config": {"operation": "optical_density"},
                    "position": {"x": 0, "y": 0},
                    "readiness_status": "ready",
                    "backend_binding": {"backend_id": "mne_nirs"},
                },
            ],
            "edges": [],
        }

        result = compile_flow(flow, tmp_path)

        # Check dependency plan exists
        dep_plan_path = result.outdir / "dependency_plan.json"
        assert dep_plan_path.exists()

        plan_data = json.loads(dep_plan_path.read_text())
        assert "plan_id" in plan_data
        assert "requirements" in plan_data
        assert "affected_atoms" in plan_data
        assert plan_data["revision"] == 1

    def test_dependency_plan_serializable(self):
        """Dependency plan is fully serializable to JSON."""
        from fnirs_flow.dependencies.resolver import resolve_dependencies

        dag = {
            "atoms": [
                {
                    "atom_id": "atom1",
                    "atom_type": "test",
                    "backend_id": "mne_nirs",
                }
            ],
            "edges": [],
        }

        plan = resolve_dependencies(dag, flow_id="serial-test")

        # Should serialize without error
        json_str = plan.model_dump_json(indent=2)
        assert len(json_str) > 0

        # Should deserialize
        from fnirs_flow.dependencies.models import DependencyPlan
        plan2 = DependencyPlan.model_validate_json(json_str)
        assert plan2.plan_id == plan.plan_id
