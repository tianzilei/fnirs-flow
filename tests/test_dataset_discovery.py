"""Tests for dataset registry, discovery, and manifest."""

from __future__ import annotations

from pathlib import Path

import pytest

from fnirs_flow.data.discovery import discover_dataset
from fnirs_flow.data.manifest import DataFile, DataManifest, DataSource, SubjectSessionRun
from fnirs_flow.data.registry import BUILTIN_DATASETS, DatasetEntry, DatasetRegistry

pytestmark = pytest.mark.core


class TestDatasetRegistry:
    def test_builtin_datasets_exist(self):
        assert "mne-fnirs-motor" in BUILTIN_DATASETS
        assert "bids-nirs-tapping" in BUILTIN_DATASETS
        assert BUILTIN_DATASETS["ds007738"].folder_name == "Sample/ds007738-download"

    def test_registry_get(self):
        reg = DatasetRegistry()
        entry = reg.get("mne-fnirs-motor")
        assert entry is not None
        assert entry.dataset_id == "mne-fnirs-motor"

    def test_registry_list(self):
        reg = DatasetRegistry()
        ids = reg.list_ids()
        assert "mne-fnirs-motor" in ids

    def test_registry_register_custom(self):
        reg = DatasetRegistry()
        custom = DatasetEntry(
            dataset_id="custom-ds",
            name="Custom",
            source_kind="snirf_file",
        )
        reg.register(custom)
        assert reg.get("custom-ds") is not None

    def test_registry_unknown_returns_none(self):
        reg = DatasetRegistry()
        assert reg.get("nonexistent") is None


class TestDataManifest:
    def test_create_manifest(self):
        m = DataManifest(
            dataset_id="test",
            source=DataSource(kind="mne_nirs_dataset"),
            files=[DataFile(path="sub-01_task-motor.snirf", role="raw_snirf")],
        )
        assert m.dataset_id == "test"
        assert len(m.files) == 1

    def test_manifest_roundtrip(self):
        m = DataManifest(
            dataset_id="test",
            subject_session_runs=[
                SubjectSessionRun(subject="01", session="01", run="01", path="/data/f.snirf"),
            ],
        )
        d = m.model_dump()
        restored = DataManifest.model_validate(d)
        assert restored.dataset_id == "test"
        assert len(restored.subject_session_runs) == 1


class TestDiscovery:
    def test_discover_unknown_raises(self, tmp_path):
        try:
            discover_dataset("nonexistent", tmp_path)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "nonexistent" in str(e)

    def test_discover_creates_manifest(self, tmp_path):
        manifest = discover_dataset("mne-fnirs-motor", tmp_path)
        assert manifest.dataset_id == "mne-fnirs-motor"
        # data_manifest.json is now written to compiled/ subdirectory
        assert (tmp_path / "compiled" / "data_manifest.json").exists()
        assert (tmp_path / "compiled" / "run_table.csv").exists()

    def test_discover_local_bids_nirs_tapping(self, tmp_path):
        dataset_root = Path(__file__).resolve().parents[1] / BUILTIN_DATASETS["bids-nirs-tapping"].folder_name
        if not dataset_root.is_dir():
            pytest.skip("Private BIDS-NIRS-Tapping sample dataset is not included in the public release")
        manifest = discover_dataset("bids-nirs-tapping", tmp_path)
        assert manifest.dataset_id == "bids-nirs-tapping"
        assert len([f for f in manifest.files if f.role == "raw_snirf"]) == 5
        assert len(manifest.subject_session_runs) == 5
        first = manifest.subject_session_runs[0]
        assert first.subject == "01"
        assert first.task == "tapping"
        assert first.relative_path.endswith("_nirs.snirf")
        assert first.size_bytes > 0
        assert first.modified_at
        assert len(manifest.metadata_tables) == 1
        assert manifest.metadata_tables[0].path.endswith("participants.tsv")
        assert manifest.metadata_tables[0].size_bytes > 0
        assert manifest.metadata_tables[0].modified_at
        # data_manifest.json is now written to compiled/ subdirectory
        assert (tmp_path / "compiled" / "data_manifest.json").exists()
        assert (tmp_path / "compiled" / "run_table.csv").exists()
        assert (tmp_path / "compiled" / "participant_table_manifest.json").exists()
