"""Tests for dry-run report output (--outdir) with derivatives-style layout."""

from __future__ import annotations

import json
from pathlib import Path

from fnirs_flow.compiler.compiler import compile_flow
from fnirs_flow.execution.engine import dry_run


def _compile_demo(tmp_path) -> Path:
    """Compile the demo flow and return the output directory (root, not compiled/)."""
    demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
    flow_dict = json.loads(demo_path.read_text())
    outdir = tmp_path / "compiled"
    compile_flow(flow_dict, outdir)
    return outdir


class TestDryRunReport:
    def test_writes_report_md(self, tmp_path):
        compiled = _compile_demo(tmp_path)
        report_dir = tmp_path / "dryrun_output"
        dry_run(compiled, outdir=report_dir)

        # Reports are now in derivatives/reports/
        report_md = report_dir / "derivatives" / "reports" / "run_report.md"
        assert report_md.exists()
        content = report_md.read_text()
        assert "# Dry-Run Report" in content
        assert "Planned runs" in content
        assert "DAG nodes" in content

    def test_writes_report_json(self, tmp_path):
        compiled = _compile_demo(tmp_path)
        report_dir = tmp_path / "dryrun_output"
        dry_run(compiled, outdir=report_dir)

        report_json = report_dir / "derivatives" / "reports" / "run_report.json"
        assert report_json.exists()
        data = json.loads(report_json.read_text())
        assert "total_runs" in data
        assert "planned_runs" in data
        assert "plan_dir" in data
        assert "generated_at" in data

    def test_report_json_matches_result(self, tmp_path):
        compiled = _compile_demo(tmp_path)
        report_dir = tmp_path / "dryrun_output"
        result = dry_run(compiled, outdir=report_dir)

        data = json.loads((report_dir / "derivatives" / "reports" / "run_report.json").read_text())
        assert data["total_runs"] == result.total_runs
        assert len(data["planned_runs"]) == len(result.planned_runs)

    def test_no_outdir_still_works(self, tmp_path):
        compiled = _compile_demo(tmp_path)
        result = dry_run(compiled)
        assert result.total_runs >= 1
        assert result.summary["dag_nodes"] > 0

    def test_report_md_contains_run_ids(self, tmp_path):
        compiled = _compile_demo(tmp_path)
        report_dir = tmp_path / "dryrun_output"
        result = dry_run(compiled, outdir=report_dir)

        content = (report_dir / "derivatives" / "reports" / "run_report.md").read_text()
        for run in result.planned_runs:
            assert run.run_id in content

    def test_report_includes_bids_run_metadata(self, tmp_path):
        dag = {"nodes": [{"step_id": "s1"}], "execution_layers": [["s1"]]}
        (tmp_path / "execution_dag.json").write_text(json.dumps(dag))
        manifest = {
            "subject_session_runs": [
                {
                    "subject": "01",
                    "task": "tapping",
                    "path": "/data/sub-01_task-tapping_nirs.snirf",
                    "relative_path": "sub-01/nirs/sub-01_task-tapping_nirs.snirf",
                    "data_sha256": "abc123def4567890",
                    "source_file_role": "raw_snirf",
                }
            ]
        }
        (tmp_path / "data_manifest.json").write_text(json.dumps(manifest))
        report_dir = tmp_path / "dryrun_output"
        dry_run(tmp_path, outdir=report_dir)

        report_md = (report_dir / "derivatives" / "reports" / "run_report.md").read_text()
        report_json = json.loads((report_dir / "derivatives" / "reports" / "run_report.json").read_text())

        assert "sub-01_task-tapping" in report_md
        assert "sub-01/nirs/sub-01_task-tapping_nirs.snirf" in report_md
        assert "abc123def456" in report_md
        assert report_json["planned_runs"][0]["task"] == "tapping"
        assert report_json["planned_runs"][0]["data_path"] == "/data/sub-01_task-tapping_nirs.snirf"

    def test_creates_derivatives_layout(self, tmp_path):
        compiled = _compile_demo(tmp_path)
        report_dir = tmp_path / "dryrun_output"
        dry_run(compiled, outdir=report_dir)

        assert (report_dir / "compiled").exists()
        assert (report_dir / "work").exists()
        assert (report_dir / "derivatives").exists()
        assert (report_dir / "derivatives" / "reports").exists()
        assert (report_dir / "derivatives" / "group").exists()
        assert (report_dir / "logs").exists()
        assert (report_dir / "export").exists()

    def test_writes_run_history(self, tmp_path):
        compiled = _compile_demo(tmp_path)
        report_dir = tmp_path / "dryrun_output"
        dry_run(compiled, outdir=report_dir)

        history_path = report_dir / "logs" / "run_history.jsonl"
        assert history_path.exists()
        lines = history_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert "timestamp" in entry
        assert "total_runs" in entry
