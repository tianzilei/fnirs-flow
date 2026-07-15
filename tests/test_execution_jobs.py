"""Persistent execution job and attempt API tests."""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from fnirs_flow.api.app import app
from fnirs_flow.api.jobs import ExecutionJobManager
from fnirs_flow.api.models import ExecuteResult
from fnirs_flow.api.projects import ProjectStore
from fnirs_flow.execution.service import ExecutionCancelledError


def _result(attempt_id: str) -> ExecuteResult:
    return ExecuteResult(
        attempt_id=attempt_id,
        total_runs=1,
        successful=1,
        failed=0,
    )


def _wait_for(manager: ExecutionJobManager, project_id: str, attempt_id: str, status: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = manager.get(project_id, attempt_id)
        if job is not None and job.status == status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"attempt {attempt_id} did not reach {status}")


def test_job_persists_result_and_supports_attempt_query(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("job")

    def runner(store, project_id, *, attempt_id, **kwargs):
        return _result(attempt_id)

    manager = ExecutionJobManager(store, runner=runner, recover=False)
    job = manager.create(project.id)
    completed = _wait_for(manager, project.id, job.attempt_id, "completed")

    assert completed.result is not None
    assert completed.result.attempt_id == job.attempt_id
    persisted = json.loads(
        (store.get_output_dir(project.id) / "attempts" / job.attempt_id / "job.json").read_text(encoding="utf-8")
    )
    assert persisted["status"] == "completed"
    manager.shutdown()


def test_running_job_can_be_cancelled(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("cancel")
    started = threading.Event()

    def runner(store, project_id, *, attempt_id, cancel_check, **kwargs):
        started.set()
        while not cancel_check():
            time.sleep(0.005)
        raise ExecutionCancelledError("cancelled")

    manager = ExecutionJobManager(store, runner=runner, recover=False)
    job = manager.create(project.id)
    assert started.wait(timeout=2)
    cancelling = manager.cancel(project.id, job.attempt_id)
    assert cancelling is not None
    assert cancelling.status in {"cancelling", "cancelled"}
    cancelled = _wait_for(manager, project.id, job.attempt_id, "cancelled")
    assert cancelled.cancel_requested
    manager.shutdown()


def test_project_execution_cancellation_is_not_logged_as_failure(monkeypatch, tmp_path):
    import fnirs_flow.api.projects as projects_module
    from fnirs_flow.execution.service import ExecutionService

    store = ProjectStore(tmp_path)
    project = store.create("cancel logging")
    monkeypatch.setattr(projects_module, "validate_project_execution", lambda *_args: True)
    monkeypatch.setattr(projects_module, "create_snapshot", lambda *_args: None)
    info_messages = []
    error_messages = []
    monkeypatch.setattr(
        projects_module.logger,
        "info",
        lambda *args, **_kwargs: info_messages.append(args),
    )
    monkeypatch.setattr(
        projects_module.logger,
        "exception",
        lambda *args, **_kwargs: error_messages.append(args),
    )

    def cancel(_service, _request):
        raise ExecutionCancelledError("cancelled")

    monkeypatch.setattr(ExecutionService, "execute", cancel)
    with pytest.raises(ExecutionCancelledError):
        projects_module.execute_project_runs(store, project.id, attempt_id="attempt-cancel")

    assert store._projects[project.id]["state"]["last_execution_status"] == "cancelled"
    assert any("cancelled" in args[0].lower() for args in info_messages)
    assert error_messages == []


def test_restart_recovers_incomplete_attempt(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("recover")
    attempt_id = "attempt-restart"
    job_dir = store.get_output_dir(project.id) / "attempts" / attempt_id
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "attempt_id": attempt_id,
                "project_id": project.id,
                "status": "running",
                "created_at": "2026-01-01T00:00:00+00:00",
                "started_at": "2026-01-01T00:01:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    def runner(store, project_id, *, attempt_id, **kwargs):
        return _result(attempt_id)

    manager = ExecutionJobManager(store, runner=runner)
    recovered = _wait_for(manager, project.id, attempt_id, "completed")
    assert recovered.recovery_count == 1
    assert recovered.result is not None
    manager.shutdown()


def test_execute_api_returns_202_and_exposes_attempt(monkeypatch, tmp_path):
    import fnirs_flow.api.app as api_module

    store = ProjectStore(tmp_path)
    project = store.create("api job")

    def runner(store, project_id, *, attempt_id, **kwargs):
        return _result(attempt_id)

    manager = ExecutionJobManager(store, runner=runner, recover=False)
    monkeypatch.setattr(api_module, "_store", store)
    monkeypatch.setattr(api_module, "_job_manager", manager)
    monkeypatch.setattr(api_module, "validate_project_execution", lambda store, project_id: True)

    client = TestClient(app)
    accepted = client.post(f"/api/projects/{project.id}/execute")
    assert accepted.status_code == 202
    attempt_id = accepted.json()["attempt_id"]
    _wait_for(manager, project.id, attempt_id, "completed")

    queried = client.get(f"/api/projects/{project.id}/attempts/{attempt_id}")
    assert queried.status_code == 200
    assert queried.json()["status"] == "completed"
    listed = client.get(f"/api/projects/{project.id}/attempts")
    assert [item["attempt_id"] for item in listed.json()] == [attempt_id]
    manager.shutdown()
