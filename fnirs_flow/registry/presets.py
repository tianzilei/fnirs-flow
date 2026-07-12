"""Parameter presets: pre-configured parameter sets for common workflows."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ParameterPreset(BaseModel):
    preset_id: str
    name: str
    domain: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    reference: str = ""
    recommended_sensitivity: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PresetLibrary:
    def __init__(self) -> None:
        self._presets: dict[str, ParameterPreset] = {}

    def register(self, preset: ParameterPreset) -> None:
        self._presets[preset.preset_id] = preset

    def get(self, preset_id: str) -> ParameterPreset | None:
        return self._presets.get(preset_id)

    def by_domain(self, domain: str) -> list[ParameterPreset]:
        return [p for p in self._presets.values() if p.domain == domain]

    def all_ids(self) -> list[str]:
        return sorted(self._presets.keys())


# Built-in presets
BUILTIN_PRESETS: list[ParameterPreset] = [
    ParameterPreset(
        preset_id="conservative_qc",
        name="Conservative QC",
        domain="qc",
        parameters={
            "sci_threshold": 0.8,
            "sd_distance_min": 0.01,
            "sd_distance_max": 0.08,
            "snr_threshold": 2.0,
        },
        rationale="Conservative quality thresholds for high-quality data",
        warnings=["May exclude more channels than standard thresholds"],
    ),
    ParameterPreset(
        preset_id="standard_task_glm",
        name="Standard Task GLM",
        domain="analysis",
        parameters={
            "hrf_model": "canonical",
            "drift_model": "polynomial",
            "drift_order": 3,
        },
        rationale="Standard GLM parameters for task-based fNIRS",
    ),
    ParameterPreset(
        preset_id="tddr_motion",
        name="TDDR Motion Correction",
        domain="preprocessing",
        parameters={
            "method": "tddr",
            "iterations": 50,
        },
        rationale="Robust motion correction without user parameters",
        reference="MNE-NIRS TDDR implementation",
    ),
    ParameterPreset(
        preset_id="basic_bandpass",
        name="Basic Bandpass Filter",
        domain="preprocessing",
        parameters={
            "l_freq": 0.01,
            "h_freq": 0.2,
            "method": "fir",
            "fir_design": "firwin",
        },
        rationale="Standard bandpass filter for task-based fNIRS",
        warnings=["May need adjustment for resting-state or high-frequency analysis"],
    ),
    ParameterPreset(
        preset_id="short_channel_regression",
        name="Short-Channel Regression",
        domain="preprocessing",
        parameters={
            "short_channel_threshold": 0.01,
            "regression_method": "linear",
        },
        rationale="Remove systemic physiological noise using short-separation channels",
        warnings=["Requires short-separation channels in the montage"],
    ),
    ParameterPreset(
        preset_id="resting_state_bandpass",
        name="Resting-State Bandpass Filter",
        domain="preprocessing",
        parameters={
            "l_freq": 0.01,
            "h_freq": 0.1,
            "method": "fir",
            "fir_design": "firwin",
        },
        rationale="Standard bandpass filter for resting-state connectivity analysis",
        warnings=["Frequency band may need adjustment for specific connectivity analyses"],
    ),
    ParameterPreset(
        preset_id="real_world_qc",
        name="Real-World QC",
        domain="qc",
        parameters={
            "sci_threshold": 0.7,
            "sd_distance_min": 0.01,
            "sd_distance_max": 0.08,
            "motion_threshold": 0.1,
        },
        rationale="Relaxed QC thresholds for real-world/free movement recordings",
        warnings=["Lower SCI threshold due to motion artifacts in naturalistic settings"],
    ),
    ParameterPreset(
        preset_id="ml_leakage_safe",
        name="ML Leakage-Safe Settings",
        domain="analysis",
        parameters={
            "split_strategy": "subject_wise",
            "cv_folds": 5,
            "nested_cv": True,
            "preprocessing_in_fold": True,
        },
        rationale="Settings that prevent data leakage in ML analysis",
        warnings=["Always use subject-wise or group-wise splits for fNIRS ML"],
    ),
    # Multi-site presets
    ParameterPreset(
        preset_id="combat_default",
        name="ComBat Harmonization",
        domain="multi_site",
        parameters={
            "method": "combat",
            "eb": True,
            "parametric": True,
            "preserve_biological": True,
            "covariates": [],
        },
        rationale="Standard ComBat harmonization for removing site effects",
        reference="Johnson et al. 2007, NeuroImage",
        warnings=[
            "Requires sufficient subjects per site (>= 5 recommended)",
            "May attenuate biological signals if site is confounded with outcome",
        ],
        recommended_sensitivity=["mixed_effects_comparison", "covariate_comparison"],
    ),
    ParameterPreset(
        preset_id="mixed_effects_site",
        name="Mixed-Effects Site Model",
        domain="multi_site",
        parameters={
            "random_effects": ["site"],
            "random_intercept": True,
            "random_slope": False,
            "covariance_structure": "unstructured",
            "reml": True,
        },
        rationale="Linear mixed-effects model with site as random intercept",
        reference="Bates et al. 2015, JSS",
        warnings=[
            "Requires lme4 or equivalent mixed-effects library",
            "Convergence issues possible with small site counts",
        ],
        recommended_sensitivity=["combat_comparison", "site_covariate_comparison"],
    ),
    ParameterPreset(
        preset_id="site_covariate_fixed",
        name="Site as Fixed Covariate",
        domain="multi_site",
        parameters={
            "site_as_covariate": True,
            "coding": "dummy",
            "reference_site": "auto",
        },
        rationale="Include site as fixed-effect covariate in GLM",
        warnings=[
            "Loses one degree of freedom per additional site",
            "Assumes site effect is constant across conditions",
        ],
        recommended_sensitivity=["mixed_effects_comparison", "combat_comparison"],
    ),
    ParameterPreset(
        preset_id="site_qc_strict",
        name="Strict Site-Level QC",
        domain="multi_site",
        parameters={
            "metrics": ["mean_intensity", "snr", "sci_pass_rate", "channel_dropout_rate"],
            "outlier_threshold": 1.5,
            "min_subjects_per_site": 8,
            "max_site_dropout_rate": 0.2,
        },
        rationale="Strict QC thresholds for multi-site studies",
        warnings=[
            "May exclude entire sites with poor data quality",
            "Verify site exclusion does not introduce selection bias",
        ],
    ),
    # Evidence-derived presets from literature extraction
    ParameterPreset(
        preset_id="ica_motion",
        name="ICA Motion Correction",
        domain="preprocessing",
        parameters={
            "method": "ica",
            "n_components": None,
            "threshold": 3.0,
        },
        rationale="Most commonly reported motion correction method (405 studies)",
        reference="Virtanen et al. 2019; Chiarelli et al. 2018",
        warnings=[
            "ICA component selection may require manual inspection",
            "Not all components may be motion-related",
        ],
    ),
    ParameterPreset(
        preset_id="wavelet_motion",
        name="Wavelet Motion Correction",
        domain="preprocessing",
        parameters={
            "method": "wavelet",
            "wavelet_level": 5,
            "threshold_type": "soft",
        },
        rationale="Second most common motion correction method (339 studies)",
        reference="Molavi & Dumont 2012; HOMER3",
        warnings=[
            "Wavelet level may need adjustment for different sampling rates",
        ],
    ),
    ParameterPreset(
        preset_id="spline_motion",
        name="Spline Motion Correction",
        domain="preprocessing",
        parameters={
            "method": "spline",
            "spline_segments": 3,
            "threshold": 1.0,
        },
        rationale="Widely used automated motion correction (95 studies)",
        reference="Scholkmann et al. 2010; HOMER3",
    ),
    ParameterPreset(
        preset_id="pca_motion",
        name="PCA Motion Correction",
        domain="preprocessing",
        parameters={
            "method": "pca",
            "n_components": 0.95,
            "threshold": 3.0,
        },
        rationale="Data-driven motion correction (56 studies)",
        reference="Yücel et al. 2014; HOMER3",
        warnings=[
            "Number of components to retain may need tuning",
        ],
    ),
    ParameterPreset(
        preset_id="mara_motion",
        name="MARA Motion Correction",
        domain="preprocessing",
        parameters={
            "method": "mara",
            "spline_segments": 3,
            "wavelet_level": 5,
        },
        rationale="Hybrid spline-wavelet approach (60 studies)",
        reference="Scholkmann et al. 2010",
    ),
    ParameterPreset(
        preset_id="bandpass_task",
        name="Task Bandpass Filter",
        domain="preprocessing",
        parameters={
            "l_freq": 0.01,
            "h_freq": 0.2,
            "method": "fir",
            "fir_design": "firwin",
        },
        rationale="Standard bandpass for task-based fNIRS (97 studies report band-pass)",
        reference="MNE-Python: mne.filter.filter_data",
    ),
    ParameterPreset(
        preset_id="bandpass_resting",
        name="Resting-State Bandpass Filter",
        domain="preprocessing",
        parameters={
            "l_freq": 0.01,
            "h_freq": 0.1,
            "method": "fir",
            "fir_design": "firwin",
        },
        rationale="Standard bandpass for resting-state connectivity",
        reference="MNE-Python: mne.filter.filter_data",
        warnings=["Frequency band may need adjustment for specific connectivity analyses"],
    ),
    ParameterPreset(
        preset_id="pearson_connectivity",
        name="Pearson Correlation Connectivity",
        domain="analysis",
        parameters={
            "method": "pearson",
            "fisher_z_transform": True,
        },
        rationale="Most common connectivity metric (29/45 hyperscanning studies)",
    ),
    ParameterPreset(
        preset_id="plv_connectivity",
        name="Phase Locking Value Connectivity",
        domain="analysis",
        parameters={
            "method": "plv",
            "frequency_band": [0.01, 0.1],
            "n_surrogate": 100,
        },
        rationale="Phase synchronization measure independent of amplitude",
        reference="Lachaux et al. 1999",
    ),
    ParameterPreset(
        preset_id="wtc_connectivity",
        name="Wavelet Transform Coherence",
        domain="analysis",
        parameters={
            "method": "wtc",
            "mother_wavelet": "morlet",
            "omega0": 6,
        },
        rationale="Time-frequency connectivity for non-stationary signals",
        reference="Grinsted et al. 2004",
    ),
    ParameterPreset(
        preset_id="leave_one_out_cv",
        name="Leave-One-Out Cross-Validation",
        domain="analysis",
        parameters={
            "cv_strategy": "leave_one_out",
            "nested": True,
            "preprocessing_in_fold": True,
        },
        rationale="Gold standard CV for small-sample fNIRS ML (23 studies)",
        warnings=["Computationally expensive for large datasets"],
    ),
    ParameterPreset(
        preset_id="nested_cv",
        name="Nested Cross-Validation",
        domain="analysis",
        parameters={
            "outer_folds": 5,
            "inner_folds": 5,
            "preprocessing_in_fold": True,
        },
        rationale="Unbiased ML performance estimation (11 studies)",
        reference="scikit-learn: cross_val_score with GridSearchCV",
    ),
    ParameterPreset(
        preset_id="fdr_correction",
        name="FDR Multiple Comparison Correction",
        domain="analysis",
        parameters={
            "method": "fdr",
            "alpha": 0.05,
            "fdr_method": "indep",
        },
        rationale="Standard multiple comparison correction",
        reference="Benjamini & Hochberg 1995",
    ),
    # Evidence-backed acquisition presets
    ParameterPreset(
        preset_id="standard_cw_fnirs",
        name="Standard CW-fNIRS Acquisition",
        domain="acquisition",
        parameters={
            "wavelengths_nm": [760, 850],
            "source_detector_distance_mm": 30,
            "short_channel_distance_mm": 8,
            "sampling_rate_hz": 10,
        },
        rationale="Most common CW-fNIRS acquisition parameters from literature",
        warnings=["Sampling rate often not reported; verify from raw data"],
    ),
    ParameterPreset(
        preset_id="nirx_nirscout_defaults",
        name="NIRx NIRScout Defaults",
        domain="acquisition",
        parameters={
            "device_brand_model": "NIRScout",
            "wavelengths_nm": [760, 850],
            "source_detector_distance_mm": 30,
            "short_channel_distance_mm": 8,
        },
        rationale="NIRx NIRScout system defaults (66 studies)",
    ),
    ParameterPreset(
        preset_id="hitachi_etg4000_defaults",
        name="Hitachi ETG-4000 Defaults",
        domain="acquisition",
        parameters={
            "device_brand_model": "ETG-4000",
            "wavelengths_nm": [695, 830],
            "source_detector_distance_mm": 30,
        },
        rationale="Hitachi ETG-4000 system defaults (58 studies)",
    ),
]
