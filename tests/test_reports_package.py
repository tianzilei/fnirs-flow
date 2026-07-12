"""Tests for reports, package export/import."""

from __future__ import annotations

import json

from fnirs_flow.exporters.package_exporter import export_package, get_package_contents
from fnirs_flow.exporters.package_importer import check_package_integrity, import_package
from fnirs_flow.exporters.reports import (
    generate_analysis_plan,
    generate_run_report,
    generate_validation_report,
)


class TestReports:
    def test_generate_analysis_plan(self, tmp_path):
        plan = {
            "flow_id": "test-001",
            "name": "Test Flow",
            "description": "A test flow",
            "flow_hash": "abc123def456",
            "preprocessing_chain": [
                {"step_id": "od", "type": "optical_density", "parameters": {}},
            ],
            "analysis_chain": [
                {
                    "step_id": "glm",
                    "type": "first_level_glm",
                    "parameters": {"hrf_model": "canonical"},
                },
            ],
            "execution": {"total_steps": 2},
        }
        path = generate_analysis_plan(plan, tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "test-001" in content
        assert "optical_density" in content

    def test_generate_validation_report(self, tmp_path):
        path = generate_validation_report(
            errors=["Error 1"],
            warnings=["Warning 1"],
            risks=[{"severity": "high", "message": "Risk 1"}],
            outdir=tmp_path,
        )
        assert path.exists()
        content = path.read_text()
        assert "Error 1" in content
        assert "[high] Risk 1" in content

    def test_generate_run_report(self, tmp_path):
        summary = {"total": 10, "successful": 8, "failed": 2, "failure_ids": ["r1", "r2"]}
        path = generate_run_report(summary, tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "10" in content
        assert "r1" in content


class TestPackageExportImport:
    def _setup_output_dir(self, tmp_path):
        outdir = tmp_path / "output"
        outdir.mkdir()
        (outdir / "plan.json").write_text('{"flow_id": "test"}')
        (outdir / "execution_dag.json").write_text('{"nodes": []}')
        (outdir / "adapter_manifest.json").write_text("{}")
        return outdir

    def test_export_package(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        pkg_path = tmp_path / "test.fnirsflow.zip"
        result = export_package(outdir, pkg_path)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_get_package_contents(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        pkg_path = tmp_path / "test.fnirsflow.zip"
        export_package(outdir, pkg_path)
        contents = get_package_contents(pkg_path)
        assert "plan.json" in contents
        assert "RELINK_INSTRUCTIONS.json" in contents

    def test_import_package(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        pkg_path = tmp_path / "test.fnirsflow.zip"
        export_package(outdir, pkg_path)

        import_dir = tmp_path / "imported"
        result = import_package(pkg_path, import_dir)
        assert len(result["extracted_files"]) > 0
        assert (import_dir / "plan.json").exists()

    def test_import_with_relink(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        # Add data manifest
        manifest = {"local_root": "/old/path", "dataset_id": "test"}
        (outdir / "data_manifest.json").write_text(json.dumps(manifest))

        pkg_path = tmp_path / "test.fnirsflow.zip"
        export_package(outdir, pkg_path)

        import_dir = tmp_path / "imported"
        result = import_package(pkg_path, import_dir, relink_data=True, data_root="/new/path")
        assert result["relinked"] is True

        imported_manifest = json.loads((import_dir / "data_manifest.json").read_text())
        assert imported_manifest["local_root"] == "/new/path"

    def test_check_package_integrity(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        pkg_path = tmp_path / "test.fnirsflow.zip"
        export_package(outdir, pkg_path)

        result = check_package_integrity(pkg_path)
        assert result["valid"] is True

    def test_check_missing_package(self, tmp_path):
        result = check_package_integrity(tmp_path / "nonexistent.zip")
        assert result["valid"] is False
