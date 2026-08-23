"""Operation Registry: maps atom operations to metadata and dispatch keys.

Each registered operation specifies:
- operation_id: unique identifier
- category: preprocessing, analysis, or output
- input_schemas: expected input port schemas
- output_schemas: produced output port schemas
- capabilities: required capabilities (e.g., "mne", "mne_nirs")

Execution dispatch is handled by ExecutionService via operation_id lookup.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class OperationHandler(Protocol):
    """Runtime handler contract exposed to adapters and UI tooling."""

    spec: OperationSpec

    def execute(self, context: Any) -> Any: ...


@dataclass
class OperationContext:
    adapter: Any
    raw: Any
    parameters: dict[str, Any]
    service: Any = None


class CallableOperationHandler:
    def __init__(self, spec: OperationSpec, callback: Callable[[OperationContext], Any]) -> None:
        self.spec = spec
        self.callback = callback

    def execute(self, context: OperationContext) -> Any:
        return self.callback(context)


class ReviewedNoopHandler:
    """Explicit pass-through for operations reviewed as safe no-ops."""

    def __init__(self, spec: OperationSpec) -> None:
        self.spec = spec

    def execute(self, context: OperationContext) -> Any:
        return context.raw


class DelegatedOperationHandler:
    """Contract marker for operations owned by a non-run executor."""

    def __init__(self, spec: OperationSpec) -> None:
        self.spec = spec

    def execute(self, context: OperationContext) -> Any:
        raise ValueError(
            f"Operation {self.spec.operation_id} must be executed by its {self.spec.execution_scope}-scope executor"
        )


class BackendMethodOperationHandler:
    """Invoke an explicitly verified adapter method for a MethodAtom."""

    def __init__(self, spec: OperationSpec, method_name: str) -> None:
        self.spec = spec
        self.method_name = method_name

    def execute(self, context: OperationContext) -> Any:
        method = getattr(context.adapter, self.method_name, None)
        if method is None or not callable(method):
            raise ValueError(
                f"Backend {getattr(context.adapter, 'backend_id', 'unknown')} does not implement {self.method_name}"
            )
        parameters = {key: value for key, value in context.parameters.items() if not key.startswith("_")}
        if context.raw is None:
            return method(**parameters)
        return method(context.raw, **parameters)


def backend_method_factory(method_name: str) -> Callable[[OperationSpec], OperationHandler]:
    """Build a handler factory for a reviewed adapter method binding."""

    def factory(spec: OperationSpec) -> OperationHandler:
        return BackendMethodOperationHandler(spec, method_name)

    return factory


def reviewed_noop_factory(spec: OperationSpec) -> OperationHandler:
    return ReviewedNoopHandler(spec)


def delegated_handler_factory(spec: OperationSpec) -> OperationHandler:
    return DelegatedOperationHandler(spec)


@dataclass
class OperationSpec:
    """Specification for a registered operation."""

    operation_id: str
    category: str = ""
    input_schemas: list[str] = field(default_factory=list)
    output_schemas: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    execution_scope: str = "run"
    supported_backends: list[str] = field(default_factory=list)
    artifact_contract: dict[str, Any] = field(default_factory=dict)
    allow_reviewed_noop: bool = False
    handler_factory: Callable[..., OperationHandler] | None = None
    backend_handler_factories: dict[str, Callable[..., OperationHandler]] = field(default_factory=dict)

    def handler_factory_for(self, backend_id: str | None = None) -> Callable[..., OperationHandler] | None:
        if backend_id and backend_id in self.backend_handler_factories:
            return self.backend_handler_factories[backend_id]
        if backend_id and self.supported_backends and backend_id not in self.supported_backends:
            return None
        return self.handler_factory


class OperationRegistry:
    """Registry of available operations for discovery and validation."""

    def __init__(self) -> None:
        self._operations: dict[str, OperationSpec] = {}

    def register(self, spec: OperationSpec) -> None:
        """Register an operation. Raises ValueError on duplicate."""
        if spec.operation_id in self._operations:
            raise ValueError(f"Duplicate operation registration: {spec.operation_id}")
        self._operations[spec.operation_id] = spec
        for alias in spec.aliases:
            if alias in self._operations:
                raise ValueError(f"Duplicate operation registration: {alias}")
            self._operations[alias] = spec

    def get(self, operation_id: str) -> OperationSpec | None:
        """Get an operation spec by ID, or None if not found."""
        return self._operations.get(operation_id)

    def has(self, operation_id: str) -> bool:
        """Check if an operation is registered."""
        return operation_id in self._operations

    def canonicalize(self, operation_id: str) -> str:
        """Canonicalize aliases using registry metadata rather than a dispatcher."""
        spec = self.get(operation_id)
        return spec.operation_id if spec else operation_id

    def validate_execution(
        self,
        operation_id: str,
        *,
        scope: str = "run",
        backend_id: str | None = None,
        required_capabilities: set[str] | None = None,
        require_handler: bool = False,
    ) -> list[str]:
        spec = self.get(operation_id)
        if spec is None:
            return [f"Unknown operation: {operation_id}"]
        errors: list[str] = []
        if spec.execution_scope and spec.execution_scope != scope:
            errors.append(f"Operation {operation_id} requires scope {spec.execution_scope}, got {scope}")
        if backend_id and spec.supported_backends and backend_id not in spec.supported_backends:
            errors.append(f"Operation {operation_id} does not support backend {backend_id}")
        missing_capabilities = set(spec.capabilities) - set(required_capabilities or set())
        if missing_capabilities:
            errors.append(
                f"Operation {operation_id} is missing required capability declarations: "
                + ", ".join(sorted(missing_capabilities))
            )
        if require_handler and spec.handler_factory_for(backend_id) is None:
            errors.append(f"Operation {operation_id} has no registered handler")
        return errors

    def execute(self, operation_id: str, context: OperationContext) -> Any:
        spec = self.get(operation_id)
        if spec is None:
            raise ValueError(f"Unknown operation: {operation_id}")
        backend_id = getattr(context.adapter, "backend_id", None)
        if backend_id is None:
            backend_id = "cedalion" if "cedalion" in getattr(context.adapter, "versions", {}) else "mne_nirs"
        factory = spec.handler_factory_for(str(backend_id))
        if factory is None:
            raise ValueError(f"Operation has no registered handler: {operation_id}")
        return factory(spec).execute(context)

    def list_operations(self) -> list[str]:
        """List all registered operation IDs."""
        return list(self._operations.keys())

    def validate_inputs(self, operation_id: str, available_schemas: set[str]) -> list[str]:
        """Validate that required inputs are available.

        Returns list of missing input schemas.
        """
        spec = self.get(operation_id)
        if spec is None:
            return [f"Unknown operation: {operation_id}"]
        return [s for s in spec.input_schemas if s not in available_schemas]


OPERATION_ALIASES: dict[str, str] = {
    "snirf_reader": "read_run",
    "optical_density_conversion": "optical_density",
    "qc_metrics": "compute_qc",
    "sci_check": "compute_qc",
    "cv_check": "compute_qc",
    "snr_check": "compute_qc",
    "bad_channel_detection": "compute_qc",
    "tddr": "motion_correction",
    "wavelet": "motion_correction",
    "spline": "motion_correction",
    "ica": "motion_correction",
    "pca": "motion_correction",
    "bandpass": "filtering",
    "notch": "filtering",
    "lowpass": "filtering",
    "mbll": "beer_lambert_law",
    "design_matrix": "build_design_matrix",
    "contrast": "estimate_contrast",
}


def canonical_operation(operation_id: str) -> str:
    """Return the execution operation used by the current backend dispatch."""
    return OPERATION_ALIASES.get(operation_id, operation_id)


def create_default_registry() -> OperationRegistry:
    """Create and return the default operation registry with all known operations."""
    from fnirs_flow.execution.builtin_handlers import builtin_handler_factory

    registry = OperationRegistry()

    mne_handlers = {"mne_nirs": builtin_handler_factory}
    cedalion_handlers = {"cedalion": builtin_handler_factory}

    # Preprocessing operations
    registry.register(
        OperationSpec(
            operation_id="dataset_discovery",
            category="data",
            execution_scope="run",
            description="Discover and index project data before run execution",
            handler_factory=delegated_handler_factory,
            backend_handler_factories={"core": delegated_handler_factory},
        )
    )
    for op_id, desc in [
        ("read_run", "Read raw SNIRF/BIDS-NIRS data"),
        ("snirf_reader", "Read a SNIRF run with the selected backend"),
        ("optical_density", "Convert raw intensity to optical density"),
        ("optical_density_conversion", "Alias for optical_density used by node templates"),
        ("compute_qc", "Compute quality control metrics"),
        ("qc_metrics", "Alias for compute_qc used by legacy demo flows"),
        ("sci_check", "Alias for compute_qc used by QC templates"),
        ("cv_check", "Alias for compute_qc used by QC templates"),
        ("snr_check", "Alias for compute_qc used by QC templates"),
        ("bad_channel_detection", "Alias for compute_qc used by QC templates"),
        ("motion_correction", "Apply motion artifact correction"),
        ("tddr", "Alias for motion_correction with TDDR method"),
        ("wavelet", "Alias for motion_correction with wavelet method"),
        ("spline", "Alias for motion_correction with spline method"),
        ("ica", "Alias for motion_correction with ICA method"),
        ("pca", "Alias for motion_correction with PCA method"),
        ("filtering", "Apply bandpass/notch filtering"),
        ("bandpass", "Alias for filtering with bandpass method"),
        ("notch", "Alias for filtering with notch method"),
        ("lowpass", "Alias for filtering with lowpass method"),
        ("beer_lambert_law", "Convert OD to haemoglobin concentration"),
        ("mbll", "Alias for beer_lambert_law used by node templates"),
    ]:
        backend_handlers = dict(mne_handlers)
        if op_id in {
            "read_run",
            "snirf_reader",
            "optical_density",
            "optical_density_conversion",
            "beer_lambert_law",
            "mbll",
        }:
            backend_handlers.update(cedalion_handlers)
        registry.register(
            OperationSpec(
                operation_id=op_id,
                category="preprocessing",
                description=desc,
                supported_backends=sorted(backend_handlers),
                handler_factory=builtin_handler_factory,
                backend_handler_factories=backend_handlers,
            )
        )

    # Analysis operations
    for op_id, desc in [
        ("build_design_matrix", "Construct GLM design matrix from events"),
        ("design_matrix", "Alias for build_design_matrix used by legacy demo flows"),
        ("first_level_glm", "Fit first-level GLM (HbO/HbR)"),
        ("estimate_contrast", "Estimate linear contrasts"),
        ("contrast", "Alias for estimate_contrast used by legacy demo flows"),
        ("channel_output", "Export channel-level results"),
        ("roi_output", "Export ROI-level results"),
        ("block_averaging", "Compute event-related block averages"),
    ]:
        registry.register(
            OperationSpec(
                operation_id=op_id,
                category="analysis",
                description=desc,
                supported_backends=["mne_nirs"],
                handler_factory=builtin_handler_factory,
                backend_handler_factories=mne_handlers,
            )
        )

    # Report operations
    for op_id, desc in [
        ("run_report", "Generate run-level report"),
        ("project_report", "Generate project-level summary report"),
        ("group_summary", "Compute group-level statistics across subjects"),
        ("package_export", "Export a project-level reproducibility package"),
    ]:
        scope = "run"
        if op_id == "group_summary":
            scope = "group"
        elif op_id in {"project_report", "package_export"}:
            scope = "project"
        registry.register(
            OperationSpec(
                operation_id=op_id,
                category="output",
                execution_scope=scope,
                description=desc,
                handler_factory=delegated_handler_factory,
                backend_handler_factories={"core": delegated_handler_factory},
            )
        )

    registry.register(
        OperationSpec(
            operation_id="empty_marker",
            category="control",
            description="Mark a reviewed empty/no-op processing stage without transforming data",
            handler_factory=delegated_handler_factory,
            backend_handler_factories={"core": delegated_handler_factory},
        )
    )

    # Participant metadata and group-scope helper operations
    for op_id, desc in [
        ("participant_table_input", "Read participant CSV/TSV metadata"),
        ("participant_metadata_validate", "Validate participant metadata joins"),
        ("participant_metadata_join", "Join participant metadata to subject-level results"),
        ("participant_label_projection", "Project participant metadata to ML labels"),
        ("participant_site_projection", "Project participant metadata to site metadata"),
        ("participant_covariate_projection", "Project participant metadata to covariate matrices"),
        ("participant_dpf_projection", "Project participant age metadata to DPF inputs"),
        ("participant_outcome_projection", "Project participant metadata to behavioral or clinical outcomes"),
        ("localization_projection_import", "Import prepared localization projection CSV coordinates"),
        (
            "nirs_spm_surface_projection",
            "Project MNI head-surface coordinates to cortical MNI coordinates "
            "using a Python rewrite of NIRS-SPM projection_CS",
        ),
        ("fnirs_filename_inventory", "Inventory and validate study-specific fNIRS filenames"),
        ("nirs_spm_header_inspection", "Inspect NIRS-SPM-style text headers"),
        ("probe_layout_split", "Split probe layout coordinates into source, detector, and channel tables"),
        ("combat_preflight", "Validate ComBat site and covariate metadata preconditions"),
        ("observation_pairing_projection", "Project observation metadata to pairing and dyad structures"),
        ("group_design_matrix", "Compile an SPM-style group design matrix"),
        ("group_level_glm", "Fit group-level GLM"),
        ("group_contrast", "Estimate group-level contrasts"),
    ]:
        registry.register(
            OperationSpec(
                operation_id=op_id,
                category="group",
                execution_scope="group",
                description=desc,
                handler_factory=delegated_handler_factory,
                backend_handler_factories={"core": delegated_handler_factory},
            )
        )

    # Complete the discovery catalog from declarative MethodAtom templates.
    # Catalog presence is deliberately separate from executability: an
    # unimplemented scientific MethodAtom has no handler and therefore fails
    # the compile gate instead of degrading to a pass-through.
    from fnirs_flow.adapters.cedalion_bindings import is_verified_cedalion_atom
    from fnirs_flow.execution.deep_learning_handlers import DEEP_LEARNING_OPERATIONS, deep_learning_handler_factory
    from fnirs_flow.execution.scientific_handlers import SCIENTIFIC_OPERATIONS, generic_handler_factory
    from fnirs_flow.registry.atom_templates import ALL_METHOD_ATOM_TEMPLATES

    for template in ALL_METHOD_ATOM_TEMPLATES:
        operation_id = str(template.operation or template.atom_type)
        if not operation_id or registry.has(operation_id):
            continue
        scope = template.default_execution_scope or "run"
        if operation_id in {
            "combat_harmonization",
            "linear_mixed_effects_glm",
            "site_covariate_glm",
            "group_glm_nirs_spm",
        }:
            scope = "group"
        verified_backend_handlers: dict[str, Callable[..., OperationHandler]] = {}
        if (
            template.backend_binding
            and template.metadata.get("source_atom_id")
            and is_verified_cedalion_atom(str(template.metadata["source_atom_id"]))
        ):
            verified_backend_handlers[template.backend_binding.backend_id] = backend_method_factory(
                template.backend_binding.operation
            )
        scientific_handler = generic_handler_factory if operation_id in SCIENTIFIC_OPERATIONS else None
        operation_handler = scientific_handler or (
            deep_learning_handler_factory if operation_id in DEEP_LEARNING_OPERATIONS else None
        )
        declared_backend_handlers = dict(verified_backend_handlers)
        # Literature Cedalion atoms retain their explicit backend binding.  A
        # binding becomes executable only when its wrapper is present; the
        # template verification/readiness fields still control compile-time
        # approval and make the unverified state visible to users.
        if template.backend_binding and not declared_backend_handlers:
            declared_backend_handlers[template.backend_binding.backend_id] = backend_method_factory(
                template.backend_binding.operation
            )
        registry.register(
            OperationSpec(
                operation_id=operation_id,
                category=str(template.category.value),
                input_schemas=[port.port_schema for port in template.ports if port.direction == "in" and port.required],
                output_schemas=[port.port_schema for port in template.ports if port.direction == "out"],
                capabilities=list(template.required_capabilities),
                execution_scope=scope,
                supported_backends=[template.backend_binding.backend_id] if template.backend_binding else [],
                description=template.description,
                allow_reviewed_noop=operation_id == "study_design",
                handler_factory=(reviewed_noop_factory if operation_id == "study_design" else operation_handler),
                backend_handler_factories=(
                    declared_backend_handlers
                    or ({"core": reviewed_noop_factory} if operation_id == "study_design" else {})
                    or ({"mne_nirs": operation_handler} if operation_handler else {})
                ),
            )
        )

    return registry
