"""Execution orchestrator implementation for CLI, API, and WebUI.

Loads compiled plan, resolves data runs, dispatches operations via the
operation registry, and produces structured ExecutionResult.
"""

from __future__ import annotations

import csv
import json
import logging
import warnings
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from fnirs_flow.execution.artifact_writer import (
    collect_group_result_artifacts,
    path_artifact_summary,
    write_run_result_tables,
)
from fnirs_flow.execution.artifacts import ArtifactRecord, ArtifactStore, write_artifact_manifest
from fnirs_flow.execution.concurrency import native_thread_limit, resolve_concurrency
from fnirs_flow.execution.dag_payload import execution_atoms
from fnirs_flow.execution.dag_scheduler import DAGScheduler, resolve_edge_dependency
from fnirs_flow.execution.engine import RunContext, ensure_derivatives_layout
from fnirs_flow.execution.failures import FailureStore
from fnirs_flow.execution.group_executor import GroupExecutor, extract_group_config
from fnirs_flow.execution.models import AtomExecutionResult, ExecutionRequest, ExecutionResult, RunExecutionResult
from fnirs_flow.execution.operation_dispatcher import OperationDispatcher
from fnirs_flow.execution.operations import (
    OperationContext,
    OperationRegistry,
    canonical_operation,
    create_default_registry,
)
from fnirs_flow.execution.plan_loader import load_dag, load_plan, resolve_runs
from fnirs_flow.execution.provenance import ProvenanceRecord
from fnirs_flow.execution.run_executor import RunExecutor
from fnirs_flow.execution.run_worker import RunWorkerRequest, RunWorkerResponse, execute_run_worker
from fnirs_flow.infrastructure.filesystem import remove_macos_metadata_paths
from fnirs_flow.settings import Settings

logger = logging.getLogger(__name__)


def resolve_atom_backend_id(atom: dict[str, Any], default_backend_id: str) -> str:
    """Return the atom backend, treating missing/null backend ids as default."""
    return atom.get("backend_id") or default_backend_id


class ExecutionCancelledError(RuntimeError):
    """Raised when a persistent execution job requests cooperative cancellation."""


class ExecutionService:
    """Unified execution service for CLI, API, and WebUI.

    Loads the compiled plan and DAG, resolves data runs from the manifest,
    dispatches operations through the registry, and produces a structured
    ExecutionResult.
    """

    def __init__(
        self,
        registry: OperationRegistry | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        runtime_settings: Settings | None = None,
    ) -> None:
        self.registry = registry or create_default_registry()
        self.dispatcher = OperationDispatcher(self.registry)
        self.run_executor = RunExecutor(self)
        self.group_executor = GroupExecutor(self)
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.runtime_settings = runtime_settings or Settings.from_env()
        self._active_attempt_id: str = ""

    def _check_cancelled(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            self._emit_progress("execution_cancelled")
            raise ExecutionCancelledError("Execution cancelled")

    def _emit_progress(self, event_type: str, **details: Any) -> None:
        if self.progress_callback is None:
            return
        event = {
            "type": event_type,
            "attempt_id": self._active_attempt_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **details,
        }
        try:
            self.progress_callback(event)
        except Exception:
            # Observability must never alter scientific execution semantics.
            import logging

            logging.getLogger(__name__).debug("Progress callback error", exc_info=True)
            return

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Compatibility facade delegating orchestration to ``ExecutionOrchestrator``."""
        from fnirs_flow.execution.orchestrator import ExecutionOrchestrator

        return ExecutionOrchestrator(self).execute(request)

    def _execute_impl(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute a full analysis pipeline.

        This is the main entry point that CLI, API, and WebUI all call.
        """
        project_dir = Path(request.project_dir)
        compiled_dir = project_dir / "compiled"
        if not compiled_dir.exists():
            compiled_dir = project_dir

        # Load plan and DAG
        plan = self._load_plan(compiled_dir)
        dag = self._load_dag(compiled_dir)
        plan_data = plan.get("plan", plan) if "plan" in plan else plan

        # Resolve data runs
        runs = self._resolve_runs(
            compiled_dir,
            request,
        )
        concurrency = resolve_concurrency(self.runtime_settings, run_count=len(runs))

        # Set up output directories
        outdir = Path(request.outdir) if request.outdir else project_dir
        dirs = ensure_derivatives_layout(outdir)

        attempt_id = request.attempt_id or f"attempt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
        self._active_attempt_id = attempt_id
        started_at = datetime.now(timezone.utc).isoformat()
        self._emit_progress("execution_started", total_runs=len(runs))

        # Execute each run
        run_results: list[RunExecutionResult] = []
        artifact_store = ArtifactStore()
        provenance = ProvenanceRecord()
        if request.commit_id or request.snapshot_id:
            provenance.set_design_anchor(
                commit_id=request.commit_id,
                snapshot_id=request.snapshot_id,
            )
        provenance.log(
            step_id="execution/concurrency",
            parameters={"concurrency": concurrency.as_dict(), "lineage": {"predecessor_atom_ids": []}},
        )
        failure_store = FailureStore()
        group_atom_results = self.group_executor.execute_atoms(dag, outdir)

        if concurrency.backend == "process":
            self._check_cancelled()
            worker_requests = [
                RunWorkerRequest(
                    run_context=run_ctx.model_dump(mode="json"),
                    plan=plan_data,
                    dag=dag,
                    outdir=str(outdir),
                    continue_on_failure=request.continue_on_failure,
                    blas_threads=concurrency.blas_threads,
                    attempt_id=attempt_id,
                ).model_dump(mode="json")
                for run_ctx in runs
            ]
            for run_ctx in runs:
                self._emit_progress("run_started", run_id=run_ctx.run_id)
            pool = ProcessPoolExecutor(max_workers=concurrency.run_workers)
            futures = []
            try:
                futures = [pool.submit(execute_run_worker, payload) for payload in worker_requests]
                pending = set(futures)
                while pending:
                    self._check_cancelled()
                    _done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                # Index order, rather than completion order, defines aggregation.
                worker_payloads = [future.result() for future in futures]
                pool.shutdown(wait=True)
            except ExecutionCancelledError:
                for future in futures:
                    future.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                raise
            except Exception as exc:
                pool.shutdown(wait=True, cancel_futures=True)
                # No serial retry is attempted after workers may have written outputs.
                raise RuntimeError("Run process pool failed; the attempt must be rolled back") from exc
            for payload in worker_payloads:
                response = RunWorkerResponse.model_validate(payload)
                run_results.append(response.result)
                self._emit_progress(
                    "run_completed", run_id=response.run_id, status=response.result.status
                )
        else:
            with native_thread_limit(concurrency.blas_threads):
                for run_ctx in runs:
                    self._check_cancelled()
                    self._emit_progress("run_started", run_id=run_ctx.run_id)
                    run_result = self.run_executor.execute(
                        run_ctx,
                        plan_data,
                        dag,
                        outdir,
                        continue_on_failure=request.continue_on_failure,
                    )
                    run_results.append(run_result)
                    self._emit_progress(
                        "run_completed",
                        run_id=run_ctx.run_id,
                        status=run_result.status,
                    )

        for run_ctx, run_result in zip(runs, run_results, strict=True):

            # Collect artifacts from this run
            for artifact_index, art in enumerate(run_result.artifacts):
                artifact_store.register(
                    ArtifactRecord(
                        artifact_id=art.get("artifact_id")
                        or f"{run_result.run_id}_{art.get('atom_id', 'run')}_{artifact_index}",
                        subject=run_ctx.subject,
                        session=run_ctx.session,
                        task=run_ctx.task,
                        run=run_ctx.run,
                        step_id=art.get("step_id") or art.get("atom_id", ""),
                        artifact_type=art.get("type", ""),
                        uri=art.get("uri", art.get("path", "")),
                        path=art.get("uri", art.get("path", "")),
                        sha256=art.get("checksum", ""),
                    )
                )

            # Record provenance for each atom
            for ar in run_result.atom_results:
                provenance.log(
                    step_id=f"{run_result.run_id}/{ar.atom_id}",
                    parameters={
                        "status": ar.status,
                        "output_handles": ar.output_handles,
                        "lineage": ar.provenance,
                    },
                )

            # Record failures
            if run_result.status == "failed":
                for ar in run_result.atom_results:
                    if ar.status == "failed":
                        failure_store.register(
                            subject=run_ctx.subject,
                            session=run_ctx.session,
                            run=run_ctx.run,
                            atom_id=ar.atom_id,
                            message=ar.error or "Unknown error",
                        )

        for atom in group_atom_results:
            for artifact_index, art in enumerate(atom.artifacts):
                artifact_store.register(
                    ArtifactRecord(
                        artifact_id=art.get("artifact_id") or f"group_{atom.atom_id}_{artifact_index}",
                        step_id=art.get("step_id") or atom.atom_id,
                        artifact_type=art.get("type", ""),
                        uri=art.get("uri", art.get("path", "")),
                        path=art.get("uri", art.get("path", "")),
                        sha256=art.get("checksum", ""),
                    )
                )
            provenance.log(
                step_id=f"group/{atom.atom_id}",
                parameters={
                    "status": atom.status,
                    "output_handles": atom.output_handles,
                    "lineage": atom.provenance,
                },
            )

        # Summarize
        successful = sum(1 for r in run_results if r.status == "completed")
        failed = sum(1 for r in run_results if r.status == "failed")
        skipped = sum(1 for r in run_results if r.status == "skipped")
        failure_ids = [r.run_id for r in run_results if r.status == "failed"]
        if group_atom_results and any(item.status == "failed" for item in group_atom_results):
            failed += 1
            failure_ids.append("group")

        completed_at = datetime.now(timezone.utc).isoformat()

        result = ExecutionResult(
            attempt_id=attempt_id,
            total_runs=len(runs),
            successful_runs=successful,
            failed_runs=failed,
            skipped_runs=skipped,
            run_results=[
                *run_results,
                *(
                    [
                        RunExecutionResult(
                            run_id="group",
                            status=(
                                "completed"
                                if all(item.status == "completed" for item in group_atom_results)
                                else "failed"
                            ),
                            atom_results=group_atom_results,
                            started_at=started_at,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                        )
                    ]
                    if group_atom_results
                    else []
                ),
            ],
            artifacts=[
                *[artifact for run in run_results for artifact in run.artifacts],
                *[artifact for atom in group_atom_results for artifact in atom.artifacts],
            ],
            failure_ids=failure_ids,
            started_at=started_at,
            completed_at=completed_at,
            concurrency=concurrency.as_dict(),
        )

        # Write summary
        self._write_execution_summary(result, dirs["logs"])

        # Write structured manifests
        write_artifact_manifest(
            artifact_store.to_manifest(run_id=attempt_id),
            dirs["logs"],
        )
        provenance.write(dirs["logs"], project_root=outdir)
        # Always replace the manifests so a successful retry cannot retain
        # failures from a previous attempt in the same output directory.
        failure_store.write_json(dirs["logs"])
        failure_store.write_csv(dirs["logs"])

        # Write dependency provenance.
        # §16 MVP: runtime artifacts record actual dependency and backend versions.
        self._write_dependency_provenance(compiled_dir, dirs["logs"], dag)

        # Generate group summary across subjects
        group_path = self.group_executor.generate_summary(
            run_results,
            outdir,
            group_config=type(self)._extract_group_config(plan_data, dag),
        )
        if group_path:
            result.reports.append(str(group_path))
        group_artifacts = self._collect_group_result_artifacts(outdir)
        if group_artifacts:
            result.artifacts.extend(group_artifacts)
            group_run = next((run for run in result.run_results if run.run_id == "group"), None)
            if group_run is not None:
                group_run.artifacts.extend(group_artifacts)
                for atom_result in group_run.atom_results:
                    operation = str(atom_result.provenance.get("operation", ""))
                    matching = []
                    for artifact in group_artifacts:
                        artifact_atom_id = str(artifact.get("atom_id", ""))
                        if artifact_atom_id in {atom_result.atom_id, operation}:
                            matching.append({**artifact, "atom_id": atom_result.atom_id})
                    atom_result.artifacts.extend(matching)

        self._emit_progress(
            "execution_completed",
            successful=successful,
            failed=failed,
            skipped=skipped,
        )
        remove_macos_metadata_paths(outdir)

        return result

    @staticmethod
    def _extract_group_config(plan: dict[str, Any], dag: dict[str, Any]) -> dict[str, Any]:
        return extract_group_config(plan, dag)
    def _execute_group_scope_atoms(self, dag: dict[str, Any], outdir: Path) -> list[AtomExecutionResult]:
        """Deprecated compatibility wrapper; group ownership lives in GroupExecutor."""
        return self.group_executor.execute_atoms(dag, outdir)

    def _generate_group_summary(
        self,
        run_results: list[RunExecutionResult],
        outdir: Path,
        *,
        group_config: dict[str, Any] | None = None,
    ) -> Path | None:
        """Deprecated compatibility wrapper; group ownership lives in GroupExecutor."""
        return self.group_executor.generate_summary(run_results, outdir, group_config=group_config)

    def _load_plan(self, compiled_dir: Path) -> dict[str, Any]:
        """Load plan.json from compiled directory."""
        return load_plan(compiled_dir)

    def _load_dag(self, compiled_dir: Path) -> dict[str, Any]:
        """Load execution_dag.json from compiled directory."""
        return load_dag(compiled_dir)

    def _resolve_runs(
        self,
        compiled_dir: Path,
        request: ExecutionRequest,
    ) -> list[RunContext]:
        """Resolve data runs from manifest, filtered by request labels."""
        return resolve_runs(compiled_dir, request)

    def _execute_run(
        self,
        run_ctx: RunContext,
        plan: dict[str, Any],
        dag: dict[str, Any],
        outdir: Path,
        continue_on_failure: bool = True,
    ) -> RunExecutionResult:
        """Compatibility wrapper around the extracted single-run executor."""
        return self.run_executor.execute(
            run_ctx,
            plan,
            dag,
            outdir,
            continue_on_failure=continue_on_failure,
        )

    def _write_run_outputs(self, run_result: RunExecutionResult, outdir: Path) -> None:
        """Persist finite channel and ROI tables for one completed run."""
        write_run_result_tables(run_result, outdir)

    @staticmethod
    def _path_artifact_summary(
        path: Path,
        outdir: Path,
        *,
        artifact_type: str,
        artifact_id: str,
        atom_id: str = "",
        step_id: str = "",
    ) -> dict[str, Any]:
        """Return the stable API/UI representation of a derivative file."""
        return path_artifact_summary(
            path, outdir, artifact_type=artifact_type, artifact_id=artifact_id,
            atom_id=atom_id, step_id=step_id,
        )

    def _append_adapter_artifacts(
        self,
        run_result: RunExecutionResult,
        atom_result: AtomExecutionResult | None,
        records: list[ArtifactRecord],
        outdir: Path,
    ) -> None:
        """Attach newly emitted adapter artifacts to their atom and run."""
        from fnirs_flow.infrastructure.uri import create_project_uri

        existing_run = {(str(item.get("artifact_id", "")), str(item.get("path", ""))) for item in run_result.artifacts}
        existing_atom = (
            {(str(item.get("artifact_id", "")), str(item.get("path", ""))) for item in atom_result.artifacts}
            if atom_result is not None
            else set()
        )
        for record in records:
            path = Path(record.path).resolve() if record.path else None
            relative_path = ""
            if path is not None:
                try:
                    relative_path = path.relative_to(outdir.resolve()).as_posix()
                except ValueError:
                    pass
            uri = create_project_uri(f"outputs/{relative_path}") if relative_path else None
            artifact = {
                "artifact_id": record.artifact_id,
                "type": record.artifact_type,
                "uri": str(uri) if uri else "",
                "path": str(uri) if uri else "",
                "resolved_path": str(path) if path is not None else "",
                "relative_path": relative_path,
                "checksum": record.sha256,
                "exists": path.is_file() if path is not None else False,
                "atom_id": atom_result.atom_id if atom_result is not None else "",
                "step_id": record.step_id,
            }
            identity = (record.artifact_id, str(artifact["path"]))
            if atom_result is not None and identity not in existing_atom:
                atom_result.artifacts.append(artifact)
                existing_atom.add(identity)
            if identity not in existing_run:
                run_result.artifacts.append(artifact)
                existing_run.add(identity)

    def _collect_group_result_artifacts(self, outdir: Path) -> list[dict[str, Any]]:
        return collect_group_result_artifacts(outdir)

    def _execute_dag(
        self,
        run_ctx: RunContext,
        dag: dict[str, Any],
        outdir: Path,
        run_result: RunExecutionResult,
        continue_on_failure: bool = True,
    ) -> None:
        """Execute atoms following DAG topological layers.

        This replaces the three-chain approach with proper DAG scheduling:
        - Uses execution_layers from execution_dag.json
        - Executes atoms in topological order
        - Passes outputs between connected atoms via edges
        - Supports parallel execution within layers (future enhancement)
        - Uses LazyAdapterPool for MethodAtom-level backend loading
        """
        from fnirs_flow.adapters.backend_registry import LazyAdapterPool, get_registry

        # Get backend registry and adapter pool
        registry = get_registry()
        adapter_pool = LazyAdapterPool(registry)

        # Determine the default backend for data reading
        atoms_list = execution_atoms(dag)
        default_backend_id = "mne_nirs"  # Default backend

        # Check if any atom specifies a backend
        for atom in atoms_list:
            if atom.get("backend_id"):
                default_backend_id = atom["backend_id"]
                break

        # Create run output directory
        run_outdir = outdir / run_ctx.run_id
        run_outdir.mkdir(parents=True, exist_ok=True)

        # Get the default adapter for data reading
        adapter_kwargs = {
            "subject": run_ctx.subject,
            "session": run_ctx.session,
            "task": run_ctx.task,
            "run": run_ctx.run,
            "outdir": run_outdir,
        }
        default_adapter = adapter_pool.get(default_backend_id, **adapter_kwargs)

        # Read data using the default adapter
        raw = default_adapter.read_run(run_ctx.data_path)
        initial_artifacts = default_adapter.artifacts.all() if hasattr(default_adapter, "artifacts") else []

        # Build atom map from DAG (reuse atoms_list from above)
        atom_map = {str(atom["atom_id"]): atom for atom in atoms_list}

        # Get execution layers
        layers = dag.get("execution_layers", [])

        # If no layers, fall back to simple sequential execution
        if not layers:
            layers = [[str(atom["atom_id"]) for atom in atoms_list]]

        # Fix layer ordering: if two atoms share a layer but have a DAG edge
        # between them, split so the dependency executes first.
        edges_list = dag.get("edges", [])
        dep_map: dict[str, set[str]] = {}
        for edge in edges_list:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            dep_map.setdefault(tgt, set()).add(src)

        fixed_layers = []
        for layer in layers:
            layer_set = set(layer)
            # Find atoms in this layer that depend on other atoms in the same layer
            needs_split = False
            for atom_id in layer:
                deps_in_layer = dep_map.get(atom_id, set()) & layer_set
                if deps_in_layer:
                    needs_split = True
                    break
            if needs_split:
                # Build intra-layer dependency subgraph
                intra_deps: dict[str, set[str]] = {}
                for atom_id in layer:
                    intra_deps[atom_id] = dep_map.get(atom_id, set()) & layer_set

                # Topological sort within the layer
                sorted_atoms = []
                remaining = set(layer)
                while remaining:
                    # Find atoms with no unresolved intra-layer deps
                    ready = [a for a in remaining if not (intra_deps.get(a, set()) & remaining)]
                    if not ready:
                        # Cycle detected within a layer — fall back to original order
                        sorted_atoms.extend(sorted(remaining))
                        break
                    ready.sort()
                    sorted_atoms.extend(ready)
                    remaining -= set(ready)

                # Group into sub-layers: each sub-layer contains atoms that can
                # run in parallel (no dependencies on each other)
                placed: set[str] = set()
                while placed < set(sorted_atoms):
                    batch = []
                    for atom_id in sorted_atoms:
                        if atom_id in placed:
                            continue
                        deps = intra_deps.get(atom_id, set())
                        if not (deps - placed):
                            batch.append(atom_id)
                    if not batch:
                        break  # safety
                    batch.sort()
                    fixed_layers.append(batch)
                    placed |= set(batch)
            else:
                fixed_layers.append(layer)
        layers = DAGScheduler.normalize_layers(fixed_layers, edges_list)

        # Track intermediate results: atom_id -> result
        intermediate_state: dict[str, Any] = {
            "raw": raw,
            "data_path": run_ctx.data_path,
            "events_path": run_ctx.events_path,
        }
        raw_outputs: dict[str, Any] = {}
        unavailable_atoms: set[str] = set()

        # Execute layer by layer
        for layer in layers:
            for atom_id in layer:
                self._check_cancelled()
                current_atom = atom_map.get(atom_id)
                if not current_atom:
                    continue

                atom = current_atom
                declared_operation = str(atom.get("operation") or atom.get("atom_type", ""))
                operation = canonical_operation(declared_operation)
                params = dict(atom.get("parameters", {}))
                category = atom.get("category", "")
                execution_scope = atom.get("execution_scope", "run")
                if execution_scope != "run":
                    continue
                predecessors = dep_map.get(atom_id, set())

                blocked_by = sorted(predecessors & unavailable_atoms)
                if blocked_by:
                    run_result.atom_results.append(
                        AtomExecutionResult(
                            atom_id=atom_id,
                            status="skipped",
                            warnings=[
                                "Skipped because upstream atoms did not produce usable output: " + ", ".join(blocked_by)
                            ],
                        )
                    )
                    unavailable_atoms.add(atom_id)
                    self._emit_progress(
                        "atom_completed",
                        run_id=run_ctx.run_id,
                        atom_id=atom_id,
                        status="skipped",
                    )
                    continue

                raw_candidates = [raw_outputs[pred] for pred in predecessors if pred in raw_outputs]
                raw_input = raw_candidates[0] if raw_candidates else raw
                intermediate_state["raw"] = raw_input

                # Data loading happens before DAG dispatch, but it still receives
                # a first-class atom result so the UI can show its derivative files.
                if category == "data":
                    is_read_atom = operation == "read_run"
                    data_result = AtomExecutionResult(
                        atom_id=atom_id,
                        status="completed" if is_read_atom else "skipped",
                        output_handles={"data": type(raw).__name__} if is_read_atom else {},
                        warnings=[] if is_read_atom else ["Handled during project data discovery."],
                        evidence_refs=atom.get("evidence_refs", []),
                        provenance={
                            "predecessor_atom_ids": sorted(predecessors),
                            "operation": operation,
                            "declared_operation": declared_operation,
                            "backend_id": default_backend_id,
                        },
                    )
                    if is_read_atom:
                        matching_records = [record for record in initial_artifacts if record.step_id == "read_run"]
                        self._append_adapter_artifacts(
                            run_result,
                            data_result,
                            matching_records,
                            outdir,
                        )
                    run_result.atom_results.append(data_result)
                    intermediate_state[atom_id] = {
                        "status": data_result.status,
                        "data": raw if is_read_atom else None,
                    }
                    raw_outputs[atom_id] = raw_input
                    self._emit_progress(
                        "atom_completed",
                        run_id=run_ctx.run_id,
                        atom_id=atom_id,
                        status=data_result.status,
                    )
                    continue

                atom_result = AtomExecutionResult(
                    atom_id=atom_id,
                    status="running",
                    evidence_refs=atom.get("evidence_refs", []),
                    provenance={
                        "predecessor_atom_ids": sorted(predecessors),
                        "operation": operation,
                        "declared_operation": declared_operation,
                        "backend_id": resolve_atom_backend_id(atom, default_backend_id),
                    },
                )
                self._emit_progress(
                    "atom_started",
                    run_id=run_ctx.run_id,
                    atom_id=atom_id,
                )

                if not self.registry.has(declared_operation) and not self.registry.has(operation):
                    atom_result.status = "failed"
                    atom_result.error = f"Unregistered operation: {declared_operation}"
                    atom_result.error_code = "UNREGISTERED_OPERATION"
                    run_result.atom_results.append(atom_result)
                    unavailable_atoms.add(atom_id)
                    self._emit_progress(
                        "atom_completed",
                        run_id=run_ctx.run_id,
                        atom_id=atom_id,
                        status=atom_result.status,
                    )
                    continue

                if operation == "empty_marker":
                    marker = {
                        "status": "empty",
                        "operation": operation,
                        "category": category,
                        "no_op": True,
                        "predecessor_atom_ids": sorted(predecessors),
                        "state_marker": params.get("state_marker") or f"empty_{category or atom_id}",
                    }
                    intermediate_state[atom_id] = marker
                    raw_outputs[atom_id] = raw_input
                    atom_result.status = "completed"
                    atom_result.output_handles = {
                        "marker": marker,
                        "data": type(raw_input).__name__,
                    }
                    atom_result.provenance.update(
                        {
                            "empty_processing": True,
                            "backend_id": "none",
                        }
                    )
                    atom_result.warnings.append("Empty marker only updates state metadata; no processing was run.")
                    run_result.atom_results.append(atom_result)
                    self._emit_progress(
                        "atom_completed",
                        run_id=run_ctx.run_id,
                        atom_id=atom_id,
                        status=atom_result.status,
                    )
                    continue

                adapter = None
                artifact_offset = 0
                result = None
                caught_warnings: list[warnings.WarningMessage] = []
                try:
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always", RuntimeWarning)
                        # Inject outputs only from this atom's actual DAG predecessors.
                        self._inject_edge_dependencies(
                            atom_id,
                            atom,
                            params,
                            intermediate_state,
                            predecessors,
                            atom_map,
                        )
                        # Retain legacy/default injections for event parsing and old DAGs.
                        self._inject_dependencies(atom, params, intermediate_state)

                        # Get the appropriate adapter for this atom (MethodAtom-level)
                        atom_backend_id = resolve_atom_backend_id(atom, default_backend_id)
                        adapter = adapter_pool.get(atom_backend_id, **adapter_kwargs)
                        artifact_offset = len(adapter.artifacts.all()) if hasattr(adapter, "artifacts") else 0

                        # Dispatch based on category
                        if category == "preprocessing" or (category == "validation" and operation == "compute_qc"):
                            params.setdefault("_declared_operation", declared_operation)
                            result = self._dispatch_preprocessing(
                                adapter,
                                raw_input,
                                operation,
                                params,
                            )
                            # QC emits metrics rather than a transformed data object.
                            raw_outputs[atom_id] = (
                                raw_input
                                if operation in {"compute_qc", "combat_harmonization"}
                                else result
                            )
                            intermediate_state[atom_id] = result
                        elif category in ("analysis", "output"):
                            result = self._dispatch_analysis(
                                adapter,
                                raw_input,
                                operation,
                                params,
                            )
                            intermediate_state[atom_id] = result
                            raw_outputs[atom_id] = raw_input
                            # Store specific results for downstream injection
                            if operation == "build_design_matrix":
                                intermediate_state["design_matrix"] = result
                            elif operation == "first_level_glm":
                                intermediate_state["glm_result"] = result
                            elif operation == "estimate_contrast":
                                intermediate_state["contrast_result"] = result
                            elif operation == "channel_output":
                                intermediate_state["channel_results"] = result
                                # Preserve channel-level output for run and group reports.
                                channel_rows = self._extract_channel_list(result)
                                for row in channel_rows:
                                    enriched_row = dict(row)
                                    enriched_row.setdefault("source_atom_id", atom_id)
                                    run_result.channel_results.append(enriched_row)
                            elif operation == "roi_output":
                                intermediate_state["roi_results"] = result
                                # Store in run_result for group summary
                                roi_rows = self._extract_roi_list(result)
                                for row in roi_rows:
                                    enriched_row = dict(row)
                                    enriched_row.setdefault("source_atom_id", atom_id)
                                    run_result.roi_results.append(enriched_row)
                        else:
                            # Data nodes (e.g., read_run) - skip, already handled
                            intermediate_state[atom_id] = {"status": "skipped"}
                        caught_warnings = list(caught)

                    atom_result.status = "completed"
                    result_type = type(result).__name__ if result else "None"
                    atom_result.output_handles["data"] = result_type

                except ExecutionCancelledError:
                    raise
                except OSError as exc:
                    atom_result.status = "failed"
                    atom_result.error = str(exc)
                    atom_result.error_code = "EXECUTION_IO_ERROR"
                    if not continue_on_failure:
                        run_result.status = "failed"
                except (ValueError, TypeError) as exc:
                    atom_result.status = "failed"
                    atom_result.error = str(exc)
                    atom_result.error_code = "EXECUTION_VALIDATION_ERROR"
                    if not continue_on_failure:
                        run_result.status = "failed"
                except TimeoutError as exc:
                    atom_result.status = "failed"
                    atom_result.error = str(exc)
                    atom_result.error_code = "EXECUTION_TIMEOUT"
                    if not continue_on_failure:
                        run_result.status = "failed"
                except Exception as exc:
                    logger.exception("Unexpected error in atom %s", atom_id)
                    atom_result.status = "failed"
                    atom_result.error = str(exc)
                    atom_result.error_code = "EXECUTION_FAILED"
                    if not continue_on_failure:
                        run_result.status = "failed"

                if caught_warnings:
                    seen_warning_messages = set(atom_result.warnings)
                    for warning_message in caught_warnings:
                        text = f"{warning_message.category.__name__}: {warning_message.message}"
                        if text not in seen_warning_messages:
                            atom_result.warnings.append(text)
                            seen_warning_messages.add(text)

                if adapter is not None and hasattr(adapter, "artifacts"):
                    self._append_adapter_artifacts(
                        run_result,
                        atom_result,
                        adapter.artifacts.all()[artifact_offset:],
                        outdir,
                    )

                run_result.atom_results.append(atom_result)
                self._emit_progress(
                    "atom_completed",
                    run_id=run_ctx.run_id,
                    atom_id=atom_id,
                    status=atom_result.status,
                    error=atom_result.error,
                )
                if atom_result.status == "failed":
                    unavailable_atoms.add(atom_id)
                    if not continue_on_failure:
                        return

        # Collect any residual adapter artifacts that were emitted outside an
        # atom dispatch (for example, legacy flows without an explicit read atom).
        for backend_id, adapter_instance in adapter_pool.items():
            if hasattr(adapter_instance, "artifacts"):
                self._append_adapter_artifacts(
                    run_result,
                    None,
                    adapter_instance.artifacts.all(),
                    outdir,
                )

        if run_result.status == "running":
            run_result.status = (
                "failed" if any(result.status == "failed" for result in run_result.atom_results) else "completed"
            )

    def _create_backend_adapter(
        self,
        registry: Any,
        backend_id: str,
        **kwargs: Any,
    ) -> Any:
        """Create the requested backend without scientifically unsafe fallback."""
        # Resolve exception classes at call time because registry plugins/tests
        # may reload the backend module during the process lifetime.
        from fnirs_flow.adapters.backend_registry import (
            BackendLoadError,
            BackendNotAvailableError,
        )

        try:
            return registry.create(backend_id, **kwargs)
        except BackendNotAvailableError as exc:
            # Structured error for missing backend
            raise ImportError(
                f"Required backend '{backend_id}' is not available. "
                f"Please install the required package. "
                f"Error: {exc.message}"
            ) from exc
        except BackendLoadError as exc:
            # Structured error for failed backend load
            raise ImportError(
                f"Failed to load backend '{backend_id}' from '{exc.class_path}'. "
                f"Please check the installation. "
                f"Error: {exc}"
            ) from exc
        except ValueError as exc:
            # Never substitute a different scientific backend. In particular,
            # Cedalion-only MethodAtoms must not be silently executed by MNE.
            raise ImportError(f"Required backend '{backend_id}' is unavailable: {exc}") from exc

    def _inject_dependencies(
        self,
        atom: dict[str, Any],
        params: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        """Inject intermediate results from state into atom parameters.

        Uses a data-driven mapping of operation -> state keys to inject.
        """
        operation = canonical_operation(str(atom.get("operation") or atom.get("atom_type") or ""))

        # Mapping of (operation, param_key) -> state_key to auto-inject
        injection_map: dict[tuple[str, str], str] = {
            ("first_level_glm", "design_matrix"): "design_matrix",
            ("estimate_contrast", "glm_result"): "glm_result",
            ("channel_output", "contrast_result"): "contrast_result",
            ("roi_output", "channel_results"): "channel_results",
        }

        for (op, param_key), state_key in injection_map.items():
            if operation == op and param_key not in params and state_key in state:
                params[param_key] = state[state_key]

        # Special case: estimate_contrast also injects contrasts from atom config
        if operation == "estimate_contrast" and "contrasts" not in params:
            params["contrasts"] = atom.get("parameters", {}).get("contrasts", [])

        # Special case: build_design_matrix needs events from TSV file
        if operation == "build_design_matrix" and "events" not in params:
            events_path = state.get("events_path", "")
            if events_path:
                raw_obj = state.get("raw")
                sfreq = 10.0  # default
                if raw_obj is not None and hasattr(raw_obj, "info"):
                    try:
                        sfreq = raw_obj.info.get("sfreq", 10.0)
                    except (AttributeError, TypeError):
                        pass
                events, event_id = self._parse_bids_events_tsv(
                    events_path,
                    sfreq,
                )
                params["events"] = events
                params["event_id"] = event_id

    def _inject_edge_dependencies(
        self,
        atom_id: str,
        atom: dict[str, Any],
        params: dict[str, Any],
        state: dict[str, Any],
        predecessors: set[str],
        atom_map: dict[str, dict[str, Any]],
    ) -> None:
        """Compatibility wrapper around the extracted pure edge resolver."""
        resolve_edge_dependency(atom_id, atom, params, state, predecessors, atom_map)

    def _dispatch_preprocessing(
        self,
        adapter: Any,
        raw: Any,
        operation: str,
        params: dict[str, Any],
    ) -> Any:
        """Dispatch a preprocessing operation to the adapter."""
        declared_operation = str(params.get("_declared_operation") or operation)
        operation = canonical_operation(str(operation))
        spec = self.registry.get(declared_operation) or self.registry.get(operation)
        if spec is not None and spec.handler_factory_for(
            getattr(adapter, "backend_id", None)
        ) is not None:
            return self.dispatcher.execute(
                declared_operation if self.registry.has(declared_operation) else operation,
                OperationContext(adapter=adapter, raw=raw, parameters=params, service=self),
            )
        raise ValueError(f"Operation has no registered preprocessing handler: {declared_operation}")

    @staticmethod
    def _public_operation_params(params: dict[str, Any], *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Remove dispatch-private keys and explicit positional kwargs."""
        excluded = {"method", *(exclude or set())}
        return {key: value for key, value in params.items() if not key.startswith("_") and key not in excluded}

    def _dispatch_analysis(
        self,
        adapter: Any,
        raw: Any,
        operation: str,
        params: dict[str, Any],
    ) -> Any:
        """Dispatch an analysis operation to the adapter."""
        operation = canonical_operation(str(operation))
        spec = self.registry.get(operation)
        if spec is not None and spec.handler_factory_for(
            getattr(adapter, "backend_id", None)
        ) is not None:
            return self.dispatcher.execute(
                operation,
                OperationContext(adapter=adapter, raw=raw, parameters=params, service=self),
            )
        raise ValueError(f"Operation has no registered analysis handler: {operation}")

    @staticmethod
    def _normalize_hrf_model(value: Any) -> str:
        """Map common legacy UI labels to backend-supported HRF model ids."""
        model = str(value or "glover").strip().lower()
        if model in {"canonical", "canonical_hrf", "default"}:
            return "glover"
        return model

    @staticmethod
    def _normalize_contrasts(contrasts: Any, glm_result: Any) -> list[Any]:
        """Accept legacy string contrasts and convert them to adapter-ready specs."""
        if not isinstance(contrasts, list):
            return []
        if not isinstance(glm_result, dict):
            return contrasts
        n_conditions = int(glm_result.get("n_conditions", 0) or 0)
        conditions = [str(item) for item in glm_result.get("conditions", [])]
        normalized: list[dict[str, Any]] = []
        for item in contrasts:
            if isinstance(item, dict):
                normalized.append(item)
                continue
            label = str(item)
            weights = [0.0] * n_conditions
            if ">" in label and conditions:
                left, right = [part.strip() for part in label.split(">", 1)]
                if left in conditions:
                    weights[conditions.index(left)] = 1.0
                if right in conditions:
                    weights[conditions.index(right)] = -1.0
            elif n_conditions:
                weights[0] = 1.0
            normalized.append({"name": label.replace(" ", "_") or "contrast", "weights": weights})
        return normalized

    def _parse_bids_events_tsv(self, events_path: str, sfreq: float) -> tuple[np.ndarray, dict[str, int]]:
        """Parse a BIDS events TSV into MNE events array and event_id dict.

        Returns:
            (events, event_id) where events is (n_events, 3) array
            with columns [sample, 0, event_id_int], and event_id maps
            condition names to integer IDs.
        """
        rows: list[dict[str, str]] = []
        with open(events_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(row)

        if not rows:
            raise ValueError(f"Empty events file: {events_path}")

        # Determine onset column
        onset_key = None
        for key in ("onset", "Onset", "ONSET"):
            if key in rows[0]:
                onset_key = key
                break
        if onset_key is None:
            raise ValueError(f"No 'onset' column found in {events_path}. Columns: {list(rows[0].keys())}")

        # Determine trial_type / condition column
        cond_key = None
        for key in ("trial_type", "condition", "stim_type", "value"):
            if key in rows[0]:
                cond_key = key
                break

        # Honor dataset-level exclusion decisions. BIDS permits extra columns;
        # ds007738 uses ``include`` as the final trial eligibility flag.
        if "include" in rows[0]:
            rows = [row for row in rows if str(row.get("include", "1")).strip().lower() in {"1", "true", "yes"}]
        if not rows:
            raise ValueError(f"No included events in {events_path}")

        # Build event_id mapping from unique non-empty conditions.
        conditions_seen: list[str] = []
        for row in rows:
            cond = str(row.get(cond_key, "unknown") if cond_key else "unknown").strip()
            if not cond or cond.lower() == "nan":
                continue
            if cond not in conditions_seen:
                conditions_seen.append(cond)
        if not conditions_seen:
            raise ValueError(f"No task events after filtering {events_path}")
        event_id = {name: i + 1 for i, name in enumerate(conditions_seen)}

        # Build events array [sample, duration_samples, event_id_int].
        events = []
        for row in rows:
            onset = float(row[onset_key])
            sample = int(onset * sfreq)
            duration = float(row.get("duration", 0) or 0)
            duration_samples = max(1, int(round(duration * sfreq)))
            cond = str(row.get(cond_key, "unknown") if cond_key else "unknown").strip()
            eid = event_id.get(cond, 0)
            if eid:
                events.append([sample, duration_samples, eid])

        return np.array(events, dtype=int), event_id

    def _write_execution_summary(
        self,
        result: ExecutionResult,
        logdir: Path,
    ) -> None:
        """Write execution summary to logs directory."""
        logdir.mkdir(parents=True, exist_ok=True)

        summary = {
            "attempt_id": result.attempt_id,
            "total_runs": result.total_runs,
            "successful_runs": result.successful_runs,
            "failed_runs": result.failed_runs,
            "skipped_runs": result.skipped_runs,
            "failure_ids": result.failure_ids,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "concurrency": result.concurrency,
        }
        (logdir / "execution_summary.json").write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )

        # Write action attempts
        attempts = []
        for rr in result.run_results:
            attempts.append(
                {
                    "attempt_id": f"{result.attempt_id}_{rr.run_id}",
                    "run_id": rr.run_id,
                    "status": rr.status,
                    "started_at": rr.started_at,
                    "completed_at": rr.completed_at,
                }
            )
        (logdir / "action_attempts.json").write_text(
            json.dumps(attempts, indent=2),
            encoding="utf-8",
        )

    def _extract_roi_list(self, roi_output: Any) -> list[dict[str, Any]]:
        """Extract ROI results as a flat list from roi_output adapter result."""
        if isinstance(roi_output, dict) and "rois" in roi_output:
            result: list[dict[str, Any]] = roi_output["rois"]
            return result
        return []

    def _extract_channel_list(self, channel_output: Any) -> list[dict[str, Any]]:
        """Extract channel results as a flat list from channel_output adapter result."""
        if isinstance(channel_output, dict) and "channels" in channel_output:
            result2: list[dict[str, Any]] = channel_output["channels"]
            return result2
        return []

    def _write_dependency_provenance(
        self,
        compiled_dir: Path,
        logdir: Path,
        dag: dict[str, Any],
    ) -> None:
        """Write dependency provenance for the execution.

        §16 MVP: runtime artifacts record actual dependency and backend versions.
        §11: environment_manifest.json, backend_probe.json
        """
        import platform
        import sys

        logdir.mkdir(parents=True, exist_ok=True)

        # Collect backend information from DAG
        atoms_list = execution_atoms(dag)
        backends_used: dict[str, dict[str, Any]] = {}

        for atom in atoms_list:
            backend_id = atom.get("backend_id")
            if backend_id and backend_id not in backends_used:
                backends_used[backend_id] = {
                    "backend_id": backend_id,
                    "dependency_profile_id": atom.get("dependency_profile_id"),
                    "required_capabilities": atom.get("required_capabilities", []),
                }

        # Try to get actual backend versions
        backend_versions: dict[str, str] = {}
        for backend_id in backends_used:
            try:
                import importlib.metadata

                if backend_id == "cedalion":
                    version = importlib.metadata.version("cedalion")
                    backend_versions[backend_id] = version
                elif backend_id == "mne_nirs":
                    mne_version = importlib.metadata.version("mne")
                    mne_nirs_version = importlib.metadata.version("mne-nirs")
                    backend_versions[backend_id] = f"mne={mne_version}, mne-nirs={mne_nirs_version}"
            except importlib.metadata.PackageNotFoundError:
                backend_versions[backend_id] = "not installed"

        # Write environment manifest
        env_manifest = {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform.platform(),
            "backends_used": backends_used,
            "backend_versions": backend_versions,
            "execution_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (logdir / "environment_manifest.json").write_text(
            json.dumps(env_manifest, indent=2),
            encoding="utf-8",
        )

        # Copy dependency plan if exists
        dep_plan_path = compiled_dir / "dependency_plan.json"
        if dep_plan_path.exists():
            import shutil

            shutil.copy2(dep_plan_path, logdir / "dependency_plan.json")

        # Write backend probe results
        backend_probe: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "backends": {},
        }
        for backend_id in backends_used:
            backend_probe["backends"][backend_id] = {
                "version": backend_versions.get(backend_id, "unknown"),
                "available": backend_id in backend_versions and backend_versions[backend_id] != "not installed",
            }
        (logdir / "backend_probe.json").write_text(
            json.dumps(backend_probe, indent=2),
            encoding="utf-8",
        )
