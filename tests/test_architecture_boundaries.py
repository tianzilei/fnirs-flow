"""Regression tests for package dependency direction."""

import ast
import re
from pathlib import Path

from fnirs_flow.infrastructure.filesystem import is_macos_metadata_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "fnirs_flow"

# This allowlist documents the intended modular-monolith dependency graph.
# Interface packages are deliberately excluded: lower layers may never depend
# on ``api`` or ``cli``.
ALLOWED_INTERNAL_DEPENDENCIES: dict[str, set[str]] = {
    "application": {
        "compiler", "data", "execution", "exporters", "flow", "history",
        "infrastructure", "validation", "recommendation",
    },
    "flow": {"validation"},  # migration compatibility only; removed with schema v0.1
    "validation": {"flow", "registry", "security"},
    "security": {"flow", "validation"},
    "infrastructure": {"application", "history"},
    "data": {"infrastructure"},
    # Compilation validates OperationSpec scope/backend contracts before a DAG
    # can reach runtime; it depends on execution contracts, not the executor.
    "compiler": {"dependencies", "execution", "flow", "infrastructure", "validation"},
    # Processed-Hb orchestration consumes the dedicated scientific-analysis
    # kernel; execution remains the owner of I/O and task fan-out.
        "execution": {"adapters", "analysis", "data", "infrastructure", "processed_hb", "registry", "settings"},
    "exporters": {"execution", "infrastructure", "validation"},
}


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _visible_source_files(root: Path, pattern: str) -> list[Path]:
    return [
        path
        for path in root.rglob(pattern)
        if path.is_file() and not is_macos_metadata_path(path.relative_to(PROJECT_ROOT))
    ]


def test_lower_layers_do_not_import_api() -> None:
    violations: list[str] = []
    for package in ("application", "flow", "validation", "security", "data", "execution", "exporters"):
        for path in _visible_source_files(PACKAGE_ROOT / package, "*.py"):
            for imported in _absolute_imports(path):
                if imported == "fnirs_flow.api" or imported.startswith("fnirs_flow.api."):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)} -> {imported}")
    assert not violations, "Lower-layer API imports found:\n" + "\n".join(violations)


def test_infrastructure_does_not_import_api() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT)} -> {imported}"
        for path in _visible_source_files(PACKAGE_ROOT / "infrastructure", "*.py")
        for imported in _absolute_imports(path)
        if imported == "fnirs_flow.api" or imported.startswith("fnirs_flow.api.")
    ]
    assert not violations, "Infrastructure API imports found:\n" + "\n".join(violations)


def test_application_does_not_import_api() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT)} -> {imported}"
        for path in _visible_source_files(PACKAGE_ROOT / "application", "*.py")
        for imported in _absolute_imports(path)
        if imported == "fnirs_flow.api" or imported.startswith("fnirs_flow.api.")
    ]
    assert not violations, "Application API imports found:\n" + "\n".join(violations)


def test_cross_package_dependencies_match_allowlist() -> None:
    violations: list[str] = []
    for package, allowed in ALLOWED_INTERNAL_DEPENDENCIES.items():
        for path in _visible_source_files(PACKAGE_ROOT / package, "*.py"):
            for imported in _absolute_imports(path):
                if not imported.startswith("fnirs_flow."):
                    continue
                target = imported.split(".", 2)[1]
                if target != package and target not in allowed:
                    violations.append(f"{path.relative_to(PROJECT_ROOT)} -> {target}")
    assert not violations, "Undeclared cross-package imports found:\n" + "\n".join(sorted(violations))


def test_api_routers_are_isolated_modules() -> None:
    router_files = _visible_source_files(PACKAGE_ROOT / "api" / "routers", "*.py")
    assert {path.stem for path in router_files} >= {
        "registry",
        "progress",
        "diagnostics",
        "dependencies",
        "history",
        "packages",
        "discovery",
        "projects",
        "execution",
        "results",
        "ai",
    }


def test_legacy_uri_imports_share_canonical_objects() -> None:
    from fnirs_flow.api.uri import ProjectURI as LegacyProjectURI
    from fnirs_flow.api.uri import URIBindingStore as LegacyURIBindingStore
    from fnirs_flow.infrastructure.uri import ProjectURI, URIBindingStore

    assert LegacyProjectURI is ProjectURI
    assert LegacyURIBindingStore is URIBindingStore


def test_legacy_result_output_imports_share_canonical_models() -> None:
    from fnirs_flow.execution.result_outputs import ROIResult
    from fnirs_flow.exporters.outputs import ROIResult as LegacyROIResult

    assert LegacyROIResult is ROIResult


def test_execution_service_reexports_canonical_models() -> None:
    from fnirs_flow.execution.models import ExecutionRequest, RunExecutionResult
    from fnirs_flow.execution.service import ExecutionRequest as LegacyExecutionRequest
    from fnirs_flow.execution.service import RunExecutionResult as LegacyRunExecutionResult

    assert LegacyExecutionRequest is ExecutionRequest
    assert LegacyRunExecutionResult is RunExecutionResult


def test_migrated_compatibility_modules_reexport_canonical_objects() -> None:
    from fnirs_flow.adapters.mne_nirs_preprocessing import filter_raw
    from fnirs_flow.adapters.mne_nirs_steps import filter_raw as legacy_filter_raw
    from fnirs_flow.data.group_analysis import fit_group_glm
    from fnirs_flow.data.participant_tables import ParticipantTable
    from fnirs_flow.data.participants import ParticipantTable as LegacyParticipantTable
    from fnirs_flow.data.participants import fit_group_glm as legacy_fit_group_glm

    assert legacy_filter_raw is filter_raw
    assert LegacyParticipantTable is ParticipantTable
    assert legacy_fit_group_glm is fit_group_glm


def test_production_code_does_not_import_migrated_compatibility_modules() -> None:
    compatibility_modules = {
        "fnirs_flow.data.participants",
        "fnirs_flow.adapters.mne_nirs_steps",
    }
    violations = []
    for path in _visible_source_files(PACKAGE_ROOT, "*.py"):
        if path.name in {"participants.py", "mne_nirs_steps.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in compatibility_modules:
                violations.append(f"{path.relative_to(PROJECT_ROOT)} -> {node.module}")
    assert not violations, "Compatibility implementation imports found:\n" + "\n".join(violations)


def test_legacy_filesystem_imports_share_canonical_helpers() -> None:
    from fnirs_flow.filesystem import is_macos_metadata_path as legacy_helper
    from fnirs_flow.infrastructure.filesystem import is_macos_metadata_path

    assert legacy_helper is is_macos_metadata_path


def test_legacy_project_data_root_store_is_canonical() -> None:
    from fnirs_flow.api.projects import ProjectDataRootStore as LegacyProjectDataRootStore
    from fnirs_flow.infrastructure.project_data_roots import ProjectDataRootStore

    assert LegacyProjectDataRootStore is ProjectDataRootStore


def test_domain_models_do_not_parse_legacy_flow_or_dag_fields() -> None:
    """Legacy payload names belong to explicit version-conversion modules."""
    model_paths = [
        PACKAGE_ROOT / "flow" / "atoms.py",
        PACKAGE_ROOT / "flow" / "models.py",
        PACKAGE_ROOT / "compiler" / "execution_dag.py",
    ]
    forbidden = ("AliasChoices", "validation_alias")
    violations = [
        f"{path.relative_to(PROJECT_ROOT)} contains {token}"
        for path in model_paths
        for token in forbidden
        if token in path.read_text(encoding="utf-8")
    ]
    assert not violations, "Domain-model compatibility parsing found:\n" + "\n".join(violations)


def test_frontend_flow_compatibility_is_centralized() -> None:
    source_root = PROJECT_ROOT / "webui" / "src"
    compatibility_module = source_root / "features" / "flow" / "normalization.ts"
    legacy_access = re.compile(r"\batom\.type\b|\bflow\.nodes\b|\bpayload\.nodes\b")
    violations = [
        str(path.relative_to(PROJECT_ROOT))
        for path in _visible_source_files(source_root, "*.ts*")
        if path != compatibility_module and legacy_access.search(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "Frontend legacy Flow parsing found outside normalization.ts:\n" + "\n".join(violations)


def test_documented_public_model_imports_remain_available() -> None:
    """Smoke the stable model names listed in the public API contract."""
    from fnirs_flow.execution.failures import ActionAttempt, FailureRecord
    from fnirs_flow.flow.models import AdapterDefinition, FlowEdge, FlowGraph, FlowNode, NodePort

    assert FlowGraph and FlowNode and FlowEdge and NodePort and AdapterDefinition
    assert ActionAttempt and FailureRecord
