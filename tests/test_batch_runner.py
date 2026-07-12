"""Tests for batch runner and execution engine."""

from __future__ import annotations

import json

from fnirs_flow.execution.artifacts import (
    ArtifactRecord,
    ArtifactStore,
    write_artifact_manifest,
)
from fnirs_flow.execution.batch import run_batch
from fnirs_flow.execution.batch_adapter import run_batch_with_adapter
from fnirs_flow.execution.engine import DryRunResult, RunContext, dry_run
from fnirs_flow.execution.failures import FailureStore
from fnirs_flow.execution.provenance import ProvenanceRecord


class TestDryRun:
    def test_dry_run_without_manifest(self, tmp_path):
        # Create a minimal execution_dag.json
        dag = {
            "nodes": [{"step_id": "s1"}, {"step_id": "s2"}],
            "execution_layers": [["s1"], ["s2"]],
        }
        (tmp_path / "execution_dag.json").write_text(json.dumps(dag))

        result = dry_run(tmp_path)
        assert result.total_runs == 1
        assert result.planned_runs[0].run_id == "dry-run-placeholder"

    def test_dry_run_with_manifest(self, tmp_path):
        dag = {"nodes": [{"step_id": "s1"}], "execution_layers": [["s1"]]}
        (tmp_path / "execution_dag.json").write_text(json.dumps(dag))

        manifest = {
            "subject_session_runs": [
                {"subject": "01", "session": "01", "run": "01", "path": "/data/f.snirf"},
                {"subject": "02", "session": "01", "run": "01", "path": "/data/f2.snirf"},
            ]
        }
        (tmp_path / "data_manifest.json").write_text(json.dumps(manifest))

        result = dry_run(tmp_path)
        assert result.total_runs == 2
        assert result.planned_runs[0].run_id == "sub-01_ses-01_run-01"
        assert result.planned_runs[0].subject == "01"
        assert result.planned_runs[0].data_path == "/data/f.snirf"
        assert result.planned_runs[1].subject == "02"

    def test_dry_run_with_bids_manifest_fields(self, tmp_path):
        dag = {"nodes": [{"step_id": "s1"}], "execution_layers": [["s1"]]}
        (tmp_path / "execution_dag.json").write_text(json.dumps(dag))

        manifest = {
            "subject_session_runs": [
                {
                    "subject": "01",
                    "task": "tapping",
                    "path": "/data/sub-01_task-tapping_nirs.snirf",
                    "relative_path": "sub-01/nirs/sub-01_task-tapping_nirs.snirf",
                    "data_sha256": "abc123",
                    "source_file_role": "raw_snirf",
                }
            ]
        }
        (tmp_path / "data_manifest.json").write_text(json.dumps(manifest))

        result = dry_run(tmp_path)
        run = result.planned_runs[0]
        assert run.run_id == "sub-01_task-tapping"
        assert run.task == "tapping"
        assert run.data_path == "/data/sub-01_task-tapping_nirs.snirf"
        assert run.relative_path == "sub-01/nirs/sub-01_task-tapping_nirs.snirf"
        assert run.data_sha256 == "abc123"
        assert run.source_file_role == "raw_snirf"

    def test_dry_run_missing_dag_raises(self, tmp_path):
        try:
            dry_run(tmp_path)
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass


class TestBatchRunner:
    def test_batch_all_success(self):
        dry = DryRunResult(
            total_runs=2,
            planned_runs=[
                RunContext(run_id="r1", status="planned", steps_completed=["s1"]),
                RunContext(run_id="r2", status="planned", steps_completed=["s1"]),
            ],
        )
        result = run_batch(dry)
        assert result.total == 2
        assert len(result.successful) == 2
        assert len(result.failed) == 0

    def test_batch_with_failure_continue(self):
        def execute(ctx):
            if ctx.run_id == "r2":
                raise RuntimeError("Simulated failure")

        dry = DryRunResult(
            total_runs=3,
            planned_runs=[
                RunContext(run_id="r1", status="planned"),
                RunContext(run_id="r2", status="planned"),
                RunContext(run_id="r3", status="planned"),
            ],
        )
        result = run_batch(dry, execute_fn=execute, continue_on_failure=True)
        assert len(result.successful) == 2
        assert len(result.failed) == 1
        assert result.failed[0].run_id == "r2"

    def test_batch_with_failure_stop(self):
        def execute(ctx):
            raise RuntimeError("Always fail")

        dry = DryRunResult(
            total_runs=3,
            planned_runs=[
                RunContext(run_id="r1", status="planned"),
                RunContext(run_id="r2", status="planned"),
                RunContext(run_id="r3", status="planned"),
            ],
        )
        result = run_batch(dry, execute_fn=execute, continue_on_failure=False)
        assert len(result.failed) == 1  # Only first failure

    def test_batch_summary(self):
        dry = DryRunResult(
            total_runs=2,
            planned_runs=[RunContext(run_id="r1"), RunContext(run_id="r2")],
        )
        result = run_batch(dry)
        s = result.summary()
        assert s["total"] == 2
        assert s["successful"] == 2

    def test_batch_adapter_placeholder_run_writes_manifests(self, tmp_path):
        dry = DryRunResult(
            total_runs=1,
            planned_runs=[RunContext(run_id="r1", status="planned")],
        )
        result = run_batch_with_adapter(dry, {"flow_hash": "abc123"}, tmp_path)
        assert result.total == 1
        assert len(result.successful) == 1
        assert (tmp_path / "artifact_manifest.json").exists()
        assert (tmp_path / "provenance_log.json").exists()


class TestFailureStore:
    def test_write_csv(self, tmp_path):
        store = FailureStore()
        store.register(
            subject="01",
            session="01",
            run="01",
            atom_id="atom-1",
            exception_type="RuntimeError",
            message="Something went wrong",
        )
        path = store.write_csv(tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "01" in content
        assert "Something went wrong" in content

    def test_write_json(self, tmp_path):
        store = FailureStore()
        store.register(
            subject="01",
            session="01",
            run="01",
            atom_id="atom-1",
            message="err1",
        )
        path = store.write_json(tmp_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1


class TestArtifactStore:
    def test_register_and_manifest(self):
        store = ArtifactStore()
        store.register(
            ArtifactRecord(
                artifact_id="a1",
                step_id="s1",
                artifact_type="qc_table",
            )
        )
        manifest = store.to_manifest(run_id="run-001")
        assert len(manifest.artifacts) == 1
        assert manifest.run_id == "run-001"

    def test_write_manifest(self, tmp_path):
        store = ArtifactStore()
        store.register(ArtifactRecord(artifact_id="a1", path="/out/qc.csv"))
        manifest = store.to_manifest()
        path = write_artifact_manifest(manifest, tmp_path)
        assert path.exists()


class TestProvenance:
    def test_log_and_write(self, tmp_path):
        prov = ProvenanceRecord()
        prov.log("step1", {"param": "value"})
        prov.log("step2", {"param": "value2"}, input_hashes={"f1": "abc"})
        assert len(prov.all()) == 2
        path = prov.write(tmp_path)
        assert path.exists()
