"""Dataset registry: manages dataset metadata for discovery."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DatasetEntry:
    dataset_id: str
    name: str
    source_kind: str  # mne_nirs_dataset, bids_dataset, snirf_file, etc.
    url: str = ""
    doi: str = ""
    citation: str = ""
    license: str = ""
    description: str = ""
    folder_name: str = ""
    archive_name: str = ""
    config_key: str = ""


# Built-in dataset registry
BUILTIN_DATASETS: dict[str, DatasetEntry] = {
    "mne-fnirs-motor": DatasetEntry(
        dataset_id="mne-fnirs-motor",
        name="MNE fNIRS Motor Task",
        source_kind="mne_nirs_dataset",
        url="https://osf.io/download/dj3eh?version=1",
        doi="10.1038/s41597-020-0413-9",
        citation="MNE software for processing MEG and EEG data, NeuroImage 2024",
        license="BSD-3-Clause",
        description="fNIRS motor task dataset: finger tapping experiment with 2 wavelengths",
        folder_name="MNE-fNIRS-motor-data",
        archive_name="MNE-fNIRS-motor-data.tgz",
        config_key="MNE_DATASETS_FNIRS_MOTOR_PATH",
    ),
    "bids-nirs-tapping": DatasetEntry(
        dataset_id="bids-nirs-tapping",
        name="BIDS-NIRS Finger Tapping",
        source_kind="local_bids_nirs",
        url="https://github.com/rob-luke/BIDS-NIRS-Tapping",
        doi="10.5281/zenodo.5529797",
        citation="Luke R, McAlpine D. fNIRS Finger Tapping Data in BIDS Format.",
        license="",
        description="Local BIDS-NIRS finger tapping dataset with five participants.",
        folder_name="bids-nirs-dataset",
    ),
}


class DatasetRegistry:
    """Registry of known fNIRS datasets."""

    def __init__(self) -> None:
        self._datasets: dict[str, DatasetEntry] = dict(BUILTIN_DATASETS)

    def register(self, entry: DatasetEntry) -> None:
        self._datasets[entry.dataset_id] = entry

    def get(self, dataset_id: str) -> DatasetEntry | None:
        return self._datasets.get(dataset_id)

    def list_ids(self) -> list[str]:
        return sorted(self._datasets.keys())

    def all_entries(self) -> list[DatasetEntry]:
        return list(self._datasets.values())
