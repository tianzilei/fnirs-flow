"""MNE-NIRS I/O wrapper: read SNIRF/NIRx data via MNE-Python."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def read_raw_snirf(filepath: str | Path, **kwargs: Any) -> Any:
    """Read a SNIRF file using MNE-Python.

    Args:
        filepath: Path to .snirf file
        **kwargs: Additional arguments passed to mne.io.read_raw_snirf

    Returns:
        MNE Raw object with fNIRS data
    """
    try:
        import mne

        return mne.io.read_raw_snirf(str(filepath), **kwargs)
    except ImportError:
        raise ImportError(
            "MNE-Python is required for SNIRF reading. Install with: pip install fnirs-flow[mne]"
        ) from None


def read_raw_nirx(filepath: str | Path, **kwargs: Any) -> Any:
    """Read a NIRx file using MNE-Python.

    Args:
        filepath: Path to NIRx directory or file
        **kwargs: Additional arguments passed to mne.io.read_raw_nirx

    Returns:
        MNE Raw object with fNIRS data
    """
    try:
        import mne

        return mne.io.read_raw_nirx(str(filepath), **kwargs)
    except ImportError:
        raise ImportError(
            "MNE-Python is required for NIRx reading. Install with: pip install fnirs-flow[mne]"
        ) from None


def get_dataset_path(dataset_name: str = "fnirs_motor") -> Path:
    """Get the path to a built-in MNE dataset.

    Args:
        dataset_name: Name of the MNE dataset

    Returns:
        Path to the dataset directory
    """
    try:
        from mne.datasets import fnirs_motor

        return Path(fnirs_motor.data_path())
    except ImportError:
        raise ImportError(
            "MNE-Python is required for dataset access. Install with: pip install fnirs-flow[mne]"
        ) from None


def capture_versions() -> dict[str, str]:
    """Capture versions of MNE-related packages.

    Returns:
        Dict of package name -> version string
    """
    versions: dict[str, str] = {}

    try:
        import mne

        versions["mne"] = mne.__version__
    except ImportError:
        versions["mne"] = "not installed"

    try:
        import mne_nirs

        versions["mne-nirs"] = getattr(mne_nirs, "__version__", "unknown")
    except ImportError:
        versions["mne-nirs"] = "not installed"

    try:
        import mne_bids

        versions["mne-bids"] = getattr(mne_bids, "__version__", "unknown")
    except ImportError:
        versions["mne-bids"] = "not installed"

    import sys

    versions["python"] = sys.version.split()[0]

    return versions
