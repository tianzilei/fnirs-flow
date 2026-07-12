"""Batch runner: iterates over subject/session/run and handles failures."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fnirs_flow.execution.engine import DryRunResult, RunContext
from fnirs_flow.execution.failures import ActionAttempt, FailureStore


class BatchResult:
    def __init__(self):
        self.successful: list[RunContext] = []
        self.failed: list[RunContext] = []
        self.total: int = 0
        self.attempts: list[ActionAttempt] = []

    @property
    def has_failures(self) -> bool:
        return len(self.failed) > 0

    def summary(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "successful": len(self.successful),
            "failed": len(self.failed),
            "failure_ids": [r.run_id for r in self.failed],
        }


def run_batch(
    dry_result: DryRunResult,
    execute_fn: Any = None,
    continue_on_failure: bool = True,
) -> BatchResult:
    """Run a batch of planned runs. In dry-run mode, just validates the plan."""
    result = BatchResult()
    result.total = dry_result.total_runs

    for run_ctx in dry_result.planned_runs:
        attempt = ActionAttempt(
            attempt_id=f"attempt-{run_ctx.run_id}",
            subject=run_ctx.subject,
            session=run_ctx.session,
            run=run_ctx.run,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        result.attempts.append(attempt)

        try:
            if execute_fn is not None:
                execute_fn(run_ctx)
            # Only set completed if execute_fn didn't already set a terminal status
            if run_ctx.status not in ("failed", "cancelled"):
                run_ctx.status = "completed"
                run_ctx.completed_at = datetime.now(timezone.utc).isoformat()
                attempt.status = "completed"
                attempt.completed_at = run_ctx.completed_at
                result.successful.append(run_ctx)
            else:
                run_ctx.completed_at = datetime.now(timezone.utc).isoformat()
                attempt.status = "failed"
                attempt.completed_at = datetime.now(timezone.utc).isoformat()
                attempt.error_message = f"Run ended with status: {run_ctx.status}"
                result.failed.append(run_ctx)
        except Exception as exc:
            run_ctx.status = "failed"
            run_ctx.errors.append(str(exc))
            run_ctx.completed_at = datetime.now(timezone.utc).isoformat()
            attempt.status = "failed"
            attempt.completed_at = datetime.now(timezone.utc).isoformat()
            attempt.error_type = type(exc).__name__
            attempt.error_message = str(exc)
            result.failed.append(run_ctx)
            if not continue_on_failure:
                break

    return result


def write_batch_report(batch_result: BatchResult, outdir: Path) -> None:
    """Write batch execution summary and failure manifest."""
    outdir.mkdir(parents=True, exist_ok=True)

    # Write batch summary
    summary = batch_result.summary()
    (outdir / "batch_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Write action attempts
    attempts_data = [a.model_dump() for a in batch_result.attempts]
    (outdir / "action_attempts.json").write_text(json.dumps(attempts_data, indent=2), encoding="utf-8")

    # Write failure manifest if there are failures
    if batch_result.has_failures:
        store = FailureStore()
        for attempt in batch_result.attempts:
            if attempt.status == "failed":
                store.register_attempt(attempt)
        store.write_json(outdir)
