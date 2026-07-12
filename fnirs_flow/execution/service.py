"""ExecutionService: unified execution entry point for CLI, API, and WebUI.

Loads compiled plan, resolves data runs, dispatches operations via the
operation registry, and produces structured ExecutionResult.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from fnirs_flow.execution.artifacts import ArtifactRecord, ArtifactStore, write_artifact_manifest
from fnirs_flow.execution.engine import (
    RunContext,
    _build_run_id,
    ensure_derivatives_layout,
)
from fnirs_flow.execution.failures import FailureStore
from fnirs_flow.execution.operations import OperationRegistry, create_default_registry
from fnirs_flow.execution.provenance import ProvenanceRecord


class ExecutionRequest(BaseModel):
    """Unified execution request for CLI, API, and WebUI."""

    project_dir: str
    data_root: str | None = None
    outdir: str | None = None
    participant_labels: list[str] = Field(default_factory=list)
    session_labels: list[str] = Field(default_factory=list)
    run_labels: list[str] = Field(default_factory=list)
    continue_on_failure: bool = True
    reports_only: bool = False


class AtomExecutionResult(BaseModel):
    """Result of executing a single atom/operation."""

    atom_id: str
    status: str = "pending"  # pending, running, completed, failed, skipped
    output_handles: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None


class RunExecutionResult(BaseModel):
    """Result of executing all atoms for a single run."""

    run_id: str
    status: str = "pending"
    atom_results: list[AtomExecutionResult] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    roi_results: list[dict[str, Any]] = Field(default_factory=list)
    channel_results: list[dict[str, Any]] = Field(default_factory=list)
    qc_summary: dict[str, Any] = Field(default_factory=dict)
    started_at: str = ""
    completed_at: str = ""


class ExecutionResult(BaseModel):
    """Unified execution result returned by ExecutionService."""

    attempt_id: str = ""
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    skipped_runs: int = 0
    run_results: list[RunExecutionResult] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    reports: list[str] = Field(default_factory=list)
    failure_ids: list[str] = Field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""


class ExecutionService:
    """Unified execution service for CLI, API, and WebUI.

    Loads the compiled plan and DAG, resolves data runs from the manifest,
    dispatches operations through the registry, and produces a structured
    ExecutionResult.
    """

    def __init__(
        self,
        registry: OperationRegistry | None = None,
    ) -> None:
        self.registry = registry or create_default_registry()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
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

        # Set up output directories
        outdir = Path(request.outdir) if request.outdir else project_dir
        dirs = ensure_derivatives_layout(outdir)

        attempt_id = f"attempt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        started_at = datetime.now(timezone.utc).isoformat()

        # Execute each run
        run_results: list[RunExecutionResult] = []
        artifact_store = ArtifactStore()
        provenance = ProvenanceRecord()
        failure_store = FailureStore()

        for run_ctx in runs:
            run_result = self._execute_run(
                run_ctx,
                plan_data,
                dag,
                outdir,
                continue_on_failure=request.continue_on_failure,
            )
            run_results.append(run_result)

            # Collect artifacts from this run
            for art in run_result.artifacts:
                artifact_store.register(
                    ArtifactRecord(
                        artifact_id=f"{run_result.run_id}_{art.get('type', 'unknown')}",
                        subject=run_ctx.subject,
                        session=run_ctx.session,
                        run=run_ctx.run,
                        step_id=art.get("type", ""),
                        artifact_type=art.get("type", ""),
                        path=art.get("path", ""),
                        sha256=art.get("checksum", ""),
                    )
                )

            # Record provenance for each atom
            for ar in run_result.atom_results:
                provenance.log(
                    step_id=f"{run_result.run_id}/{ar.atom_id}",
                    parameters=ar.output_handles,
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

        # Summarize
        successful = sum(1 for r in run_results if r.status == "completed")
        failed = sum(1 for r in run_results if r.status == "failed")
        skipped = sum(1 for r in run_results if r.status == "skipped")
        failure_ids = [r.run_id for r in run_results if r.status == "failed"]

        completed_at = datetime.now(timezone.utc).isoformat()

        result = ExecutionResult(
            attempt_id=attempt_id,
            total_runs=len(runs),
            successful_runs=successful,
            failed_runs=failed,
            skipped_runs=skipped,
            run_results=run_results,
            failure_ids=failure_ids,
            started_at=started_at,
            completed_at=completed_at,
        )

        # Write summary
        self._write_execution_summary(result, dirs["logs"])

        # Write structured manifests
        write_artifact_manifest(
            artifact_store.to_manifest(run_id=attempt_id),
            dirs["logs"],
        )
        provenance.write(dirs["logs"])
        if failure_store.all():
            failure_store.write_json(dirs["logs"])
            failure_store.write_csv(dirs["logs"])

        # Generate group summary across subjects
        group_path = self._generate_group_summary(run_results, outdir)
        if group_path:
            result.reports.append(str(group_path))

        return result

    def _load_plan(self, compiled_dir: Path) -> dict[str, Any]:
        """Load plan.json from compiled directory."""
        plan_path = compiled_dir / "plan.json"
        if not plan_path.exists():
            raise FileNotFoundError(f"plan.json not found in {compiled_dir}")
        result: dict[str, Any] = json.loads(plan_path.read_text(encoding="utf-8"))
        return result

    def _load_dag(self, compiled_dir: Path) -> dict[str, Any]:
        """Load execution_dag.json from compiled directory."""
        dag_path = compiled_dir / "execution_dag.json"
        if not dag_path.exists():
            raise FileNotFoundError(f"execution_dag.json not found in {compiled_dir}")
        result2: dict[str, Any] = json.loads(dag_path.read_text(encoding="utf-8"))
        return result2

    def _resolve_runs(
        self,
        compiled_dir: Path,
        request: ExecutionRequest,
    ) -> list[RunContext]:
        """Resolve data runs from manifest, filtered by request labels."""
        manifest_path = compiled_dir / "data_manifest.json"
        if not manifest_path.exists():
            # Fallback to parent directory
            manifest_path = compiled_dir.parent / "data_manifest.json"

        if not manifest_path.exists():
            # No manifest: single placeholder run
            return [
                RunContext(
                    run_id="placeholder-run",
                    status="pending",
                )
            ]

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        runs: list[RunContext] = []

        for sr in manifest.get("subject_session_runs", []):
            # Apply filters
            if request.participant_labels:
                if sr.get("subject") not in request.participant_labels:
                    continue
            if request.session_labels:
                if sr.get("session") not in request.session_labels:
                    continue
            if request.run_labels:
                if sr.get("run") not in request.run_labels:
                    continue

            run_id = _build_run_id(sr)

            # Resolve data path
            data_path = sr.get("path", "")
            if request.data_root and data_path:
                candidate = Path(request.data_root) / data_path
                if candidate.exists():
                    data_path = str(candidate)
                else:
                    # Try relative path as-is
                    candidate = Path(data_path)
                    if candidate.exists():
                        data_path = str(candidate)

            runs.append(
                RunContext(
                    run_id=run_id,
                    subject=sr.get("subject", ""),
                    session=sr.get("session", ""),
                    run=sr.get("run", ""),
                    task=sr.get("task", ""),
                    data_path=data_path,
                    relative_path=sr.get("relative_path", ""),
                    data_sha256=sr.get("data_sha256", ""),
                    events_path=sr.get("events_path", ""),
                    status="pending",
                )
            )

        return runs

    def _execute_run(
        self,
        run_ctx: RunContext,
        plan: dict[str, Any],
        dag: dict[str, Any],
        outdir: Path,
        continue_on_failure: bool = True,
    ) -> RunExecutionResult:
        """Execute all atoms for a single run using DAG-based scheduling."""
        run_result = RunExecutionResult(
            run_id=run_ctx.run_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # Check if data file exists
            if not run_ctx.data_path or not Path(run_ctx.data_path).exists():
                run_result.status = "skipped"
                run_result.completed_at = datetime.now(timezone.utc).isoformat()
                return run_result

            # Execute using DAG-based scheduling
            self._execute_dag(
                run_ctx,
                dag,
                outdir,
                run_result,
                continue_on_failure=continue_on_failure,
            )

        except ImportError:
            # MNE not available: mark as failed with clear message
            run_result.status = "failed"
            run_result.atom_results.append(
                AtomExecutionResult(
                    atom_id="mne_import",
                    status="failed",
                    error="MNE-Python is required for real execution.",
                    error_code="ATOM_MANIFEST_MISSING",
                )
            )
        except Exception as exc:
            run_result.status = "failed"
            run_result.atom_results.append(
                AtomExecutionResult(
                    atom_id="execution",
                    status="failed",
                    error=str(exc),
                    error_code="FLOW_CYCLE_DETECTED",
                )
            )

        run_result.completed_at = datetime.now(timezone.utc).isoformat()
        return run_result

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
        """
        from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter

        # Create adapter
        run_outdir = outdir / run_ctx.run_id
        run_outdir.mkdir(parents=True, exist_ok=True)
        adapter = MneNirsAdapter(
            subject=run_ctx.subject,
            session=run_ctx.session,
            run=run_ctx.run,
            outdir=run_outdir,
        )

        # Read data
        raw = adapter.read_run(run_ctx.data_path)

        # Build atom map from DAG
        atoms_list = dag.get("atoms", dag.get("nodes", []))
        atom_map = {a.get("atom_id") or a.get("step_id"): a for a in atoms_list}

        # Get execution layers
        layers = dag.get("execution_layers", [])

        # If no layers, fall back to simple sequential execution
        if not layers:
            layers = [[a.get("atom_id") or a.get("step_id") for a in atoms_list]]

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
                # Split: execute dependencies first, then dependents
                dep_atoms = []
                non_dep_atoms = []
                for atom_id in layer:
                    deps_in_layer = dep_map.get(atom_id, set()) & layer_set
                    if not deps_in_layer:
                        dep_atoms.append(atom_id)
                    else:
                        non_dep_atoms.append(atom_id)
                if dep_atoms:
                    fixed_layers.append(sorted(dep_atoms))
                if non_dep_atoms:
                    fixed_layers.append(sorted(non_dep_atoms))
            else:
                fixed_layers.append(layer)
        layers = fixed_layers

        # Track intermediate results: atom_id -> result
        intermediate_state: dict[str, Any] = {
            "raw": raw,
            "data_path": run_ctx.data_path,
            "events_path": run_ctx.events_path,
        }

        # Execute layer by layer
        for layer in layers:
            for atom_id in layer:
                atom = atom_map.get(atom_id)
                if not atom:
                    continue

                operation = atom.get("operation") or atom.get("atom_type") or atom.get("node_type", "")
                params = dict(atom.get("parameters", {}))
                category = atom.get("category", "")

                # Skip data nodes (dataset_discovery, read_run) - already handled
                if category == "data":
                    intermediate_state[atom_id] = {"status": "skipped"}
                    continue

                atom_result = AtomExecutionResult(
                    atom_id=atom_id,
                    status="running",
                )

                try:
                    # Inject dependencies from intermediate state
                    self._inject_dependencies(atom, params, intermediate_state)

                    # Dispatch based on category
                    if category == "preprocessing":
                        result = self._dispatch_preprocessing(
                            adapter,
                            intermediate_state.get("raw"),
                            operation,
                            params,
                        )
                        # Update raw if result is a raw-like object
                        if hasattr(result, "ch_names"):
                            intermediate_state["raw"] = result
                        intermediate_state[atom_id] = result
                    elif category in ("analysis", "output"):
                        result = self._dispatch_analysis(
                            adapter,
                            intermediate_state.get("raw"),
                            operation,
                            params,
                        )
                        intermediate_state[atom_id] = result
                        # Store specific results for downstream injection
                        if operation == "build_design_matrix":
                            intermediate_state["design_matrix"] = result
                        elif operation == "first_level_glm":
                            intermediate_state["glm_result"] = result
                        elif operation == "estimate_contrast":
                            intermediate_state["contrast_result"] = result
                        elif operation == "channel_output":
                            intermediate_state["channel_results"] = result
                        elif operation == "roi_output":
                            intermediate_state["roi_results"] = result
                            # Store in run_result for group summary
                            run_result.roi_results = self._extract_roi_list(result)
                        elif operation == "channel_output":
                            run_result.channel_results = self._extract_channel_list(result)
                    else:
                        # Data nodes (e.g., read_run) - skip, already handled
                        intermediate_state[atom_id] = {"status": "skipped"}

                    atom_result.status = "completed"
                    result_type = type(result).__name__ if result else "None"
                    atom_result.output_handles["data"] = result_type

                except Exception as exc:
                    atom_result.status = "failed"
                    atom_result.error = str(exc)
                    run_result.atom_results.append(atom_result)
                    if not continue_on_failure:
                        run_result.status = "failed"
                        return

                run_result.atom_results.append(atom_result)

        # Collect artifacts
        for artifact in adapter.artifacts.all():
            run_result.artifacts.append(
                {
                    "type": artifact.artifact_type,
                    "path": artifact.path,
                    "checksum": artifact.sha256,
                }
            )

        if run_result.status == "running":
            run_result.status = "completed"

    def _inject_dependencies(
        self,
        atom: dict[str, Any],
        params: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        """Inject intermediate results from state into atom parameters.

        Uses a data-driven mapping of operation -> state keys to inject.
        """
        operation = atom.get("operation") or atom.get("atom_type") or ""

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

    def _dispatch_preprocessing(
        self,
        adapter: Any,
        raw: Any,
        operation: str,
        params: dict[str, Any],
    ) -> Any:
        """Dispatch a preprocessing operation to the adapter."""
        dispatch = {
            "optical_density": lambda: adapter.to_optical_density(raw),
            "compute_qc": lambda: adapter.compute_qc(raw),
            "motion_correction": lambda: adapter.apply_motion_correction(
                raw,
                method=params.get("method", "tddr"),
            ),
            "filtering": lambda: adapter.apply_filter(
                raw,
                l_freq=params.get("l_freq", 0.01),
                h_freq=params.get("h_freq", 0.2),
            ),
            "beer_lambert_law": lambda: adapter.to_haemoglobin(
                raw,
                ppf=params.get("ppf", 6.0),
            ),
        }
        handler = dispatch.get(operation)
        if handler is None:
            raise ValueError(f"Unknown preprocessing operation: {operation}")
        return handler()

    def _dispatch_analysis(
        self,
        adapter: Any,
        raw: Any,
        operation: str,
        params: dict[str, Any],
    ) -> Any:
        """Dispatch an analysis operation to the adapter."""

        def _build_design_matrix():
            events = params.get("events")
            event_id = params.get("event_id", {})
            if events is None:
                raise ValueError(
                    "build_design_matrix requires 'events' in params. Provide MNE events array or events TSV path."
                )
            return adapter.build_design_matrix(
                raw,
                events=events,
                event_id=event_id,
                hrf_model=params.get("hrf_model", "glover"),
                drift_order=params.get("drift_order", 1),
                high_pass=params.get("high_pass", 0.01),
            )

        def _first_level_glm():
            design_matrix = params.get("design_matrix")
            if design_matrix is None:
                raise ValueError("first_level_glm requires 'design_matrix' in params. Run build_design_matrix first.")
            return adapter.fit_first_level_glm(
                raw,
                design_matrix,
                hrf_model=params.get("hrf_model", "glover"),
                noise_model=params.get("noise_model", "ar1"),
            )

        def _estimate_contrast():
            glm_result = params.get("glm_result")
            contrasts = params.get("contrasts", [])
            if glm_result is None:
                raise ValueError("estimate_contrast requires 'glm_result' in params. Run first_level_glm first.")
            return adapter.estimate_contrast(glm_result, contrasts)

        def _channel_output():
            contrast_result = params.get("contrast_result")
            if contrast_result is None:
                raise ValueError("channel_output requires 'contrast_result' in params. Run estimate_contrast first.")
            return adapter.channel_output(contrast_result)

        def _roi_output():
            channel_results = params.get("channel_results")
            if channel_results is None:
                raise ValueError("roi_output requires 'channel_results' in params. Run channel_output first.")
            return adapter.roi_output(
                channel_results,
                atlas=params.get("atlas", "mni"),
                roi_mapping=params.get("roi_mapping"),
            )

        dispatch = {
            "block_averaging": lambda: adapter.block_averaging(
                raw,
                baseline_window=params.get("baseline_window", [-5, 0]),
                response_window=params.get("response_window", [0, 20]),
            ),
            "build_design_matrix": _build_design_matrix,
            "first_level_glm": _first_level_glm,
            "estimate_contrast": _estimate_contrast,
            "channel_output": _channel_output,
            "roi_output": _roi_output,
        }
        handler = dispatch.get(operation)
        if handler is None:
            raise ValueError(f"Unknown analysis operation: {operation}")
        return handler()

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

        # Build event_id mapping from unique conditions
        conditions_seen: list[str] = []
        for row in rows:
            cond = row.get(cond_key, "unknown") if cond_key else "unknown"
            if cond not in conditions_seen:
                conditions_seen.append(cond)
        event_id = {name: i + 1 for i, name in enumerate(conditions_seen)}

        # Build MNE events array [sample, 0, event_id_int]
        events = []
        for row in rows:
            onset = float(row[onset_key])
            sample = int(onset * sfreq)
            cond = row.get(cond_key, "unknown") if cond_key else "unknown"
            eid = event_id.get(cond, 0)
            events.append([sample, 0, eid])

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

    def _generate_group_summary(
        self,
        run_results: list[RunExecutionResult],
        outdir: Path,
    ) -> Path | None:
        """Compute group-level statistics across all completed runs.

        Collects ROI results from completed runs, converts to ROIResult models,
        and calls compute_group_statistics() + export_group_summary().

        Returns:
            Path to group_summary.csv, or None if insufficient data.
        """
        from fnirs_flow.exporters.outputs import (
            ROIResult,
            compute_group_statistics,
            export_group_summary,
        )

        all_roi_results: list[ROIResult] = []
        excluded_subjects: list[str] = []

        for rr in run_results:
            if rr.status == "failed":
                excluded_subjects.append(rr.run_id)
                continue
            if rr.status == "skipped":
                excluded_subjects.append(rr.run_id)
                continue
            if not rr.roi_results:
                continue

            # Extract subject label from run_id (e.g., "sub-01_task-tapping" -> "sub-01")
            subject = rr.run_id.split("_")[0] if "_" in rr.run_id else rr.run_id

            for roi_dict in rr.roi_results:
                roi_name = roi_dict.get("roi_name", roi_dict.get("roi", ""))
                for key, value in roi_dict.items():
                    if key.endswith("_beta_mean") or key.endswith("_beta"):
                        contrast = key.replace("_beta_mean", "").replace("_beta", "")
                        all_roi_results.append(
                            ROIResult(
                                subject=subject,
                                roi=roi_name,
                                contrast=contrast,
                                beta=float(value) if value is not None else 0.0,
                                n_channels=roi_dict.get("n_channels", 0),
                            )
                        )

        if not all_roi_results:
            return None

        # Compute group statistics
        summaries = compute_group_statistics(all_roi_results, exclude_subjects=excluded_subjects)

        # Patch excluded_subjects into summaries (subjects that never produced ROI results
        # won't appear in compute_group_statistics's intersection logic)
        for s in summaries:
            existing = set(s.excluded_subjects)
            for subj in excluded_subjects:
                if subj not in existing:
                    s.excluded_subjects.append(subj)

        # Write to derivatives/group/
        group_dir = outdir / "derivatives" / "group"
        group_dir.mkdir(parents=True, exist_ok=True)

        # Export group summary CSV
        csv_path = export_group_summary(summaries, group_dir)

        # Export group summary JSON
        group_json = {
            "n_subjects_included": len(
                {r.subject for r in all_roi_results}
            ),
            "n_subjects_excluded": len(excluded_subjects),
            "excluded_subjects": excluded_subjects,
            "n_rois": len(summaries),
            "summaries": [
                {
                    "roi": s.roi,
                    "chromophore": s.chromophore,
                    "contrast": s.contrast,
                    "n_subjects": s.n_subjects,
                    "mean_beta": s.mean_beta,
                    "std_beta": s.std_beta,
                    "p_value": s.p_value,
                    "ci_lower": s.confidence_interval[0],
                    "ci_upper": s.confidence_interval[1],
                }
                for s in summaries
            ],
        }
        (group_dir / "group_summary.json").write_text(
            json.dumps(group_json, indent=2),
            encoding="utf-8",
        )

        return csv_path
