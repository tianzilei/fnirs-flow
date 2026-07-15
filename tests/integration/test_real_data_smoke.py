"""Smoke tests using the repository's real ds007738 SNIRF fixture."""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np
import pytest

mne = pytest.importorskip("mne")

from fnirs_flow.adapters.mne_nirs_io import read_raw_snirf  # noqa: E402
from fnirs_flow.adapters.mne_nirs_steps import (  # noqa: E402
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
    if not path.is_file():
        pytest.skip("Set FNIRS_TEST_SNIRF to a real SNIRF file")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Extraction of measurement date.*", category=RuntimeWarning)
        raw = read_raw_snirf(path, preload=True, verbose="ERROR")
    pairs: dict[str, list[int]] = {}
    for index, name in enumerate(raw.ch_names):
        pairs.setdefault(name.rsplit(" ", 1)[0], []).append(index)
    selected = [indices for indices in pairs.values() if len(indices) == 2][:8]
    assert len(selected) == 8, "SNIRF fixture must contain at least eight wavelength pairs"
    picks = [index for pair in selected for index in pair]
    return raw.pick(picks).crop(tmax=min(60.0, float(raw.times[-1]))).load_data()


@pytest.mark.real_data
class TestRealDataSmoke:
    """Verify that the real fixture survives the primary preprocessing chain."""

    def test_read_snirf(self, paired_raw):
        data = paired_raw.get_data()
        assert data.shape[0] == 16
        assert data.shape[1] > 100
        assert paired_raw.get_channel_types(unique=True) == ["fnirs_cw_amplitude"]
        assert np.isfinite(data).all()

    def test_optical_density(self, paired_raw):
        optical = optical_density(paired_raw.copy())
        assert optical.get_data().shape == paired_raw.get_data().shape
        assert optical.get_channel_types(unique=True) == ["fnirs_od"]
        assert np.isfinite(optical.get_data()).all()

    def test_filter(self, paired_raw):
        optical = optical_density(paired_raw.copy())
        filtered = filter_raw(optical, l_freq=0.01, h_freq=0.2, method="iir")
        assert filtered.get_data().shape == optical.get_data().shape
        assert np.isfinite(filtered.get_data()).all()
        assert not np.array_equal(filtered.get_data(), optical.get_data())

    def test_beer_lambert(self, paired_raw):
        optical = optical_density(paired_raw.copy())
        haemoglobin = beer_lambert_law(optical, ppf=6.0)
        assert haemoglobin.get_data().shape == optical.get_data().shape
        assert set(haemoglobin.get_channel_types(unique=True)) == {"hbo", "hbr"}
        assert np.isfinite(haemoglobin.get_data()).all()
