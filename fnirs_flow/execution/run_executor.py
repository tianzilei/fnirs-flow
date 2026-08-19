"""Single-run execution lifecycle independent from top-level orchestration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from fnirs_flow.execution.engine import RunContext
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
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            self.host._check_cancelled()
            if not run_ctx.data_path or not Path(run_ctx.data_path).exists():
                run_result.status = "skipped"
                run_result.completed_at = datetime.now(timezone.utc).isoformat()
                return run_result

            self.host._execute_dag(
                run_ctx,
                dag,
                outdir,
                run_result,
                continue_on_failure=continue_on_failure,
            )
            if run_result.status == "completed":
                self.host._write_run_outputs(run_result, outdir)
        except Exception as exc:
            # Cancellation is intentionally not translated into a failed run.
            from fnirs_flow.execution.orchestrator_impl import ExecutionCancelledError

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

        run_result.completed_at = datetime.now(timezone.utc).isoformat()
        return run_result
