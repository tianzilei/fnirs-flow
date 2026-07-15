"""Tests for reportlets module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fnirs_flow.exporters.reportlets import (
    generate_package_report,
    generate_project_report,
    generate_run_reportlet,
)


@pytest.fixture
def sample_run_ctx() -> dict:
    """Sample run context for testing."""
    return {
        "run_id": "sub-01_ses-01_run-01",
        "subject": "sub-01",
        "session": "ses-01",
        "run": "run-01",
        "status": "completed",
        "steps_completed": ["read_run", "optical_density", "qc"],
        "errors": [],
    }


@pytest.fixture
def sample_artifacts() -> list[dict]:
    """Sample artifacts list for testing."""
    return [
        {
            "step_id": "read_run",
            "artifact_type": "raw_data",
            "sha256": "abc123def456" * 4,
        },
        {
            "step_id": "optical_density",
            "artifact_type": "processed_data",
            "sha256": "789xyz012abc" * 4,
        },
    ]


@pytest.fixture
def sample_runs() -> list[dict]:
    """Sample runs list for testing."""
    return [
        {
            "run_id": "sub-01_ses-01_run-01",
            "subject": "sub-01",
            "session": "ses-01",
            "status": "completed",
            "steps_completed": ["read_run", "qc"],
        },
        {
            "run_id": "sub-02_ses-01_run-01",
            "subject": "sub-02",
            "session": "ses-01",
            "status": "failed",
            "steps_completed": ["read_run"],
        },
        {
            "run_id": "sub-03_ses-01_run-01",
            "subject": "sub-03",
            "session": "ses-01",
            "status": "pending",
            "steps_completed": [],
        },
    ]


@pytest.fixture
def sample_risks() -> list[dict]:
    """Sample risks list for testing."""
    return [
        {
            "severity": "fatal",
            "domain": "security",
            "code": "atom-manifest-missing",
            "message": "Missing capability manifest for custom atom",
        },
        {
            "severity": "high",
            "domain": "qc",
            "code": "qc-sci-below-threshold",
            "message": "SCI below threshold for 3 channels",
        },
    ]


class TestGenerateRunReportlet:
    """Tests for generate_run_reportlet function."""

    def test_generates_markdown_file(
        self, tmp_path: Path, sample_run_ctx: dict, sample_artifacts: list[dict]
    ) -> None:
        """Test that markdown reportlet is generated."""
        md_path = generate_run_reportlet(sample_run_ctx, sample_artifacts, tmp_path)

        assert md_path.exists()
        assert md_path.name == "sub-01_ses-01_run-01_reportlet.md"
        assert md_path.suffix == ".md"

    def test_generates_json_file(
        self, tmp_path: Path, sample_run_ctx: dict, sample_artifacts: list[dict]
    ) -> None:
        """Test that JSON reportlet is generated."""
        generate_run_reportlet(sample_run_ctx, sample_artifacts, tmp_path)

        json_path = tmp_path / "sub-01_ses-01_run-01_reportlet.json"
        assert json_path.exists()

        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["run_id"] == "sub-01_ses-01_run-01"
        assert data["subject"] == "sub-01"
        assert data["status"] == "completed"

    def test_markdown_contains_run_info(
        self, tmp_path: Path, sample_run_ctx: dict, sample_artifacts: list[dict]
    ) -> None:
        """Test that markdown contains run information."""
        md_path = generate_run_reportlet(sample_run_ctx, sample_artifacts, tmp_path)

        content = md_path.read_text(encoding="utf-8")
        assert "sub-01" in content
        assert "ses-01" in content
        assert "run-01" in content
        assert "completed" in content

    def test_markdown_contains_artifacts_table(
        self, tmp_path: Path, sample_run_ctx: dict, sample_artifacts: list[dict]
    ) -> None:
        """Test that markdown contains artifacts table."""
        md_path = generate_run_reportlet(sample_run_ctx, sample_artifacts, tmp_path)

        content = md_path.read_text(encoding="utf-8")
        assert "Artifacts" in content
        assert "read_run" in content
        assert "optical_density" in content

    def test_handles_empty_artifacts(
        self, tmp_path: Path, sample_run_ctx: dict
    ) -> None:
        """Test handling of empty artifacts list."""
        md_path = generate_run_reportlet(sample_run_ctx, [], tmp_path)

        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "**Artifacts:** 0" in content

    def test_handles_errors(
        self, tmp_path: Path, sample_artifacts: list[dict]
    ) -> None:
        """Test handling of run with errors."""
        run_ctx = {
            "run_id": "sub-01_failed",
            "subject": "sub-01",
            "session": "ses-01",
            "run": "run-01",
            "status": "failed",
            "steps_completed": ["read_run"],
            "errors": ["ImportError: MNE not available", "Timeout during QC"],
        }

        md_path = generate_run_reportlet(run_ctx, sample_artifacts, tmp_path)

        content = md_path.read_text(encoding="utf-8")
        assert "Errors" in content
        assert "MNE not available" in content
        assert "Timeout during QC" in content

    def test_creates_output_directory(
        self, tmp_path: Path, sample_run_ctx: dict, sample_artifacts: list[dict]
    ) -> None:
        """Test that output directory is created if it doesn't exist."""
        nested_dir = tmp_path / "reports" / "sub-01"
        md_path = generate_run_reportlet(sample_run_ctx, sample_artifacts, nested_dir)

        assert nested_dir.exists()
        assert md_path.exists()


class TestGenerateProjectReport:
    """Tests for generate_project_report function."""

    def test_generates_markdown_file(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test that project report markdown is generated."""
        md_path = generate_project_report(sample_runs, sample_risks, tmp_path)

        assert md_path.exists()
        assert md_path.name == "project_report.md"

    def test_generates_json_file(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test that project report JSON is generated."""
        generate_project_report(sample_runs, sample_risks, tmp_path)

        json_path = tmp_path / "project_report.json"
        assert json_path.exists()

        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["summary"]["total_runs"] == 3
        assert data["summary"]["successful"] == 1
        assert data["summary"]["failed"] == 1
        assert data["summary"]["pending"] == 1

    def test_markdown_contains_summary(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test that markdown contains summary section."""
        md_path = generate_project_report(sample_runs, sample_risks, tmp_path)

        content = md_path.read_text(encoding="utf-8")
        assert "Summary" in content
        assert "**Total runs:** 3" in content
        assert "**Successful:** 1" in content
        assert "**Failed:** 1" in content

    def test_markdown_contains_runs_table(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test that markdown contains runs table."""
        md_path = generate_project_report(sample_runs, sample_risks, tmp_path)

        content = md_path.read_text(encoding="utf-8")
        assert "Runs" in content
        assert "sub-01" in content
        assert "sub-02" in content

    def test_markdown_contains_risks_table(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test that markdown contains risks table."""
        md_path = generate_project_report(sample_runs, sample_risks, tmp_path)

        content = md_path.read_text(encoding="utf-8")
        assert "Risks" in content
        assert "fatal" in content
        assert "atom-manifest-missing" in content

    def test_handles_empty_runs(
        self, tmp_path: Path, sample_risks: list[dict]
    ) -> None:
        """Test handling of empty runs list."""
        md_path = generate_project_report([], sample_risks, tmp_path)

        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "**Total runs:** 0" in content

    def test_handles_empty_risks(
        self, tmp_path: Path, sample_runs: list[dict]
    ) -> None:
        """Test handling of empty risks list."""
        md_path = generate_project_report(sample_runs, [], tmp_path)

        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "**Fatal risks:** 0" in content


class TestGeneratePackageReport:
    """Tests for generate_package_report function."""

    def test_generates_markdown_file(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test that package report markdown is generated."""
        # Create project report first
        project_report_path = generate_project_report(sample_runs, sample_risks, tmp_path)

        # Create some run reportlets
        run_reportlets = []
        for run in sample_runs[:2]:
            md_path = tmp_path / f"{run['run_id']}_reportlet.md"
            md_path.write_text(f"# Report for {run['run_id']}")
            run_reportlets.append(md_path)

        md_path = generate_package_report(
            project_report_path, run_reportlets, "reproducibility_package", tmp_path
        )

        assert md_path.exists()
        assert md_path.name == "package_report.md"

    def test_contains_profile_info(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test that package report contains profile information."""
        project_report_path = generate_project_report(sample_runs, sample_risks, tmp_path)

        md_path = generate_package_report(
            project_report_path, [], "submission_package", tmp_path
        )

        content = md_path.read_text(encoding="utf-8")
        assert "submission_package" in content

    def test_includes_project_summary(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test that package report includes project summary."""
        project_report_path = generate_project_report(sample_runs, sample_risks, tmp_path)

        md_path = generate_package_report(
            project_report_path, [], "reproducibility_package", tmp_path
        )

        content = md_path.read_text(encoding="utf-8")
        assert "Summary" in content
        assert "Total runs" in content

    def test_lists_run_reportlets(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test that package report lists run reportlets."""
        project_report_path = generate_project_report(sample_runs, sample_risks, tmp_path)

        run_reportlets = []
        for run in sample_runs[:2]:
            md_path = tmp_path / f"{run['run_id']}_reportlet.md"
            md_path.write_text(f"# Report for {run['run_id']}")
            run_reportlets.append(md_path)

        md_path = generate_package_report(
            project_report_path, run_reportlets, "reproducibility_package", tmp_path
        )

        content = md_path.read_text(encoding="utf-8")
        assert "Run Reportlets" in content
        assert "sub-01_ses-01_run-01_reportlet.md" in content
        assert "sub-02_ses-01_run-01_reportlet.md" in content

    def test_handles_missing_project_report(
        self, tmp_path: Path
    ) -> None:
        """Test handling of missing project report."""
        missing_path = tmp_path / "nonexistent" / "project_report.md"

        md_path = generate_package_report(
            missing_path, [], "reviewer_package", tmp_path
        )

        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "reviewer_package" in content

    def test_handles_empty_run_reportlets(
        self, tmp_path: Path, sample_runs: list[dict], sample_risks: list[dict]
    ) -> None:
        """Test handling of empty run reportlets list."""
        project_report_path = generate_project_report(sample_runs, sample_risks, tmp_path)

        md_path = generate_package_report(
            project_report_path, [], "reproducibility_package", tmp_path
        )

        assert md_path.exists()
