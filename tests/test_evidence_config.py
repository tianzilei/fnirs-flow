"""Tests for evidence_config module."""

from __future__ import annotations

from pathlib import Path

from fnirs_flow.registry.evidence_config import (
    AcquisitionConfig,
    AnalysisConfig,
    ConfigManager,
    EvidenceBackedConfig,
    MLConfig,
    PreprocessingConfig,
    QCConfig,
)


class TestPydanticModels:
    """Tests for Pydantic configuration models."""

    def test_acquisition_config_defaults(self) -> None:
        """Test AcquisitionConfig default values."""
        config = AcquisitionConfig()
        assert config.wavelengths_nm == [760, 850]
        assert config.source_detector_distance_mm == 30
        assert config.short_channel_distance_mm == 8
        assert config.sampling_rate_hz == 10.0

    def test_acquisition_config_custom(self) -> None:
        """Test AcquisitionConfig with custom values."""
        config = AcquisitionConfig(
            device_brand_model="NIRX NIRScout",
            wavelengths_nm=[690, 830],
            sampling_rate_hz=12.5,
        )
        assert config.device_brand_model == "NIRX NIRScout"
        assert config.wavelengths_nm == [690, 830]
        assert config.sampling_rate_hz == 12.5

    def test_preprocessing_config_defaults(self) -> None:
        """Test PreprocessingConfig default values."""
        config = PreprocessingConfig()
        assert "optical_density" in config.sequence
        assert "bandpass_filter" in config.sequence
        assert config.filter_l_freq == 0.01
        assert config.filter_h_freq == 0.2
        assert config.motion_correction_method == "tddr"

    def test_qc_config_defaults(self) -> None:
        """Test QCConfig default values."""
        config = QCConfig()
        assert config.sci_threshold == 0.8
        assert config.cv_threshold == 0.15
        assert config.snr_threshold == 2.0
        assert config.sd_distance_min_mm == 10.0
        assert config.sd_distance_max_mm == 50.0

    def test_analysis_config_defaults(self) -> None:
        """Test AnalysisConfig default values."""
        config = AnalysisConfig()
        assert config.scenario == "task"
        assert config.hrf_model == "canonical"
        assert config.drift_model == "polynomial"
        assert config.drift_order == 3
        assert config.multiple_comparison_alpha == 0.05

    def test_ml_config_defaults(self) -> None:
        """Test MLConfig default values."""
        config = MLConfig()
        assert config.split_strategy == "subject_wise"
        assert config.cv_scheme == "leave_one_out"
        assert config.nested_cv
        assert config.preprocessing_in_fold
        assert "random_trial_split" in config.prohibited_strategies

    def test_evidence_backed_config_defaults(self) -> None:
        """Test EvidenceBackedConfig default values."""
        config = EvidenceBackedConfig()
        assert isinstance(config.acquisition, AcquisitionConfig)
        assert isinstance(config.preprocessing, PreprocessingConfig)
        assert isinstance(config.qc, QCConfig)
        assert isinstance(config.analysis, AnalysisConfig)
        assert isinstance(config.ml, MLConfig)


class TestConfigManager:
    """Tests for ConfigManager class."""

    def test_init_with_default_dir(self) -> None:
        """Test ConfigManager initialization with default directory."""
        manager = ConfigManager()
        assert manager._config_dir.exists()

    def test_init_with_custom_dir(self, tmp_path: Path) -> None:
        """Test ConfigManager initialization with custom directory."""
        manager = ConfigManager(config_dir=tmp_path)
        assert manager._config_dir == tmp_path

    def test_get_acquisition_config_default(self) -> None:
        """Test getting default acquisition configuration."""
        manager = ConfigManager()
        config = manager.get_acquisition_config()
        assert isinstance(config, AcquisitionConfig)

    def test_get_acquisition_config_custom_device(self) -> None:
        """Test getting acquisition configuration for custom device."""
        manager = ConfigManager()
        config = manager.get_acquisition_config(device="nirx_nirscout")
        assert isinstance(config, AcquisitionConfig)

    def test_shimadzu_unknown_geometry_is_not_defaulted(self) -> None:
        manager = ConfigManager()
        config = manager.get_acquisition_config(device="shimadzu_omm")
        assert config.source_detector_distance_mm is None
        assert config.short_channel_distance_mm is None

    def test_get_preprocessing_config_task(self) -> None:
        """Test getting preprocessing configuration for task scenario."""
        manager = ConfigManager()
        config = manager.get_preprocessing_config(scenario="task")
        assert isinstance(config, PreprocessingConfig)
        assert config.motion_correction_method == "tddr"

    def test_get_preprocessing_config_resting_state(self) -> None:
        """Test getting preprocessing configuration for resting state."""
        manager = ConfigManager()
        config = manager.get_preprocessing_config(scenario="resting_state")
        assert isinstance(config, PreprocessingConfig)
        assert config.short_channel_regression

    def test_get_qc_config_conservative(self) -> None:
        """Test getting conservative QC configuration."""
        manager = ConfigManager()
        config = manager.get_qc_config(strictness="conservative")
        assert isinstance(config, QCConfig)
        assert config.sci_threshold == 0.8

    def test_get_qc_config_relaxed(self) -> None:
        """Test getting relaxed QC configuration."""
        manager = ConfigManager()
        config = manager.get_qc_config(strictness="relaxed")
        assert isinstance(config, QCConfig)

    def test_get_analysis_config_task(self) -> None:
        """Test getting analysis configuration for task scenario."""
        manager = ConfigManager()
        config = manager.get_analysis_config(scenario="task")
        assert isinstance(config, AnalysisConfig)
        assert config.scenario == "task"
        assert config.hrf_model == "canonical"

    def test_get_analysis_config_resting_state(self) -> None:
        """Test getting analysis configuration for resting state."""
        manager = ConfigManager()
        config = manager.get_analysis_config(scenario="resting_state")
        assert isinstance(config, AnalysisConfig)
        assert config.scenario == "resting_state"
        assert config.connectivity_method == "pearson"

    def test_get_ml_config_svm(self) -> None:
        """Test getting ML configuration for SVM."""
        manager = ConfigManager()
        config = manager.get_ml_config(model_type="svm")
        assert isinstance(config, MLConfig)
        assert config.model_type == "svm"
        assert config.split_strategy == "subject_wise"

    def test_get_ml_config_random_forest(self) -> None:
        """Test getting ML configuration for Random Forest."""
        manager = ConfigManager()
        config = manager.get_ml_config(model_type="random_forest")
        assert isinstance(config, MLConfig)
        assert config.model_type == "random_forest"

    def test_get_full_config(self) -> None:
        """Test getting full evidence-backed configuration."""
        manager = ConfigManager()
        config = manager.get_full_config()
        assert isinstance(config, EvidenceBackedConfig)
        assert isinstance(config.acquisition, AcquisitionConfig)
        assert isinstance(config.preprocessing, PreprocessingConfig)
        assert isinstance(config.qc, QCConfig)
        assert isinstance(config.analysis, AnalysisConfig)
        assert isinstance(config.ml, MLConfig)

    def test_get_full_config_custom(self) -> None:
        """Test getting full configuration with custom parameters."""
        manager = ConfigManager()
        config = manager.get_full_config(
            scenario="resting_state",
            device="nirx_nirscout",
            motion_correction="spline",
            qc_strictness="relaxed",
            ml_model="random_forest",
        )
        assert isinstance(config, EvidenceBackedConfig)
        assert config.analysis.scenario == "resting_state"
        assert config.preprocessing.motion_correction_method == "spline"
        assert config.ml.model_type == "random_forest"

    def test_get_motion_correction_info(self) -> None:
        """Test getting motion correction information."""
        manager = ConfigManager()
        info = manager.get_motion_correction_info()
        assert isinstance(info, list)

    def test_get_device_list(self) -> None:
        """Test getting device list."""
        manager = ConfigManager()
        devices = manager.get_device_list()
        assert isinstance(devices, list)

    def test_get_scenario_list(self) -> None:
        """Test getting scenario list."""
        manager = ConfigManager()
        scenarios = manager.get_scenario_list()
        assert isinstance(scenarios, list)
        assert "task" in scenarios
        assert "resting_state" in scenarios

    def test_load_presets_with_missing_file(self, tmp_path: Path) -> None:
        """Test loading presets when file doesn't exist."""
        manager = ConfigManager(config_dir=tmp_path)
        assert manager._presets == {}

    def test_load_presets_with_empty_file(self, tmp_path: Path) -> None:
        """Test loading presets from empty file."""
        preset_file = tmp_path / "evidence_backed_presets.json"
        preset_file.write_text("{}", encoding="utf-8")

        manager = ConfigManager(config_dir=tmp_path)
        assert manager._presets == {}

    def test_load_presets_with_valid_file(self, tmp_path: Path) -> None:
        """Test loading presets from valid file."""
        preset_data = {
            "presets": {
                "acquisition": {
                    "standard_cw_fnirs": {
                        "device_brand_model": "Standard CW fNIRS",
                        "wavelengths_nm": [760, 850],
                    }
                }
            }
        }
        preset_file = tmp_path / "evidence_backed_presets.json"
        preset_file.write_text(
            __import__("json").dumps(preset_data),
            encoding="utf-8",
        )

        manager = ConfigManager(config_dir=tmp_path)
        assert "acquisition" in manager._presets
