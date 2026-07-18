"""Complete set of node templates for fNIRS analysis."""

from __future__ import annotations

from fnirs_flow.flow.atoms import AtomPort, BackendBinding, MethodAtomCategory
from fnirs_flow.registry.node_library import MethodAtomTemplate

# ============================================================================
# DATA NODES
# ============================================================================

DATASET_DISCOVERY = MethodAtomTemplate(
    template_id="dataset_discovery",
    name="Dataset Discovery",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="dataset_discovery",
    description="Discover and enumerate fNIRS dataset files",
    default_config={"dataset_id": "", "source_kind": "mne_nirs_dataset"},
    ports=[
        AtomPort(name="data_manifest", direction="out", schema="DataManifest"),
    ],
    tags=["data", "input"],
)

BIDS_IMPORT = MethodAtomTemplate(
    template_id="bids_import",
    name="BIDS Import",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="bids_import",
    description="Import data from BIDS-formatted dataset",
    default_config={"bids_dir": "", "datatype": "nirs"},
    ports=[
        AtomPort(name="bids_path", direction="in", schema="FilePath"),
        AtomPort(name="raw_data", direction="out", schema="RawData"),
        AtomPort(name="metadata", direction="out", schema="BIDSMetadata"),
    ],
    tags=["data", "bids"],
)

SNIRF_READER = MethodAtomTemplate(
    template_id="snirf_reader",
    name="SNIRF Reader",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="snirf_reader",
    description="Read SNIRF format fNIRS data files",
    default_config={"preload": False},
    ports=[
        AtomPort(name="file_path", direction="in", schema="FilePath"),
        AtomPort(name="raw_data", direction="out", schema="RawData"),
    ],
    reference="MNE-Python: mne.io.read_raw_snirf",
    tags=["data", "snirf"],
)

RUN_READER = MethodAtomTemplate(
    template_id="read_run",
    name="Read Dataset Run",
    category=MethodAtomCategory.DATA,
    atom_type="read_run",
    operation="read_run",
    description="Read each discovered BIDS/SNIRF run from a data manifest",
    default_config={"preload": False},
    ports=[
        AtomPort(name="data_manifest", direction="in", schema="DataManifest"),
        AtomPort(name="raw_data", direction="out", schema="RawData"),
    ],
    tags=["data", "bids", "snirf", "run"],
)

LOCALIZATION_PROJECTION_IMPORT = MethodAtomTemplate(
    template_id="localization_projection_import",
    name="Localization Projection Import",
    category=MethodAtomCategory.DATA,
    atom_type="localization_projection_import",
    operation="localization_projection_import",
    description="Import a prepared localization/projection CSV as standardized MNI channel coordinates",
    default_config={
        "path": (
            "Sample/privatedata/定位/usable_projection_csv/"
            "Protocol02_QYZ_optimized_10-20MNI_projection_coordinates.csv"
        ),
        "coordinate_set_id": "Protocol02_QYZ_optimized_10-20MNI",
        "execution_scope": "group",
        "readiness_status": "ready",
        "accuracy_caveat": "not_claimed_to_reproduce_nirsspm_accuracy",
        "method_note": "Imports prepared projection coordinates; does not implement NIRS-SPM/NFRI projection.",
    },
    ports=[
        AtomPort(name="projection_csv", direction="in", schema="ProjectionCoordinateCSV"),
        AtomPort(name="projected_mni_channels", direction="out", schema="ProjectedMNIChannels"),
        AtomPort(name="projection_import_manifest", direction="out", schema="ProjectionImportManifest"),
    ],
    tags=["data", "localization", "projection", "mni", "group"],
)

NIRS_SPM_SURFACE_PROJECTION = MethodAtomTemplate(
    template_id="nirs_spm_surface_projection",
    name="NIRS-SPM Surface Projection",
    category=MethodAtomCategory.DATA,
    atom_type="nirs_spm_surface_projection",
    operation="nirs_spm_surface_projection",
    description=(
        "Rewrite NIRS-SPM v4 r1 projection_CS: project MNI head-surface coordinates "
        "to cortical MNI coordinates using bundled NIRS-SPM surface references"
    ),
    default_config={
        "path": (
            "Sample/privatedata/定位/usable_projection_csv/"
            "G1_shouzhen_ch01_ch42_projection_coordinates.csv"
        ),
        "reference_dir": "References/NIRS_SPM_v4_r1",
        "coordinate_set_id": "G1_shouzhen_ch01_ch42",
        "head_coordinate_columns": {
            "x": "projected_head_x",
            "y": "projected_head_y",
            "z": "projected_head_z",
        },
        "reference_coordinate_columns": {
            "x": "projected_mni_x",
            "y": "projected_mni_y",
            "z": "projected_mni_z",
        },
        "execution_scope": "group",
        "readiness_status": "needs_attention",
        "method_note": (
            "Implements projection_CS only. Full NIRS-SPM equivalence also depends on the "
            "preceding registration and head-surface MNI coordinate generation."
        ),
    },
    ports=[
        AtomPort(name="head_surface_mni_csv", direction="in", schema="ProjectionCoordinateCSV"),
        AtomPort(name="nirsspm_projected_mni", direction="out", schema="ProjectedMNIChannels"),
        AtomPort(name="projection_validation", direction="out", schema="ProjectionValidationReport"),
    ],
    reference="NIRS-SPM v4 r1: projection_CS.m",
    tags=["data", "localization", "projection", "mni", "nirsspm", "group", "experimental"],
)

NIRX_READER = MethodAtomTemplate(
    template_id="nirx_reader",
    name="NIRx Reader",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="nirx_reader",
    description="Read NIRx fNIRS data files (NIRScout, NIRSport, NIRSport2)",
    default_config={},
    ports=[
        AtomPort(name="file_path", direction="in", schema="FilePath"),
        AtomPort(name="raw_data", direction="out", schema="RawData"),
    ],
    reference="MNE-Python: mne.io.read_raw_nirx",
    evidence_refs=["acq-NIRScout-66", "acq-NIRSport-36", "acq-NIRSport2-36"],
    tags=["data", "nirx"],
)

HITACHI_READER = MethodAtomTemplate(
    template_id="hitachi_reader",
    name="Hitachi ETG-4000 Reader",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="hitachi_reader",
    description="Read Hitachi ETG-4000 fNIRS data files",
    default_config={"system": "ETG-4000"},
    ports=[
        AtomPort(name="file_path", direction="in", schema="FilePath"),
        AtomPort(name="raw_data", direction="out", schema="RawData"),
    ],
    reference="MNE-Python: mne.io.read_raw_hitachi",
    evidence_refs=["acq-ETG-4000-43", "acq-Hitachi-ETG-4000-15"],
    tags=["data", "hitachi", "etg4000"],
)

ISS_READER = MethodAtomTemplate(
    template_id="iss_reader",
    name="ISS Imagent Reader",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="iss_reader",
    description="Read ISS Imagent frequency-domain fNIRS data",
    default_config={"system": "ISS_Imagent", "data_type": "frequency_domain"},
    ports=[
        AtomPort(name="file_path", direction="in", schema="FilePath"),
        AtomPort(name="raw_data", direction="out", schema="RawData"),
    ],
    evidence_refs=["acq-ISS-Imagent-11", "acq-iss-8"],
    tags=["data", "iss", "frequency_domain"],
)

TECHEN_READER = MethodAtomTemplate(
    template_id="techen_reader",
    name="TechEn CW6 Reader",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="techen_reader",
    description="Read TechEn CW6 continuous-wave fNIRS data",
    default_config={"system": "TechEn_CW6"},
    ports=[
        AtomPort(name="file_path", direction="in", schema="FilePath"),
        AtomPort(name="raw_data", direction="out", schema="RawData"),
    ],
    evidence_refs=["acq-TechEn-CW6-9"],
    tags=["data", "techen", "cw6"],
)

KERNEL_READER = MethodAtomTemplate(
    template_id="kernel_reader",
    name="Kernel Flow Reader",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="kernel_reader",
    description="Read Kernel Flow TD-fNIRS data",
    default_config={"system": "Kernel_Flow", "data_type": "time_domain"},
    ports=[
        AtomPort(name="file_path", direction="in", schema="FilePath"),
        AtomPort(name="raw_data", direction="out", schema="RawData"),
    ],
    evidence_refs=["acq-Kernel-Flow-9"],
    tags=["data", "kernel", "time_domain"],
)


# ============================================================================
# DESIGN NODES
# ============================================================================

STUDY_DESIGN = MethodAtomTemplate(
    template_id="study_design",
    name="Study Design",
    category=MethodAtomCategory.DESIGN,
    atom_type="design",
    operation="study_design",
    description="Define study design, conditions, and contrasts",
    default_config={
        "design_type": "block",
        "conditions": [],
        "contrasts": [],
    },
    ports=[
        AtomPort(name="design_spec", direction="out", schema="DesignSpec"),
    ],
    tags=["design", "conditions"],
)

EVENT_EXTRACTION = MethodAtomTemplate(
    template_id="event_extraction",
    name="Event Extraction",
    category=MethodAtomCategory.DESIGN,
    atom_type="design",
    operation="event_extraction",
    description="Extract events from annotations or triggers",
    default_config={"event_id_mapping": {}},
    ports=[
        AtomPort(name="raw_data", direction="in", schema="RawData"),
        AtomPort(name="events", direction="out", schema="EventData"),
    ],
    tags=["design", "events"],
)

DESIGN_MATRIX = MethodAtomTemplate(
    template_id="design_matrix",
    name="Design Matrix",
    category=MethodAtomCategory.DESIGN,
    atom_type="design",
    operation="design_matrix",
    description="Construct GLM design matrix from events",
    default_config={
        "hrf_model": "canonical",
        "drift_model": "polynomial",
        "drift_order": 3,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="design_spec", direction="in", schema="DesignSpec"),
        AtomPort(name="design_matrix", direction="out", schema="DesignMatrix"),
    ],
    reference="MNE-NIRS: mne_nirs.experimental_paradigm",
    tags=["design", "glm"],
)


# ============================================================================
# PREPROCESSING NODES
# ============================================================================

OPTICAL_DENSITY = MethodAtomTemplate(
    template_id="optical_density",
    name="Optical Density Conversion",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="optical_density",
    operation="optical_density_conversion",
    description="Convert raw intensity to optical density",
    default_config={},
    ports=[
        AtomPort(name="raw_data", direction="in", schema="RawData"),
        AtomPort(name="od_data", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["evidence-mne-od"],
    reference="MNE-NIRS: mne.preprocessing.nirs.optical_density",
    tags=["preprocessing", "od"],
)

TDDR_MOTION = MethodAtomTemplate(
    template_id="tddr_motion_correction",
    name="TDDR Motion Correction",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="tddr",
    description="Temporal Derivative Distribution Repair for motion artifacts",
    default_config={"method": "tddr"},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="od_corrected", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["evidence-mne-tddr"],
    reference="MNE-NIRS: mne.preprocessing.nirs.temporal_derivative_distribution_repair",
    tags=["preprocessing", "motion"],
)

SPLINE_MOTION = MethodAtomTemplate(
    template_id="spline_motion_correction",
    name="Spline Motion Correction",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="spline",
    description="Spline-based motion artifact correction",
    default_config={"method": "spline", "spline_segments": 3},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="od_corrected", direction="out", schema="OpticalDensityData"),
    ],
    tags=["preprocessing", "motion"],
)

WAVELET_MOTION = MethodAtomTemplate(
    template_id="wavelet_motion_correction",
    name="Wavelet Motion Correction",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="wavelet",
    description="Wavelet-based motion artifact correction (339 studies in literature)",
    default_config={"method": "wavelet", "wavelet_level": 5},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="od_corrected", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["prep-wavelet-339"],
    reference="HOMER3: hmrR_MotionCorrectWavelet; Molavi & Dumont 2012",
    tags=["preprocessing", "motion", "wavelet"],
)

ICA_MOTION = MethodAtomTemplate(
    template_id="ica_motion_correction",
    name="ICA Motion Correction",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="ica",
    description="Independent Component Analysis for motion artifact removal (405 studies)",
    default_config={"method": "ica", "n_components": None, "threshold": 3.0},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="od_corrected", direction="out", schema="OpticalDensityData"),
        AtomPort(name="ica_components", direction="out", schema="ICAComponents"),
    ],
    evidence_refs=["prep-ica-405"],
    reference="fNIRS-ICA: Virtanen et al. 2019; Chiarelli et al. 2018",
    tags=["preprocessing", "motion", "ica"],
)

PCA_MOTION = MethodAtomTemplate(
    template_id="pca_motion_correction",
    name="PCA Motion Correction",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="pca",
    description="Principal Component Analysis for motion artifact removal (56 studies)",
    default_config={"method": "pca", "n_components": 0.95, "threshold": 3.0},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="od_corrected", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["prep-pca-56"],
    reference="Yücel et al. 2014; HOMER3: hmrR_MotionCorrectPCA",
    tags=["preprocessing", "motion", "pca"],
)

MARA_MOTION = MethodAtomTemplate(
    template_id="mara_motion_correction",
    name="MARA Motion Correction",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="mara",
    description="Motion Artifact Reduction Algorithm combining spline and wavelet",
    default_config={"method": "mara", "spline_segments": 3, "wavelet_level": 5},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="od_corrected", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["prep-mara-60"],
    reference="Scholkmann et al. 2010; HOMER3: hmrR_MotionCorrectSpline",
    tags=["preprocessing", "motion", "mara"],
)

CBSI_MOTION = MethodAtomTemplate(
    template_id="cbsi_motion_correction",
    name="CBSI Motion Correction",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="cbsi",
    description="Correlation-Based Signal Improvement for motion artifact correction",
    default_config={"method": "cbsi"},
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="haemoglobin_corrected", direction="out", schema="HaemoglobinData"),
    ],
    evidence_refs=["prep-cbsi-5"],
    reference="Cui et al. 2010; HOMER3: hmrR_MotionCorrectCBSI",
    tags=["preprocessing", "motion", "cbsi"],
)

RLS_ADAPTIVE_FILTER = MethodAtomTemplate(
    template_id="rls_adaptive_filter",
    name="RLS Adaptive Filter",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="rls",
    description="Recursive Least Squares adaptive filtering for motion artifact removal",
    default_config={"method": "rls", "forgetting_factor": 0.99, "filter_order": 10},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="od_corrected", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["prep-rls-1"],
    tags=["preprocessing", "motion", "adaptive"],
)

KALMAN_FILTER = MethodAtomTemplate(
    template_id="kalman_filter",
    name="Kalman Filter",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="kalman",
    description="Kalman filter state-space model for noise and motion artifact handling",
    default_config={"method": "kalman", "process_noise": 0.01, "measurement_noise": 0.1},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="od_corrected", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["prep-kalman-1"],
    tags=["preprocessing", "motion", "kalman"],
)

BLOCK_REJECTION = MethodAtomTemplate(
    template_id="block_rejection",
    name="Block/Trial Rejection",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="motion_correction",
    operation="block_rejection",
    description="Reject motion-contaminated trials/blocks based on amplitude thresholds",
    default_config={
        "amplitude_threshold": 0.5,
        "std_threshold": 3.0,
        "min_valid_trials": 3,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="events", direction="in", schema="EventData"),
        AtomPort(name="haemoglobin_clean", direction="out", schema="HaemoglobinData"),
        AtomPort(name="rejection_mask", direction="out", schema="BooleanMask"),
    ],
    evidence_refs=["prep-block-rejection"],
    tags=["preprocessing", "motion", "rejection"],
)


# ============================================================================
# FILTERING NODES
# ============================================================================

BANDPASS_FILTER = MethodAtomTemplate(
    template_id="bandpass_filter",
    name="Bandpass Filter",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="filter",
    operation="bandpass",
    description="Apply bandpass filter to fNIRS data (97 studies report band-pass filtering)",
    default_config={
        "l_freq": 0.01,
        "h_freq": 0.2,
        "method": "fir",
        "fir_design": "firwin",
    },
    ports=[
        AtomPort(name="input_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="filtered_data", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["prep-bandpass-97"],
    reference="MNE-Python: mne.filter.filter_data",
    tags=["preprocessing", "filter", "bandpass"],
)

NOTCH_FILTER = MethodAtomTemplate(
    template_id="notch_filter",
    name="Notch Filter",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="filter",
    operation="notch",
    description="Apply notch filter to remove line noise (13 studies report notch filtering)",
    default_config={
        "freqs": [50.0, 100.0],
        "method": "fir",
        "notch_widths": 2.0,
    },
    ports=[
        AtomPort(name="input_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="filtered_data", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["prep-notch-13"],
    reference="MNE-Python: mne.filter.notch_filter",
    tags=["preprocessing", "filter", "notch"],
)

LOWPASS_FILTER = MethodAtomTemplate(
    template_id="lowpass_filter",
    name="Lowpass Filter",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="filter",
    operation="lowpass",
    description="Apply lowpass filter to fNIRS data (3 studies report lowpass filtering)",
    default_config={
        "h_freq": 0.5,
        "method": "fir",
        "fir_design": "firwin",
    },
    ports=[
        AtomPort(name="input_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="filtered_data", direction="out", schema="OpticalDensityData"),
    ],
    evidence_refs=["prep-lowpass-3"],
    tags=["preprocessing", "filter", "lowpass"],
)

BEER_LAMBERT = MethodAtomTemplate(
    template_id="beer_lambert_law",
    name="Modified Beer-Lambert Law",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="mbll_conversion",
    operation="mbll",
    description="Convert optical density to haemoglobin concentration",
    default_config={"ppf": 6.0},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="haemoglobin", direction="out", schema="HaemoglobinData"),
    ],
    evidence_refs=["evidence-mne-mbll"],
    reference="MNE-NIRS: mne.preprocessing.nirs.beer_lambert_law",
    tags=["preprocessing", "mbll"],
)

SHORT_CHANNEL_REGRESSION = MethodAtomTemplate(
    template_id="short_channel_regression",
    name="Short-Channel Regression",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="short_channel_regression",
    operation="short_channel_regression",
    description="Remove systemic physiological noise using short-separation channels (17 studies)",
    default_config={"threshold": 0.01, "method": "linear"},
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="haemoglobin_clean", direction="out", schema="HaemoglobinData"),
    ],
    evidence_refs=["prep-short-channel-17"],
    reference="MNE-NIRS; Gagnon et al. 2012",
    tags=["preprocessing", "regression", "short_channel"],
)

SYSTEMIC_PHYSIOLOGY_REGRESSION = MethodAtomTemplate(
    template_id="systemic_physiology_regression",
    name="Systemic Physiology Regression",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="short_channel_regression",
    operation="systemic_physiology_regression",
    description="Regress out systemic physiological confounds",
    default_config={
        "confounds": ["heart_rate", "respiration", "blood_pressure"],
        "method": "linear",
        "include_derivatives": True,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="physio_signals", direction="in", schema="PhysioSignals"),
        AtomPort(name="haemoglobin_clean", direction="out", schema="HaemoglobinData"),
    ],
    evidence_refs=["prep-systemic-regression"],
    reference="Tachtsidis & Scholkmann 2016; Kirilina et al. 2013",
    tags=["preprocessing", "regression", "systemic", "physiology"],
)

NUISANCE_REGRESSION = MethodAtomTemplate(
    template_id="nuisance_regression",
    name="Nuisance Regression",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="short_channel_regression",
    operation="nuisance_regression",
    description="Regress nuisance signals from haemoglobin data",
    default_config={
        "confound_types": ["motion_parameters", "physiological", "task_related"],
        "method": "ols",
        "add_intercept": True,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="confounds", direction="in", schema="Confounds"),
        AtomPort(name="haemoglobin_clean", direction="out", schema="HaemoglobinData"),
    ],
    evidence_refs=["prep-nuisance-regression"],
    reference="MNE-NIRS; GLM-based denoising",
    tags=["preprocessing", "regression", "nuisance"],
)

BAD_CHANNEL_DETECTION = MethodAtomTemplate(
    template_id="bad_channel_detection",
    name="Bad Channel Detection",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="signal_qc",
    operation="bad_channel_detection",
    description="Detect and mark bad channels based on QC metrics",
    default_config={"sci_threshold": 0.8, "cv_threshold": 0.15},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="od_clean", direction="out", schema="OpticalDensityData"),
        AtomPort(name="bad_channel_mask", direction="out", schema="ChannelMask"),
    ],
    tags=["preprocessing", "qc"],
)


# ============================================================================
# QC NODES
# ============================================================================

QC_METRICS = MethodAtomTemplate(
    template_id="qc_metrics",
    name="QC Metrics",
    category=MethodAtomCategory.VALIDATION,
    atom_type="signal_qc",
    operation="qc_metrics",
    description="Compute quality control metrics (SCI, CV, SNR, etc.)",
    default_config={
        "preset": "conservative_qc",
        "sci_threshold": 0.8,
        "sd_distance_min": 0.01,
        "sd_distance_max": 0.08,
    },
    ports=[
        AtomPort(name="raw_data", direction="in", schema="RawData"),
        AtomPort(name="qc_report", direction="out", schema="QCReport"),
    ],
    tags=["qc", "validation"],
)

SCI_CHECK = MethodAtomTemplate(
    template_id="sci_check",
    name="SCI Quality Check",
    category=MethodAtomCategory.VALIDATION,
    atom_type="signal_qc",
    operation="sci_check",
    description="Scalp Coupling Index quality assessment",
    default_config={"l_freq": 0.7, "h_freq": 1.5, "threshold": 0.8},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="sci_values", direction="out", schema="FloatArray"),
        AtomPort(name="pass_mask", direction="out", schema="BooleanMask"),
    ],
    reference="MNE-NIRS: mne.preprocessing.nirs.scalp_coupling_index",
    tags=["qc", "sci"],
)

CV_CHECK = MethodAtomTemplate(
    template_id="cv_check",
    name="Coefficient of Variation Check",
    category=MethodAtomCategory.VALIDATION,
    atom_type="signal_qc",
    operation="cv_check",
    description="Coefficient of Variation quality assessment for signal stability",
    default_config={"cv_threshold": 0.15, "window_size": 10},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="cv_values", direction="out", schema="FloatArray"),
        AtomPort(name="pass_mask", direction="out", schema="BooleanMask"),
    ],
    evidence_refs=["qc-cv"],
    tags=["qc", "cv", "signal_quality"],
)

SNR_CHECK = MethodAtomTemplate(
    template_id="snr_check",
    name="Signal-to-Noise Ratio Check",
    category=MethodAtomCategory.VALIDATION,
    atom_type="signal_qc",
    operation="snr_check",
    description="Signal-to-Noise Ratio quality assessment",
    default_config={"snr_threshold": 2.0, "method": "peak_snr"},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="snr_values", direction="out", schema="FloatArray"),
        AtomPort(name="pass_mask", direction="out", schema="BooleanMask"),
    ],
    evidence_refs=["qc-snr"],
    tags=["qc", "snr", "signal_quality"],
)


# ============================================================================
# ANALYSIS NODES
# ============================================================================

FIRST_LEVEL_GLM = MethodAtomTemplate(
    template_id="first_level_glm",
    name="First-Level GLM",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="first_level_glm",
    operation="first_level_glm",
    description="General linear model for task activation",
    default_config={"hrf_model": "canonical"},
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="design_matrix", direction="in", schema="DesignMatrix"),
        AtomPort(name="glm_results", direction="out", schema="GLMResults"),
    ],
    reference="MNE-NIRS: mne_nirs.statistics",
    tags=["analysis", "glm"],
)

CONTRAST = MethodAtomTemplate(
    template_id="contrast",
    name="Contrast Estimation",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="first_level_glm",
    operation="contrast",
    description="Estimate contrasts between conditions",
    default_config={"contrasts": []},
    ports=[
        AtomPort(name="glm_results", direction="in", schema="GLMResults"),
        AtomPort(name="contrast_results", direction="out", schema="ContrastResults"),
    ],
    tags=["analysis", "contrast"],
)

MULTIPLE_COMPARISON_CORRECTION = MethodAtomTemplate(
    template_id="multiple_comparison_correction",
    name="Multiple Comparison Correction",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="first_level_glm",
    operation="multiple_comparison_correction",
    description="Correct for multiple comparisons (Bonferroni/FDR/FWE, 6 studies)",
    default_config={
        "method": "fdr",
        "alpha": 0.05,
        "fdr_method": "indep",
    },
    ports=[
        AtomPort(name="contrast_results", direction="in", schema="ContrastResults"),
        AtomPort(name="corrected_results", direction="out", schema="ContrastResults"),
    ],
    evidence_refs=["ana-mcc-bonferroni", "ana-mcc-fdr", "ana-mcc-fwe"],
    reference="statsmodels: multipletests; MNE: mne.stats.fdr_correction",
    tags=["analysis", "statistics", "multiple_comparisons"],
)

NUISANCE_GLM = MethodAtomTemplate(
    template_id="nuisance_glm",
    name="Nuisance GLM",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="first_level_glm",
    operation="nuisance_glm",
    description="GLM with nuisance regressors (motion, physiology) for signal cleaning",
    default_config={
        "nuisance_types": ["motion_parameters", "heart_rate", "respiration"],
        "include_derivatives": True,
        "hrf_model": "canonical",
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="design_matrix", direction="in", schema="DesignMatrix"),
        AtomPort(name="nuisance_signals", direction="in", schema="NuisanceSignals"),
        AtomPort(name="glm_results", direction="out", schema="GLMResults"),
    ],
    evidence_refs=["ana-nuisance-glm"],
    reference="MNE-NIRS; GLM with confound regressors",
    tags=["analysis", "glm", "nuisance"],
)

BLOCK_AVERAGING = MethodAtomTemplate(
    template_id="block_averaging",
    name="Block/Trial Averaging",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="first_level_glm",
    operation="block_averaging",
    description="Average haemodynamic responses across trials/blocks (78 studies)",
    default_config={
        "baseline_window": [-5, 0],
        "response_window": [0, 20],
        "baseline_correction": "mean",
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="events", direction="in", schema="EventData"),
        AtomPort(name="average_response", direction="out", schema="AverageResponse"),
    ],
    evidence_refs=["ana-block-averaging-78"],
    reference="HOMER3: hmrR_BlockAvg; MNE-NIRS",
    tags=["analysis", "averaging", "erp"],
)


# ============================================================================
# CONNECTIVITY NODES
# ============================================================================

CONNECTIVITY_ANALYSIS = MethodAtomTemplate(
    template_id="connectivity_analysis",
    name="Functional Connectivity Analysis",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="resting_connectivity",
    operation="pearson",
    description="Compute functional connectivity between channels/ROIs (Pearson correlation)",
    default_config={
        "method": "pearson",
        "fisher_z_transform": True,
        "window_size": None,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="connectivity_matrix", direction="out", schema="ConnectivityMatrix"),
    ],
    evidence_refs=["ana-fc-pearson"],
    reference="MNE-NIRS; resting-state FC common in 29/45 hyperscanning studies",
    tags=["analysis", "connectivity", "resting_state", "pearson"],
)

PLV_CONNECTIVITY = MethodAtomTemplate(
    template_id="plv_connectivity",
    name="Phase Locking Value Connectivity",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="resting_connectivity",
    operation="plv",
    description="Compute Phase Locking Value (PLV) for phase synchronization between channels",
    default_config={
        "method": "plv",
        "frequency_band": [0.01, 0.1],
        "n_surrogate": 100,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="connectivity_matrix", direction="out", schema="ConnectivityMatrix"),
    ],
    evidence_refs=["ana-plv"],
    reference="Lachaux et al. 1999; fNIRS PLV applications",
    tags=["analysis", "connectivity", "resting_state", "plv", "phase"],
)

COHERENCE_CONNECTIVITY = MethodAtomTemplate(
    template_id="coherence_connectivity",
    name="Coherence Connectivity",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="resting_connectivity",
    operation="coherence",
    description="Compute spectral coherence between channels for frequency-domain connectivity",
    default_config={
        "method": "coherence",
        "frequency_band": [0.01, 0.1],
        "nperseg": 256,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="connectivity_matrix", direction="out", schema="ConnectivityMatrix"),
    ],
    evidence_refs=["ana-coherence"],
    reference="scipy.signal.coherence; fNIRS coherence analysis",
    tags=["analysis", "connectivity", "resting_state", "coherence", "frequency"],
)

WTC_CONNECTIVITY = MethodAtomTemplate(
    template_id="wtc_connectivity",
    name="Wavelet Transform Coherence",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="resting_connectivity",
    operation="wtc",
    description="Compute Wavelet Transform Coherence for time-frequency connectivity",
    default_config={
        "method": "wtc",
        "mother_wavelet": "morlet",
        "omega0": 6,
        "significance_level": 0.05,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="connectivity_matrix", direction="out", schema="ConnectivityMatrix"),
        AtomPort(name="wtc_spectrum", direction="out", schema="WTCSpectrum"),
    ],
    evidence_refs=["ana-wtc"],
    reference="Grinsted et al. 2004; MATLAB: wtc; Python: awr",
    tags=["analysis", "connectivity", "resting_state", "wtc", "wavelet"],
)

GRANGER_CAUSALITY = MethodAtomTemplate(
    template_id="granger_causality",
    name="Granger Causality",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="resting_connectivity",
    operation="granger",
    description="Compute Granger causality for effective connectivity between channels",
    default_config={
        "method": "granger",
        "max_lag": 10,
        "significance_level": 0.05,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="connectivity_matrix", direction="out", schema="ConnectivityMatrix"),
    ],
    evidence_refs=["ana-granger"],
    reference="statsmodels: grangercausalitytests; 2/45 hyperscanning studies",
    tags=["analysis", "connectivity", "effective_connectivity", "granger"],
)

GRAPH_THEORY = MethodAtomTemplate(
    template_id="graph_theory",
    name="Graph Theory Analysis",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="resting_connectivity",
    operation="graph_theory",
    description="Compute graph theory metrics from connectivity matrices",
    default_config={
        "threshold_method": "proportional",
        "threshold": 0.15,
        "metrics": ["clustering_coefficient", "path_length", "small_worldness"],
    },
    ports=[
        AtomPort(name="connectivity_matrix", direction="in", schema="ConnectivityMatrix"),
        AtomPort(name="graph_metrics", direction="out", schema="GraphMetrics"),
    ],
    evidence_refs=["ana-graph-theory"],
    reference="NetworkX; BCT; 2/16 rsfNIRS studies",
    tags=["analysis", "connectivity", "graph_theory"],
)


# ============================================================================
# HYPERSCANNING NODES
# ============================================================================

INTER_BRAIN_CONNECTIVITY = MethodAtomTemplate(
    template_id="inter_brain_connectivity",
    name="Inter-Brain Connectivity",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="resting_connectivity",
    operation="inter_brain_connectivity",
    description="Compute connectivity between brains in hyperscanning",
    default_config={"method": "pearson", "level": "dyad"},
    ports=[
        AtomPort(name="haemoglobin_multi", direction="in", schema="HaemoglobinDataMulti"),
        AtomPort(name="inter_brain_matrix", direction="out", schema="ConnectivityMatrix"),
    ],
    tags=["analysis", "connectivity", "hyperscanning"],
)

FEATURE_EXTRACTION = MethodAtomTemplate(
    template_id="feature_extraction",
    name="Feature Extraction",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="feature_extraction",
    operation="feature_extraction",
    description="Extract ML features from fNIRS signals",
    default_config={
        "features": ["mean", "std", "slope", "peak"],
        "window_size": 10,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="features", direction="out", schema="FeatureMatrix"),
    ],
    tags=["analysis", "ml", "features"],
)

ML_MODEL = MethodAtomTemplate(
    template_id="ml_model",
    name="ML Model",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="ml_classification",
    operation="ml_model",
    description="Train and evaluate machine learning model (generic)",
    default_config={
        "model_type": "svm",
        "cv_folds": 5,
        "split_strategy": "subject_wise",
    },
    ports=[
        AtomPort(name="features", direction="in", schema="FeatureMatrix"),
        AtomPort(name="labels", direction="in", schema="LabelVector"),
        AtomPort(name="ml_results", direction="out", schema="MLResults"),
    ],
    tags=["analysis", "ml"],
)

SVM_MODEL = MethodAtomTemplate(
    template_id="svm_model",
    name="SVM Classifier",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="ml_classification",
    operation="svm",
    description="Support Vector Machine classifier (common in fNIRS ML studies)",
    default_config={
        "model_type": "svm",
        "kernel": "rbf",
        "cv_folds": 5,
        "split_strategy": "subject_wise",
        "nested_cv": True,
        "preprocessing_in_fold": True,
    },
    ports=[
        AtomPort(name="features", direction="in", schema="FeatureMatrix"),
        AtomPort(name="labels", direction="in", schema="LabelVector"),
        AtomPort(name="ml_results", direction="out", schema="MLResults"),
    ],
    evidence_refs=["ml-svm"],
    reference="scikit-learn: SVC; common in fNIRS-ML literature",
    tags=["analysis", "ml", "svm"],
)

LDA_MODEL = MethodAtomTemplate(
    template_id="lda_model",
    name="LDA Classifier",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="ml_classification",
    operation="lda",
    description="Linear Discriminant Analysis classifier (used with connectivity features)",
    default_config={
        "model_type": "lda",
        "solver": "svd",
        "cv_folds": 5,
        "split_strategy": "subject_wise",
        "nested_cv": True,
    },
    ports=[
        AtomPort(name="features", direction="in", schema="FeatureMatrix"),
        AtomPort(name="labels", direction="in", schema="LabelVector"),
        AtomPort(name="ml_results", direction="out", schema="MLResults"),
    ],
    evidence_refs=["ml-lda"],
    reference="scikit-learn: LinearDiscriminantAnalysis; shrinkage LDA with connectivity features",
    tags=["analysis", "ml", "lda"],
)

CNN_MODEL = MethodAtomTemplate(
    template_id="cnn_model",
    name="CNN Model",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="ml_classification",
    operation="cnn",
    description="Convolutional Neural Network for fNIRS classification (>89.57% accuracy for MCI)",
    default_config={
        "model_type": "cnn",
        "architecture": "1d_cnn",
        "conv_layers": 3,
        "filters": [32, 64, 128],
        "kernel_size": 3,
        "dropout": 0.5,
        "cv_folds": 5,
        "split_strategy": "subject_wise",
        "nested_cv": True,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="labels", direction="in", schema="LabelVector"),
        AtomPort(name="ml_results", direction="out", schema="MLResults"),
    ],
    evidence_refs=["ml-cnn"],
    reference="PyTorch/TensorFlow; >89.57% accuracy for MCI detection",
    tags=["analysis", "ml", "cnn", "deep_learning"],
)

LSTM_MODEL = MethodAtomTemplate(
    template_id="lstm_model",
    name="LSTM Model",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="ml_classification",
    operation="lstm",
    description="Long Short-Term Memory network for temporal fNIRS classification",
    default_config={
        "model_type": "lstm",
        "hidden_size": 128,
        "num_layers": 2,
        "dropout": 0.3,
        "bidirectional": True,
        "cv_folds": 5,
        "split_strategy": "subject_wise",
        "nested_cv": True,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="labels", direction="in", schema="LabelVector"),
        AtomPort(name="ml_results", direction="out", schema="MLResults"),
    ],
    evidence_refs=["ml-lstm"],
    reference="PyTorch/TensorFlow; MODWT-LSTM for physiological noise filtering",
    tags=["analysis", "ml", "lstm", "deep_learning"],
)

TRANSFORMER_MODEL = MethodAtomTemplate(
    template_id="transformer_model",
    name="Transformer Model",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="ml_classification",
    operation="transformer",
    description="Transformer architecture for fNIRS sequence classification",
    default_config={
        "model_type": "transformer",
        "d_model": 128,
        "nhead": 8,
        "num_layers": 4,
        "dropout": 0.1,
        "cv_folds": 5,
        "split_strategy": "subject_wise",
        "nested_cv": True,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="labels", direction="in", schema="LabelVector"),
        AtomPort(name="ml_results", direction="out", schema="MLResults"),
    ],
    evidence_refs=["ml-transformer"],
    reference="PyTorch; attention-based temporal modeling for fNIRS",
    tags=["analysis", "ml", "transformer", "deep_learning"],
)

DECISION_TREE_MODEL = MethodAtomTemplate(
    template_id="decision_tree_model",
    name="Decision Tree Classifier",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="ml_classification",
    operation="decision_tree",
    description="Decision Tree / Random Forest classifier for interpretable fNIRS classification",
    default_config={
        "model_type": "random_forest",
        "n_estimators": 100,
        "max_depth": None,
        "cv_folds": 5,
        "split_strategy": "subject_wise",
        "nested_cv": True,
    },
    ports=[
        AtomPort(name="features", direction="in", schema="FeatureMatrix"),
        AtomPort(name="labels", direction="in", schema="LabelVector"),
        AtomPort(name="ml_results", direction="out", schema="MLResults"),
    ],
    evidence_refs=["ml-decision-tree"],
    reference="scikit-learn: RandomForestClassifier; interpretable ML for fNIRS",
    tags=["analysis", "ml", "decision_tree", "interpretable"],
)

FEATURE_SELECTION = MethodAtomTemplate(
    template_id="feature_selection",
    name="Feature Selection",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="feature_extraction",
    operation="feature_selection",
    description="Select relevant features for ML classification (reduce dimensionality)",
    default_config={
        "method": "mutual_info",
        "n_features": 50,
        "cv_folds": 5,
    },
    ports=[
        AtomPort(name="features", direction="in", schema="FeatureMatrix"),
        AtomPort(name="labels", direction="in", schema="LabelVector"),
        AtomPort(name="selected_features", direction="out", schema="FeatureMatrix"),
    ],
    evidence_refs=["ml-feature-selection"],
    reference="scikit-learn: SelectKBest, RFE; fNIRS feature selection",
    tags=["analysis", "ml", "feature_selection"],
)

CROSS_VALIDATION = MethodAtomTemplate(
    template_id="cross_validation",
    name="Cross-Validation",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="ml_classification",
    operation="cross_validation",
    description="Cross-validation for ML model evaluation (LOSO, nested CV, 10-fold)",
    default_config={
        "cv_strategy": "leave_one_out",
        "nested": True,
        "outer_folds": 5,
        "inner_folds": 5,
        "preprocessing_in_fold": True,
    },
    ports=[
        AtomPort(name="ml_model", direction="in", schema="MLModel"),
        AtomPort(name="features", direction="in", schema="FeatureMatrix"),
        AtomPort(name="labels", direction="in", schema="LabelVector"),
        AtomPort(name="cv_results", direction="out", schema="CVResults"),
    ],
    evidence_refs=["ml-cv-loo-23", "ml-cv-nested-11", "ml-cv-10fold-10"],
    reference="scikit-learn: cross_val_score, GridSearchCV; LOSO preferred for fNIRS",
    tags=["analysis", "ml", "cross_validation"],
)


# ============================================================================
# OUTPUT NODES
# ============================================================================

CHANNEL_OUTPUT = MethodAtomTemplate(
    template_id="channel_output",
    name="Channel Output",
    category=MethodAtomCategory.OUTPUT,
    atom_type="data_export",
    operation="channel_output",
    description="Export channel-level results to CSV",
    default_config={"format": "csv"},
    ports=[
        AtomPort(name="contrast_results", direction="in", schema="ContrastResults"),
        AtomPort(name="channel_csv", direction="out", schema="CSVFile"),
    ],
    tags=["output", "channel"],
)

ROI_OUTPUT = MethodAtomTemplate(
    template_id="roi_output",
    name="ROI Output",
    category=MethodAtomCategory.OUTPUT,
    atom_type="data_export",
    operation="roi_output",
    description="Export ROI-level aggregated results",
    default_config={"aggregation": "mean", "format": "csv"},
    ports=[
        AtomPort(name="contrast_results", direction="in", schema="ContrastResults"),
        AtomPort(name="roi_csv", direction="out", schema="CSVFile"),
    ],
    tags=["output", "roi"],
)

GROUP_SUMMARY = MethodAtomTemplate(
    template_id="group_summary",
    name="Group Summary",
    category=MethodAtomCategory.OUTPUT,
    atom_type="data_export",
    operation="group_summary",
    description="Compute group-level statistics across subjects",
    default_config={"exclude_subjects": []},
    ports=[
        AtomPort(name="roi_results", direction="in", schema="ROIResults"),
        AtomPort(name="group_csv", direction="out", schema="CSVFile"),
    ],
    tags=["output", "group"],
)


# ============================================================================
# VALIDATION NODES
# ============================================================================

REPORTING_CHECKLIST = MethodAtomTemplate(
    template_id="reporting_checklist",
    name="Reporting Checklist",
    category=MethodAtomCategory.VALIDATION,
    atom_type="methods_report",
    operation="reporting_checklist",
    description="Generate fNIRS reporting checklist",
    default_config={},
    ports=[
        AtomPort(name="qc_report", direction="in", schema="QCReport"),
        AtomPort(name="report", direction="out", schema="Report"),
    ],
    tags=["validation", "reporting"],
)

RISK_REGISTER = MethodAtomTemplate(
    template_id="risk_register",
    name="Risk Register",
    category=MethodAtomCategory.VALIDATION,
    atom_type="methods_report",
    operation="risk_register",
    description="Generate and manage risk register",
    default_config={},
    ports=[
        AtomPort(name="validation_results", direction="in", schema="ValidationResults"),
        AtomPort(name="risk_csv", direction="out", schema="CSVFile"),
    ],
    tags=["validation", "risk"],
)


# ============================================================================
# EXPORT NODES
# ============================================================================

PACKAGE_EXPORT = MethodAtomTemplate(
    template_id="package_export",
    name="Package Export",
    category=MethodAtomCategory.EXPORT,
    atom_type="data_export",
    operation="package_export",
    description="Export reproducibility package (.fnirsflow.zip)",
    default_config={"exclude_raw_data": True},
    ports=[
        AtomPort(name="report", direction="in", schema="Report"),
        AtomPort(name="package", direction="out", schema="Package"),
    ],
    tags=["export", "package"],
)

METHODS_REPORT = MethodAtomTemplate(
    template_id="methods_report",
    name="Methods Report",
    category=MethodAtomCategory.EXPORT,
    atom_type="methods_report",
    operation="methods_report",
    description="Generate manuscript methods section",
    default_config={},
    ports=[
        AtomPort(name="plan", direction="in", schema="Plan"),
        AtomPort(name="qc_summary", direction="in", schema="QCReport"),
        AtomPort(name="methods_md", direction="out", schema="MarkdownFile"),
    ],
    tags=["export", "methods"],
)


# ============================================================================
# MULTI-SITE REGRESSION NODES
# ============================================================================

SITE_METADATA_EXTRACTION = MethodAtomTemplate(
    template_id="site_metadata_extraction",
    name="Site Metadata Extraction",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="site_metadata_extraction",
    description="Extract site information from BIDS participants.tsv or SNIRF metadata",
    default_config={
        "site_field": "site",
        "required_fields": ["site", "scanner_id"],
        "allow_missing": False,
    },
    ports=[
        AtomPort(name="data_manifest", direction="in", schema="DataManifest"),
        AtomPort(name="site_metadata", direction="out", schema="SiteMetadata"),
    ],
    tags=["data", "multi_site", "metadata"],
)

SITE_LEVEL_QC = MethodAtomTemplate(
    template_id="site_level_qc",
    name="Site-Level QC",
    category=MethodAtomCategory.VALIDATION,
    atom_type="signal_qc",
    operation="site_level_qc",
    description="Compute QC metrics aggregated by site for batch effect detection",
    default_config={
        "metrics": ["mean_intensity", "snr", "sci_pass_rate", "channel_dropout_rate"],
        "outlier_threshold": 2.0,
        "min_subjects_per_site": 5,
    },
    ports=[
        AtomPort(name="qc_report", direction="in", schema="QCReport"),
        AtomPort(name="site_metadata", direction="in", schema="SiteMetadata"),
        AtomPort(name="site_qc_report", direction="out", schema="SiteQCReport"),
    ],
    tags=["qc", "multi_site", "validation"],
)

COMBAT_HARMONIZATION = MethodAtomTemplate(
    template_id="combat_harmonization",
    name="ComBat Harmonization",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="short_channel_regression",
    operation="combat_harmonization",
    description="ComBat harmonization to remove site effects while preserving biological signals",
    default_config={
        "method": "combat",
        "covariates": [],
        "eb": True,
        "parametric": True,
        "preserve_biological": True,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="site_metadata", direction="in", schema="SiteMetadata"),
        AtomPort(name="haemoglobin_harmonized", direction="out", schema="HaemoglobinData"),
    ],
    reference="ComBat: Johnson et al. 2007, NeuroImage",
    tags=["preprocessing", "multi_site", "harmonization"],
)

LINEAR_MIXED_EFFECTS_GLM = MethodAtomTemplate(
    template_id="linear_mixed_effects_glm",
    name="Linear Mixed-Effects GLM",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="first_level_glm",
    operation="linear_mixed_effects_glm",
    description="GLM with site as random effect for multi-site studies",
    default_config={
        "random_effects": ["site"],
        "random_intercept": True,
        "random_slope": False,
        "covariance_structure": "unstructured",
        "reml": True,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="design_matrix", direction="in", schema="DesignMatrix"),
        AtomPort(name="site_metadata", direction="in", schema="SiteMetadata"),
        AtomPort(name="glm_results", direction="out", schema="GLMResults"),
    ],
    reference="lme4: Bates et al. 2015, JSS",
    tags=["analysis", "multi_site", "mixed_effects"],
)

SITE_COVARIATE_GLM = MethodAtomTemplate(
    template_id="site_covariate_glm",
    name="Site-Covariate GLM",
    category=MethodAtomCategory.ANALYSIS,
    atom_type="first_level_glm",
    operation="site_covariate_glm",
    description="GLM with site as fixed-effect covariate",
    default_config={
        "site_as_covariate": True,
        "coding": "dummy",
        "reference_site": "auto",
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="design_matrix", direction="in", schema="DesignMatrix"),
        AtomPort(name="site_metadata", direction="in", schema="SiteMetadata"),
        AtomPort(name="glm_results", direction="out", schema="GLMResults"),
    ],
    tags=["analysis", "multi_site", "covariate"],
)

BATCH_EFFECT_DIAGNOSTICS = MethodAtomTemplate(
    template_id="batch_effect_diagnostics",
    name="Batch Effect Diagnostics",
    category=MethodAtomCategory.VALIDATION,
    atom_type="signal_qc",
    operation="batch_effect_diagnostics",
    description="Diagnose and visualize batch effects across sites",
    default_config={
        "methods": ["pca", "anova", "icc"],
        "significance_threshold": 0.05,
        "icc_threshold": 0.1,
    },
    ports=[
        AtomPort(name="haemoglobin", direction="in", schema="HaemoglobinData"),
        AtomPort(name="site_metadata", direction="in", schema="SiteMetadata"),
        AtomPort(name="diagnostics_report", direction="out", schema="DiagnosticsReport"),
    ],
    tags=["validation", "multi_site", "diagnostics"],
)


# ============================================================================
# ALL TEMPLATES
# ============================================================================

ALL_NODE_TEMPLATES: list[MethodAtomTemplate] = [
    # Data
    DATASET_DISCOVERY,
    BIDS_IMPORT,
    SNIRF_READER,
    RUN_READER,
    NIRX_READER,
    HITACHI_READER,
    ISS_READER,
    TECHEN_READER,
    KERNEL_READER,
    LOCALIZATION_PROJECTION_IMPORT,
    NIRS_SPM_SURFACE_PROJECTION,
    # Design
    STUDY_DESIGN,
    EVENT_EXTRACTION,
    DESIGN_MATRIX,
    # Preprocessing - Motion Correction
    OPTICAL_DENSITY,
    TDDR_MOTION,
    SPLINE_MOTION,
    WAVELET_MOTION,
    ICA_MOTION,
    PCA_MOTION,
    MARA_MOTION,
    CBSI_MOTION,
    RLS_ADAPTIVE_FILTER,
    KALMAN_FILTER,
    BLOCK_REJECTION,
    # Preprocessing - Filtering
    BANDPASS_FILTER,
    NOTCH_FILTER,
    LOWPASS_FILTER,
    # Preprocessing - Conversion & Regression
    BEER_LAMBERT,
    SHORT_CHANNEL_REGRESSION,
    SYSTEMIC_PHYSIOLOGY_REGRESSION,
    NUISANCE_REGRESSION,
    BAD_CHANNEL_DETECTION,
    # QC
    QC_METRICS,
    SCI_CHECK,
    CV_CHECK,
    SNR_CHECK,
    # Analysis - GLM
    FIRST_LEVEL_GLM,
    CONTRAST,
    MULTIPLE_COMPARISON_CORRECTION,
    NUISANCE_GLM,
    BLOCK_AVERAGING,
    # Analysis - Connectivity
    CONNECTIVITY_ANALYSIS,
    PLV_CONNECTIVITY,
    COHERENCE_CONNECTIVITY,
    WTC_CONNECTIVITY,
    GRANGER_CAUSALITY,
    GRAPH_THEORY,
    # Analysis - Hyperscanning
    INTER_BRAIN_CONNECTIVITY,
    # Analysis - ML
    FEATURE_EXTRACTION,
    FEATURE_SELECTION,
    ML_MODEL,
    SVM_MODEL,
    LDA_MODEL,
    CNN_MODEL,
    LSTM_MODEL,
    TRANSFORMER_MODEL,
    DECISION_TREE_MODEL,
    CROSS_VALIDATION,
    # Output
    CHANNEL_OUTPUT,
    ROI_OUTPUT,
    GROUP_SUMMARY,
    # Validation
    REPORTING_CHECKLIST,
    RISK_REGISTER,
    # Export
    PACKAGE_EXPORT,
    METHODS_REPORT,
    # Multi-Site Regression
    SITE_METADATA_EXTRACTION,
    SITE_LEVEL_QC,
    COMBAT_HARMONIZATION,
    LINEAR_MIXED_EFFECTS_GLM,
    SITE_COVARIATE_GLM,
    BATCH_EFFECT_DIAGNOSTICS,
]

# ============================================================================
# CEDALION BACKEND TEMPLATES
# ============================================================================

CEDALION_SNIRF_READER = MethodAtomTemplate(
    template_id="cedalion_snirf_reader",
    name="Cedalion SNIRF Reader",
    category=MethodAtomCategory.DATA,
    atom_type="data_import",
    operation="snirf_reader",
    description="Read SNIRF format fNIRS data files using Cedalion backend",
    default_config={"preload": False},
    ports=[
        AtomPort(name="file_path", direction="in", schema="FilePath"),
        AtomPort(name="raw_data", direction="out", schema="RawData"),
    ],
    reference="Cedalion: cedalion.io.read_snirf",
    tags=["data", "snirf", "cedalion"],
    backend_binding=BackendBinding(
        backend_id="cedalion",
        operation="snirf_read",
        version_spec=">=26.5,<27",
    ),
)

CEDALION_OPTICAL_DENSITY = MethodAtomTemplate(
    template_id="cedalion_optical_density",
    name="Cedalion Optical Density",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="optical_density",
    operation="optical_density",
    description="Convert intensity to optical density using Cedalion backend",
    default_config={"nonpositive_policy": "nan"},
    ports=[
        AtomPort(name="raw_data", direction="in", schema="RawData"),
        AtomPort(name="od_data", direction="out", schema="OpticalDensityData"),
    ],
    reference="Cedalion: cedalion.nirs.cw.int2od",
    tags=["preprocessing", "optical_density", "cedalion"],
    backend_binding=BackendBinding(
        backend_id="cedalion",
        operation="int2od",
        version_spec=">=26.5,<27",
    ),
)

CEDALION_BEER_LAMBERT = MethodAtomTemplate(
    template_id="cedalion_beer_lambert",
    name="Cedalion Beer-Lambert Law",
    category=MethodAtomCategory.PREPROCESSING,
    atom_type="beer_lambert_law",
    operation="beer_lambert_law",
    description="Convert optical density to haemoglobin concentration using Cedalion backend",
    default_config={"ppf": 6.0, "spectrum": "prahl"},
    ports=[
        AtomPort(name="od_data", direction="in", schema="OpticalDensityData"),
        AtomPort(name="hb_data", direction="out", schema="HaemoglobinData"),
    ],
    reference="Cedalion: cedalion.nirs.cw.od2conc",
    tags=["preprocessing", "beer_lambert", "cedalion"],
    backend_binding=BackendBinding(
        backend_id="cedalion",
        operation="od2conc",
        version_spec=">=26.5,<27",
    ),
)

# Add Cedalion templates to ALL_NODE_TEMPLATES
ALL_NODE_TEMPLATES.extend([
    CEDALION_SNIRF_READER,
    CEDALION_OPTICAL_DENSITY,
    CEDALION_BEER_LAMBERT,
])


# ============================================================================
# PARTICIPANT METADATA AND GROUP-SCOPE TEMPLATES
# ============================================================================

PARTICIPANT_TABLE_INPUT = MethodAtomTemplate(
    template_id="participant_table_input",
    name="Participant Table Input",
    category=MethodAtomCategory.DATA,
    atom_type="participant_table_input",
    operation="participant_table_input",
    description="Read CSV/TSV/BIDS participants.tsv into a typed participant metadata table",
    default_config={
        "path": "",
        "id_column": "participant_id",
        "include_column": "include",
        "delimiter": "auto",
        "encoding": "utf-8-sig",
        "execution_scope": "group",
        "readiness_status": "needs_attention",
    },
    ports=[
        AtomPort(name="table_file", direction="in", schema="FilePath"),
        AtomPort(name="participant_table", direction="out", schema="ParticipantTable"),
        AtomPort(name="column_role_map", direction="out", schema="ColumnRoleMap"),
        AtomPort(name="validation_report", direction="out", schema="TableValidationReport"),
    ],
    tags=["metadata", "participant", "group", "ml", "site"],
)

PARTICIPANT_METADATA_VALIDATE = MethodAtomTemplate(
    template_id="participant_metadata_validate",
    name="Participant Metadata Validate",
    category=MethodAtomCategory.VALIDATION,
    atom_type="participant_metadata_validate",
    operation="participant_metadata_validate",
    description="Validate participant metadata coverage, duplicates, include flags, and dataset joins",
    default_config={"execution_scope": "group", "readiness_status": "needs_attention"},
    ports=[
        AtomPort(name="participant_table", direction="in", schema="ParticipantTable"),
        AtomPort(name="data_manifest", direction="in", schema="DataManifest"),
        AtomPort(name="validated_participant_table", direction="out", schema="ValidatedParticipantTable"),
        AtomPort(name="join_preview", direction="out", schema="ParticipantJoinPreview"),
    ],
    tags=["metadata", "validation", "participant", "group"],
)

GROUP_DESIGN_MATRIX = MethodAtomTemplate(
    template_id="group_design_matrix",
    name="Group Design Matrix",
    category=MethodAtomCategory.DESIGN,
    atom_type="group_design_matrix",
    operation="group_design_matrix",
    description="Compile an SPM-style group-level design matrix from annotated subject results",
    default_config={
        "design_type": "two_sample_t",
        "group_column": "group",
        "covariates": [],
        "execution_scope": "group",
        "readiness_status": "needs_attention",
    },
    ports=[
        AtomPort(name="annotated_subject_results", direction="in", schema="AnnotatedSubjectResults"),
        AtomPort(name="group_design_matrix", direction="out", schema="GroupDesignMatrix"),
        AtomPort(name="analysis_table", direction="out", schema="AnalysisTable"),
    ],
    tags=["group", "design", "spm"],
)

PARTICIPANT_LABEL_PROJECTION = MethodAtomTemplate(
    template_id="participant_label_projection",
    name="Participant Label Projection",
    category=MethodAtomCategory.DATA,
    atom_type="participant_label_projection",
    operation="participant_label_projection",
    description="Project a participant table column to ML labels and subject IDs",
    default_config={"label_column": "group", "execution_scope": "group", "readiness_status": "needs_attention"},
    ports=[
        AtomPort(name="participant_table", direction="in", schema="ParticipantTable"),
        AtomPort(name="labels", direction="out", schema="LabelVector"),
        AtomPort(name="subject_ids", direction="out", schema="SubjectIDs"),
    ],
    tags=["metadata", "machine_learning", "labels"],
)

PARTICIPANT_SITE_PROJECTION = MethodAtomTemplate(
    template_id="participant_site_projection",
    name="Participant Site Projection",
    category=MethodAtomCategory.DATA,
    atom_type="participant_site_projection",
    operation="participant_site_projection",
    description="Project participant metadata into site and scanner metadata for multisite analysis",
    default_config={"site_column": "site", "execution_scope": "group", "readiness_status": "needs_attention"},
    ports=[
        AtomPort(name="participant_table", direction="in", schema="ParticipantTable"),
        AtomPort(name="site_metadata", direction="out", schema="SiteMetadata"),
        AtomPort(name="batch_labels", direction="out", schema="BatchLabels"),
    ],
    tags=["metadata", "site", "combat"],
)

OBSERVATION_PAIRING_PROJECTION = MethodAtomTemplate(
    template_id="observation_pairing_projection",
    name="Observation Pairing Projection",
    category=MethodAtomCategory.DATA,
    atom_type="observation_pairing_projection",
    operation="observation_pairing_projection",
    description="Project observation rows into paired, repeated-measures, or dyad structures",
    default_config={"execution_scope": "group", "readiness_status": "needs_attention"},
    ports=[
        AtomPort(name="observation_table", direction="in", schema="ObservationTable"),
        AtomPort(name="pairing_structure", direction="out", schema="PairingStructure"),
        AtomPort(name="dyad_structure", direction="out", schema="DyadStructure"),
    ],
    tags=["metadata", "paired", "repeated_measures", "hyperscanning"],
)

ALL_NODE_TEMPLATES.extend([
    PARTICIPANT_TABLE_INPUT,
    PARTICIPANT_METADATA_VALIDATE,
    GROUP_DESIGN_MATRIX,
    PARTICIPANT_LABEL_PROJECTION,
    PARTICIPANT_SITE_PROJECTION,
    OBSERVATION_PAIRING_PROJECTION,
])
