"""Sprint C tests: MNE-NIRS adapter artifact manifests and version capture."""

from __future__ import annotations

import pytest

from fnirs_flow.adapters.mne_nirs_io import capture_versions
from fnirs_flow.execution.artifacts import ArtifactRecord, ArtifactStore

pytestmark = pytest.mark.full

# ============================================================================
# Version capture tests
# ============================================================================


class TestVersionCapture:
    def test_capture_versions_returns_dict(self):
        versions = capture_versions()
        assert isinstance(versions, dict)
        assert "python" in versions

    def test_python_version_format(self):
        versions = capture_versions()
        assert "." in versions["python"]


# ============================================================================
# ArtifactRecord tests
# ============================================================================


class TestArtifactRecord:
    def test_create_artifact_record(self):
        rec = ArtifactRecord(
            artifact_id="a1",
            subject="01",
            session="01",
            run="01",
            step_id="optical_density",
            artifact_type="OpticalDensity",
            sha256="abc123",
        )
        assert rec.artifact_type == "OpticalDensity"
        assert rec.subject == "01"

    def test_artifact_record_to_dict(self):
        rec = ArtifactRecord(
            artifact_id="a1",
            artifact_type="RawIntensity",
            step_id="read_run",
        )
        d = rec.model_dump()
        assert d["artifact_id"] == "a1"
        assert "created_at" in d


# ============================================================================
# ArtifactStore tests
# ============================================================================


class TestArtifactStore:
    def test_register_and_retrieve(self):
        store = ArtifactStore()
        rec = ArtifactRecord(artifact_id="a1", artifact_type="QCReport")
        store.register(rec)
        assert len(store.all()) == 1

    def test_to_manifest(self):
        store = ArtifactStore()
        store.register(ArtifactRecord(artifact_id="a1", artifact_type="OpticalDensity"))
        manifest = store.to_manifest(run_id="run-1")
        assert manifest.run_id == "run-1"
        assert len(manifest.artifacts) == 1


# ============================================================================
# Adapter artifact emission tests (with mock MNE objects)
# ============================================================================


class TestAdapterArtifactEmission:
    def test_adapter_initializes_with_versions(self):
        from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter

        adapter = MneNirsAdapter(subject="01", session="01", run="01")
        assert "python" in adapter.versions
        assert adapter._subject == "01"

    def test_adapter_stores_subject_session_run(self):
        from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter

        adapter = MneNirsAdapter(subject="02", session="02", run="03")
        assert adapter._subject == "02"
        assert adapter._session == "02"
        assert adapter._run == "03"

    def test_adapter_artifacts_store_exists(self):
        from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter

        adapter = MneNirsAdapter()
        assert isinstance(adapter.artifacts, ArtifactStore)
        assert len(adapter.artifacts.all()) == 0

    def test_adapter_provenance_exists(self):
        from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter
        from fnirs_flow.execution.provenance import ProvenanceRecord

        adapter = MneNirsAdapter()
        assert isinstance(adapter.provenance, ProvenanceRecord)


# ============================================================================
# QC metric tests (pure Python, no MNE required)
# ============================================================================


class TestQCMetrics:
    def test_compute_cv(self):
        import numpy as np

        from fnirs_flow.adapters.mne_nirs_steps import compute_coefficient_of_variation

        data = np.random.randn(5, 100)
        cv = compute_coefficient_of_variation(data)
        assert cv.shape == (5,)
        assert all(cv >= 0)

    def test_detect_bad_channels(self):
        import numpy as np

        from fnirs_flow.adapters.mne_nirs_steps import detect_bad_channels

        data = np.random.randn(5, 100)
        result = detect_bad_channels(data)
        assert "bad_mask" in result
        assert "n_bad" in result
        assert result["n_bad"] >= 0


# ============================================================================
# Package profile + artifact integration
# ============================================================================


class TestPackageProfileIntegration:
    def test_reproducibility_includes_artifacts(self):
        from fnirs_flow.exporters.package_exporter import get_package_profile

        p = get_package_profile("reproducibility_package")
        assert "artifact_manifest.json" in p.include_patterns

    def test_submission_excludes_artifacts(self):
        from fnirs_flow.exporters.package_exporter import get_package_profile

        p = get_package_profile("submission_package")
        assert "artifact_manifest.json" not in p.include_patterns
