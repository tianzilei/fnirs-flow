"""Evidence-backed configuration manager for fnirs-flow.

Loads and manages parameter presets derived from literature extraction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fnirs_flow.registry.acquisition_presets import get_builtin_acquisition_preset


class AcquisitionConfig(BaseModel):
    """Acquisition configuration derived from literature."""

    device_brand_model: str = ""
    wavelengths_nm: list[int] = Field(default_factory=lambda: [760, 850])
    source_detector_distance_mm: int | None = 30
    short_channel_distance_mm: int | None = 8
    sampling_rate_hz: float = 10.0
    # Shimadzu OMM metadata.  These fields are deliberately separate from
    # ``wavelengths_nm``: the values shown in the OMM AnalysisInfo "Applied
    # Voltage" table are source drive voltages, not optical wavelengths.
    applied_voltage: list[float] = Field(default_factory=list)
    amp_gain: list[str] = Field(default_factory=list)
    collection_interval_ms: float | None = None
    get_data_time_ms: float | None = None
    average: int | None = None
    data_format: str = ""
    condition_file: str = ""
    protocol: str = ""
    measurement_mode: str = ""
    gain_change: str = ""
    task_change: bool | None = None
    hb_calculation_formula_id: str = ""
    hb_calculation_coefficients: dict[str, Any] = Field(default_factory=dict)


class PreprocessingConfig(BaseModel):
    """Preprocessing configuration derived from literature."""

    sequence: list[str] = Field(
        default_factory=lambda: [
            "optical_density",
            "bandpass_filter",
            "motion_correction",
            "beer_lambert_law",
        ]
    )
    filter_l_freq: float = 0.01
    filter_h_freq: float = 0.2
    filter_method: str = "fir"
    motion_correction_method: str = "tddr"
    motion_correction_params: dict[str, Any] = Field(default_factory=dict)
    short_channel_regression: bool = False
    short_channel_threshold: float = 0.01


class QCConfig(BaseModel):
    """QC configuration derived from literature."""

    sci_threshold: float = 0.8
    cv_threshold: float = 0.15
    snr_threshold: float = 2.0
    sd_distance_min_mm: float = 10.0
    sd_distance_max_mm: float = 50.0
    max_bad_channel_percentage: float = 30.0


class AnalysisConfig(BaseModel):
    """Analysis configuration derived from literature."""

    scenario: str = "task"
    hrf_model: str = "canonical"
    drift_model: str = "polynomial"
    drift_order: int = 3
    connectivity_method: str = "pearson"
    fisher_z_transform: bool = True
    frequency_band: list[float] = Field(default_factory=lambda: [0.01, 0.1])
    multiple_comparison_method: str = "fdr"
    multiple_comparison_alpha: float = 0.05


class MLConfig(BaseModel):
    """ML configuration with leakage prevention."""

    split_strategy: str = "subject_wise"
    cv_scheme: str = "leave_one_out"
    cv_folds: int = 5
    nested_cv: bool = True
    preprocessing_in_fold: bool = True
    validation_unit: str = "subject"
    model_type: str = "svm"
    features: list[str] = Field(
        default_factory=lambda: [
            "mean",
            "std",
            "variance",
            "skewness",
            "kurtosis",
            "connectivity",
            "correlation",
            "entropy",
        ]
    )
    prohibited_strategies: list[str] = Field(default_factory=lambda: ["random_trial_split", "random_window_split"])


class EvidenceBackedConfig(BaseModel):
    """Complete evidence-backed configuration."""

    acquisition: AcquisitionConfig = Field(default_factory=AcquisitionConfig)
    preprocessing: PreprocessingConfig = Field(default_factory=PreprocessingConfig)
    qc: QCConfig = Field(default_factory=QCConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    ml: MLConfig = Field(default_factory=MLConfig)


class ConfigManager:
    """Manages evidence-backed configurations."""

    def __init__(self, config_dir: Path | str | None = None):
        """Initialize configuration manager.

        Args:
            config_dir: Directory containing configuration files
        """
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent / "configs"
        self._config_dir = Path(config_dir)
        self._presets: dict[str, dict[str, Any]] = {}
        self._load_presets()

    def _load_presets(self) -> None:
        """Load presets from configuration files."""
        preset_file = self._config_dir / "evidence_backed_presets.json"
        if preset_file.exists():
            with open(preset_file, encoding="utf-8") as f:
                data = json.load(f)
                self._presets = data.get("presets", {})

    def get_acquisition_config(
        self,
        device: str = "standard_cw_fnirs",
    ) -> AcquisitionConfig:
        """Get acquisition configuration for a device.

        Args:
            device: Device name (e.g., 'standard_cw_fnirs', 'nirx_nirscout')

        Returns:
            Acquisition configuration
        """
        acq_presets = self._presets.get("acquisition", {})
        preset = acq_presets.get(device)
        if preset is None:
            preset = get_builtin_acquisition_preset(device)
        if preset is None:
            preset = acq_presets.get("standard_cw_fnirs", {})

        return AcquisitionConfig(
            device_brand_model=preset.get("device_brand_model", ""),
            wavelengths_nm=preset.get("wavelengths_nm", [760, 850]),
            source_detector_distance_mm=preset.get("source_detector_distance_mm", 30),
            short_channel_distance_mm=preset.get("short_channel_distance_mm", 8),
            sampling_rate_hz=preset.get("sampling_rate_hz", 10.0),
            applied_voltage=preset.get("applied_voltage", []),
            amp_gain=preset.get("amp_gain", []),
            collection_interval_ms=preset.get("collection_interval_ms"),
            get_data_time_ms=preset.get("get_data_time_ms"),
            average=preset.get("average"),
            data_format=preset.get("data_format", ""),
            condition_file=preset.get("condition_file", ""),
            protocol=preset.get("protocol", ""),
            measurement_mode=preset.get("measurement_mode", ""),
            gain_change=preset.get("gain_change", ""),
            task_change=preset.get("task_change"),
            hb_calculation_formula_id=preset.get("hb_calculation_formula_id", ""),
            hb_calculation_coefficients=preset.get("hb_calculation_coefficients", {}),
        )

    def get_preprocessing_config(
        self,
        scenario: str = "task",
        motion_correction: str = "tddr",
    ) -> PreprocessingConfig:
        """Get preprocessing configuration for a scenario.

        Args:
            scenario: Analysis scenario ('task' or 'resting_state')
            motion_correction: Motion correction method

        Returns:
            Preprocessing configuration
        """
        pp_presets = self._presets.get("preprocessing", {})

        if scenario == "resting_state":
            preset = pp_presets.get("standard_resting_pipeline", {})
        else:
            preset = pp_presets.get("standard_task_pipeline", {})

        filter_config = preset.get("filter", {})

        return PreprocessingConfig(
            sequence=preset.get("sequence", []),
            filter_l_freq=filter_config.get("l_freq", 0.01),
            filter_h_freq=filter_config.get("h_freq", 0.2),
            filter_method=filter_config.get("method", "fir"),
            motion_correction_method=motion_correction,
            short_channel_regression=(scenario == "resting_state"),
        )

    def get_qc_config(
        self,
        strictness: str = "conservative",
    ) -> QCConfig:
        """Get QC configuration.

        Args:
            strictness: QC strictness level ('conservative' or 'relaxed')

        Returns:
            QC configuration
        """
        qc_presets = self._presets.get("qc", {})
        preset = qc_presets.get(strictness, qc_presets.get("conservative", {}))

        return QCConfig(
            sci_threshold=preset.get("sci_threshold", 0.8),
            cv_threshold=preset.get("cv_threshold", 0.15),
            snr_threshold=preset.get("snr_threshold", 2.0),
            sd_distance_min_mm=preset.get("sd_distance_min_mm", 10.0),
            sd_distance_max_mm=preset.get("sd_distance_max_mm", 50.0),
        )

    def get_analysis_config(
        self,
        scenario: str = "task",
    ) -> AnalysisConfig:
        """Get analysis configuration for a scenario.

        Args:
            scenario: Analysis scenario ('task', 'resting_state', etc.)

        Returns:
            Analysis configuration
        """
        ana_presets = self._presets.get("analysis", {})

        if scenario == "resting_state":
            preset = ana_presets.get("resting_connectivity", {})
            return AnalysisConfig(
                scenario=scenario,
                connectivity_method=preset.get("method", "pearson"),
                fisher_z_transform=preset.get("fisher_z_transform", True),
                frequency_band=preset.get("frequency_band", [0.01, 0.1]),
            )
        else:
            preset = ana_presets.get("task_glm", {})
            return AnalysisConfig(
                scenario=scenario,
                hrf_model=preset.get("hrf_model", "canonical"),
                drift_model=preset.get("drift_model", "polynomial"),
                drift_order=preset.get("drift_order", 3),
            )

    def get_ml_config(
        self,
        model_type: str = "svm",
        cv_scheme: str = "leave_one_out",
    ) -> MLConfig:
        """Get ML configuration with leakage prevention.

        Args:
            model_type: ML model type
            cv_scheme: Cross-validation scheme

        Returns:
            ML configuration with leakage-safe settings
        """
        ml_presets = self._presets.get("ml", {})
        leakage_config = ml_presets.get("leakage_safe_config", {})
        features_config = ml_presets.get("common_features", {})

        return MLConfig(
            split_strategy=leakage_config.get("split_strategy", "subject_wise"),
            cv_scheme=cv_scheme,
            cv_folds=5,
            nested_cv=leakage_config.get("nested_cv", True),
            preprocessing_in_fold=leakage_config.get("preprocessing_in_fold", True),
            validation_unit=leakage_config.get("validation_unit", "subject"),
            model_type=model_type,
            features=features_config.get(
                "features",
                [
                    "mean",
                    "std",
                    "variance",
                    "skewness",
                    "kurtosis",
                    "connectivity",
                    "correlation",
                    "entropy",
                ],
            ),
        )

    def get_full_config(
        self,
        scenario: str = "task",
        device: str = "standard_cw_fnirs",
        motion_correction: str = "tddr",
        qc_strictness: str = "conservative",
        ml_model: str = "svm",
    ) -> EvidenceBackedConfig:
        """Get complete evidence-backed configuration.

        Args:
            scenario: Analysis scenario
            device: Device type
            motion_correction: Motion correction method
            qc_strictness: QC strictness level
            ml_model: ML model type

        Returns:
            Complete configuration
        """
        return EvidenceBackedConfig(
            acquisition=self.get_acquisition_config(device),
            preprocessing=self.get_preprocessing_config(scenario, motion_correction),
            qc=self.get_qc_config(qc_strictness),
            analysis=self.get_analysis_config(scenario),
            ml=self.get_ml_config(ml_model),
        )

    def get_motion_correction_info(self) -> list[dict[str, Any]]:
        """Get information about available motion correction methods.

        Returns:
            List of motion correction methods with evidence
        """
        pp_presets = self._presets.get("preprocessing", {})
        ranking = pp_presets.get("motion_correction_ranking", {})
        result: list[dict[str, Any]] = ranking.get("methods", [])
        return result

    def get_device_list(self) -> list[str]:
        """Get list of available device configurations.

        Returns:
            List of device names
        """
        acq_presets = self._presets.get("acquisition", {})
        return list(acq_presets.keys())

    def get_scenario_list(self) -> list[str]:
        """Get list of available scenarios.

        Returns:
            List of scenario names
        """
        return ["task", "resting_state", "hyperscanning", "machine_learning", "real_world"]
