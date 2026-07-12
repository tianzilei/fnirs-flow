"""Scenario definitions: task, resting_state, real_world, hyperscanning, machine_learning.

MethodAtom-first naming:
  - required_atom_types / optional_atom_types are the preferred fields.
  - required_node_types / optional_node_types are retained for backward compatibility.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fnirs_flow.flow.models import (
    NodeCategory,
    NodePort,
)
from fnirs_flow.registry.node_library import NodeTemplate


class ScenarioDefinition(BaseModel):
    """Defines a scenario type with its required atoms, constraints, and defaults.

    MethodAtom-first fields (preferred):
      - required_atom_types: atom types required by this scenario
      - optional_atom_types: atom types optional in this scenario

    Legacy fields (kept for backward compatibility):
      - required_node_types: same as required_atom_types
      - optional_node_types: same as optional_atom_types
    """

    scenario_id: str
    name: str
    description: str = ""
    # Legacy fields
    required_node_types: list[str] = Field(default_factory=list)
    optional_node_types: list[str] = Field(default_factory=list)
    # MethodAtom-first fields (dual-write)
    required_atom_types: list[str] = Field(default_factory=list)
    optional_atom_types: list[str] = Field(default_factory=list)
    required_config_fields: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    default_presets: dict[str, str] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    reporting_requirements: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        """Auto-sync atom fields from node fields if not set."""
        if not self.required_atom_types and self.required_node_types:
            self.required_atom_types = list(self.required_node_types)
        if not self.optional_atom_types and self.optional_node_types:
            self.optional_atom_types = list(self.optional_node_types)


# Built-in scenario definitions
TASK_SCENARIO = ScenarioDefinition(
    scenario_id="task",
    name="Task-Based fNIRS",
    description="Block/event/mixed design task activation analysis",
    required_node_types=[
        "dataset_discovery",
        "study_design",
        "event_extraction",
        "optical_density",
        "motion_correction",
        "filtering",
        "beer_lambert_law",
        "design_matrix",
        "first_level_glm",
        "contrast",
    ],
    optional_node_types=[
        "short_channel_regression",
        "systemic_physiology_regression",
        "nuisance_regression",
        "bad_channel_detection",
        "multiple_comparison_correction",
        "block_averaging",
        "channel_output",
        "roi_output",
    ],
    required_config_fields=[
        "conditions",
        "contrasts",
        "hrf_model",
    ],
    constraints={
        "min_conditions": 2,
        "min_contrasts": 1,
        "hrf_options": ["canonical", "fir", "finite_impulse_response"],
        "motion_correction_methods": [
            "tddr",
            "spline",
            "wavelet",
            "ica",
            "pca",
            "mara",
            "cbsi",
            "rls",
            "kalman",
            "block_rejection",
        ],
    },
    default_presets={
        "qc": "conservative_qc",
        "motion": "tddr_motion",
        "filter": "basic_bandpass",
        "glm": "standard_task_glm",
    },
    risks=[
        "Missing contrast specification",
        "Unconfirmed motion correction preset",
        "No ROI mapping for ROI-level output",
        "Motion correction method not validated against literature",
    ],
    reporting_requirements=[
        "conditions",
        "contrasts",
        "hrf_model",
        "motion_correction_method",
        "filter_parameters",
        "qc_thresholds",
        "short_channel_regression_method",
    ],
)


RESTING_STATE_SCENARIO = ScenarioDefinition(
    scenario_id="resting_state",
    name="Resting-State fNIRS",
    description="Functional connectivity analysis during rest",
    required_node_types=[
        "dataset_discovery",
        "optical_density",
        "motion_correction",
        "filtering",
        "beer_lambert_law",
        "connectivity_analysis",
    ],
    optional_node_types=[
        "short_channel_regression",
        "systemic_physiology_regression",
        "nuisance_regression",
        "bad_channel_detection",
        "plv_connectivity",
        "coherence_connectivity",
        "wtc_connectivity",
        "granger_causality",
        "graph_theory",
    ],
    required_config_fields=[
        "min_duration_seconds",
        "frequency_band",
        "connectivity_metric",
    ],
    constraints={
        "min_duration_seconds": 120,
        "frequency_bands": ["0.01-0.1", "0.01-0.08", "0.009-0.1"],
        "connectivity_metrics": [
            "pearson",
            "fisher_z",
            "mutual_information",
            "plv",
            "coherence",
            "wtc",
            "granger",
        ],
    },
    default_presets={
        "qc": "conservative_qc",
        "motion": "tddr_motion",
        "filter": "resting_state_bandpass",
    },
    risks=[
        "Duration below minimum threshold",
        "No eye state recording",
        "Systemic physiology not regressed",
        "Frequency band mismatch with literature",
        "Connectivity metric not validated against literature",
    ],
    reporting_requirements=[
        "duration",
        "eye_state",
        "frequency_band",
        "connectivity_metric",
        "systemic_regression_method",
    ],
)


REAL_WORLD_SCENARIO = ScenarioDefinition(
    scenario_id="real_world",
    name="Real-World/Naturalistic fNIRS",
    description="fNIRS during naturalistic behavior, walking, or free movement",
    required_node_types=[
        "dataset_discovery",
        "optical_density",
        "motion_correction",
        "filtering",
        "beer_lambert_law",
        "event_reconstruction",
    ],
    optional_node_types=[
        "behavioral_coding",
        "sensor_sync",
        "motion_stratification",
    ],
    required_config_fields=[
        "behavioral_sensors",
        "event_reconstruction_method",
    ],
    constraints={
        "sensor_types": ["accelerometer", "gyroscope", "video", "audio", "gps"],
        "event_methods": ["threshold", "manual_coding", "automatic"],
    },
    default_presets={
        "qc": "real_world_qc",
        "motion": "tddr_motion",
    },
    risks=[
        "Motion artifacts in free movement",
        "Event reconstruction accuracy",
        "Sensor synchronization drift",
    ],
    reporting_requirements=[
        "behavioral_sensors",
        "event_reconstruction_method",
        "motion_stratification",
        "exclusion_criteria",
    ],
)


HYPERSCANNING_SCENARIO = ScenarioDefinition(
    scenario_id="hyperscanning",
    name="Hyperscanning fNIRS",
    description="Simultaneous fNIRS recording from multiple participants",
    required_node_types=[
        "dataset_discovery",
        "optical_density",
        "motion_correction",
        "filtering",
        "beer_lambert_law",
        "inter_brain_connectivity",
    ],
    optional_node_types=[
        "dyad_analysis",
        "group_analysis",
        "sync_error_correction",
    ],
    required_config_fields=[
        "dyad_group_structure",
        "sync_method",
        "connectivity_metric",
    ],
    constraints={
        "sync_methods": ["hardware_trigger", "audio_sync", "network_sync"],
        "min_participants": 2,
        "connectivity_levels": ["intra_brain", "inter_brain", "dyad", "group"],
    },
    default_presets={
        "qc": "conservative_qc",
        "motion": "tddr_motion",
    },
    risks=[
        "Synchronization error between devices",
        "Pseudo-synchronization in analysis",
        "Insufficient dyad sample size",
    ],
    reporting_requirements=[
        "sync_method",
        "sync_error_ms",
        "dyad_count",
        "connectivity_level",
        "permutation_test_results",
    ],
)


MACHINE_LEARNING_SCENARIO = ScenarioDefinition(
    scenario_id="machine_learning",
    name="Machine Learning fNIRS",
    description="ML-based classification or regression on fNIRS features",
    required_node_types=[
        "dataset_discovery",
        "optical_density",
        "motion_correction",
        "filtering",
        "beer_lambert_law",
        "feature_extraction",
        "ml_model",
    ],
    optional_node_types=[
        "feature_selection",
        "svm_model",
        "lda_model",
        "cnn_model",
        "lstm_model",
        "transformer_model",
        "decision_tree_model",
        "cross_validation",
        "hyperparameter_tuning",
        "model_interpretation",
    ],
    required_config_fields=[
        "split_strategy",
        "cv_folds",
        "model_type",
        "metrics",
    ],
    constraints={
        "split_strategies": ["subject_wise", "group_wise", "session_wise"],
        "prohibited": ["random_trial_split", "random_window_split"],
        "cv_folds_min": 5,
        "required_metrics": ["accuracy", "sensitivity", "specificity", "auc"],
        "model_types": [
            "svm",
            "lda",
            "cnn",
            "lstm",
            "transformer",
            "random_forest",
            "decision_tree",
        ],
        "cv_strategies": [
            "leave_one_out",
            "nested",
            "10_fold",
            "5_fold",
            "leave_one_subject_out",
        ],
    },
    default_presets={
        "qc": "conservative_qc",
        "motion": "tddr_motion",
        "ml": "ml_leakage_safe",
    },
    risks=[
        "Data leakage from random trial splitting",
        "Preprocessing before train/test split",
        "No external test set",
        "Insufficient cross-validation folds",
        "Nested CV not used for hyperparameter tuning",
        "Subject-wise split not enforced",
    ],
    reporting_requirements=[
        "split_strategy",
        "cv_folds",
        "model_type",
        "hyperparameters",
        "feature_set",
        "metrics",
        "external_test_set",
        "nested_cv_status",
        "preprocessing_in_fold",
    ],
)


MULTI_SITE_SCENARIO = ScenarioDefinition(
    scenario_id="multi_site",
    name="Multi-Site fNIRS",
    description="Multi-site fNIRS study with site effect harmonization",
    required_node_types=[
        "dataset_discovery",
        "site_metadata_extraction",
        "site_level_qc",
        "optical_density",
        "motion_correction",
        "filtering",
        "beer_lambert_law",
        "multi_site_harmonization",
        "design_matrix",
        "first_level_glm",
        "contrast",
    ],
    optional_node_types=[
        "batch_effect_diagnostics",
        "mixed_effects_glm",
        "site_covariate_glm",
        "short_channel_regression",
        "bad_channel_detection",
    ],
    required_config_fields=[
        "site_field",
        "harmonization_method",
        "min_subjects_per_site",
    ],
    constraints={
        "harmonization_methods": ["combat", "limma", "mixed_effects", "covariate"],
        "min_sites": 2,
        "min_subjects_per_site": 5,
        "required_diagnostics": ["batch_effect_test", "icc_report"],
    },
    default_presets={
        "qc": "conservative_qc",
        "motion": "tddr_motion",
        "filter": "basic_bandpass",
        "harmonization": "combat_default",
    },
    risks=[
        "Site confounded with demographic variables",
        "Insufficient subjects per site for stable harmonization",
        "Batch effects not fully removed",
        "Biological signal attenuation from over-harmonization",
        "Site-level QC outlier not excluded",
    ],
    reporting_requirements=[
        "site_count",
        "subjects_per_site",
        "harmonization_method",
        "batch_effect_diagnostics",
        "icc_before_after",
        "site_covariates",
        "exclusion_by_site",
    ],
)


# All scenarios
ALL_SCENARIOS: list[ScenarioDefinition] = [
    TASK_SCENARIO,
    RESTING_STATE_SCENARIO,
    REAL_WORLD_SCENARIO,
    HYPERSCANNING_SCENARIO,
    MACHINE_LEARNING_SCENARIO,
    MULTI_SITE_SCENARIO,
]


class ScenarioRegistry:
    """Registry of scenario definitions."""

    def __init__(self) -> None:
        self._scenarios: dict[str, ScenarioDefinition] = {s.scenario_id: s for s in ALL_SCENARIOS}

    def get(self, scenario_id: str) -> ScenarioDefinition | None:
        return self._scenarios.get(scenario_id)

    def list_ids(self) -> list[str]:
        return sorted(self._scenarios.keys())

    def all(self) -> list[ScenarioDefinition]:
        return list(self._scenarios.values())

    def detect_scenario(self, config: dict[str, Any]) -> str:
        """Detect scenario type from study configuration."""
        if config.get("uses_machine_learning"):
            return "machine_learning"
        if config.get("uses_hyperscanning"):
            return "hyperscanning"
        if config.get("is_real_world"):
            return "real_world"
        if config.get("uses_resting_state"):
            return "resting_state"
        return "task"


# Scenario-specific node templates
SCENARIO_NODE_TEMPLATES: dict[str, list[NodeTemplate]] = {
    "resting_state": [
        NodeTemplate(
            template_id="connectivity_analysis",
            name="Connectivity Analysis",
            category=NodeCategory.ANALYSIS,
            atom_type="connectivity_analysis",
            description="Compute functional connectivity between channels/ROIs",
            default_config={
                "method": "pearson",
                "fisher_z_transform": True,
            },
            ports=[
                NodePort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
                NodePort(name="connectivity_matrix", direction="out", schema="ConnectivityMatrix"),
            ],
            tags=["resting_state"],
        ),
    ],
    "real_world": [
        NodeTemplate(
            template_id="event_reconstruction",
            name="Event Reconstruction",
            category=NodeCategory.DESIGN,
            atom_type="event_reconstruction",
            description="Reconstruct events from behavioral sensors or manual coding",
            default_config={
                "method": "threshold",
                "sensors": ["accelerometer"],
            },
            ports=[
                NodePort(name="raw_data", direction="in", schema="RawData"),
                NodePort(name="events", direction="out", schema="EventData"),
            ],
            tags=["real_world"],
        ),
    ],
    "hyperscanning": [
        NodeTemplate(
            template_id="inter_brain_connectivity",
            name="Inter-Brain Connectivity",
            category=NodeCategory.ANALYSIS,
            atom_type="inter_brain_connectivity",
            description="Compute connectivity between brains in hyperscanning",
            default_config={
                "method": "pearson",
                "level": "dyad",
            },
            ports=[
                NodePort(name="haemoglobin_multi", direction="in", schema="HaemoglobinDataMulti"),
                NodePort(name="inter_brain_matrix", direction="out", schema="ConnectivityMatrix"),
            ],
            tags=["hyperscanning"],
        ),
    ],
    "machine_learning": [
        NodeTemplate(
            template_id="feature_extraction",
            name="Feature Extraction",
            category=NodeCategory.ANALYSIS,
            atom_type="feature_extraction",
            description="Extract ML features from fNIRS signals",
            default_config={
                "features": ["mean", "std", "slope", "peak"],
                "window_size": 10,
            },
            ports=[
                NodePort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
                NodePort(name="features", direction="out", schema="FeatureMatrix"),
            ],
            tags=["machine_learning"],
        ),
        NodeTemplate(
            template_id="ml_model",
            name="ML Model",
            category=NodeCategory.ANALYSIS,
            atom_type="ml_model",
            description="Train and evaluate machine learning model",
            default_config={
                "model_type": "svm",
                "cv_folds": 5,
                "split_strategy": "subject_wise",
            },
            ports=[
                NodePort(name="features", direction="in", schema="FeatureMatrix"),
                NodePort(name="labels", direction="in", schema="LabelVector"),
                NodePort(name="ml_results", direction="out", schema="MLResults"),
            ],
            tags=["machine_learning"],
        ),
    ],
    "multi_site": [
        NodeTemplate(
            template_id="site_metadata_extraction",
            name="Site Metadata Extraction",
            category=NodeCategory.DATA,
            atom_type="site_metadata_extraction",
            description="Extract site information from BIDS participants.tsv or SNIRF metadata",
            default_config={
                "site_field": "site",
                "required_fields": ["site", "scanner_id"],
                "allow_missing": False,
            },
            ports=[
                NodePort(name="data_manifest", direction="in", schema="DataManifest"),
                NodePort(name="site_metadata", direction="out", schema="SiteMetadata"),
            ],
            tags=["multi_site"],
        ),
        NodeTemplate(
            template_id="site_level_qc",
            name="Site-Level QC",
            category=NodeCategory.VALIDATION,
            atom_type="site_level_qc",
            description="Compute QC metrics aggregated by site for batch effect detection",
            default_config={
                "metrics": ["mean_intensity", "snr", "sci_pass_rate", "channel_dropout_rate"],
                "outlier_threshold": 2.0,
                "min_subjects_per_site": 5,
            },
            ports=[
                NodePort(name="qc_report", direction="in", schema="QCReport"),
                NodePort(name="site_metadata", direction="in", schema="SiteMetadata"),
                NodePort(name="site_qc_report", direction="out", schema="SiteQCReport"),
            ],
            tags=["multi_site"],
        ),
        NodeTemplate(
            template_id="combat_harmonization",
            name="ComBat Harmonization",
            category=NodeCategory.PREPROCESSING,
            atom_type="multi_site_harmonization",
            description="ComBat harmonization to remove site effects",
            default_config={
                "method": "combat",
                "eb": True,
                "parametric": True,
                "preserve_biological": True,
            },
            ports=[
                NodePort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
                NodePort(name="site_metadata", direction="in", schema="SiteMetadata"),
                NodePort(name="haemoglobin_harmonized", direction="out", schema="HaemoglobinData"),
            ],
            tags=["multi_site"],
        ),
        NodeTemplate(
            template_id="batch_effect_diagnostics",
            name="Batch Effect Diagnostics",
            category=NodeCategory.VALIDATION,
            atom_type="batch_effect_diagnostics",
            description="Diagnose and visualize batch effects across sites",
            default_config={
                "methods": ["pca", "anova", "icc"],
                "significance_threshold": 0.05,
            },
            ports=[
                NodePort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
                NodePort(name="site_metadata", direction="in", schema="SiteMetadata"),
                NodePort(name="diagnostics_report", direction="out", schema="DiagnosticsReport"),
            ],
            tags=["multi_site"],
        ),
    ],
}
