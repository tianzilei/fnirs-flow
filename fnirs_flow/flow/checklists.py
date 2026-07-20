"""Scenario-guided Flow checklist contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from fnirs_flow.flow.empty_markers import is_empty_marker_atom
from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.validation.models import RiskItem

OPERATION_ALIASES: dict[str, tuple[str, ...]] = {
    "build_design_matrix": ("design_matrix", "study_design"),
    "compute_qc": ("qc_metrics", "signal_qc"),
    "estimate_contrast": ("contrast", "estimate_contrast"),
    "filtering": ("bandpass_filter", "filter"),
    "motion_correction": ("tddr_motion_correction", "motion_correction"),
}

HANDLE_SCHEMA_ALIASES: dict[str, str] = {
    "data_manifest": "DataManifest",
    "raw": "RawData",
    "raw_data": "RawData",
    "od_data": "OpticalDensityData",
    "corrected_data": "OpticalDensityData",
    "filtered_data": "OpticalDensityData",
    "hb_data": "HaemoglobinData",
    "haemoglobin": "HaemoglobinData",
    "design": "DesignSpec",
    "design_spec": "DesignSpec",
    "design_matrix": "DesignMatrix",
    "glm_result": "GLMResults",
    "contrast_result": "ContrastResults",
    "channel_results": "ContrastResults",
}

SCHEMA_ALIASES: dict[str, str] = {
    "GLMResult": "GLMResults",
    "ContrastResult": "ContrastResults",
    "ChannelResults": "ContrastResults",
}

OPERATION_OUTPUT_SCHEMAS: dict[str, tuple[str, ...]] = {
    "dataset_discovery": ("DataManifest",),
    "read_run": ("RawData",),
    "optical_density": ("OpticalDensityData",),
    "compute_qc": ("QCReport",),
    "motion_correction": ("OpticalDensityData",),
    "filtering": ("OpticalDensityData",),
    "beer_lambert_law": ("HaemoglobinData",),
    "build_design_matrix": ("DesignSpec", "DesignMatrix"),
    "first_level_glm": ("GLMResults",),
    "estimate_contrast": ("ContrastResults",),
    "channel_output": ("ContrastResults",),
    "roi_output": ("ROIResults",),
}


@dataclass(frozen=True)
class FlowChecklistStep:
    slot_id: str
    label: str
    required: bool
    recommended_template_ids: tuple[str, ...]
    recommended_atom_types: tuple[str, ...]
    default_template_id: str = ""
    alternative_template_ids: tuple[str, ...] = ()
    input_requirements: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    allow_empty_marker: bool = False
    category: str = ""
    guidance: str = ""


@dataclass(frozen=True)
class FlowChecklist:
    scenario_id: str
    label: str
    description: str
    version: str
    steps: tuple[FlowChecklistStep, ...]


TASK_GLM_CHECKLIST = FlowChecklist(
    scenario_id="task_glm",
    label="Task GLM",
    description="Guided assembly for task-based fNIRS GLM analysis.",
    version="2026.07.18",
    steps=(
        FlowChecklistStep(
            slot_id="data_input",
            label="Data input",
            required=True,
            recommended_template_ids=("dataset_discovery",),
            recommended_atom_types=("data_import", "dataset_discovery"),
            default_template_id="dataset_discovery",
            category="data",
            guidance="Discover dataset files before reading individual runs.",
        ),
        FlowChecklistStep(
            slot_id="read_run",
            label="Read run",
            required=True,
            recommended_template_ids=("read_run",),
            recommended_atom_types=("read_run",),
            default_template_id="read_run",
            input_requirements=("DataManifest",),
            depends_on=("data_input",),
            category="data",
            guidance="Read each discovered BIDS/SNIRF run.",
        ),
        FlowChecklistStep(
            slot_id="signal_conversion",
            label="Signal conversion",
            required=True,
            recommended_template_ids=("optical_density",),
            recommended_atom_types=("optical_density",),
            default_template_id="optical_density",
            input_requirements=("RawData",),
            depends_on=("read_run",),
            category="preprocessing",
            guidance="Convert raw intensity to optical density.",
        ),
        FlowChecklistStep(
            slot_id="quality_control",
            label="Quality control",
            required=False,
            recommended_template_ids=("qc_metrics", "sci_check", "cv_check", "snr_check"),
            recommended_atom_types=("signal_qc", "qc_metrics"),
            default_template_id="qc_metrics",
            alternative_template_ids=("sci_check", "cv_check", "snr_check"),
            input_requirements=("OpticalDensityData",),
            depends_on=("signal_conversion",),
            allow_empty_marker=True,
            category="preprocessing",
            guidance="Compute SCI/CV/SNR or mark QC as intentionally skipped.",
        ),
        FlowChecklistStep(
            slot_id="motion_handling",
            label="Motion handling",
            required=False,
            recommended_template_ids=(
                "tddr_motion_correction",
                "spline_motion_correction",
                "wavelet_motion_correction",
            ),
            recommended_atom_types=("motion_correction",),
            default_template_id="tddr_motion_correction",
            alternative_template_ids=("spline_motion_correction", "wavelet_motion_correction"),
            input_requirements=("OpticalDensityData",),
            depends_on=("signal_conversion",),
            allow_empty_marker=True,
            category="preprocessing",
            guidance="Apply or explicitly skip motion correction.",
        ),
        FlowChecklistStep(
            slot_id="filtering",
            label="Filtering",
            required=False,
            recommended_template_ids=("bandpass_filter",),
            recommended_atom_types=("filter", "filtering"),
            default_template_id="bandpass_filter",
            alternative_template_ids=("notch_filter", "lowpass_filter"),
            input_requirements=("OpticalDensityData",),
            depends_on=("signal_conversion",),
            allow_empty_marker=True,
            category="preprocessing",
            guidance="Apply bandpass filtering or mark filtering as a reviewed no-op.",
        ),
        FlowChecklistStep(
            slot_id="haemoglobin_conversion",
            label="Haemoglobin conversion",
            required=True,
            recommended_template_ids=("beer_lambert_law",),
            recommended_atom_types=("mbll_conversion", "beer_lambert_law"),
            default_template_id="beer_lambert_law",
            input_requirements=("OpticalDensityData",),
            depends_on=("signal_conversion",),
            category="preprocessing",
            guidance="Convert optical density to haemoglobin concentration.",
        ),
        FlowChecklistStep(
            slot_id="study_design",
            label="Study design",
            required=True,
            recommended_template_ids=("study_design",),
            recommended_atom_types=("design",),
            default_template_id="study_design",
            depends_on=("data_input",),
            category="design",
            guidance="Define conditions and planned contrasts.",
        ),
        FlowChecklistStep(
            slot_id="design_matrix",
            label="Design matrix",
            required=True,
            recommended_template_ids=("design_matrix",),
            recommended_atom_types=("design",),
            default_template_id="design_matrix",
            input_requirements=("DataManifest",),
            depends_on=("haemoglobin_conversion", "study_design"),
            category="design",
            guidance="Build the GLM design matrix from haemoglobin data and design spec.",
        ),
        FlowChecklistStep(
            slot_id="first_level_glm",
            label="First-level GLM",
            required=True,
            recommended_template_ids=("first_level_glm",),
            recommended_atom_types=("first_level_glm",),
            default_template_id="first_level_glm",
            input_requirements=("HaemoglobinData", "DesignMatrix"),
            depends_on=("design_matrix",),
            category="analysis",
            guidance="Fit the first-level task GLM.",
        ),
        FlowChecklistStep(
            slot_id="contrast",
            label="Contrast",
            required=True,
            recommended_template_ids=("contrast", "estimate_contrast"),
            recommended_atom_types=("estimate_contrast",),
            default_template_id="contrast",
            input_requirements=("GLMResults",),
            depends_on=("first_level_glm",),
            category="analysis",
            guidance="Estimate configured condition contrasts.",
        ),
        FlowChecklistStep(
            slot_id="outputs",
            label="Outputs",
            required=True,
            recommended_template_ids=("channel_output", "roi_output"),
            recommended_atom_types=("data_export",),
            default_template_id="channel_output",
            alternative_template_ids=("roi_output",),
            input_requirements=("ContrastResults",),
            depends_on=("contrast",),
            category="output",
            guidance="Export channel-level or ROI-level results.",
        ),
    ),
)

RESTING_CONNECTIVITY_CHECKLIST = FlowChecklist(
    scenario_id="resting_state_connectivity",
    label="Resting Connectivity",
    description="Guided assembly for resting-state fNIRS connectivity analysis.",
    version="2026.07.18",
    steps=(
        FlowChecklistStep(
            "data_input",
            "Data input",
            True,
            ("dataset_discovery",),
            ("data_import", "dataset_discovery"),
            "dataset_discovery",
            category="data",
            guidance="Discover resting-state recordings.",
        ),
        FlowChecklistStep(
            "read_run",
            "Read run",
            True,
            ("read_run",),
            ("read_run",),
            "read_run",
            input_requirements=("DataManifest",),
            depends_on=("data_input",),
            category="data",
            guidance="Read each resting-state run.",
        ),
        FlowChecklistStep(
            "signal_conversion",
            "Signal conversion",
            True,
            ("optical_density",),
            ("optical_density",),
            "optical_density",
            input_requirements=("RawData",),
            depends_on=("read_run",),
            category="preprocessing",
            guidance="Convert raw intensity to optical density.",
        ),
        FlowChecklistStep(
            "quality_control",
            "Quality control",
            False,
            ("qc_metrics", "sci_check", "cv_check", "snr_check"),
            ("signal_qc",),
            "qc_metrics",
            ("sci_check", "cv_check", "snr_check"),
            ("RawData",),
            ("signal_conversion",),
            True,
            "preprocessing",
            "Compute or intentionally skip signal quality checks.",
        ),
        FlowChecklistStep(
            "motion_handling",
            "Motion handling",
            False,
            ("tddr_motion_correction", "spline_motion_correction", "wavelet_motion_correction"),
            ("motion_correction",),
            "tddr_motion_correction",
            ("spline_motion_correction", "wavelet_motion_correction"),
            ("OpticalDensityData",),
            ("signal_conversion",),
            True,
            "preprocessing",
            "Repair major motion artifacts when needed.",
        ),
        FlowChecklistStep(
            "filtering",
            "Filtering",
            True,
            ("bandpass_filter",),
            ("filter",),
            "bandpass_filter",
            ("notch_filter", "lowpass_filter"),
            ("OpticalDensityData",),
            ("signal_conversion",),
            False,
            "preprocessing",
            "Limit slow drifts and physiological bands before connectivity.",
        ),
        FlowChecklistStep(
            "haemoglobin_conversion",
            "Haemoglobin conversion",
            True,
            ("beer_lambert_law",),
            ("mbll_conversion", "beer_lambert_law"),
            "beer_lambert_law",
            input_requirements=("OpticalDensityData",),
            depends_on=("filtering",),
            category="preprocessing",
            guidance="Convert cleaned optical density to haemoglobin concentration.",
        ),
        FlowChecklistStep(
            "connectivity",
            "Connectivity",
            True,
            ("connectivity_analysis", "plv_connectivity", "coherence_connectivity", "wtc_connectivity"),
            ("resting_connectivity",),
            "connectivity_analysis",
            ("plv_connectivity", "coherence_connectivity", "wtc_connectivity"),
            ("HaemoglobinData",),
            ("haemoglobin_conversion",),
            False,
            "analysis",
            "Estimate functional connectivity with the method matching the hypothesis.",
        ),
        FlowChecklistStep(
            "outputs",
            "Outputs",
            True,
            ("group_summary",),
            ("data_export",),
            "group_summary",
            input_requirements=("ROIResults", "ConnectivityMatrix"),
            depends_on=("connectivity",),
            category="output",
            guidance="Export matrices or downstream summaries.",
        ),
    ),
)

GROUP_ANALYSIS_CHECKLIST = FlowChecklist(
    scenario_id="group_analysis",
    label="Group Analysis",
    description="Guided assembly for participant metadata and group-level analysis.",
    version="2026.07.18",
    steps=(
        FlowChecklistStep(
            "participant_table",
            "Participant table",
            True,
            ("participant_table_input",),
            ("participant_table_input",),
            "participant_table_input",
            input_requirements=("FilePath",),
            category="data",
            guidance="Load the participant or observation metadata table.",
        ),
        FlowChecklistStep(
            "metadata_validation",
            "Metadata validation",
            True,
            ("participant_metadata_validate",),
            ("participant_metadata_validate",),
            "participant_metadata_validate",
            input_requirements=("ParticipantTable", "DataManifest"),
            depends_on=("participant_table",),
            category="validation",
            guidance="Validate IDs, duplicates, inclusion flags, and data joins.",
        ),
        FlowChecklistStep(
            "site_projection",
            "Site projection",
            False,
            ("participant_site_projection",),
            ("participant_site_projection",),
            "participant_site_projection",
            input_requirements=("ParticipantTable",),
            depends_on=("participant_table",),
            allow_empty_marker=True,
            category="data",
            guidance="Project site/scanner labels for multisite studies, or skip if single-site.",
        ),
        FlowChecklistStep(
            "group_design",
            "Group design",
            True,
            ("group_design_matrix",),
            ("group_design_matrix",),
            "group_design_matrix",
            input_requirements=("AnnotatedSubjectResults",),
            depends_on=("metadata_validation",),
            category="design",
            guidance="Define group design matrix and covariates.",
        ),
        FlowChecklistStep(
            "group_glm",
            "Group GLM",
            True,
            ("linear_mixed_effects_glm", "site_covariate_glm"),
            ("first_level_glm",),
            "linear_mixed_effects_glm",
            ("site_covariate_glm",),
            ("HaemoglobinData", "GroupDesignMatrix"),
            ("group_design",),
            False,
            "analysis",
            "Run group-level or multisite GLM.",
        ),
        FlowChecklistStep(
            "outputs",
            "Outputs",
            True,
            ("group_summary",),
            ("data_export",),
            "group_summary",
            input_requirements=("ROIResults",),
            depends_on=("group_glm",),
            category="output",
            guidance="Export group summary tables.",
        ),
    ),
)

ML_CLASSIFICATION_CHECKLIST = FlowChecklist(
    scenario_id="ml_classification",
    label="ML Classification",
    description="Guided assembly for fNIRS machine-learning classification with leakage checks.",
    version="2026.07.18",
    steps=(
        FlowChecklistStep(
            "data_input",
            "Data input",
            True,
            ("dataset_discovery",),
            ("data_import", "dataset_discovery"),
            "dataset_discovery",
            category="data",
            guidance="Discover dataset files before feature construction.",
        ),
        FlowChecklistStep(
            "read_run",
            "Read run",
            True,
            ("read_run",),
            ("read_run",),
            "read_run",
            input_requirements=("DataManifest",),
            depends_on=("data_input",),
            category="data",
            guidance="Read each subject/run.",
        ),
        FlowChecklistStep(
            "labels",
            "Labels",
            True,
            ("participant_table_input", "participant_label_projection"),
            ("participant_table_input", "participant_label_projection"),
            "participant_table_input",
            ("participant_label_projection",),
            input_requirements=("FilePath",),
            category="data",
            guidance="Load labels and subject IDs before model training.",
        ),
        FlowChecklistStep(
            "signal_conversion",
            "Signal conversion",
            True,
            ("optical_density",),
            ("optical_density",),
            "optical_density",
            input_requirements=("RawData",),
            depends_on=("read_run",),
            category="preprocessing",
            guidance="Convert intensity to optical density.",
        ),
        FlowChecklistStep(
            "haemoglobin_conversion",
            "Haemoglobin conversion",
            True,
            ("beer_lambert_law",),
            ("mbll_conversion", "beer_lambert_law"),
            "beer_lambert_law",
            input_requirements=("OpticalDensityData",),
            depends_on=("signal_conversion",),
            category="preprocessing",
            guidance="Convert to haemoglobin concentration.",
        ),
        FlowChecklistStep(
            "feature_extraction",
            "Feature extraction",
            True,
            ("feature_extraction",),
            ("feature_extraction",),
            "feature_extraction",
            input_requirements=("HaemoglobinData",),
            depends_on=("haemoglobin_conversion",),
            category="analysis",
            guidance="Extract features inside the planned analysis scope.",
        ),
        FlowChecklistStep(
            "feature_selection",
            "Feature selection",
            False,
            ("feature_selection",),
            ("feature_extraction",),
            "feature_selection",
            input_requirements=("FeatureMatrix", "LabelVector"),
            depends_on=("feature_extraction", "labels"),
            allow_empty_marker=True,
            category="analysis",
            guidance="Select features inside cross-validation folds or mark as intentionally skipped.",
        ),
        FlowChecklistStep(
            "model",
            "Model",
            True,
            ("ml_model", "svm_model", "lda_model"),
            ("ml_classification",),
            "ml_model",
            ("svm_model", "lda_model"),
            ("FeatureMatrix", "LabelVector"),
            ("feature_extraction", "labels"),
            False,
            "analysis",
            "Choose classifier and leakage-safe split settings.",
        ),
        FlowChecklistStep(
            "cross_validation",
            "Cross-validation",
            True,
            ("cross_validation",),
            ("ml_classification",),
            "cross_validation",
            input_requirements=("FeatureMatrix", "LabelVector"),
            depends_on=("model",),
            category="analysis",
            guidance="Use subject-wise or nested CV and keep preprocessing in fold.",
        ),
        FlowChecklistStep(
            "outputs",
            "Outputs",
            True,
            ("group_summary",),
            ("data_export",),
            "group_summary",
            input_requirements=("ROIResults", "CVResults"),
            depends_on=("cross_validation",),
            category="output",
            guidance="Export model metrics and summary tables.",
        ),
    ),
)

FLOW_CHECKLISTS = {
    checklist.scenario_id: checklist
    for checklist in (
        TASK_GLM_CHECKLIST,
        RESTING_CONNECTIVITY_CHECKLIST,
        GROUP_ANALYSIS_CHECKLIST,
        ML_CLASSIFICATION_CHECKLIST,
    )
}


def list_flow_checklists() -> list[dict[str, Any]]:
    """Return available checklist summaries."""
    return [
        {
            "scenario_id": checklist.scenario_id,
            "label": checklist.label,
            "description": checklist.description,
            "version": checklist.version,
            "step_count": len(checklist.steps),
        }
        for checklist in FLOW_CHECKLISTS.values()
    ]


def get_flow_checklist(scenario_id: str) -> FlowChecklist | None:
    """Return a checklist by scenario ID."""
    return FLOW_CHECKLISTS.get(scenario_id)


def checklist_to_dict(checklist: FlowChecklist) -> dict[str, Any]:
    """Serialize a checklist contract for API clients."""
    return {
        "scenario_id": checklist.scenario_id,
        "label": checklist.label,
        "description": checklist.description,
        "version": checklist.version,
        "steps": [asdict(step) for step in checklist.steps],
    }


def _atom_matches_step(atom: Any, step: FlowChecklistStep) -> bool:
    template_id = str(getattr(atom, "template_id", "") or atom.metadata.get("template_id", ""))
    atom_type = str(getattr(atom, "atom_type", "") or getattr(atom, "type", ""))
    operation = str(getattr(atom, "operation", "") or "")
    identifiers = {
        template_id,
        atom_type,
        operation,
        *OPERATION_ALIASES.get(operation, ()),
        *OPERATION_ALIASES.get(atom_type, ()),
    }
    return (
        bool(identifiers.intersection(step.recommended_template_ids))
        or bool(identifiers.intersection(step.recommended_atom_types))
    )


def _step_satisfied(flow: FlowGraph, step: FlowChecklistStep) -> bool:
    return any(_atom_matches_step(atom, step) for atom in flow.nodes)


def _canonical_schema(schema: str) -> str:
    return SCHEMA_ALIASES.get(schema, schema)


def _input_requirement_missing(flow: FlowGraph, atom: Any, step: FlowChecklistStep) -> tuple[str, ...]:
    if not step.input_requirements:
        return ()
    incoming_schemas = set()
    atom_id = str(getattr(atom, "id", ""))
    atom_by_id = {str(source.id): source for source in flow.nodes}
    for edge in flow.edges:
        if str(edge.target) != atom_id:
            continue
        source = atom_by_id.get(str(edge.source))
        if source is None:
            continue
        source_port_name = edge.source_handle
        edge_schemas: set[str] = set()
        for port in getattr(source, "ports", []):
            if port.direction != "out":
                continue
            if source_port_name is None or port.name == source_port_name:
                edge_schemas.add(_canonical_schema(port.port_schema))
        if not edge_schemas:
            for handle in (edge.source_handle, edge.target_handle):
                schema = HANDLE_SCHEMA_ALIASES.get(str(handle or ""))
                if schema:
                    edge_schemas.add(_canonical_schema(schema))
            source_operation = str(getattr(source, "operation", "") or getattr(source, "atom_type", "") or "")
            edge_schemas.update(
                _canonical_schema(schema)
                for schema in OPERATION_OUTPUT_SCHEMAS.get(source_operation, ())
            )
        incoming_schemas.update(edge_schemas)
    return tuple(schema for schema in step.input_requirements if _canonical_schema(schema) not in incoming_schemas)


def _step_skipped(flow: FlowGraph, step: FlowChecklistStep) -> bool:
    if not step.allow_empty_marker:
        return False
    return any(
        is_empty_marker_atom(atom.model_dump(mode="json"))
        and atom.metadata.get("skipped_processing_category") == step.category
        for atom in flow.nodes
    )


def validate_checklist_coverage(flow: FlowGraph, scenario_id: str) -> list[RiskItem]:
    """Validate checklist coverage as non-blocking design guidance."""
    checklist = get_flow_checklist(scenario_id)
    if checklist is None:
        return []

    risks: list[RiskItem] = []
    completed_slots = {
        step.slot_id for step in checklist.steps if _step_satisfied(flow, step) or _step_skipped(flow, step)
    }
    for step in checklist.steps:
        satisfied = step.slot_id in completed_slots
        blocked_by = [slot for slot in step.depends_on if slot not in completed_slots]
        matched_atom = next((atom for atom in flow.nodes if _atom_matches_step(atom, step)), None)
        missing_inputs = _input_requirement_missing(flow, matched_atom, step) if matched_atom is not None else ()
        if step.required and not satisfied:
            risks.append(
                RiskItem(
                    risk_id=f"checklist-missing-{scenario_id}-{step.slot_id}",
                    code="CHECKLIST_REQUIRED_STEP_MISSING",
                    severity="medium",
                    domain="design",
                    affected_object=f"checklist:{step.slot_id}",
                    message=f"Checklist step '{step.label}' is missing",
                    suggested_action=f"Add one of: {', '.join(step.recommended_template_ids)}",
                )
            )
        elif missing_inputs:
            risks.append(
                RiskItem(
                    risk_id=f"checklist-inputs-{scenario_id}-{step.slot_id}",
                    code="CHECKLIST_STEP_INPUTS_MISSING",
                    severity="low",
                    domain="design",
                    affected_object=f"checklist:{step.slot_id}",
                    message=f"Checklist step '{step.label}' is missing input links: {', '.join(missing_inputs)}",
                    suggested_action="Use checklist Connect or link compatible upstream atoms to the required inputs",
                )
            )
        elif blocked_by and not satisfied:
            risks.append(
                RiskItem(
                    risk_id=f"checklist-blocked-{scenario_id}-{step.slot_id}",
                    code="CHECKLIST_STEP_BLOCKED",
                    severity="low",
                    domain="design",
                    affected_object=f"checklist:{step.slot_id}",
                    message=f"Checklist step '{step.label}' is waiting for: {', '.join(blocked_by)}",
                    suggested_action="Complete upstream checklist steps before adding this atom",
                )
            )
        elif _step_skipped(flow, step):
            risks.append(
                RiskItem(
                    risk_id=f"checklist-empty-{scenario_id}-{step.slot_id}",
                    code="CHECKLIST_STEP_EMPTY_MARKER",
                    severity="low",
                    domain="design",
                    affected_object=f"checklist:{step.slot_id}",
                    message=f"Checklist step '{step.label}' is marked as empty/no-op",
                    suggested_action="Replace with a real processing atom when data and methods are available",
                )
            )
    return risks
