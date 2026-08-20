"""Tests for reports, package export/import."""

from __future__ import annotations

import json
import warnings
import zipfile

import pytest

from fnirs_flow.exporters.package_exporter import export_package, get_package_contents
from fnirs_flow.exporters.package_importer import check_package_integrity, fork_package, import_package
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
            "preprocessing_atoms": [
                {"atom_id": "od", "atom_type": "optical_density", "parameters": {}},
            ],
            "analysis_atoms": [
                {
                    "atom_id": "glm",
                    "atom_type": "first_level_glm",
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

    def test_fork_package_ignores_macos_metadata_sidecars(self, tmp_path):
        package_dir = tmp_path / "imported"
        package_dir.mkdir()
        (package_dir / "plan.json").write_text("{}", encoding="utf-8")
        (package_dir / "._plan.json").write_bytes(b"appledouble")
        (package_dir / ".DS_Store").write_bytes(b"finder")
        macosx = package_dir / "__MACOSX"
        macosx.mkdir()
        (macosx / "._plan.json").write_bytes(b"appledouble")
        (package_dir / "import_metadata.json").write_text(
            json.dumps({"read_only": True, "quarantined_atoms": []}),
            encoding="utf-8",
        )

        result = fork_package(package_dir, tmp_path / "forked", unfork=True)

        fork_dir = tmp_path / "forked"
        assert result["fork_dir"] == str(fork_dir)
        assert (fork_dir / "plan.json").exists()
        assert not (fork_dir / "._plan.json").exists()
        assert not (fork_dir / ".DS_Store").exists()
        assert not (fork_dir / "__MACOSX").exists()

    def test_import_package_rejects_duplicate_members(self, tmp_path):
        pkg_path = tmp_path / "duplicate.fnirsflow.zip"
        with zipfile.ZipFile(pkg_path, "w") as archive:
            archive.writestr("plan.json", "{}")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("plan.json", "{\"duplicate\": true}")
            archive.writestr("execution_dag.json", "{}")

        with pytest.raises(ValueError, match="duplicate paths"):
            import_package(pkg_path, tmp_path / "imported")

    def test_import_with_relink(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        # Add data manifest
        manifest = {"local_root": "/old/path", "dataset_id": "test"}
        (outdir / "data_manifest.json").write_text(json.dumps(manifest))

        pkg_path = tmp_path / "test.fnirsflow.zip"
        export_package(outdir, pkg_path)

        import_dir = tmp_path / "imported"
        data_root = tmp_path / "new-data"
        data_root.mkdir()
        result = import_package(pkg_path, import_dir, relink_data=True, data_root=data_root)
        assert result["relinked"]

        imported_manifest = json.loads((import_dir / "data_manifest.json").read_text())
        assert imported_manifest["local_root"] == ""

    def test_exported_data_manifest_contains_only_portable_data_uris(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        old_root = tmp_path / "source-machine"
        relative = "sub-01/nirs/run.snirf"
        (outdir / "data_manifest.json").write_text(
            json.dumps(
                {
                    "dataset_id": "portable-dataset",
                    "local_root": str(old_root),
                    "access_instructions": f"Local dataset expected at {old_root}",
                    "subject_session_runs": [
                        {
                            "relative_path": relative,
                            "path": str(old_root / relative),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        package_path = tmp_path / "portable.fnirsflow.zip"

        export_package(outdir, package_path)

        with zipfile.ZipFile(package_path) as archive:
            manifest = json.loads(archive.read("data_manifest.json"))
        serialized = json.dumps(manifest)
        assert manifest["local_root"] == ""
        assert manifest["requires_data_binding"]
        assert manifest["access_instructions"] == (
            "Bind external-data://portable-dataset/ to a local dataset directory before rerunning."
        )
        assert manifest["subject_session_runs"][0]["path"] == (
            "external-data://portable-dataset/sub-01/nirs/run.snirf"
        )
        assert str(old_root) not in serialized

    def test_export_sanitizes_legacy_artifact_and_provenance_paths(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        derivative = outdir / "derivatives" / "result.csv"
        derivative.parent.mkdir()
        derivative.write_text("value\n1\n", encoding="utf-8")
        (outdir / "artifact_manifest.json").write_text(
            json.dumps(
                {
                    "artifacts": [
                        {
                            "path": str(derivative),
                            "resolved_path": str(derivative),
                            "relative_path": "derivatives/result.csv",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (outdir / "provenance_log.json").write_text(
            json.dumps([{"parameters": {"output": str(derivative)}}]),
            encoding="utf-8",
        )
        package_path = tmp_path / "portable-json.fnirsflow.zip"

        export_package(outdir, package_path)

        with zipfile.ZipFile(package_path) as archive:
            artifact_text = archive.read("artifact_manifest.json").decode()
            provenance_text = archive.read("provenance_log.json").decode()
        assert str(outdir) not in artifact_text
        assert str(outdir) not in provenance_text
        assert "project://outputs/derivatives/result.csv" in artifact_text
        assert "project://outputs/derivatives/result.csv" in provenance_text

    def test_reproducibility_package_prefers_runtime_manifest_and_results(self, tmp_path):
        outdir = tmp_path / "output"
        (outdir / "compiled").mkdir(parents=True)
        (outdir / "logs").mkdir()
        (outdir / "derivatives" / "channel").mkdir(parents=True)
        (outdir / "compiled" / "plan.json").write_text("{}", encoding="utf-8")
        (outdir / "compiled" / "execution_dag.json").write_text("{}", encoding="utf-8")
        (outdir / "compiled" / "artifact_manifest.json").write_text('{"scope":"compile"}', encoding="utf-8")
        (outdir / "logs" / "artifact_manifest.json").write_text('{"scope":"runtime"}', encoding="utf-8")
        (outdir / "logs" / "execution_summary.json").write_text(
            '{"successful_runs":1,"failed_runs":0}', encoding="utf-8"
        )
        result_path = outdir / "derivatives" / "channel" / "result.csv"
        result_path.write_text("beta\n1.0\n", encoding="utf-8")
        package = tmp_path / "runtime.fnirsflow.zip"

        export_package(outdir, package)

        with zipfile.ZipFile(package) as archive:
            assert json.loads(archive.read("artifact_manifest.json"))["scope"] == "runtime"
            assert json.loads(archive.read("execution_summary.json"))["successful_runs"] == 1
            assert "derivatives/channel/result.csv" in archive.namelist()

    def test_reproducibility_package_includes_group_metadata_artifacts(self, tmp_path):
        outdir = tmp_path / "output"
        (outdir / "compiled").mkdir(parents=True)
        (outdir / "logs").mkdir()
        group_dir = outdir / "derivatives" / "group"
        group_dir.mkdir(parents=True)
        (outdir / "compiled" / "plan.json").write_text("{}", encoding="utf-8")
        (outdir / "compiled" / "execution_dag.json").write_text("{}", encoding="utf-8")
        for name in [
            "participant_table_manifest.json",
            "analysis_table.csv",
            "group_design_matrix.csv",
            "contrast_matrix.csv",
            "multiple_comparison_results.csv",
            "sensitivity_analysis_results.csv",
            "cluster_inference_results.csv",
        ]:
            content = "{}\n" if name.endswith(".json") else "placeholder\n"
            (group_dir / name).write_text(content, encoding="utf-8")

        package = tmp_path / "group.fnirsflow.zip"
        export_package(outdir, package)

        with zipfile.ZipFile(package) as archive:
            names = set(archive.namelist())
        assert "derivatives/group/participant_table_manifest.json" in names
        assert "derivatives/group/analysis_table.csv" in names
        assert "derivatives/group/group_design_matrix.csv" in names
        assert "derivatives/group/contrast_matrix.csv" in names
        assert "derivatives/group/multiple_comparison_results.csv" in names
        assert "derivatives/group/sensitivity_analysis_results.csv" in names
        assert "derivatives/group/cluster_inference_results.csv" in names

    def test_export_package_rejects_more_than_ten_mib_uncompressed(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        result = outdir / "derivatives" / "group" / "large_statistics.txt"
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text("x" * (10 * 1024**2), encoding="utf-8")
        package = tmp_path / "oversized.fnirsflow.zip"

        with pytest.raises(ValueError, match="10 MiB"):
            export_package(outdir, package)

        assert not package.exists()

    def test_check_package_integrity(self, tmp_path):
        outdir = self._setup_output_dir(tmp_path)
        pkg_path = tmp_path / "test.fnirsflow.zip"
        export_package(outdir, pkg_path)

        result = check_package_integrity(pkg_path)
        assert result["valid"]

    def test_check_missing_package(self, tmp_path):
        result = check_package_integrity(tmp_path / "nonexistent.zip")
        assert not result["valid"]
