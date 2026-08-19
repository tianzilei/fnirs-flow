"""Reference-equivalence tests against direct MNE/SciPy operations."""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import butter, sosfiltfilt

mne = pytest.importorskip("mne")
pytest.importorskip("mne_nirs")

from fnirs_flow.adapters.mne_nirs_analysis import (  # noqa: E402
    build_design_matrix,
    first_level_glm,
)
from fnirs_flow.adapters.mne_nirs_preprocessing import (  # noqa: E402
    beer_lambert_law,
    filter_raw,
    optical_density,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNIRF_PATH = (
    PROJECT_ROOT
    / "Sample"
    / "ds007738-download"
    / "sub-01"
    / "nirs"
    / "sub-01_task-covert_run-01_nirs.snirf"
)


@pytest.fixture(scope="module")
def paired_raw():
    path = Path(os.environ.get("FNIRS_TEST_SNIRF", str(SNIRF_PATH)))
    if os.environ.get("FNIRS_REQUIRE_REAL_DATA") == "1" and not path.is_file():
        pytest.fail(f"Required real-data fixture is missing: {path}")
    if not path.is_file():
        pytest.skip("Set FNIRS_TEST_SNIRF to a real SNIRF file")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Extraction of measurement date.*", category=RuntimeWarning)
        raw = mne.io.read_raw_snirf(path, preload=True, verbose="ERROR")
    pairs: dict[str, list[int]] = {}
    for index, name in enumerate(raw.ch_names):
        pairs.setdefault(name.rsplit(" ", 1)[0], []).append(index)
    selected = [indices for indices in pairs.values() if len(indices) == 2][:8]
    assert len(selected) == 8, "SNIRF fixture must contain at least eight wavelength pairs"
    picks = [index for pair in selected for index in pair]
    return raw.pick(picks).crop(tmax=min(60.0, float(raw.times[-1]))).load_data()


class TestMneReferenceEquivalence:
    """fnirs-flow wrappers must agree numerically with their direct references."""

    @pytest.mark.full
    def test_optical_density_equivalence(self, paired_raw):
        expected = mne.preprocessing.nirs.optical_density(paired_raw.copy())
        actual = optical_density(paired_raw.copy())

        assert actual.get_channel_types() == expected.get_channel_types()
        np.testing.assert_allclose(actual.get_data(), expected.get_data(), rtol=0.0, atol=0.0)

    @pytest.mark.full
    def test_filter_equivalence(self, paired_raw):
        optical = optical_density(paired_raw.copy())
        sfreq = float(optical.info["sfreq"])
        l_freq, h_freq = 0.01, 0.2
        sos = butter(
            4,
            [l_freq / (sfreq / 2.0), h_freq / (sfreq / 2.0)],
            btype="band",
            output="sos",
        )
        expected = np.vstack([sosfiltfilt(sos, channel) for channel in optical.get_data()])

        actual = filter_raw(optical, l_freq=l_freq, h_freq=h_freq, method="iir")
        np.testing.assert_allclose(actual.get_data(), expected, rtol=1e-13, atol=1e-15)

    @pytest.mark.full
    def test_beer_lambert_equivalence(self, paired_raw):
        optical = optical_density(paired_raw.copy())
        expected = mne.preprocessing.nirs.beer_lambert_law(optical.copy(), ppf=6.0)
        actual = beer_lambert_law(optical.copy(), ppf=6.0)

        assert actual.get_channel_types() == expected.get_channel_types()
        np.testing.assert_allclose(actual.get_data(), expected.get_data(), rtol=0.0, atol=0.0)

    @pytest.mark.full
    def test_glm_equivalence(self, paired_raw):
        haemoglobin = beer_lambert_law(optical_density(paired_raw.copy()), ppf=6.0)
        events = np.asarray([[20, 30, 1], [220, 35, 2], [390, 25, 1]], dtype=int)
        design = build_design_matrix(
            haemoglobin,
            events,
            {"Left": 1, "Right": 2},
            sfreq=float(haemoglobin.info["sfreq"]),
            drift_order=1,
            high_pass=0.01,
        )
        matrix = design["design_matrix"]
        data = haemoglobin.get_data()
        scale = float(np.max(np.abs(data)))
        expected_scaled_betas = np.linalg.lstsq(matrix, (data / scale).T, rcond=None)[0].T
        expected_betas = expected_scaled_betas * scale
        expected_fitted = np.einsum("cr,sr->cs", expected_scaled_betas, matrix, optimize=False)
        expected_residuals = (data / scale - expected_fitted) * scale

        actual = first_level_glm(haemoglobin, design, noise_model="ols")
        np.testing.assert_allclose(actual["betas"], expected_betas, rtol=1e-10, atol=1e-15)
        np.testing.assert_allclose(actual["residuals"], expected_residuals, rtol=1e-10, atol=1e-15)
