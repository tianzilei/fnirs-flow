"""Real-data equivalence for serial and spawn-based run orchestration."""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

import pytest

from fnirs_flow.execution.models import ExecutionRequest
from fnirs_flow.execution.orchestrator_impl import ExecutionService
from fnirs_flow.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNIRF = (
    PROJECT_ROOT
    / "Sample"
    / "ds007738-download"
    / "sub-01"
    / "nirs"
    / "sub-01_task-covert_run-01_nirs.snirf"
)


def _project(directory: Path, source: Path) -> None:
    compiled = directory / "compiled"
    compiled.mkdir(parents=True)
    (compiled / "plan.json").write_text("{}", encoding="utf-8")
    (compiled / "execution_dag.json").write_text(
        json.dumps({"atoms": [], "execution_layers": [], "edges": []}), encoding="utf-8"
    )
    (compiled / "data_manifest.json").write_text(
        json.dumps(
            {
                "subject_session_runs": [
                    {"subject": "01", "run": "01", "path": str(source)},
                    {"subject": "01", "run": "02", "path": str(source)},
                ]
            }
        ),
        encoding="utf-8",
    )


def test_real_snirf_serial_process_equivalence(tmp_path):
    source = Path(os.environ.get("FNIRS_TEST_SNIRF", str(DEFAULT_SNIRF)))
    if os.environ.get("FNIRS_REQUIRE_REAL_DATA") == "1" and not source.is_file():
        pytest.fail(f"Required real-data fixture is missing: {source}")
    if not source.is_file():
        pytest.skip("Set FNIRS_TEST_SNIRF to a real SNIRF file")

    serial_project = tmp_path / "serial"
    process_project = tmp_path / "process"
    _project(serial_project, source)
    _project(process_project, source)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Extraction of measurement date from SNIRF file failed.*")
        serial = ExecutionService(
            runtime_settings=Settings(job_workers=1, run_workers=1, blas_threads=1)
        ).execute(ExecutionRequest(project_dir=str(serial_project), outdir=str(serial_project)))
    process = ExecutionService(
        runtime_settings=Settings(
            job_workers=1, run_workers=2, blas_threads=1, parallel_backend="process"
        )
    ).execute(ExecutionRequest(project_dir=str(process_project), outdir=str(process_project)))

    assert [run.run_id for run in serial.run_results] == [run.run_id for run in process.run_results]
    assert [run.status for run in serial.run_results] == [run.status for run in process.run_results]
    def signature(run):
        return {
            "run_id": run.run_id,
            "status": run.status,
            "artifacts": [
                (item.get("artifact_id", ""), item.get("type", ""), item.get("checksum", ""))
                for item in run.artifacts
            ],
            "atom_statuses": [(item.atom_id, item.status, item.error_code) for item in run.atom_results],
            "channel_results": run.channel_results,
            "roi_results": run.roi_results,
        }

    assert [signature(run) for run in serial.run_results] == [signature(run) for run in process.run_results]
