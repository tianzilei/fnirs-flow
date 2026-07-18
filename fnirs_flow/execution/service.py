"""ExecutionService: unified execution entry point for CLI, API, and WebUI.

Loads compiled plan, resolves data runs, dispatches operations via the
operation registry, and produces structured ExecutionResult.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import warnings
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from fnirs_flow.data.participants import (
    ParticipantTable,
    build_group_design_matrix,
    default_group_contrasts,
    fit_group_glm,
    join_participant_metadata,
    load_participant_table_from_artifacts,
    write_participant_table_artifacts,
)
from fnirs_flow.execution.artifacts import ArtifactRecord, ArtifactStore, write_artifact_manifest
from fnirs_flow.execution.engine import (
    RunContext,
    _build_run_id,
    ensure_derivatives_layout,
)
from fnirs_flow.execution.failures import FailureStore
from fnirs_flow.execution.operations import OperationRegistry, create_default_registry
from fnirs_flow.execution.provenance import ProvenanceRecord
from fnirs_flow.filesystem import remove_macos_metadata_paths

logger = logging.getLogger(__name__)


def resolve_atom_backend_id(atom: dict[str, Any], default_backend_id: str) -> str:
    """Return the atom backend, treating missing/null backend ids as default."""
    return atom.get("backend_id") or default_backend_id


class ExecutionRequest(BaseModel):
    """Unified execution request for CLI, API, and WebUI."""

    project_dir: str
    data_root: str | None = None
    outdir: str | None = None
    participant_labels: list[str] = Field(default_factory=list)
    session_labels: list[str] = Field(default_factory=list)
    task_labels: list[str] = Field(default_factory=list)
    run_labels: list[str] = Field(default_factory=list)
    continue_on_failure: bool = True
    reports_only: bool = False
    attempt_id: str = ""
    commit_id: str = ""
    snapshot_id: str = ""


class ExecutionCancelledError(RuntimeError):
    """Raised when a persistent execution job requests cooperative cancellation."""


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
    evidence_refs: list[str] = Field(default_factory=list)


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
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.registry = registry or create_default_registry()
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self._active_attempt_id = ""

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
        failure_store = FailureStore()
        group_atom_results = self._execute_group_scope_atoms(dag, outdir)

        for run_ctx in runs:
            self._check_cancelled()
            self._emit_progress("run_started", run_id=run_ctx.run_id)
            run_result = self._execute_run(
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

        # Write dependency provenance (§16 MVP: run artifacts record actual dependencies and backend versions)
        self._write_dependency_provenance(compiled_dir, dirs["logs"], dag)

        # Generate group summary across subjects
        group_path = self._generate_group_summary(
            run_results,
            outdir,
            group_config=self._extract_group_config(plan_data, dag),
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

    def _execute_group_scope_atoms(self, dag: dict[str, Any], outdir: Path) -> list[AtomExecutionResult]:
        atoms = dag.get("atoms", dag.get("nodes", []))
        group_atoms = [
            atom
            for atom in atoms
            if atom.get("execution_scope") == "group"
            and (atom.get("operation") or atom.get("atom_type"))
            in {
                "participant_table_input",
                "participant_metadata_validate",
                "participant_label_projection",
                "participant_site_projection",
                "participant_covariate_projection",
                "participant_dpf_projection",
                "participant_outcome_projection",
                "localization_projection_import",
                "nirs_spm_surface_projection",
                "combat_preflight",
                "observation_pairing_projection",
                "group_design_matrix",
                "group_level_glm",
                "group_contrast",
            }
        ]
        if not group_atoms:
            return []
        results: list[AtomExecutionResult] = []
        state: dict[str, Any] = {}
        compiled_dir = outdir / "compiled"
        for atom in group_atoms:
            atom_id = atom.get("atom_id") or atom.get("step_id") or atom.get("operation", "group_atom")
            operation = atom.get("operation") or atom.get("atom_type", "")
            params = dict(atom.get("parameters", {}))
            result = AtomExecutionResult(
                atom_id=atom_id,
                status="running",
                evidence_refs=atom.get("evidence_refs", []),
                provenance={"operation": operation, "execution_scope": "group"},
            )
            try:
                from fnirs_flow.data.manifest import DataManifest
                from fnirs_flow.data.participants import (
                    ColumnRoleMap,
                    project_combat_manifest,
                    project_covariate_matrix,
                    project_dpf_inputs,
                    project_dyad_structure,
                    project_label_vector,
                    project_outcome_vector,
                    project_pairing_structure,
                    project_site_metadata,
                    read_participant_table,
                    validate_participant_table,
                    write_participant_table_artifacts,
                )

                if operation == "participant_table_input":
                    path = params.get("path") or params.get("table_path")
                    if not path:
                        loaded = load_participant_table_from_artifacts(
                            compiled_dir
                        ) or load_participant_table_from_artifacts(outdir)
                        if loaded is None:
                            raise ValueError("GROUP_METADATA_MISSING: participant_table_input requires path")
                        table = loaded
                    else:
                        roles = ColumnRoleMap(
                            id_column=params.get("id_column", "participant_id"),
                            include_column=params.get("include_column", "include"),
                            group_column=params.get("group_column", "group"),
                            label_column=params.get("label_column", ""),
                            site_column=params.get("site_column", "site"),
                            scanner_column=params.get("scanner_column", "scanner_id"),
                            covariate_columns=list(params.get("covariates", [])),
                        )
                        table = read_participant_table(
                            path,
                            table_kind=params.get("table_kind", "participant"),
                            delimiter=params.get("delimiter", "auto"),
                            encoding=params.get("encoding", "utf-8-sig"),
                            column_role_map=roles,
                        )
                    manifest_path = compiled_dir / "data_manifest.json"
                    manifest = (
                        DataManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
                        if manifest_path.exists()
                        else None
                    )
                    bundle = write_participant_table_artifacts(table, compiled_dir, manifest=manifest)
                    state["participant_table"] = table
                    result.output_handles = {
                        "participant_table": "ParticipantTable",
                        "rows": len(table.rows),
                        "manifest": bundle.participant_table_manifest.model_dump(),
                    }
                elif operation == "participant_metadata_validate":
                    validate_table: ParticipantTable | None = state.get(
                        "participant_table"
                    ) or load_participant_table_from_artifacts(compiled_dir)
                    if validate_table is None:
                        raise ValueError("GROUP_METADATA_MISSING: no participant table to validate")
                    manifest_path = compiled_dir / "data_manifest.json"
                    manifest = (
                        DataManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
                        if manifest_path.exists()
                        else None
                    )
                    report = validate_participant_table(validate_table, manifest)
                    state["participant_validation_report"] = report
                    if not report.is_valid:
                        raise ValueError("; ".join(report.errors))
                    result.output_handles = {"validation_report": report.model_dump()}
                elif operation == "participant_label_projection":
                    label_table: ParticipantTable | None = state.get(
                        "participant_table"
                    ) or load_participant_table_from_artifacts(compiled_dir)
                    if label_table is None:
                        raise ValueError("GROUP_METADATA_MISSING: no participant table for labels")
                    labels = project_label_vector(label_table, params.get("label_column"))
                    state["labels"] = labels
                    result.output_handles = labels
                elif operation == "participant_site_projection":
                    site_table: ParticipantTable | None = state.get(
                        "participant_table"
                    ) or load_participant_table_from_artifacts(compiled_dir)
                    if site_table is None:
                        raise ValueError("GROUP_METADATA_MISSING: no participant table for site metadata")
                    site_metadata = project_site_metadata(site_table, params.get("site_column"))
                    state["site_metadata"] = site_metadata
                    result.output_handles = site_metadata
                elif operation == "participant_covariate_projection":
                    covariate_table: ParticipantTable | None = state.get(
                        "participant_table"
                    ) or load_participant_table_from_artifacts(compiled_dir)
                    if covariate_table is None:
                        raise ValueError("GROUP_METADATA_MISSING: no participant table for covariates")
                    covariates_raw = params.get("covariates", params.get("covariate_columns", []))
                    covariates = list(covariates_raw) if covariates_raw is not None else []
                    covariate_matrix = project_covariate_matrix(covariate_table, [str(column) for column in covariates])
                    state["covariate_matrix"] = covariate_matrix
                    result.output_handles = covariate_matrix
                elif operation == "participant_dpf_projection":
                    dpf_table: ParticipantTable | None = state.get(
                        "participant_table"
                    ) or load_participant_table_from_artifacts(compiled_dir)
                    if dpf_table is None:
                        raise ValueError("GROUP_METADATA_MISSING: no participant table for DPF projection")
                    dpf_inputs = project_dpf_inputs(
                        dpf_table,
                        age_column=str(params.get("age_column", "age")),
                        wavelength_columns=[str(column) for column in params.get("wavelength_columns", [])],
                    )
                    state["dpf_inputs"] = dpf_inputs
                    result.output_handles = dpf_inputs
                elif operation == "participant_outcome_projection":
                    outcome_table: ParticipantTable | None = state.get(
                        "participant_table"
                    ) or load_participant_table_from_artifacts(compiled_dir)
                    if outcome_table is None:
                        raise ValueError("GROUP_METADATA_MISSING: no participant table for outcome projection")
                    outcome = project_outcome_vector(
                        outcome_table,
                        str(params.get("outcome_column", "")),
                        outcome_kind=str(params.get("outcome_kind", "behavioral")),
                    )
                    state["outcome_vector"] = outcome
                    result.output_handles = outcome
                elif operation == "localization_projection_import":
                    from fnirs_flow.adapters.localization_import import import_projection_coordinate_csv

                    path = params.get("path") or params.get("csv_path") or params.get("projection_csv")
                    if not path:
                        raise ValueError(
                            "LOCALIZATION_PROJECTION_MISSING: localization_projection_import requires path"
                        )
                    import_result = import_projection_coordinate_csv(
                        path,
                        outdir / "derivatives" / "localization",
                        base_dir=outdir,
                        atom_id=atom_id,
                        coordinate_set_id=str(params.get("coordinate_set_id", "")),
                        coordinate_columns=params.get("coordinate_columns"),
                        label_column=str(params.get("label_column", "")),
                        include_match_statuses=params.get("include_match_statuses"),
                        accuracy_caveat=str(params.get("accuracy_caveat", "not_claimed_to_reproduce_nirsspm_accuracy")),
                        method_id=str(params.get("method_id", operation)),
                    )
                    state["projected_mni_channels"] = import_result["output"]
                    result.output_handles = import_result["output_handles"]
                    result.provenance.update(import_result["provenance"])
                    result.warnings.extend(import_result["warnings"])
                    result.artifacts.extend(
                        [
                            self._path_artifact_summary(
                                path,
                                outdir,
                                artifact_type="ProjectedMNIChannels"
                                if path.name.endswith("_projected_mni_channels.csv")
                                else "ProjectionImportManifest",
                                artifact_id=f"{atom_id}-{path.stem}",
                                atom_id=atom_id,
                                step_id=atom_id,
                            )
                            for path in import_result["artifact_paths"]
                        ]
                    )
                elif operation == "nirs_spm_surface_projection":
                    from fnirs_flow.adapters.nirsspm_projection import run_nirsspm_surface_projection_csv

                    path = params.get("path") or params.get("csv_path") or params.get("head_surface_mni_csv")
                    if not path:
                        raise ValueError("NIRS_SPM_PROJECTION_MISSING: nirs_spm_surface_projection requires path")
                    projection_result = run_nirsspm_surface_projection_csv(
                        path,
                        outdir / "derivatives" / "localization",
                        reference_dir=params.get("reference_dir"),
                        base_dir=outdir,
                        atom_id=atom_id,
                        coordinate_set_id=str(params.get("coordinate_set_id", "")),
                        label_column=str(params.get("label_column", "")),
                        head_coordinate_columns=params.get("head_coordinate_columns"),
                        reference_coordinate_columns=params.get("reference_coordinate_columns"),
                    )
                    state["nirsspm_projected_mni"] = projection_result["output"]
                    result.output_handles = projection_result["output_handles"]
                    result.provenance.update(projection_result["provenance"])
                    result.warnings.extend(projection_result["warnings"])
                    result.artifacts.extend(
                        [
                            self._path_artifact_summary(
                                path,
                                outdir,
                                artifact_type="NirsspmSurfaceProjection"
                                if path.name.endswith("_nirsspm_surface_projection.csv")
                                else "ProjectionValidationReport",
                                artifact_id=f"{atom_id}-{path.stem}",
                                atom_id=atom_id,
                                step_id=atom_id,
                            )
                            for path in projection_result["artifact_paths"]
                        ]
                    )
                elif operation == "combat_preflight":
                    combat_table: ParticipantTable | None = state.get(
                        "participant_table"
                    ) or load_participant_table_from_artifacts(compiled_dir)
                    if combat_table is None:
                        raise ValueError("GROUP_METADATA_MISSING: no participant table for ComBat preflight")
                    combat_manifest = project_combat_manifest(
                        combat_table,
                        site_column=params.get("site_column"),
                        biological_covariates=[str(column) for column in params.get("biological_covariates", [])],
                    )
                    from fnirs_flow.registry.combat_diagnostics import validate_combat_preflight

                    preflight = validate_combat_preflight(
                        combat_manifest,
                        site_field="site",
                        biological_covariates=combat_manifest["biological_covariates"],
                        min_samples_per_site=int(params.get("min_samples_per_site", 5)),
                    )
                    state["combat_preflight"] = preflight.model_dump()
                    result.output_handles = preflight.model_dump()
                elif operation == "observation_pairing_projection":
                    pairing_table: ParticipantTable | None = state.get(
                        "participant_table"
                    ) or load_participant_table_from_artifacts(compiled_dir)
                    if pairing_table is None:
                        raise ValueError("GROUP_METADATA_MISSING: no observation table for pairing")
                    if getattr(pairing_table, "table_kind", "participant") != "observation":
                        raise ValueError(
                            "GROUP_METADATA_MISSING: observation_pairing_projection requires ObservationTable"
                        )
                    from fnirs_flow.data.participants import ObservationTable

                    observation_table = ObservationTable(**pairing_table.model_dump())
                    pairing = project_pairing_structure(observation_table)
                    dyad = project_dyad_structure(observation_table)
                    result.output_handles = {"pairing_structure": pairing, "dyad_structure": dyad}
                elif operation == "group_design_matrix":
                    result.output_handles = {"status": "deferred_to_group_summary"}
                elif operation == "group_level_glm":
                    result.output_handles = {
                        "status": "deferred_to_group_summary",
                        "expected_tables": ["group_glm_results.csv", "group_glm_results.json"],
                    }
                elif operation == "group_contrast":
                    result.output_handles = {
                        "status": "deferred_to_group_summary",
                        "expected_tables": ["contrast_results.csv", "contrast_results.json"],
                        "expected_figures": ["contrast_effects.svg"],
                    }
                result.status = "completed"
            except (OSError, ValueError, TypeError) as exc:
                result.status = "failed"
                result.error = str(exc)
                result.error_code = "GROUP_EXECUTION_VALIDATION_ERROR"
            results.append(result)
        return results

    @staticmethod
    def _extract_group_config(plan: dict[str, Any], dag: dict[str, Any]) -> dict[str, Any]:
        config: dict[str, Any] = {}
        for atom in dag.get("atoms", dag.get("nodes", [])):
            operation = atom.get("operation") or atom.get("atom_type")
            if operation not in {"group_design_matrix", "group_level_glm", "group_contrast"}:
                continue
            params = atom.get("parameters", {})
            if not isinstance(params, dict):
                continue
            if operation == "group_contrast":
                contrast_params = dict(params)
                if "contrasts" not in contrast_params and (
                    contrast_params.get("contrast_expression")
                    or contrast_params.get("weights")
                    or contrast_params.get("weight_matrix")
                ):
                    contrast_params["contrasts"] = [
                        {
                            "name": contrast_params.get("contrast_name")
                            or contrast_params.get("name")
                            or "Group contrast",
                            "type": contrast_params.get("contrast_type") or contrast_params.get("type") or "T",
                            "expression": contrast_params.get("contrast_expression", ""),
                            "weights": contrast_params.get("weights"),
                            "weight_matrix": contrast_params.get("weight_matrix"),
                            "terms": contrast_params.get("terms"),
                        }
                    ]
                config.update({key: value for key, value in contrast_params.items() if value not in (None, "")})
            else:
                config.update(params)
        group_model = plan.get("group_model", {})
        if isinstance(group_model, dict):
            return {**group_model, **config}
        return config

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
            raise FileNotFoundError(f"data_manifest.json not found in {compiled_dir}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        data_root = (
            Path(request.data_root or manifest.get("local_root", "")).resolve()
            if (request.data_root or manifest.get("local_root"))
            else None
        )
        runs: list[RunContext] = []
        seen_run_ids: set[str] = set()

        def resolve_data_path(value: str, relative_path: str = "") -> str:
            from fnirs_flow.api.uri import ProjectURI

            if value.startswith("external-data://"):
                try:
                    uri = ProjectURI(value)
                except ValueError:
                    return ""
                if data_root is not None:
                    candidate = data_root / Path(*uri.path.parts)
                    return str(candidate) if candidate.exists() else ""
                return ""
            if data_root is not None and relative_path:
                candidate = data_root / relative_path
                if candidate.exists():
                    return str(candidate)
            if value:
                candidate = Path(value)
                if candidate.exists():
                    return str(candidate)
            return ""

        for sr in manifest.get("subject_session_runs", []):
            # Apply filters
            if request.participant_labels:
                if sr.get("subject") not in request.participant_labels:
                    continue
            if request.session_labels:
                if sr.get("session") not in request.session_labels:
                    continue
            if request.task_labels:
                if sr.get("task") not in request.task_labels:
                    continue
            if request.run_labels:
                if sr.get("run") not in request.run_labels:
                    continue

            run_id = _build_run_id(sr, _seen=seen_run_ids)

            # Resolve data path
            relative_path = str(sr.get("relative_path", ""))
            data_path = resolve_data_path(
                str(sr.get("uri") or sr.get("path", "")),
                relative_path,
            )
            events_path = resolve_data_path(
                str(sr.get("events_uri") or sr.get("events_path", "")),
            )

            runs.append(
                RunContext(
                    run_id=run_id,
                    subject=sr.get("subject", ""),
                    session=sr.get("session", ""),
                    run=sr.get("run", ""),
                    task=sr.get("task", ""),
                    data_path=data_path,
                    relative_path=relative_path,
                    data_sha256=sr.get("data_sha256", ""),
                    events_path=events_path,
                    status="pending",
                )
            )

        if not runs:
            raise ValueError("No data runs matched the execution request")
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
            self._check_cancelled()
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
            if run_result.status == "completed":
                self._write_run_outputs(run_result, outdir)

        except ExecutionCancelledError:
            raise
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
        except OSError as exc:
            run_result.status = "failed"
            run_result.atom_results.append(
                AtomExecutionResult(
                    atom_id="execution",
                    status="failed",
                    error=str(exc),
                    error_code="EXECUTION_IO_ERROR",
                )
            )
        except (ValueError, TypeError) as exc:
            run_result.status = "failed"
            run_result.atom_results.append(
                AtomExecutionResult(
                    atom_id="execution",
                    status="failed",
                    error=str(exc),
                    error_code="EXECUTION_VALIDATION_ERROR",
                )
            )
        except TimeoutError as exc:
            run_result.status = "failed"
            run_result.atom_results.append(
                AtomExecutionResult(
                    atom_id="execution",
                    status="failed",
                    error=str(exc),
                    error_code="EXECUTION_TIMEOUT",
                )
            )
        except Exception as exc:
            logger.exception("Unexpected error during run %s", run_ctx.run_id)
            run_result.status = "failed"
            run_result.atom_results.append(
                AtomExecutionResult(
                    atom_id="execution",
                    status="failed",
                    error=str(exc),
                    error_code="EXECUTION_FAILED",
                )
            )

        run_result.completed_at = datetime.now(timezone.utc).isoformat()
        return run_result

    def _write_run_outputs(self, run_result: RunExecutionResult, outdir: Path) -> None:
        """Persist finite channel and ROI tables for one completed run."""

        outputs = (
            ("channel", run_result.channel_results),
            ("roi", run_result.roi_results),
        )
        for kind, rows in outputs:
            if not rows:
                continue
            for row_index, row in enumerate(rows):
                for key, value in row.items():
                    if isinstance(value, float) and not math.isfinite(value):
                        raise ValueError(f"Non-finite {kind} result at row {row_index}, field '{key}'")
            result_dir = outdir / "derivatives" / kind
            result_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{run_result.run_id}_{kind}_results"
            json_path = result_dir / f"{stem}.json"
            csv_path = result_dir / f"{stem}.csv"
            json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            fieldnames = list(dict.fromkeys(key for row in rows for key in row))
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            for path in (json_path, csv_path):
                source_atom_ids = sorted(
                    {str(row.get("source_atom_id", "")) for row in rows if row.get("source_atom_id")}
                )
                artifact = self._path_artifact_summary(
                    path,
                    outdir,
                    artifact_type=f"{kind.title()}Results",
                    artifact_id=f"{run_result.run_id}-{kind}-{path.suffix.lstrip('.')}",
                    atom_id=",".join(source_atom_ids),
                    step_id=f"{kind}_output",
                )
                run_result.artifacts.append(artifact)
                for atom_id in source_atom_ids:
                    atom_result = next(
                        (item for item in run_result.atom_results if item.atom_id == atom_id),
                        None,
                    )
                    if atom_result is not None:
                        atom_result.artifacts.append({**artifact, "atom_id": atom_id})

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
        from fnirs_flow.api.uri import create_project_uri

        resolved_path = path.resolve()
        try:
            relative_path = str(resolved_path.relative_to(outdir.resolve()))
        except ValueError:
            relative_path = ""

        # Create project URI
        uri = create_project_uri(f"outputs/{relative_path}") if relative_path else None

        return {
            "artifact_id": artifact_id,
            "type": artifact_type,
            "uri": str(uri) if uri else "",
            "path": str(uri) if uri else "",
            "resolved_path": str(resolved_path),
            "relative_path": relative_path,
            "checksum": hashlib.sha256(resolved_path.read_bytes()).hexdigest(),
            "exists": resolved_path.is_file(),
            "atom_id": atom_id,
            "step_id": step_id,
        }

    def _append_adapter_artifacts(
        self,
        run_result: RunExecutionResult,
        atom_result: AtomExecutionResult | None,
        records: list[ArtifactRecord],
        outdir: Path,
    ) -> None:
        """Attach newly emitted adapter artifacts to their atom and run."""
        from fnirs_flow.api.uri import create_project_uri

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
        group_dir = outdir / "derivatives" / "group"
        if not group_dir.is_dir():
            return []
        artifact_specs = {
            "analysis_table.csv": ("GroupAnalysisTable", "group_design_matrix"),
            "group_design_matrix.csv": ("GroupDesignMatrix", "group_design_matrix"),
            "group_design_spec.json": ("GroupDesignSpec", "group_design_matrix"),
            "group_summary.csv": ("GroupSummaryTable", "group_summary"),
            "group_summary.json": ("GroupSummaryJson", "group_summary"),
            "group_glm_results.csv": ("GroupGLMResultsTable", "group_level_glm"),
            "group_glm_results.json": ("GroupGLMResultsJson", "group_level_glm"),
            "contrast_matrix.csv": ("ContrastMatrixTable", "group_contrast"),
            "contrast_results.csv": ("ContrastResultsTable", "group_contrast"),
            "contrast_results.json": ("ContrastResultsJson", "group_contrast"),
            "effect_sizes.csv": ("ContrastEffectSizesTable", "group_contrast"),
            "effect_sizes.json": ("ContrastEffectSizesJson", "group_contrast"),
            "multiple_comparison_results.csv": ("MultipleComparisonResultsTable", "group_contrast"),
            "multiple_comparison_results.json": ("MultipleComparisonResultsJson", "group_contrast"),
            "group_contrasts.json": ("GroupContrastSpec", "group_contrast"),
            "contrast_effects.svg": ("ContrastEffectFigure", "group_contrast"),
        }
        artifacts: list[dict[str, Any]] = []
        for filename, (artifact_type, atom_id) in artifact_specs.items():
            path = group_dir / filename
            if not path.exists():
                continue
            artifacts.append(
                self._path_artifact_summary(
                    path,
                    outdir,
                    artifact_type=artifact_type,
                    artifact_id=f"group-{path.stem}-{path.suffix.lstrip('.')}",
                    atom_id=atom_id,
                    step_id=atom_id,
                )
            )
        return artifacts

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
        atoms_list = dag.get("atoms", dag.get("nodes", []))
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
        layers = fixed_layers

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
                atom = atom_map.get(atom_id)
                if not atom:
                    continue

                operation = atom.get("operation") or atom.get("atom_type") or atom.get("node_type", "")
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
                        "backend_id": resolve_atom_backend_id(atom, default_backend_id),
                    },
                )
                self._emit_progress(
                    "atom_started",
                    run_id=run_ctx.run_id,
                    atom_id=atom_id,
                )

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
                        if category == "preprocessing":
                            result = self._dispatch_preprocessing(
                                adapter,
                                raw_input,
                                operation,
                                params,
                            )
                            # QC emits metrics rather than a transformed data object.
                            raw_outputs[atom_id] = raw_input if operation == "compute_qc" else result
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

    def _inject_edge_dependencies(
        self,
        atom_id: str,
        atom: dict[str, Any],
        params: dict[str, Any],
        state: dict[str, Any],
        predecessors: set[str],
        atom_map: dict[str, dict[str, Any]],
    ) -> None:
        """Inject typed inputs from the target atom's actual DAG predecessors.

        The legacy injector uses operation-wide state keys and cannot distinguish
        parallel branches. This method resolves each single-input analysis
        parameter from an incoming edge whose source operation produces that
        value. Ambiguous fan-in fails closed instead of depending on iteration
        order.
        """
        operation = atom.get("operation") or atom.get("atom_type") or ""
        requirements: dict[str, tuple[str, ...]] = {
            "first_level_glm": ("design_matrix", "build_design_matrix"),
            "estimate_contrast": ("glm_result", "first_level_glm"),
            "channel_output": ("contrast_result", "estimate_contrast"),
            "roi_output": ("channel_results", "channel_output"),
        }
        requirement = requirements.get(operation)
        if requirement is None:
            return

        param_key, source_operation = requirement
        if param_key in params:
            return

        candidates: list[str] = []
        for predecessor in sorted(predecessors):
            source = atom_map.get(predecessor, {})
            actual_operation = source.get("operation") or source.get("atom_type") or source.get("node_type", "")
            if actual_operation == source_operation and predecessor in state:
                candidates.append(predecessor)

        if len(candidates) > 1:
            raise ValueError(f"Atom '{atom_id}' has ambiguous '{param_key}' inputs from: {candidates}")
        if candidates:
            params[param_key] = state[candidates[0]]

    def _dispatch_preprocessing(
        self,
        adapter: Any,
        raw: Any,
        operation: str,
        params: dict[str, Any],
    ) -> Any:
        """Dispatch a preprocessing operation to the adapter."""
        optical_density_kwargs = {}
        haemoglobin_kwargs = {"ppf": params.get("ppf", 6.0)}
        if "cedalion" in getattr(adapter, "versions", {}):
            optical_density_kwargs["nonpositive_policy"] = params.get(
                "nonpositive_policy",
                "nan",
            )
            haemoglobin_kwargs["spectrum"] = params.get("spectrum", "prahl")

        dispatch = {
            "optical_density": lambda: adapter.to_optical_density(
                raw,
                **optical_density_kwargs,
            ),
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
                **haemoglobin_kwargs,
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

        §16 MVP: run artifacts record actual dependencies and backend versions
        §11: environment_manifest.json, backend_probe.json
        """
        import platform
        import sys

        logdir.mkdir(parents=True, exist_ok=True)

        # Collect backend information from DAG
        atoms_list = dag.get("atoms", dag.get("nodes", []))
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

    def _generate_group_summary(
        self,
        run_results: list[RunExecutionResult],
        outdir: Path,
        group_config: dict[str, Any] | None = None,
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
        excluded_subjects: set[str] = set()
        participant_table = load_participant_table_from_artifacts(
            outdir / "compiled"
        ) or load_participant_table_from_artifacts(outdir)
        included_subjects: set[str] | None = None
        metadata_by_subject: dict[str, dict[str, Any]] = {}
        if participant_table is not None:
            write_participant_table_artifacts(participant_table, outdir / "derivatives" / "group")
            join = join_participant_metadata(
                [{"subject": self._subject_from_run_id(rr.run_id)} for rr in run_results],
                participant_table,
            )
            excluded_subjects.update(join["excluded_subjects"])
            included_subjects = set(join["matched_subjects"]) - set(join["excluded_subjects"])
            metadata_by_subject = {
                str(row.get(participant_table.column_role_map.id_column, "")): row for row in participant_table.rows
            }

        for rr in run_results:
            subject = self._subject_from_run_id(rr.run_id)
            if included_subjects is not None and subject not in included_subjects:
                excluded_subjects.add(subject)
                continue
            if rr.status == "failed":
                excluded_subjects.add(subject)
                continue
            if rr.status == "skipped":
                excluded_subjects.add(subject)
                continue
            if not rr.roi_results:
                continue

            for roi_dict in rr.roi_results:
                roi_name = roi_dict.get("roi_name", roi_dict.get("roi", ""))
                for key, value in roi_dict.items():
                    if key.endswith("_beta_mean") or key.endswith("_beta"):
                        contrast = key.replace("_beta_mean", "").replace("_beta", "")
                        all_roi_results.append(
                            ROIResult(
                                subject=subject,
                                source_atom_id=str(roi_dict.get("source_atom_id", "")),
                                roi=roi_name,
                                contrast=contrast,
                                beta=float(value) if value is not None else 0.0,
                                n_channels=roi_dict.get("n_channels", 0),
                            )
                        )

        channel_path = self._generate_channel_group_summary(run_results, outdir)
        if not all_roi_results:
            return channel_path

        # Compute group statistics
        summaries = compute_group_statistics(all_roi_results, exclude_subjects=sorted(excluded_subjects))

        # Patch excluded_subjects into summaries (subjects that never produced ROI results
        # won't appear in compute_group_statistics's intersection logic)
        for s in summaries:
            existing = set(s.excluded_subjects)
            for subj in sorted(excluded_subjects):
                if subj not in existing:
                    s.excluded_subjects.append(subj)

        # Write to derivatives/group/
        group_dir = outdir / "derivatives" / "group"
        group_dir.mkdir(parents=True, exist_ok=True)

        # Export group summary CSV
        csv_path = export_group_summary(summaries, group_dir)

        # Export group summary JSON
        group_json = {
            "n_subjects_included": len({r.subject for r in all_roi_results}),
            "n_subjects_excluded": len(excluded_subjects),
            "excluded_subjects": sorted(excluded_subjects),
            "n_rois": len(summaries),
            "summaries": [
                {
                    "roi": s.roi,
                    "source_atom_id": s.source_atom_id,
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
        if participant_table is not None:
            analysis_rows = []
            for result_row in all_roi_results:
                metadata = metadata_by_subject.get(result_row.subject, {})
                analysis_rows.append(
                    {
                        "participant_id": result_row.subject,
                        "source_atom_id": result_row.source_atom_id,
                        "roi": result_row.roi,
                        "source_contrast": result_row.contrast,
                        "beta": result_row.beta,
                        **metadata,
                    }
                )
            self._write_group_design_outputs(
                analysis_rows,
                participant_table.column_role_map.group_column,
                group_dir,
                group_config=group_config or {},
            )

        return csv_path

    @staticmethod
    def _subject_from_run_id(run_id: str) -> str:
        subject = run_id.split("_")[0] if "_" in run_id else run_id
        return subject if subject.startswith("sub-") else f"sub-{subject}"

    def _write_group_design_outputs(
        self,
        analysis_rows: list[dict[str, Any]],
        group_column: str,
        group_dir: Path,
        *,
        group_config: dict[str, Any] | None = None,
    ) -> None:
        group_config = group_config or {}
        if not analysis_rows:
            return
        analysis_path = group_dir / "analysis_table.csv"
        fieldnames = list(dict.fromkeys(key for row in analysis_rows for key in row))
        with analysis_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(analysis_rows)
        if not any(row.get(group_column, "") for row in analysis_rows):
            return
        design_type = str(group_config.get("design_type", "two_sample_t"))
        covariates = [str(value) for value in group_config.get("covariates", [])]
        factors = [str(value) for value in group_config.get("factors", [])]
        within_subject_factors = [str(value) for value in group_config.get("within_subject_factors", [])]
        random_effects = [str(value) for value in group_config.get("random_effects", [])]
        condition_column = str(group_config.get("condition_column", "condition"))
        pair_id_column = str(group_config.get("pair_id_column", "participant_id"))
        covariance = str(group_config.get("covariance", "ols"))
        cluster_column = str(group_config.get("cluster_column", "participant_id"))
        permutation_count = int(group_config.get("permutation_count", 0) or 0)
        random_seed = int(group_config.get("random_seed", 0) or 0)
        sensitivity_branches = group_config.get("sensitivity_branches", [])
        cluster_inference = bool(group_config.get("cluster_inference", False))
        cluster_alpha = float(group_config.get("cluster_alpha", 0.05) or 0.05)
        cluster_adjacency_column = str(group_config.get("cluster_adjacency_column", "channel"))
        try:
            design = build_group_design_matrix(
                analysis_rows,
                design_type=design_type,
                group_column=group_column,
                covariates=covariates,
                factors=factors,
                within_subject_factors=within_subject_factors,
                random_effects=random_effects,
                condition_column=condition_column,
                pair_id_column=pair_id_column,
            )
        except ValueError as exc:
            (group_dir / "group_design_validation.json").write_text(
                json.dumps({"status": "blocked", "error": str(exc)}, indent=2),
                encoding="utf-8",
            )
            return
        with (group_dir / "group_design_matrix.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=design.column_names)
            writer.writeheader()
            writer.writerows(design.design_matrix)
        (group_dir / "group_design_spec.json").write_text(
            json.dumps(
                {
                    "design_type": design_type,
                    "configured_design_type": design_type,
                    "group_column": group_column,
                    "covariates": covariates,
                    "factors": factors,
                    "within_subject_factors": within_subject_factors,
                    "random_effects": random_effects,
                    "condition_column": condition_column,
                    "pair_id_column": pair_id_column,
                    "covariance": covariance,
                    "cluster_column": cluster_column,
                    "permutation_count": permutation_count,
                    "cluster_inference": cluster_inference,
                    "cluster_alpha": cluster_alpha,
                    "cluster_adjacency_column": cluster_adjacency_column,
                    "sensitivity_branches": sensitivity_branches if isinstance(sensitivity_branches, list) else [],
                    "columns": design.column_names,
                    "rank": design.rank,
                    "condition_number": design.condition_number,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        contrast_specs = None
        try:
            if isinstance(group_config.get("contrasts"), list):
                from fnirs_flow.data.participants import compile_group_contrasts

                contrast_specs = compile_group_contrasts(group_config["contrasts"], design.column_names)
            effective_contrasts = contrast_specs or default_group_contrasts(design)
            glm = fit_group_glm(
                design,
                contrasts=effective_contrasts,
                covariance=covariance,
                cluster_column=cluster_column,
                permutation_count=permutation_count,
                random_seed=random_seed,
                sensitivity_branches=sensitivity_branches if isinstance(sensitivity_branches, list) else [],
            )
        except ValueError as exc:
            (group_dir / "group_glm_validation.json").write_text(
                json.dumps({"status": "blocked", "error": str(exc)}, indent=2),
                encoding="utf-8",
            )
            return
        self._write_rows(group_dir / "group_glm_results.csv", glm.coefficients)
        self._write_json_rows(group_dir / "group_glm_results.json", glm.coefficients)
        self._write_rows(group_dir / "contrast_matrix.csv", glm.contrasts)
        self._write_rows(group_dir / "contrast_results.csv", glm.contrasts)
        self._write_json_rows(group_dir / "contrast_results.json", glm.contrasts)
        self._write_rows(group_dir / "effect_sizes.csv", glm.effect_sizes)
        self._write_json_rows(group_dir / "effect_sizes.json", glm.effect_sizes)
        self._write_rows(group_dir / "multiple_comparison_results.csv", glm.corrected)
        self._write_json_rows(group_dir / "multiple_comparison_results.json", glm.corrected)
        self._write_rows(group_dir / "sensitivity_analysis_results.csv", glm.sensitivity or [])
        self._write_json_rows(group_dir / "sensitivity_analysis_results.json", glm.sensitivity or [])
        self._write_contrast_effects_svg(group_dir / "contrast_effects.svg", glm.corrected or glm.contrasts)
        if cluster_inference:
            from fnirs_flow.data.participants import summarize_cluster_inference

            self._write_rows(
                group_dir / "cluster_inference_results.csv",
                summarize_cluster_inference(
                    glm.contrasts,
                    alpha=cluster_alpha,
                    adjacency_column=cluster_adjacency_column,
                ),
            )
        (group_dir / "group_contrasts.json").write_text(
            json.dumps(
                [
                    {
                        "name": spec.name,
                        "type": spec.contrast_type,
                        "expression": spec.expression,
                        "weights": spec.weights,
                        "weight_matrix": spec.weight_matrix,
                        "design_column_names": design.column_names,
                    }
                    for spec in effective_contrasts
                ],
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _write_json_rows(path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        path.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")

    @staticmethod
    def _write_contrast_effects_svg(path: Path, rows: list[dict[str, Any]], *, limit: int = 20) -> None:
        if not rows:
            return
        candidates: list[dict[str, Any]] = []
        for row in rows:
            raw_value = row.get("estimate")
            if raw_value in ("", None):
                raw_value = row.get("t_value", row.get("f_value", 0.0))
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            label_parts = [
                str(row.get("roi") or row.get("channel") or row.get("source_atom_id") or "feature"),
                str(row.get("source_contrast") or row.get("contrast_name") or "contrast"),
            ]
            candidates.append({**row, "_value": value, "_label": " · ".join(part for part in label_parts if part)})
        if not candidates:
            return
        selected = sorted(candidates, key=lambda item: abs(float(item["_value"])), reverse=True)[:limit]
        max_abs = max(abs(float(item["_value"])) for item in selected) or 1.0
        width = 860
        row_height = 28
        top = 48
        left = 250
        plot_width = 520
        height = top + row_height * len(selected) + 34
        zero_x = left + plot_width / 2

        def esc(value: Any) -> str:
            return (
                str(value)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        parts = [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
                f'height="{height}" viewBox="0 0 {width} {height}">'
            ),
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            (
                '<text x="24" y="28" font-family="Arial, sans-serif" '
                'font-size="18" font-weight="700" fill="#0f172a">'
                "Top group contrast effects</text>"
            ),
            (
                f'<line x1="{zero_x:.1f}" y1="{top - 14}" '
                f'x2="{zero_x:.1f}" y2="{height - 24}" '
                'stroke="#94a3b8" stroke-width="1"/>'
            ),
        ]
        for index, row in enumerate(selected):
            value = float(row["_value"])
            y = top + index * row_height
            bar_width = abs(value) / max_abs * (plot_width / 2)
            x = zero_x if value >= 0 else zero_x - bar_width
            color = "#2563eb" if value >= 0 else "#b45309"
            label = esc(row["_label"])
            value_label = esc(f"{value:.3g}")
            p_value = row.get("adjusted_p_value", row.get("p_value", ""))
            p_label = esc(f"p={float(p_value):.3g}" if isinstance(p_value, int | float) else str(p_value))
            parts.extend(
                [
                    (
                        f'<text x="24" y="{y + 17}" '
                        'font-family="Arial, sans-serif" font-size="12" '
                        f'fill="#334155">{label}</text>'
                    ),
                    f'<rect x="{x:.1f}" y="{y + 5}" width="{bar_width:.1f}" height="14" rx="3" fill="{color}"/>',
                    (
                        f'<text x="{left + plot_width + 14}" y="{y + 17}" '
                        'font-family="Arial, sans-serif" font-size="12" '
                        f'fill="#334155">{value_label} {p_label}</text>'
                    ),
                ]
            )
        parts.append("</svg>")
        path.write_text("\n".join(parts), encoding="utf-8")

    def _generate_channel_group_summary(
        self,
        run_results: list[RunExecutionResult],
        outdir: Path,
    ) -> Path | None:
        """Export subject-level channel values and aggregate channel statistics."""
        rows: list[dict[str, Any]] = []
        participant_table = load_participant_table_from_artifacts(
            outdir / "compiled"
        ) or load_participant_table_from_artifacts(outdir)
        role_map = participant_table.column_role_map if participant_table is not None else None
        included_subjects: set[str] | None = None
        if participant_table is not None:
            join = join_participant_metadata(
                [{"subject": self._subject_from_run_id(rr.run_id)} for rr in run_results],
                participant_table,
            )
            included_subjects = set(join["matched_subjects"]) - set(join["excluded_subjects"])
        excluded = sorted(
            {self._subject_from_run_id(rr.run_id) for rr in run_results if rr.status in ("failed", "skipped")}
        )
        for rr in run_results:
            if rr.status != "completed":
                continue
            subject = self._subject_from_run_id(rr.run_id)
            if included_subjects is not None and subject not in included_subjects:
                continue
            for channel in rr.channel_results:
                channel_name = str(channel.get("channel", channel.get("channel_name", channel.get("channel_idx", ""))))
                for key, value in channel.items():
                    if not (key.endswith("_beta_mean") or key.endswith("_beta")):
                        continue
                    rows.append(
                        {
                            "subject": subject,
                            "channel": channel_name,
                            "source_atom_id": str(channel.get("source_atom_id", "")),
                            "contrast": key.replace("_beta_mean", "").replace("_beta", ""),
                            "beta": float(value) if value is not None else 0.0,
                        }
                    )
        if not rows:
            return None

        per_subject: dict[tuple[str, str, str, str], list[float]] = {}
        for row in rows:
            subject_key = (str(row["source_atom_id"]), str(row["channel"]), str(row["contrast"]), str(row["subject"]))
            per_subject.setdefault(subject_key, []).append(float(row["beta"]))
        grouped: dict[tuple[str, str, str], list[float]] = {}
        for subject_key_tuple, beta_values in per_subject.items():
            source_atom_id_str, channel_str, contrast_str, _subject_str = subject_key_tuple
            group_key = (source_atom_id_str, channel_str, contrast_str)
            grouped.setdefault(group_key, []).append(float(np.mean(beta_values)))
        summaries = [
            {
                "source_atom_id": source_atom_id,
                "channel": channel,
                "contrast": contrast,
                "n_subjects": len(values),
                "mean_beta": float(np.mean(values)),
                "std_beta": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                "id_column": role_map.id_column if role_map is not None else "",
                "include_column": role_map.include_column if role_map is not None else "",
                "group_column": role_map.group_column if role_map is not None else "",
            }
            for (source_atom_id, channel, contrast), values in sorted(grouped.items())
        ]

        group_dir = outdir / "derivatives" / "group"
        group_dir.mkdir(parents=True, exist_ok=True)
        csv_path = group_dir / "channel_group_summary.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "source_atom_id",
                    "channel",
                    "contrast",
                    "n_subjects",
                    "mean_beta",
                    "std_beta",
                    "id_column",
                    "include_column",
                    "group_column",
                ],
            )
            writer.writeheader()
            writer.writerows(summaries)
        (group_dir / "channel_group_summary.json").write_text(
            json.dumps(
                {
                    "n_subjects_included": len({row["subject"] for row in rows}),
                    "n_subjects_excluded": len(excluded),
                    "excluded_subjects": excluded,
                    "summaries": summaries,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return csv_path
