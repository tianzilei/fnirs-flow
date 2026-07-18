"""Persistent background execution jobs for API attempts."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fnirs_flow.api.models import ExecuteResult, ExecutionJobRead
from fnirs_flow.api.portability import portable_json_value
from fnirs_flow.api.projects import ProjectStore, execute_project_runs
from fnirs_flow.api.uri import create_project_uri
from fnirs_flow.execution.service import ExecutionCancelledError

logger = logging.getLogger(__name__)

JobRunner = Callable[..., ExecuteResult | None]
ProgressCallback = Callable[[str, dict], None]
_RECOVERABLE_STATES = {"queued", "running"}
_TERMINAL_STATES = {"completed", "failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonicalize_artifact_paths(store: ProjectStore, project_id: str, artifact: dict) -> dict:
    """Rewrite transaction-local resolved paths to committed workspace paths."""
    relative_path = str(artifact.get("relative_path", ""))
    if not relative_path:
        return artifact
    try:
        uri = str(create_project_uri(f"outputs/{relative_path}"))
    except ValueError:
        return artifact
    outdir = store.get_output_dir(project_id).resolve()
    resolved_path = (outdir / relative_path).resolve()
    return {
        **artifact,
        "uri": uri,
        "path": uri,
        "resolved_path": str(resolved_path),
        "exists": resolved_path.is_file(),
    }


def _canonicalize_execute_result(
    store: ProjectStore,
    project_id: str,
    result: ExecuteResult | None,
) -> ExecuteResult | None:
    if result is None:
        return None
    payload = result.model_dump(mode="json")
    for run in payload.get("runs", []):
        for artifact in run.get("artifacts", []):
            artifact.update(_canonicalize_artifact_paths(store, project_id, artifact))
        for atom in run.get("atom_results", []):
            for artifact in atom.get("artifacts", []):
                artifact.update(_canonicalize_artifact_paths(store, project_id, artifact))
    return ExecuteResult.model_validate(payload)


class ExecutionJobManager:
    """Runs attempts in worker threads and persists every state transition."""

    def __init__(
        self,
        store: ProjectStore,
        *,
        runner: JobRunner = execute_project_runs,
        progress_callback: ProgressCallback | None = None,
        max_workers: int = 2,
        recover: bool = True,
    ) -> None:
        self.store = store
        self.runner = runner
        self.progress_callback = progress_callback
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fnirs-execution")
        self._jobs: dict[tuple[str, str], ExecutionJobRead] = {}
        self._cancel_events: dict[tuple[str, str], threading.Event] = {}
        self._futures: dict[tuple[str, str], Future[None]] = {}
        self._lock = threading.RLock()
        self._load_persisted(recover=recover)

    def _job_dir(self, project_id: str, attempt_id: str) -> Path:
        return self.store.get_output_dir(project_id) / "attempts" / attempt_id

    def _persist(self, job: ExecutionJobRead) -> None:
        directory = self._job_dir(job.project_id, job.attempt_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "job.json"
        temporary = path.with_suffix(".json.tmp")
        persisted = portable_json_value(job.model_dump(mode="json"))
        temporary.write_text(json.dumps(persisted, indent=2), encoding="utf-8")
        temporary.replace(path)
        # Running/cancelling are transient workspace states. Persist queued and
        # terminal states to the full bundle to keep recovery without repeatedly
        # recompressing a potentially large result archive.
        if job.status in {"queued", "completed", "failed", "cancelled"}:
            self.store.commit_project(
                job.project_id,
                reason=f"execution_job_{job.status}",
            )

    def _load_persisted(self, *, recover: bool) -> None:
        recover_keys: list[tuple[str, str]] = []
        for project in self.store.list_all():
            attempts_dir = self.store.get_output_dir(project.id) / "attempts"
            if not attempts_dir.exists():
                continue
            for path in attempts_dir.glob("*/job.json"):
                try:
                    job = ExecutionJobRead.model_validate_json(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    logger.warning("Skipping invalid execution job %s: %s", path, exc)
                    continue
                key = (job.project_id, job.attempt_id)
                if recover and (job.status == "cancelling" or job.cancel_requested):
                    job.status = "cancelled"
                    job.cancel_requested = True
                    job.completed_at = job.completed_at or _now()
                    self._persist(job)
                elif recover and job.status in _RECOVERABLE_STATES:
                    job.status = "queued"
                    job.started_at = ""
                    job.completed_at = ""
                    job.cancel_requested = False
                    job.recovery_count += 1
                    self._persist(job)
                    recover_keys.append(key)
                self._jobs[key] = job
                self._cancel_events[key] = threading.Event()
        for key in recover_keys:
            self._submit(key)

    def create(self, project_id: str) -> ExecutionJobRead:
        attempt_id = f"attempt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
        job = ExecutionJobRead(
            attempt_id=attempt_id,
            project_id=project_id,
            status="queued",
            created_at=_now(),
        )
        key = (project_id, attempt_id)
        with self._lock:
            self._jobs[key] = job
            self._cancel_events[key] = threading.Event()
            self._persist(job)
            self._submit(key)
            return job.model_copy(deep=True)

    def _submit(self, key: tuple[str, str]) -> None:
        self._futures[key] = self._executor.submit(self._run, key)

    def _run(self, key: tuple[str, str]) -> None:
        project_id, attempt_id = key
        with self._lock:
            job = self._jobs[key]
            cancel_event = self._cancel_events[key]
            if cancel_event.is_set() or job.cancel_requested:
                self._mark_cancelled(job)
                return
            job.status = "running"
            job.started_at = _now()
            self._persist(job)

        def emit(event: dict) -> None:
            if self.progress_callback is not None:
                self.progress_callback(project_id, {"project_id": project_id, **event})

        try:
            from fnirs_flow.api.transaction import ProjectTransaction

            with ProjectTransaction(
                self.store, project_id, reason=f"execute_{attempt_id}"
            ) as tx:
                result = self.runner(
                    self.store,
                    project_id,
                    attempt_id=attempt_id,
                    progress_callback=emit,
                    cancel_check=cancel_event.is_set,
                )
                if result is None:
                    raise RuntimeError("Project or compiled plan not found")
                tx.commit()
                result = _canonicalize_execute_result(self.store, project_id, result)
        except ExecutionCancelledError:
            with self._lock:
                self._mark_cancelled(self._jobs[key])
            return
        except Exception as exc:
            logger.exception("Execution attempt %s failed", attempt_id)
            with self._lock:
                job = self._jobs[key]
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = _now()
                self._persist(job)
            return

        with self._lock:
            job = self._jobs[key]
            if cancel_event.is_set():
                self._mark_cancelled(job)
                return
            job.status = "completed"
            job.result = result
            job.completed_at = _now()
            self._persist(job)

    def _mark_cancelled(self, job: ExecutionJobRead) -> None:
        job.status = "cancelled"
        job.cancel_requested = True
        job.completed_at = _now()
        self._persist(job)

    def get(self, project_id: str, attempt_id: str) -> ExecutionJobRead | None:
        with self._lock:
            job = self._jobs.get((project_id, attempt_id))
            if job is None:
                return None
            copy = job.model_copy(deep=True)
            copy.result = _canonicalize_execute_result(self.store, project_id, copy.result)
            return copy

    def list(self, project_id: str) -> list[ExecutionJobRead]:
        with self._lock:
            jobs = [job.model_copy(deep=True) for key, job in self._jobs.items() if key[0] == project_id]
        for job in jobs:
            job.result = _canonicalize_execute_result(self.store, project_id, job.result)
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def cancel(self, project_id: str, attempt_id: str) -> ExecutionJobRead | None:
        key = (project_id, attempt_id)
        with self._lock:
            job = self._jobs.get(key)
            if job is None:
                return None
            if job.status in _TERMINAL_STATES:
                return job.model_copy(deep=True)
            job.cancel_requested = True
            job.status = "cancelling"
            self._cancel_events[key].set()
            future = self._futures.get(key)
            if future is not None and future.cancel():
                self._mark_cancelled(job)
            else:
                self._persist(job)
            return job.model_copy(deep=True)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
