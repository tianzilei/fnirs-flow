from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from fnirs_flow.execution.models import ExecutionRequest
from fnirs_flow.execution.orchestrator_impl import ExecutionService
from fnirs_flow.settings import Settings


def test_spawn_process_backend_preserves_manifest_order_and_records_effective_config(tmp_path):
    compiled = tmp_path / "compiled"
    compiled.mkdir()
    (compiled / "plan.json").write_text("{}", encoding="utf-8")
    (compiled / "execution_dag.json").write_text(
        json.dumps({"atoms": [], "execution_layers": [], "edges": []}), encoding="utf-8"
    )
    (compiled / "data_manifest.json").write_text(
        json.dumps(
            {
                "subject_session_runs": [
                    {"subject": "02", "run": "01", "path": "missing-02.snirf"},
                    {"subject": "01", "run": "02", "path": "missing-01.snirf"},
                ]
            }
        ),
        encoding="utf-8",
    )
    service = ExecutionService(
        runtime_settings=Settings(
            job_workers=1,
            run_workers=2,
            blas_threads=1,
            parallel_backend="process",
        )
    )
    result = service.execute(ExecutionRequest(project_dir=str(tmp_path), outdir=str(tmp_path)))

    assert result.concurrency["backend"] == "process"
    assert result.concurrency["run_workers"] == 2
    assert [run.run_id for run in result.run_results] == ["sub-02_run-01", "sub-01_run-02"]
    assert [run.status for run in result.run_results] == ["skipped", "skipped"]
    summary = json.loads((tmp_path / "logs" / "execution_summary.json").read_text(encoding="utf-8"))
    assert summary["concurrency"] == result.concurrency
    provenance = json.loads((tmp_path / "logs" / "provenance_log.json").read_text(encoding="utf-8"))
    assert provenance[0]["parameters"]["concurrency"]["backend"] == "process"


def test_spawn_process_backend_can_start_inside_api_style_thread(tmp_path):
    compiled = tmp_path / "compiled"
    compiled.mkdir()
    (compiled / "plan.json").write_text("{}", encoding="utf-8")
    (compiled / "execution_dag.json").write_text(
        json.dumps({"atoms": [], "execution_layers": [], "edges": []}), encoding="utf-8"
    )
    (compiled / "data_manifest.json").write_text(
        json.dumps(
            {
                "subject_session_runs": [
                    {"subject": "01", "run": "01", "path": "missing-01.snirf"},
                    {"subject": "02", "run": "01", "path": "missing-02.snirf"},
                ]
            }
        ),
        encoding="utf-8",
    )

    def execute():
        return ExecutionService(
            runtime_settings=Settings(
                job_workers=1, run_workers=2, blas_threads=1, parallel_backend="process"
            )
        ).execute(ExecutionRequest(project_dir=str(tmp_path), outdir=str(tmp_path)))

    with ThreadPoolExecutor(max_workers=1) as api_pool:
        result = api_pool.submit(execute).result(timeout=30)
    assert result.concurrency["backend"] == "process"
    assert [run.run_id for run in result.run_results] == ["sub-01_run-01", "sub-02_run-01"]
