"""Reference-equivalence tests against Cedalion 26.5.1."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

cedalion = pytest.importorskip("cedalion")
xr = pytest.importorskip("xarray")
from cedalion.io import read_snirf as cedalion_read_snirf  # noqa: E402
from cedalion.nirs.common import (  # noqa: E402
    channel_distances,
    get_extinction_coefficients,
)
from cedalion.nirs.cw import int2od, od2conc  # noqa: E402

from fnirs_flow.adapters.cedalion_steps import (  # noqa: E402
    compute_channel_distances,
    intensity_to_od,
    od_to_concentration,
    read_snirf,
)
from fnirs_flow.adapters.cedalion_steps import (  # noqa: E402
    get_extinction_coefficients as adapted_extinction_coefficients,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNIRF = (
    PROJECT_ROOT
    / "Sample"
    / "ds007738-download"
    / "sub-01"
    / "nirs"
    / "sub-01_task-covert_run-01_nirs.snirf"
)


@pytest.fixture(scope="module")
def snirf_path() -> Path:
    configured = os.environ.get("FNIRS_TEST_SNIRF")
    path = Path(configured) if configured else DEFAULT_SNIRF
    if os.environ.get("FNIRS_REQUIRE_REAL_DATA") == "1" and not path.is_file():
        pytest.fail(f"Required real-data fixture is missing: {path}")
    if not path.is_file():
        pytest.skip("Set FNIRS_TEST_SNIRF to a real SNIRF file")
    return path


@pytest.fixture(scope="module")
def direct_recording(snirf_path: Path):
    recordings = cedalion_read_snirf(snirf_path)
    assert len(recordings) == 1
    return recordings[0]


@pytest.mark.cedalion
@pytest.mark.real_data
class TestCedalionReferenceEquivalence:
    def test_snirf_read_equivalence(self, snirf_path: Path, direct_recording):
        adapted = read_snirf(str(snirf_path))
        assert list(adapted.timeseries) == list(direct_recording.timeseries)
        xr.testing.assert_identical(
            adapted.get_timeseries("amp"),
            direct_recording.get_timeseries("amp"),
        )

    def test_int2od_equivalence(self, snirf_path: Path, direct_recording):
        amplitudes = direct_recording.get_timeseries("amp")
        expected = int2od(amplitudes.where(amplitudes > 0))

        adapted = intensity_to_od(read_snirf(str(snirf_path)))
        xr.testing.assert_allclose(adapted.get_timeseries("od"), expected)
        assert adapted.get_timeseries("od").attrs["fnirs_flow_nonpositive_count"] > 0

    def test_od2conc_equivalence(self, snirf_path: Path, direct_recording):
        amplitudes = direct_recording.get_timeseries("amp")
        optical_density = int2od(amplitudes.where(amplitudes > 0))
        wavelengths = optical_density.wavelength.values.astype(float)
        dpf = xr.DataArray(
            [6.0] * len(wavelengths),
            dims=["wavelength"],
            coords={"wavelength": wavelengths},
        )
        expected = od2conc(optical_density, direct_recording.geo3d, dpf)

        adapted = read_snirf(str(snirf_path))
        adapted = intensity_to_od(adapted)
        adapted = od_to_concentration(adapted, ppf=6.0)
        xr.testing.assert_allclose(adapted.get_timeseries("conc"), expected)

    def test_channel_distance_equivalence(self, direct_recording):
        amplitudes = direct_recording.get_timeseries("amp")
        expected = channel_distances(amplitudes, direct_recording.geo3d)
        actual = compute_channel_distances(amplitudes, direct_recording.geo3d)
        xr.testing.assert_identical(actual, expected)

    def test_extinction_coefficient_equivalence(self, direct_recording):
        wavelengths = direct_recording.wavelengths
        expected = get_extinction_coefficients("prahl", wavelengths)
        actual = adapted_extinction_coefficients(wavelengths, "prahl")
        xr.testing.assert_identical(actual, expected)
