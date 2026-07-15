"""Batch execution with real MNE-NIRS adapter integration.

v0.2: Uses atom.operation for dispatch instead of step_type branching.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter
from fnirs_flow.execution.artifacts import ArtifactStore, write_artifact_manifest
from fnirs_flow.execution.batch import BatchResult, run_batch
from fnirs_flow.execution.engine import DryRunResult, RunContext
from fnirs_flow.execution.failures import FailureStore
from fnirs_flow.execution.provenance import ProvenanceRecord

# Operation dispatch table: atom.operation -> adapter method
OPERATION_DISPATCH: dict[str, str] = {
    "optical_density": "to_optical_density",
    "motion_correction": "apply_motion_correction",
    "filtering": "apply_filter",
    "beer_lambert_law": "to_haemoglobin",
}


def _get_operation(step: dict[str, Any]) -> str:
    """Extract operation from a step, supporting both v0.1 and v0.2 fields."""
    result: str = step.get("operation") or step.get("type", "")
    return result


def execute_run_with_adapter(
    adapter: MneNirsAdapter,
    run_ctx: RunContext,
    plan: dict[str, Any],
    outdir: Path,
) -> RunContext:
    """Execute a single run using the MNE-NIRS adapter."""
    run_ctx.status = "running"
    run_ctx.started_at = datetime.now(timezone.utc).isoformat()

    try:
        # Read data if a resolved data path is available.
        if run_ctx.data_path and Path(run_ctx.data_path).exists():
            raw = adapter.read_run(run_ctx.data_path)
        else:
            # Dry-run mode: skip actual execution
            run_ctx.status = "completed"
            run_ctx.completed_at = datetime.now(timezone.utc).isoformat()
            return run_ctx

        # Execute preprocessing chain using atom operation dispatch
        for step in plan.get("preprocessing_chain", plan.get("preprocessing_atoms", [])):
            operation = _get_operation(step)
            params = step.get("parameters", {})

            if operation == "optical_density":
                raw = adapter.to_optical_density(raw)
            elif operation == "motion_correction":
                raw = adapter.apply_motion_correction(raw, method=params.get("method", "tddr"))
            elif operation == "filtering":
                raw = adapter.apply_filter(
                    raw,
                    l_freq=params.get("l_freq", 0.01),
                    h_freq=params.get("h_freq", 0.2),
                )
            elif operation == "beer_lambert_law":
                raw = adapter.to_haemoglobin(raw, ppf=params.get("ppf", 6.0))

            # Use atom_id if available, fallback to step_id
            atom_id = step.get("atom_id") or step.get("step_id", operation)
            run_ctx.steps_completed.append(atom_id)

        # Compute QC
        qc = adapter.compute_qc(raw)
        run_ctx.artifacts.append({"type": "qc_metrics", "data": qc})

        run_ctx.status = "completed"
        run_ctx.completed_at = datetime.now(timezone.utc).isoformat()

    except (OSError, ValueError, TypeError, RuntimeError, ImportError) as exc:
        run_ctx.status = "failed"
        run_ctx.errors.append(str(exc))
        run_ctx.completed_at = datetime.now(timezone.utc).isoformat()

    return run_ctx


def run_batch_with_adapter(
    dry_result: DryRunResult,
    plan: dict[str, Any],
    outdir: str | Path,
    data_root: str | Path | None = None,
) -> BatchResult:
    """Run a batch execution with the MNE-NIRS adapter."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    shared_artifacts = ArtifactStore()
    shared_provenance = ProvenanceRecord()

    def execute_fn(ctx: RunContext) -> None:
        if not ctx.data_path:
            ctx.status = "completed"
            ctx.completed_at = datetime.now(timezone.utc).isoformat()
            return

        # Create a fresh adapter instance per run for proper isolation
        run_outdir = outdir / ctx.run_id if ctx.run_id else outdir / "default"
        run_outdir.mkdir(parents=True, exist_ok=True)
        adapter = MneNirsAdapter(
            subject=ctx.subject,
            session=ctx.session,
            task=ctx.task,
            run=ctx.run,
            outdir=run_outdir,
        )
        execute_run_with_adapter(adapter, ctx, plan, outdir)
        for artifact in adapter.artifacts.all():
            shared_artifacts.register(artifact)
        shared_provenance.extend(adapter.provenance.all())

    result = run_batch(dry_result, execute_fn=execute_fn, continue_on_failure=True)

    # Write failure manifest
    if result.failed:
        failure_store = FailureStore()
        for r in result.failed:
            failure_store.register(
                subject=r.subject,
                session=r.session,
                run=r.run,
                message="; ".join(r.errors) if r.errors else "",
                exception_type="RuntimeError",
            )
        failure_store.write_csv(outdir)
        failure_store.write_json(outdir)

    # Write artifact manifest from shared store
    manifest = shared_artifacts.to_manifest(plan_sha256=plan.get("flow_hash", ""))
    write_artifact_manifest(manifest, outdir)

    # Write provenance from shared store
    shared_provenance.write(outdir)

    return result
