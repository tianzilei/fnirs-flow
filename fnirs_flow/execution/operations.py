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


OPERATION_ALIASES: dict[str, str] = {
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
    "cbsi": "motion_correction",
    "bandpass": "filtering",
    "notch": "filtering",
    "lowpass": "filtering",
    "mbll": "beer_lambert_law",
    "design_matrix": "build_design_matrix",
    "contrast": "estimate_contrast",
    "multi_site_harmonization": "combat_harmonization",
    "linear_mixed_effects_glm": "first_level_glm",
    "mixed_effects_glm": "first_level_glm",
    "nuisance_glm": "first_level_glm",
    "site_covariate_glm": "first_level_glm",
}


def canonical_operation(operation_id: str) -> str:
    """Return the execution operation used by the current backend dispatch."""
    return OPERATION_ALIASES.get(operation_id, operation_id)


def create_default_registry() -> OperationRegistry:
    """Create and return the default operation registry with all known operations."""
    registry = OperationRegistry()

    # Preprocessing operations
    for op_id, desc in [
        ("read_run", "Read raw SNIRF/BIDS-NIRS data"),
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
        ("cbsi", "Alias for motion_correction with CBSI method"),
        ("filtering", "Apply bandpass/notch filtering"),
        ("bandpass", "Alias for filtering with bandpass method"),
        ("notch", "Alias for filtering with notch method"),
        ("lowpass", "Alias for filtering with lowpass method"),
        ("beer_lambert_law", "Convert OD to haemoglobin concentration"),
        ("mbll", "Alias for beer_lambert_law used by node templates"),
        ("combat_harmonization", "Reviewed pass-through placeholder for ComBat harmonization"),
        ("multi_site_harmonization", "Alias for combat_harmonization used by legacy demo flows"),
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
        ("design_matrix", "Alias for build_design_matrix used by legacy demo flows"),
        ("first_level_glm", "Fit first-level GLM (HbO/HbR)"),
        ("linear_mixed_effects_glm", "Legacy/template advanced GLM alias executed with first-level GLM semantics"),
        ("mixed_effects_glm", "Legacy advanced GLM alias executed with first-level GLM semantics"),
        ("nuisance_glm", "Legacy/template nuisance GLM alias executed with first-level GLM semantics"),
        ("site_covariate_glm", "Legacy site-covariate GLM alias executed with first-level GLM semantics"),
        ("estimate_contrast", "Estimate linear contrasts"),
        ("contrast", "Alias for estimate_contrast used by legacy demo flows"),
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
