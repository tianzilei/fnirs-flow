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

from dataclasses import dataclass, field


@dataclass
class OperationSpec:
    """Specification for a registered operation."""

    operation_id: str
    category: str = ""
    input_schemas: list[str] = field(default_factory=list)
    output_schemas: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    description: str = ""


class OperationRegistry:
    """Registry of available operations for discovery and validation."""

    def __init__(self) -> None:
        self._operations: dict[str, OperationSpec] = {}

    def register(self, spec: OperationSpec) -> None:
        """Register an operation. Raises ValueError on duplicate."""
        if spec.operation_id in self._operations:
            raise ValueError(f"Duplicate operation registration: {spec.operation_id}")
        self._operations[spec.operation_id] = spec

    def get(self, operation_id: str) -> OperationSpec | None:
        """Get an operation spec by ID, or None if not found."""
        return self._operations.get(operation_id)

    def has(self, operation_id: str) -> bool:
        """Check if an operation is registered."""
        return operation_id in self._operations

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


def create_default_registry() -> OperationRegistry:
    """Create and return the default operation registry with all known operations."""
    registry = OperationRegistry()

    # Preprocessing operations
    for op_id, desc in [
        ("read_run", "Read raw SNIRF/BIDS-NIRS data"),
        ("optical_density", "Convert raw intensity to optical density"),
        ("compute_qc", "Compute quality control metrics"),
        ("motion_correction", "Apply motion artifact correction"),
        ("filtering", "Apply bandpass/notch filtering"),
        ("beer_lambert_law", "Convert OD to haemoglobin concentration"),
    ]:
        registry.register(
            OperationSpec(
                operation_id=op_id,
                category="preprocessing",
                description=desc,
            )
        )

    # Analysis operations
    for op_id, desc in [
        ("build_design_matrix", "Construct GLM design matrix from events"),
        ("first_level_glm", "Fit first-level GLM (HbO/HbR)"),
        ("estimate_contrast", "Estimate linear contrasts"),
        ("channel_output", "Export channel-level results"),
        ("roi_output", "Export ROI-level results"),
    ]:
        registry.register(
            OperationSpec(
                operation_id=op_id,
                category="analysis",
                description=desc,
            )
        )

    # Report operations
    for op_id, desc in [
        ("run_report", "Generate run-level report"),
        ("project_report", "Generate project-level summary report"),
        ("group_summary", "Compute group-level statistics across subjects"),
    ]:
        registry.register(
            OperationSpec(
                operation_id=op_id,
                category="output",
                description=desc,
            )
        )

    registry.register(
        OperationSpec(
            operation_id="empty_marker",
            category="control",
            description="Mark a reviewed empty/no-op processing stage without transforming data",
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
                description=desc,
            )
        )

    return registry
