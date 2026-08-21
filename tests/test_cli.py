"""Tests for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli import main
from fnirs_flow.execution.models import ExecutionResult, RunExecutionResult


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

    def test_discover_accepts_explicit_local_data_root(self, tmp_path):
        data_root = tmp_path / "BIDS-NIRS-Tapping-master"
        data_root.mkdir()
        manifest = MagicMock(
            files=[],
            subject_session_runs=[],
            local_root="",
            runtime_local_root=str(data_root),
        )

        with patch(
            "fnirs_flow.application.data_use_cases.discover_dataset_to_workspace",
            return_value=manifest,
        ) as discover:
            result = main(
                [
                    "discover",
                    "bids-nirs-tapping",
                    "--outdir",
                    str(tmp_path / "out"),
                    "--data-root",
                    str(data_root),
                ]
            )

        assert result == 0
        discover.assert_called_once_with(
            "bids-nirs-tapping",
            str(tmp_path / "out"),
            data_root=str(data_root),
        )

    def test_run_returns_nonzero_when_all_runs_are_skipped(self, tmp_path):
        execution = ExecutionResult(
            total_runs=1,
            successful_runs=0,
            failed_runs=0,
            skipped_runs=1,
            run_results=[RunExecutionResult(run_id="sub-01", status="skipped")],
        )

        with patch(
            "fnirs_flow.application.execution_use_cases.execute_compiled_project",
            return_value=execution,
        ):
            result = main(["run", str(tmp_path), "--outdir", str(tmp_path)])

        assert result == 1

    def test_backends_output_is_ascii_safe(self, capsys):
        registry = MagicMock()
        registry.list_all.return_value = ["mne_nirs", "cedalion"]
        registry.is_available.side_effect = [True, False]
        registry.get.return_value = None

        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=registry):
            assert main(["backends"]) == 0

        output = capsys.readouterr().out
        output.encode("ascii")
        assert "[OK] Available" in output
        assert "[--] Not Available" in output

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

    def test_dry_run_accepts_bids_prefixed_entity_filters(self, tmp_path):
        dag = {"nodes": [{"step_id": "s1"}], "execution_layers": [["s1"]]}
        (tmp_path / "execution_dag.json").write_text(json.dumps(dag))
        (tmp_path / "data_manifest.json").write_text(
            json.dumps(
                {
                    "subject_session_runs": [
                        {"subject": "01", "session": "pre", "task": "covert", "run": "01", "path": "a.snirf"},
                        {"subject": "02", "session": "post", "task": "overt", "run": "02", "path": "b.snirf"},
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
                "--participant-label",
                "sub-01",
                "--session-label",
                "ses-pre",
                "--task-label",
                "task-covert",
                "--run-label",
                "run-01",
            ]
        )

        assert result == 0
        report = json.loads((tmp_path / "dry/derivatives/reports/run_report.json").read_text())
        assert [run["run_id"] for run in report["planned_runs"]] == [
            "sub-01_ses-pre_task-covert_run-01"
        ]

    def test_generate_flow_draft_cli(self, tmp_path):
        out = tmp_path / "draft.json"
        result = main(["generate-flow-draft", "task", "--output", str(out)])
        assert result == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["flow_id"].startswith("draft-task-")
        assert "ai_generation" in data["metadata"]
        assert data["metadata"]["ai_generation"]["not_used_for_execution"]
