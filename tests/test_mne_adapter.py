"""Tests for MNE-NIRS adapter (mocked, no real MNE dependency)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter
from fnirs_flow.adapters.mne_nirs_io import capture_versions


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


class TestMneNirsStepsMocked:
    """Tests for adapter steps using mocked MNE functions."""

    def test_optical_density_calls_mne(self):
        with patch("fnirs_flow.adapters.mne_nirs_steps.optical_density") as mock_od:
            mock_raw = MagicMock()
            mock_od.return_value = mock_raw

            from fnirs_flow.adapters.mne_nirs_steps import optical_density

            optical_density(mock_raw)
            mock_od.assert_called_once_with(mock_raw)

    def test_filter_raw_iir(self):
        """IIR method uses SciPy, not raw.filter()."""
        import numpy as np
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
