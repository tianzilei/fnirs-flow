"""Group-scope atom execution and statistical output ownership."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from fnirs_flow.data.group_analysis import build_group_design_matrix, default_group_contrasts, fit_group_glm
from fnirs_flow.data.participant_tables import (
    ParticipantTable,
    join_participant_metadata,
    load_participant_table_from_artifacts,
    write_participant_table_artifacts,
)
from fnirs_flow.execution.dag_payload import execution_atoms
from fnirs_flow.execution.models import AtomExecutionResult, RunExecutionResult


class GroupExecutionHost(Protocol):
    cancel_check: Any

    @staticmethod
    def _path_artifact_summary(
        path: Path,
        outdir: Path,
        *,
        artifact_type: str,
        artifact_id: str,
        atom_id: str = "",
        step_id: str = "",
    ) -> dict[str, Any]: ...


class GroupExecutor:
    """Own group-scope operations, design, GLM, contrasts and summaries."""

    def __init__(self, host: GroupExecutionHost) -> None:
        self.host = host

    def _execute_group_scope_atoms(self, dag: dict[str, Any], outdir: Path) -> list[AtomExecutionResult]:
        atoms = execution_atoms(dag)
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
                "fnirs_filename_inventory",
                "nirs_spm_header_inspection",
                "probe_layout_split",
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
            atom_id = atom.get("atom_id") or atom.get("operation", "group_atom")
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
                from fnirs_flow.data.participant_tables import (
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
                            self.host._path_artifact_summary(
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
                            self.host._path_artifact_summary(
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
                elif operation in {
                    "fnirs_filename_inventory",
                    "nirs_spm_header_inspection",
                    "probe_layout_split",
                }:
                    from fnirs_flow.adapters.private_fnirs_tools import (
                        inspect_nirs_spm_headers,
                        inventory_fnirs_filenames,
                        split_probe_layout_csv,
                    )

                    path = params.get("path") or params.get("source_path")
                    if not path:
                        raise ValueError(f"PRIVATE_FNIRS_TOOL_SOURCE_MISSING: {operation} requires path")
                    private_tools = {
                        "fnirs_filename_inventory": (
                            inventory_fnirs_filenames,
                            "FnirsFilenameInventory",
                            "filename_inventory",
                        ),
                        "nirs_spm_header_inspection": (
                            inspect_nirs_spm_headers,
                            "NirsspmHeaderInspection",
                            "header_inspection",
                        ),
                        "probe_layout_split": (
                            split_probe_layout_csv,
                            "ProbeLayoutSplit",
                            "probe_layout",
                        ),
                    }
                    tool: Any
                    tool, artifact_type, state_key = private_tools[operation]
                    private_params = {
                        key: value
                        for key, value in params.items()
                        if key not in {"path", "source_path", "execution_scope", "readiness_status"}
                        and not key.startswith("_")
                    }
                    tool_result = tool(
                        path,
                        outdir / "derivatives" / "data_quality",
                        base_dir=outdir,
                        atom_id=atom_id,
                        **private_params,
                    )
                    state[state_key] = tool_result["output"]
                    result.output_handles = tool_result["output"]
                    result.artifacts.extend(
                        [
                            self.host._path_artifact_summary(
                                artifact_path,
                                outdir,
                                artifact_type=artifact_type,
                                artifact_id=f"{atom_id}-{artifact_path.stem}",
                                atom_id=atom_id,
                                step_id=atom_id,
                            )
                            for artifact_path in tool_result["artifact_paths"]
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
                    from fnirs_flow.data.participant_tables import ObservationTable

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
        from fnirs_flow.execution.result_outputs import (
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
                from fnirs_flow.data.group_analysis import compile_group_contrasts

                contrast_specs = compile_group_contrasts(group_config["contrasts"], design.column_names)
            effective_contrasts = contrast_specs or default_group_contrasts(design)
            glm = fit_group_glm(
                design,
                contrasts=effective_contrasts,
                covariance=covariance,
                cluster_column=cluster_column,
                permutation_count=permutation_count,
                random_seed=random_seed,
                permutation_chunk_size=int(group_config.get("permutation_chunk_size", 256) or 256),
                cancel_check=self.host.cancel_check,
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
            from fnirs_flow.data.group_analysis import summarize_cluster_inference

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
            raw_value: Any = row.get("estimate")
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

    def execute_atoms(self, dag: dict[str, Any], outdir: Path) -> list[AtomExecutionResult]:
        # Keep the historical host hook available for minimal third-party test
        # doubles and integrations that pass a non-canonical placeholder DAG.
        # Canonical execution always follows the implementation below.
        if "atoms" not in dag and "flow_atoms" not in dag and hasattr(self.host, "_execute_group_scope_atoms"):
            return self.host._execute_group_scope_atoms(dag, outdir)  # type: ignore[no-any-return, attr-defined]
        return self._execute_group_scope_atoms(dag, outdir)

    def generate_summary(
        self,
        run_results: list[RunExecutionResult],
        outdir: Path,
        *,
        group_config: dict[str, Any] | None = None,
    ) -> Path | None:
        if not hasattr(self.host, "group_executor") and hasattr(self.host, "_generate_group_summary"):
            return self.host._generate_group_summary(  # type: ignore[no-any-return, attr-defined]
                run_results, outdir, group_config=group_config
            )
        return self._generate_group_summary(run_results, outdir, group_config=group_config)


def extract_group_config(plan: dict[str, Any], dag: dict[str, Any]) -> dict[str, Any]:
    """Merge group model settings with explicit group-scope atom parameters."""
    config: dict[str, Any] = {}
    for atom in execution_atoms(dag):
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
                contrast_params["contrasts"] = [{
                    "name": contrast_params.get("contrast_name") or contrast_params.get("name") or "Group contrast",
                    "type": contrast_params.get("contrast_type") or contrast_params.get("type") or "T",
                    "expression": contrast_params.get("contrast_expression", ""),
                    "weights": contrast_params.get("weights"),
                    "weight_matrix": contrast_params.get("weight_matrix"),
                    "terms": contrast_params.get("terms"),
                }]
            config.update({key: value for key, value in contrast_params.items() if value not in (None, "")})
        else:
            config.update(params)
    group_model = plan.get("group_model", {})
    return {**group_model, **config} if isinstance(group_model, dict) else config
