"""Tests for package verifier."""

from __future__ import annotations

import json
import warnings
import zipfile
from pathlib import Path

from fnirs_flow.exporters.package_verifier import verify_package


class TestPackageVerifier:
    """Test package verification."""

    def test_verify_valid_package(self, tmp_path: Path) -> None:
        """Test verification of a valid package."""
        # Create a valid package with all required files for reproducibility_package
        pkg_path = tmp_path / "test.fnirsflow.zip"

        # Create test data
        plan_data = json.dumps({"test": True}).encode()
        dag_data = json.dumps({"nodes": []}).encode()
        adapter_data = json.dumps({"adapters": []}).encode()
        risk_data = json.dumps({"risks": []}).encode()
        repro_data = json.dumps({"flow_hash": "abc123"}).encode()

        manifest = {
            "schema_version": "1.0.0",
            "profile": "reproducibility_package",
            "files": {
                "plan.json": {"sha256": self._compute_hash_bytes(plan_data)},
                "manifest.json": {"sha256": ""},  # Will be computed after writing
                "execution_dag.json": {"sha256": self._compute_hash_bytes(dag_data)},
                "adapter_manifest.json": {"sha256": self._compute_hash_bytes(adapter_data)},
                "risk_register.json": {"sha256": self._compute_hash_bytes(risk_data)},
                "reproducibility_manifest.json": {"sha256": self._compute_hash_bytes(repro_data)},
            },
        }

        with zipfile.ZipFile(pkg_path, "w") as zf:
            # Write all required files
            zf.writestr("plan.json", plan_data)
            zf.writestr("execution_dag.json", dag_data)
            zf.writestr("adapter_manifest.json", adapter_data)
            zf.writestr("risk_register.json", risk_data)
            zf.writestr("reproducibility_manifest.json", repro_data)

            # Write manifest last (after computing all hashes)
            manifest_data = json.dumps(manifest).encode()
            zf.writestr("manifest.json", manifest_data)

        result = verify_package(pkg_path)
        assert result.valid
        assert result.profile == "reproducibility_package"

    def test_verify_missing_manifest(self, tmp_path: Path) -> None:
        """Test verification fails when manifest is missing."""
        pkg_path = tmp_path / "test.fnirsflow.zip"

        with zipfile.ZipFile(pkg_path, "w") as zf:
            zf.writestr("plan.json", json.dumps({"test": True}))

        result = verify_package(pkg_path)
        assert not result.valid
        assert any("manifest.json" in e for e in result.errors)

    def test_verify_missing_required_file(self, tmp_path: Path) -> None:
        """Test verification fails when required file is missing."""
        pkg_path = tmp_path / "test.fnirsflow.zip"
        # Create manifest with profile but missing required files
        manifest = {
            "schema_version": "1.0.0",
            "profile": "reproducibility_package",
            "files": {
                "plan.json": {"sha256": self._compute_hash({"test": True})},
                "manifest.json": {"sha256": ""},
            },
        }

        with zipfile.ZipFile(pkg_path, "w") as zf:
            # Write manifest
            manifest_data = json.dumps(manifest).encode()
            zf.writestr("manifest.json", manifest_data)
            # Write plan.json but not other required files
            zf.writestr("plan.json", json.dumps({"test": True}))

        result = verify_package(pkg_path)
        assert not result.valid
        # Should have missing files for reproducibility_package profile
        assert len(result.missing_files) > 0

    def test_verify_checksum_mismatch(self, tmp_path: Path) -> None:
        """Test verification fails when checksum doesn't match."""
        pkg_path = tmp_path / "test.fnirsflow.zip"
        manifest = {
            "schema_version": "1.0.0",
            "profile": "reproducibility_package",
            "files": {
                "plan.json": {"sha256": "incorrect_hash"},
                "manifest.json": {"sha256": ""},
            },
        }

        with zipfile.ZipFile(pkg_path, "w") as zf:
            zf.writestr("plan.json", json.dumps({"test": True}))
            zf.writestr("manifest.json", json.dumps(manifest))

        result = verify_package(pkg_path)
        assert not result.valid
        assert any("plan.json" in m for m in result.checksum_mismatches)

    def test_verify_profile_mismatch(self, tmp_path: Path) -> None:
        """Test verification warns on profile mismatch."""
        pkg_path = tmp_path / "test.fnirsflow.zip"
        manifest = {
            "schema_version": "1.0.0",
            "profile": "submission_package",
            "files": {
                "plan.json": {"sha256": ""},
                "manifest.json": {"sha256": ""},
            },
        }

        with zipfile.ZipFile(pkg_path, "w") as zf:
            zf.writestr("plan.json", json.dumps({"test": True}))
            zf.writestr("manifest.json", json.dumps(manifest))

        result = verify_package(pkg_path, expected_profile="reproducibility_package")
        assert any("Profile mismatch" in w for w in result.warnings)

    def test_verify_invalid_zip(self, tmp_path: Path) -> None:
        """Test verification fails for invalid zip file."""
        pkg_path = tmp_path / "test.fnirsflow.zip"
        pkg_path.write_text("not a zip file")

        result = verify_package(pkg_path)
        assert not result.valid
        assert any("Invalid zip file" in e for e in result.errors)

    def test_verify_nonexistent_file(self, tmp_path: Path) -> None:
        """Test verification fails for nonexistent file."""
        pkg_path = tmp_path / "nonexistent.fnirsflow.zip"

        result = verify_package(pkg_path)
        assert not result.valid
        assert any("not found" in e for e in result.errors)

    def test_verify_rejects_duplicate_paths(self, tmp_path: Path) -> None:
        """Test verification fails closed on duplicate archive members."""
        pkg_path = tmp_path / "duplicate.fnirsflow.zip"

        with zipfile.ZipFile(pkg_path, "w") as zf:
            zf.writestr("plan.json", "{}")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                zf.writestr("plan.json", "{\"duplicate\": true}")
            zf.writestr("manifest.json", json.dumps({"schema_version": "1.0.0", "files": {}}))

        result = verify_package(pkg_path)
        assert not result.valid
        assert any("duplicate paths" in e for e in result.errors)

    def test_verify_rejects_unsafe_paths(self, tmp_path: Path) -> None:
        """Test verification rejects zip entries that escape the target tree."""
        pkg_path = tmp_path / "unsafe.fnirsflow.zip"

        with zipfile.ZipFile(pkg_path, "w") as zf:
            zf.writestr("../plan.json", "{}")
            zf.writestr("manifest.json", json.dumps({"schema_version": "1.0.0", "files": {}}))

        result = verify_package(pkg_path)
        assert not result.valid
        assert any("Unsafe zip entry" in e for e in result.errors)

    def _compute_hash(self, data: dict) -> str:
        """Compute hash of JSON data."""
        import hashlib
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()

    def _compute_hash_bytes(self, data: bytes) -> str:
        """Compute hash of bytes."""
        import hashlib
        return hashlib.sha256(data).hexdigest()
