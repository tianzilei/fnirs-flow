"""Execution use cases shared by interface adapters."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def dry_run_compiled_project(
    plan_dir: str | Path,
    *,
    outdir: str | Path | None = None,
    participant_labels: list[str] | None = None,
    session_labels: list[str] | None = None,
    task_labels: list[str] | None = None,
    run_labels: list[str] | None = None,
) -> Any:
    """Dry-run compiled artifacts independently of an interface adapter."""
    from fnirs_flow.execution.engine import dry_run

    return dry_run(
        plan_dir,
        outdir=outdir,
        participant_labels=participant_labels,
        session_labels=session_labels,
        task_labels=task_labels,
        run_labels=run_labels,
    )


def execute_compiled_project(request: Any) -> Any:
    """Execute a compiled project through the unified execution facade."""
    from fnirs_flow.execution.service import ExecutionService

    return ExecutionService().execute(request)


class ExecutionUseCases:
    def __init__(self, *, dry_run: Callable[..., Any], execute: Callable[..., Any]) -> None:
        self._dry_run = dry_run
        self._execute = execute

    def dry_run(self, repository: Any, project_id: str) -> Any:
        return self._dry_run(repository, project_id)

    def execute(self, repository: Any, project_id: str, **kwargs: Any) -> Any:
        return self._execute(repository, project_id, **kwargs)
