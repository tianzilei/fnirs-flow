"""Tests for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from cli import main


class TestCLI:
    def test_no_command_returns_0(self):
        result = main([])
        assert result == 0

    def test_validate_flow_success(self, tmp_path):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        result = main(["validate-flow", str(demo_path)])
        assert result == 0

    def test_validate_flow_invalid(self, tmp_path):
        bad_flow = tmp_path / "bad.json"
        bad_flow.write_text('{"schema_version": "0.1.0"}')
        result = main(["validate-flow", str(bad_flow)])
        assert result == 1

    def test_compile_flow(self, tmp_path):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        outdir = tmp_path / "compiled"
        result = main(["compile-flow", str(demo_path), "--outdir", str(outdir)])
        assert result == 0
        # Files are now in compiled/ subdirectory
        assert (outdir / "compiled" / "plan.json").exists()
        assert (outdir / "compiled" / "execution_dag.json").exists()

    def test_discover_dataset(self, tmp_path):
        result = main(["discover-dataset", "mne-fnirs-motor", "--outdir", str(tmp_path)])
        assert result == 0

    def test_discover_unknown_dataset(self, tmp_path):
        result = main(["discover-dataset", "nonexistent", "--outdir", str(tmp_path)])
        assert result == 1

    def test_dry_run(self, tmp_path):
        # Create minimal execution_dag.json for dry-run
        dag = {"nodes": [{"step_id": "s1"}], "execution_layers": [["s1"]]}
        (tmp_path / "execution_dag.json").write_text(json.dumps(dag))
        result = main(["dry-run", str(tmp_path), "--outdir", str(tmp_path / "dry")])
        assert result == 0

    def test_dry_run_missing_dag(self, tmp_path):
        result = main(["dry-run", str(tmp_path), "--outdir", str(tmp_path / "dry")])
        assert result == 1

    def test_dry_run_accepts_execution_entity_filters(self, tmp_path):
        dag = {"nodes": [{"step_id": "s1"}], "execution_layers": [["s1"]]}
        (tmp_path / "execution_dag.json").write_text(json.dumps(dag))
        (tmp_path / "data_manifest.json").write_text(
            json.dumps(
                {
                    "subject_session_runs": [
                        {"subject": "01", "task": "covert", "path": "a.snirf"},
                        {"subject": "01", "task": "overt", "path": "b.snirf"},
                    ]
                }
            )
        )

        result = main(
            [
                "dry-run",
                str(tmp_path),
                "--outdir",
                str(tmp_path / "dry"),
                "--task-label",
                "covert",
            ]
        )

        assert result == 0
        report = json.loads((tmp_path / "dry" / "derivatives" / "reports" / "run_report.json").read_text())
        assert report["total_runs"] == 1
        assert report["planned_runs"][0]["task"] == "covert"

    def test_generate_flow_draft_cli(self, tmp_path):
        out = tmp_path / "draft.json"
        result = main(["generate-flow-draft", "task", "--output", str(out)])
        assert result == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["flow_id"].startswith("draft-task-")
        assert "ai_generation" in data["metadata"]
        assert data["metadata"]["ai_generation"]["not_used_for_execution"]
