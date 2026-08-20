"""Tests for MNE-NIRS adapter (mocked, no real MNE dependency)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter
from fnirs_flow.adapters.mne_nirs_io import capture_versions

pytestmark = pytest.mark.full


class TestMneNirsAdapter:
    def test_adapter_init(self):
        adapter = MneNirsAdapter()
        assert adapter.versions is not None
        assert adapter.provenance is not None
        assert adapter.artifacts is not None

    def test_capture_versions(self):
        versions = capture_versions()
        assert "python" in versions
        assert "mne" in versions

    def test_provenance_logging(self):
        adapter = MneNirsAdapter()
        adapter._provenance.log("step1", {"param": "value"})
        records = adapter.provenance.all()
        assert len(records) == 1
        assert records[0]["step_id"] == "step1"

    def test_artifact_store(self):
        from fnirs_flow.execution.artifacts import ArtifactRecord

        adapter = MneNirsAdapter()
        adapter.artifacts.register(
            ArtifactRecord(
                artifact_id="a1",
                path="/out/qc.csv",
            )
        )
        assert len(adapter.artifacts.all()) == 1

    def test_export_channel_results(self, tmp_path):
        adapter = MneNirsAdapter()
        results = {
            "S1_D1 hbo": {"hbo_beta": 0.5, "hbo_t": 2.1, "p_value": 0.03},
            "S1_D1 hbr": {"hbr_beta": -0.2, "hbr_t": -1.5, "p_value": 0.13},
        }
        path = adapter.export_channel_results(results, tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "S1_D1 hbo" in content
        assert len(adapter.artifacts.all()) == 1

    def test_task_is_part_of_reportlet_identity(self, tmp_path):
        covert = MneNirsAdapter(subject="01", task="covert", run="01", outdir=tmp_path)
        overt = MneNirsAdapter(subject="01", task="overt", run="01", outdir=tmp_path)

        covert_path = covert._write_artifact_file("test", "summary", {"task": "covert"})
        overt_path = overt._write_artifact_file("test", "summary", {"task": "overt"})

        assert covert_path != overt_path
        assert covert_path.name == "sub-01_task-covert_run-01_desc-summary.json"
        assert overt_path.name == "sub-01_task-overt_run-01_desc-summary.json"


class TestMneNirsStepsMocked:
    """Tests for adapter steps using mocked MNE functions."""

    def test_optical_density_calls_mne(self):
        with patch("mne.preprocessing.nirs.optical_density") as mock_od:
            mock_raw = MagicMock()
            mock_od.return_value = mock_raw

            from fnirs_flow.adapters.mne_nirs_steps import optical_density

            optical_density(mock_raw)
            mock_od.assert_called_once_with(mock_raw)

    def test_filter_raw_iir(self):
        """IIR method uses SciPy, not raw.filter()."""
        import numpy as np

        pytest.importorskip("mne")
        from mne import create_info
        from mne.io import RawArray

        sfreq = 100.0
        n_channels = 2
        n_samples = 1000
        info = create_info(
            ch_names=[f"ch{i}" for i in range(n_channels)],
            sfreq=sfreq,
            ch_types="fnirs_cw_amplitude",
        )
        raw_data = np.random.randn(n_channels, n_samples)
        real_raw = RawArray(raw_data, info, verbose=False)

        from fnirs_flow.adapters.mne_nirs_steps import filter_raw

        result = filter_raw(real_raw, l_freq=0.01, h_freq=0.2, method="iir")
        assert result is not real_raw

    def test_filter_raw_fir(self):
        """FIR method delegates to raw.filter()."""
        raw = MagicMock()
        raw_copy = MagicMock()
        raw.copy.return_value = raw_copy

        from fnirs_flow.adapters.mne_nirs_steps import filter_raw

        result = filter_raw(raw, l_freq=0.01, h_freq=0.2, method="fir")
        raw.copy.assert_called_once()
        raw_copy.filter.assert_called_once_with(l_freq=0.01, h_freq=0.2)
        assert result is raw_copy

    def test_design_matrix_uses_duration_hrf_and_nuisance_regressors(self):
        import numpy as np

        from fnirs_flow.adapters.mne_nirs_steps import build_design_matrix

        raw = MagicMock()
        raw.times = np.arange(800) / 10.0
        events = np.asarray([[10, 10, 1], [400, 50, 2]], dtype=int)
        design = build_design_matrix(
            raw,
            events,
            {"Left": 1, "Right": 2},
            sfreq=10.0,
            drift_order=1,
            high_pass=0.01,
        )

        matrix = design["design_matrix"]
        assert matrix.shape[0] == 800
        assert design["regressor_names"][:2] == ["Left", "Right"]
        assert design["regressor_names"][-1] == "constant"
        assert matrix[:, 1].sum() > matrix[:, 0].sum()
        assert abs(matrix[-1, 0]) < 1e-6
        assert not np.allclose(matrix[:, 0], matrix[:, 1])

    def test_glm_keeps_condition_and_regressor_counts_distinct(self):
        import numpy as np

        from fnirs_flow.adapters.mne_nirs_analysis import first_level_glm

        raw = MagicMock()
        raw.get_data.return_value = np.arange(80, dtype=float).reshape(2, 40)
        design = {
            "design_matrix": np.column_stack(
                [np.linspace(0, 1, 40), np.linspace(1, 0, 40), np.ones(40)]
            ),
            "conditions": ["Left", "Right"],
            "regressor_names": ["Left", "Right", "constant"],
        }

        result = first_level_glm(raw, design, noise_model="ols")

        assert result["n_conditions"] == 2
        assert result["n_regressors"] == 3

    def test_named_contrast_is_invariant_to_condition_order(self):
        import numpy as np

        from fnirs_flow.adapters.mne_nirs_analysis import estimate_contrast

        contrast = [{"name": "left-right", "weights": [1, -1], "conditions": ["Left", "Right"]}]
        left_first = {
            "betas": np.array([[5.0, 2.0, 99.0]]),
            "n_channels": 1,
            "n_conditions": 2,
            "n_regressors": 3,
            "conditions": ["Left", "Right"],
            "regressor_names": ["Left", "Right", "constant"],
        }
        right_first = {
            **left_first,
            "betas": np.array([[2.0, 5.0, 99.0]]),
            "conditions": ["Right", "Left"],
            "regressor_names": ["Right", "Left", "constant"],
        }

        assert estimate_contrast(left_first, contrast)["contrasts"][0]["contrast_values"].item() == 3.0
        assert estimate_contrast(right_first, contrast)["contrasts"][0]["contrast_values"].item() == 3.0

    def test_nonfinite_policy_can_drop_channels_explicitly(self):
        import numpy as np

        from fnirs_flow.adapters.mne_nirs_analysis import first_level_glm

        raw = MagicMock()
        raw.get_data.return_value = np.array([[1.0, 2.0, 3.0, 4.0], [1.0, np.nan, 3.0, 4.0]])
        design = {
            "design_matrix": np.column_stack([np.arange(4, dtype=float), np.ones(4)]),
            "conditions": ["task"],
            "regressor_names": ["task", "constant"],
        }

        result = first_level_glm(raw, design, noise_model="ols", nonfinite_policy="drop_channels")

        assert result["n_channels"] == 1
        assert result["channel_indices"] == [0]
        assert result["data_quality"]["excluded_channel_indices"] == [1]

    def test_roi_mapping_uses_original_channel_indices_after_exclusion(self):
        from fnirs_flow.adapters.mne_nirs_analysis import roi_output

        channel_results = {
            "channels": [
                {"channel_idx": 0, "effect_beta": 1.0},
                {"channel_idx": 2, "effect_beta": 3.0},
            ]
        }

        result = roi_output(channel_results, roi_mapping={"roi": [1, 2]})

        assert result["rois"][0]["n_channels"] == 1
        assert result["rois"][0]["effect_beta_mean"] == 3.0
