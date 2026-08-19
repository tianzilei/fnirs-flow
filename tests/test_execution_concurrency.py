from __future__ import annotations

import warnings

import pytest

from fnirs_flow.execution.concurrency import resolve_concurrency
from fnirs_flow.execution.run_worker import RunWorkerRequest, RunWorkerResponse
from fnirs_flow.settings import Settings, SettingsValidationError


def test_settings_reject_invalid_parallel_backend(monkeypatch):
    monkeypatch.setenv("FNIRS_PARALLEL_BACKEND", "threads")
    with pytest.raises(SettingsValidationError, match="serial.*process"):
        Settings.from_env()


@pytest.mark.parametrize("name,value", [("FNIRS_RUN_WORKERS", "0"), ("FNIRS_BLAS_THREADS", "-1")])
def test_settings_reject_non_positive_worker_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SettingsValidationError, match=name):
        Settings.from_env()


def test_process_backend_falls_back_before_execution_for_single_run():
    effective = resolve_concurrency(
        Settings(parallel_backend="process", run_workers=4, blas_threads=1),
        run_count=1,
    )
    assert effective.backend == "serial"
    assert effective.run_workers == 1
    assert effective.fallback_reason == "fewer_than_two_runs"


def test_concurrency_budget_reduces_oversubscription(monkeypatch):
    monkeypatch.setattr("fnirs_flow.execution.concurrency.os.cpu_count", lambda: 4)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        effective = resolve_concurrency(
            Settings(job_workers=2, parallel_backend="process", run_workers=4, blas_threads=2),
            run_count=8,
        )
    assert effective.job_workers * effective.run_workers * effective.blas_threads <= 4
    assert caught


def test_worker_contract_json_round_trip():
    request = RunWorkerRequest(
        run_context={"run_id": "sub-01_run-01", "data_path": "run.snirf"},
        plan={"atoms": []},
        dag={"atoms": []},
        outdir="outputs",
        blas_threads=1,
    )
    assert RunWorkerRequest.model_validate_json(request.model_dump_json()) == request

    response = RunWorkerResponse.model_validate(
        {
            "run_id": "sub-01_run-01",
            "result": {"run_id": "sub-01_run-01", "status": "completed"},
            "events": [{"type": "run_completed"}],
        }
    )
    assert response.result.status == "completed"
