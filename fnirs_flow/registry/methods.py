"""Method definitions: reusable method templates derived from evidence."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MethodDefinition(BaseModel):
    method_id: str
    name: str
    domain: str  # preprocessing, analysis, qc, reporting
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    reference: str = ""


class MethodLibrary:
    def __init__(self) -> None:
        self._methods: dict[str, MethodDefinition] = {}

    def register(self, method: MethodDefinition) -> None:
        self._methods[method.method_id] = method

    def get(self, method_id: str) -> MethodDefinition | None:
        return self._methods.get(method_id)

    def by_domain(self, domain: str) -> list[MethodDefinition]:
        return [m for m in self._methods.values() if m.domain == domain]

    def all_ids(self) -> list[str]:
        return sorted(self._methods.keys())


# Built-in methods
BUILTIN_METHODS: list[MethodDefinition] = [
    MethodDefinition(
        method_id="optical_density",
        name="Optical Density Conversion",
        domain="preprocessing",
        description="Convert raw intensity to optical density using Beer-Lambert transform",
        parameters={"formula": "OD = -ln(I / mean(I))"},
        rationale="Standard preprocessing step for continuous-wave fNIRS",
        reference="MNE-NIRS: mne.preprocessing.nirs.optical_density",
    ),
    MethodDefinition(
        method_id="tddr_motion",
        name="Temporal Derivative Distribution Repair",
        domain="preprocessing",
        description="Motion artifact correction using robust temporal derivative estimation",
        parameters={"iterations": 50},
        rationale="Robust motion correction without user parameters",
        reference="MNE-NIRS: mne.preprocessing.nirs.temporal_derivative_distribution_repair",
    ),
    MethodDefinition(
        method_id="beer_lambert_law",
        name="Modified Beer-Lambert Law",
        domain="preprocessing",
        description="Convert optical density to haemoglobin concentration",
        parameters={"ppf": 6.0},
        rationale="Standard MBLL conversion for HbO/HbR estimation",
        reference="MNE-NIRS: mne.preprocessing.nirs.beer_lambert_law",
    ),
    MethodDefinition(
        method_id="scalp_coupling_index",
        name="Scalp Coupling Index",
        domain="qc",
        description="Quality metric based on cardiac signal correlation between wavelengths",
        parameters={"l_freq": 0.7, "h_freq": 1.5},
        rationale="Standard QC metric for fNIRS signal quality",
        reference="MNE-NIRS: mne.preprocessing.nirs.scalp_coupling_index",
    ),
    MethodDefinition(
        method_id="first_level_glm",
        name="First-Level GLM",
        domain="analysis",
        description="General linear model for task-related activation",
        parameters={"hrf_model": "canonical"},
        rationale="Standard approach for task-based fNIRS analysis",
        reference="MNE-NIRS: mne_nirs.signal_analysis.glm",
    ),
    # Evidence-derived methods from literature extraction
    MethodDefinition(
        method_id="ica_motion_correction",
        name="ICA Motion Correction",
        domain="preprocessing",
        description="Independent Component Analysis for motion artifact removal (405 studies)",
        parameters={"n_components": None, "threshold": 3.0},
        defaults={"n_components": "auto", "threshold": 3.0},
        rationale="Most commonly reported motion correction method in fNIRS literature",
        evidence_ids=["prep-ica-405"],
        reference="Virtanen et al. 2019; Chiarelli et al. 2018",
    ),
    MethodDefinition(
        method_id="wavelet_motion_correction",
        name="Wavelet Motion Correction",
        domain="preprocessing",
        description="Wavelet-based motion artifact correction (339 studies in literature)",
        parameters={"wavelet_level": 5, "threshold_type": "soft"},
        defaults={"wavelet_level": 5, "threshold_type": "soft"},
        rationale="Second most common motion correction method in fNIRS literature",
        evidence_ids=["prep-wavelet-339"],
        reference="Molavi & Dumont 2012; HOMER3: hmrR_MotionCorrectWavelet",
    ),
    MethodDefinition(
        method_id="spline_motion_correction",
        name="Spline Motion Correction",
        domain="preprocessing",
        description="Spline-based motion artifact correction (95 studies in literature)",
        parameters={"spline_segments": 3, "threshold": 1.0},
        defaults={"spline_segments": 3, "threshold": 1.0},
        rationale="Widely used motion correction with automated artifact detection",
        evidence_ids=["prep-spline-95"],
        reference="Scholkmann et al. 2010; HOMER3: hmrR_MotionCorrectSpline",
    ),
    MethodDefinition(
        method_id="pca_motion_correction",
        name="PCA Motion Correction",
        domain="preprocessing",
        description="Principal Component Analysis for motion artifact removal (56 studies)",
        parameters={"n_components": 0.95, "threshold": 3.0},
        defaults={"n_components": 0.95, "threshold": 3.0},
        rationale="Data-driven motion correction preserving signal variance",
        evidence_ids=["prep-pca-56"],
        reference="Yücel et al. 2014; HOMER3: hmrR_MotionCorrectPCA",
    ),
    MethodDefinition(
        method_id="mara_motion_correction",
        name="MARA Motion Correction",
        domain="preprocessing",
        description="Motion Artifact Reduction Algorithm combining spline and wavelet (60 studies)",
        parameters={"spline_segments": 3, "wavelet_level": 5},
        defaults={"spline_segments": 3, "wavelet_level": 5},
        rationale="Hybrid approach combining spline interpolation with wavelet filtering",
        evidence_ids=["prep-mara-60"],
        reference="Scholkmann et al. 2010",
    ),
    MethodDefinition(
        method_id="cbsi_motion_correction",
        name="CBSI Motion Correction",
        domain="preprocessing",
        description="Correlation-Based Signal Improvement for motion artifact correction",
        parameters={"method": "cbsi"},
        defaults={"method": "cbsi"},
        rationale="Uses HbO-HbR correlation to identify and correct motion artifacts",
        evidence_ids=["prep-cbsi-5"],
        reference="Cui et al. 2010; HOMER3: hmrR_MotionCorrectCBSI",
    ),
    MethodDefinition(
        method_id="bandpass_filter",
        name="Bandpass Filter",
        domain="preprocessing",
        description="Bandpass filter for fNIRS data (97 studies report band-pass filtering)",
        parameters={"l_freq": 0.01, "h_freq": 0.2, "method": "fir", "fir_design": "firwin"},
        defaults={"l_freq": 0.01, "h_freq": 0.2, "method": "fir"},
        rationale="Standard frequency filtering for task-based and resting-state fNIRS",
        evidence_ids=["prep-bandpass-97"],
        reference="MNE-Python: mne.filter.filter_data",
    ),
    MethodDefinition(
        method_id="notch_filter",
        name="Notch Filter",
        domain="preprocessing",
        description="Notch filter to remove line noise (13 studies report notch filtering)",
        parameters={"freqs": [50.0, 100.0], "method": "fir", "notch_widths": 2.0},
        defaults={"freqs": [50.0], "method": "fir"},
        rationale="Remove power line interference at 50/60 Hz",
        evidence_ids=["prep-notch-13"],
        reference="MNE-Python: mne.filter.notch_filter",
    ),
    MethodDefinition(
        method_id="short_channel_regression",
        name="Short-Channel Regression",
        domain="preprocessing",
        description="Remove systemic physiological noise using short-separation channels",
        parameters={"threshold": 0.01, "method": "linear"},
        defaults={"threshold": 0.01, "method": "linear"},
        rationale="Standard approach for removing superficial physiological noise",
        evidence_ids=["prep-short-channel-17"],
        reference="Gagnon et al. 2012; MNE-NIRS",
    ),
    MethodDefinition(
        method_id="block_averaging",
        name="Block/Trial Averaging",
        domain="analysis",
        description="Average haemodynamic responses across trials/blocks (78 studies)",
        parameters={
            "baseline_window": [-5, 0],
            "response_window": [0, 20],
            "baseline_correction": "mean",
        },
        defaults={"baseline_window": [-5, 0], "response_window": [0, 20]},
        rationale="Standard approach for extracting task-related haemodynamic responses",
        evidence_ids=["ana-block-averaging-78"],
        reference="HOMER3: hmrR_BlockAvg; MNE-NIRS",
    ),
    MethodDefinition(
        method_id="pearson_connectivity",
        name="Pearson Correlation Connectivity",
        domain="analysis",
        description="Pearson correlation for functional connectivity (most common in literature)",
        parameters={"method": "pearson", "fisher_z_transform": True},
        defaults={"method": "pearson", "fisher_z_transform": True},
        rationale="Standard connectivity metric for resting-state fNIRS",
        evidence_ids=["ana-fc-pearson"],
        reference="29/45 hyperscanning studies use Pearson correlation",
    ),
    MethodDefinition(
        method_id="plv_connectivity",
        name="Phase Locking Value",
        domain="analysis",
        description="Phase Locking Value for phase synchronization between channels",
        parameters={"method": "plv", "frequency_band": [0.01, 0.1]},
        defaults={"method": "plv"},
        rationale="Measures phase synchronization independent of amplitude",
        evidence_ids=["ana-plv"],
        reference="Lachaux et al. 1999",
    ),
    MethodDefinition(
        method_id="coherence_connectivity",
        name="Spectral Coherence",
        domain="analysis",
        description="Spectral coherence for frequency-domain connectivity",
        parameters={"method": "coherence", "frequency_band": [0.01, 0.1], "nperseg": 256},
        defaults={"method": "coherence"},
        rationale="Frequency-domain connectivity measure",
        evidence_ids=["ana-coherence"],
        reference="scipy.signal.coherence",
    ),
    MethodDefinition(
        method_id="wtc_connectivity",
        name="Wavelet Transform Coherence",
        domain="analysis",
        description="Wavelet Transform Coherence for time-frequency connectivity analysis",
        parameters={"method": "wtc", "mother_wavelet": "morlet", "omega0": 6},
        defaults={"method": "wtc", "mother_wavelet": "morlet"},
        rationale="Time-frequency connectivity analysis for non-stationary signals",
        evidence_ids=["ana-wtc"],
        reference="Grinsted et al. 2004",
    ),
    MethodDefinition(
        method_id="multiple_comparison_fdr",
        name="FDR Multiple Comparison Correction",
        domain="analysis",
        description="False Discovery Rate correction for multiple comparisons",
        parameters={"method": "fdr", "alpha": 0.05, "fdr_method": "indep"},
        defaults={"method": "fdr", "alpha": 0.05},
        rationale="Standard multiple comparison correction for channel-level analysis",
        evidence_ids=["ana-mcc-fdr"],
        reference="statsmodels: multipletests; Benjamini & Hochberg 1995",
    ),
    MethodDefinition(
        method_id="multiple_comparison_bonferroni",
        name="Bonferroni Multiple Comparison Correction",
        domain="analysis",
        description="Bonferroni correction for multiple comparisons (conservative)",
        parameters={"method": "bonferroni", "alpha": 0.05},
        defaults={"method": "bonferroni", "alpha": 0.05},
        rationale="Conservative multiple comparison correction",
        evidence_ids=["ana-mcc-bonferroni"],
        reference="statsmodels: multipletests",
    ),
    MethodDefinition(
        method_id="leave_one_out_cv",
        name="Leave-One-Out Cross-Validation",
        domain="analysis",
        description="Leave-One-Out cross-validation for ML (23 studies in literature)",
        parameters={"cv_strategy": "leave_one_out", "nested": True, "preprocessing_in_fold": True},
        defaults={"cv_strategy": "leave_one_out", "nested": True},
        rationale="Gold standard CV for small-sample fNIRS ML studies",
        evidence_ids=["ml-cv-loo-23"],
        reference="scikit-learn: LeaveOneOut; 23 studies report LOO CV",
    ),
    MethodDefinition(
        method_id="nested_cross_validation",
        name="Nested Cross-Validation",
        domain="analysis",
        description="Nested cross-validation for unbiased ML evaluation (11 studies)",
        parameters={"outer_folds": 5, "inner_folds": 5, "preprocessing_in_fold": True},
        defaults={"outer_folds": 5, "inner_folds": 5},
        rationale="Prevents optimistic bias in ML performance estimation",
        evidence_ids=["ml-cv-nested-11"],
        reference="scikit-learn: cross_val_score with GridSearchCV; 11 studies report nested CV",
    ),
    MethodDefinition(
        method_id="svm_classifier",
        name="SVM Classifier",
        domain="analysis",
        description="Support Vector Machine classifier for fNIRS classification",
        parameters={"kernel": "rbf", "cv_folds": 5, "split_strategy": "subject_wise"},
        defaults={"kernel": "rbf", "cv_folds": 5},
        rationale="Common classifier in fNIRS ML studies",
        evidence_ids=["ml-svm"],
        reference="scikit-learn: SVC",
    ),
    MethodDefinition(
        method_id="cnn_classifier",
        name="CNN Classifier",
        domain="analysis",
        description="Convolutional Neural Network for fNIRS classification",
        parameters={"architecture": "1d_cnn", "conv_layers": 3, "filters": [32, 64, 128]},
        defaults={"architecture": "1d_cnn", "conv_layers": 3},
        rationale="Deep learning approach for automatic feature extraction",
        evidence_ids=["ml-cnn"],
        reference="PyTorch/TensorFlow; >89.57% accuracy for MCI detection",
    ),
]
