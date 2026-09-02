"""Single-run execution lifecycle independent from top-level orchestration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from fnirs_flow.execution.dag_payload import execution_atoms
from fnirs_flow.execution.engine import RunContext
from fnirs_flow.execution.errors import ExecutionCancelledError
from fnirs_flow.execution.models import AtomExecutionResult, RunExecutionResult

logger = logging.getLogger(__name__)


class RunExecutionHost(Protocol):
    def _check_cancelled(self) -> None: ...

    def _execute_dag(
        self,
        run_ctx: RunContext,
        dag: dict[str, Any],
        outdir: Path,
        run_result: RunExecutionResult,
        continue_on_failure: bool = True,
    ) -> None: ...

    def _write_run_outputs(self, run_result: RunExecutionResult, outdir: Path) -> None: ...


class RunExecutor:
    """Own creation, failure mapping, completion and output for one run."""

    def __init__(self, host: RunExecutionHost) -> None:
        self.host = host

    def execute(
        self,
        run_ctx: RunContext,
        plan: dict[str, Any],
        dag: dict[str, Any],
        outdir: Path,
        continue_on_failure: bool = True,
    ) -> RunExecutionResult:
        del plan  # plan semantics are resolved before DAG run execution
        run_result = RunExecutionResult(
            run_id=run_ctx.run_id,
            status="running",
            planned_steps=[
                str(atom.get("atom_id", ""))
                for atom in execution_atoms(dag)
                if atom.get("execution_scope", "run") == "run" and str(atom.get("atom_id", ""))
            ],
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            self.host._check_cancelled()
            if not run_ctx.data_path or not Path(run_ctx.data_path).exists():
                run_result.status = "skipped"
                run_result.skipped_steps = list(run_result.planned_steps)
                run_result.completed_at = datetime.now(timezone.utc).isoformat()
                return run_result

            self.host._execute_dag(
                run_ctx,
                dag,
                outdir,
                run_result,
                continue_on_failure=continue_on_failure,
            )
            # A host may stop the DAG early when continue_on_failure is false.
            # Enforce a terminal run state here so an atom failure can never be
            # reported as a still-running (and therefore apparently successful)
            # execution attempt.
            if run_result.status == "running":
                run_result.status = (
                    "failed" if any(item.status == "failed" for item in run_result.atom_results) else "completed"
                )
            if run_result.status == "completed":
                self.host._write_run_outputs(run_result, outdir)
        except Exception as exc:
            # Cancellation is intentionally not translated into a failed run.
            if isinstance(exc, ExecutionCancelledError):
                raise
            if isinstance(exc, ImportError):
                atom_id, code = "mne_import", "ATOM_MANIFEST_MISSING"
                message = "MNE-Python is required for real execution."
            elif isinstance(exc, OSError):
                atom_id, code, message = "execution", "EXECUTION_IO_ERROR", str(exc)
            elif isinstance(exc, (ValueError, TypeError)):
                atom_id, code, message = "execution", "EXECUTION_VALIDATION_ERROR", str(exc)
            elif isinstance(exc, TimeoutError):
                atom_id, code, message = "execution", "EXECUTION_TIMEOUT", str(exc)
            else:
                logger.exception("Unexpected error during run %s", run_ctx.run_id)
                atom_id, code, message = "execution", "EXECUTION_FAILED", str(exc)
            run_result.status = "failed"
            run_result.atom_results.append(
                AtomExecutionResult(atom_id=atom_id, status="failed", error=message, error_code=code)
            )

        run_result.completed_steps = [item.atom_id for item in run_result.atom_results if item.status == "completed"]
        run_result.failed_step = next(
            (item.atom_id for item in run_result.atom_results if item.status == "failed"), ""
        )
        failed_atom = next((item for item in run_result.atom_results if item.status == "failed"), None)
        if failed_atom is not None:
            run_result.failed_error_code = failed_atom.error_code or ""
            run_result.failed_error = failed_atom.error or ""
        run_result.skipped_steps = [item.atom_id for item in run_result.atom_results if item.status == "skipped"]
        run_result.completed_at = datetime.now(timezone.utc).isoformat()
        return run_result
