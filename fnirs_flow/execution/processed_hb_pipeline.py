"""End-to-end project executor for the manifest-driven processed-Hb branch."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

import fnirs_flow
from fnirs_flow.adapters.processed_hb_mne_bridge import regularize_processed_hb_time
from fnirs_flow.adapters.vendor_processed_hb import PARSER_VERSION, parse_vendor_processed_hb
from fnirs_flow.analysis.contrasts import estimate_contrast
from fnirs_flow.analysis.design_models import (
    DESIGN_IMPLEMENTATION_VERSION,
    bind_design_contrasts,
    compile_condition_glm,
    compile_event_order_glm,
    compile_post_event_fir,
)
from fnirs_flow.analysis.first_level_solvers import SolverConfig, fit_first_level
from fnirs_flow.data.frozen_events import ingest_frozen_events
from fnirs_flow.data.processed_hb_models import DataManifest
from fnirs_flow.execution.processed_hb_outputs import (
    object_dict,
    write_design_matrix,
    write_native_timestamps,
    write_processed_hb_derivatives,
)

PROCESSED_HB_MODEL_IDS = {
    "glm_conditions_canonical_td_v1",
    "fir_post_event_0_30_10s_v1",
    "glm_event_order_linear_canonical_td_v1",
}


def _load_manifest(compiled_dir: str | Path) -> DataManifest:
    path = Path(compiled_dir) / "data_manifest.json"
    return DataManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _resolve(value: str, data_root: str | Path | None) -> Path:
    path = Path(value)
    if path.is_file():
        return path
    if data_root:
        relative = value.split("external-data://", 1)[-1]
        if "/" in relative and value.startswith("external-data://"):
            relative = relative.split("/", 1)[1]
        candidate = Path(data_root) / relative
        if candidate.exists():
            return candidate
    raise FileNotFoundError(value)


def _resolve_manifest_artifact(value: str, compiled_dir: Path, data_root: str | Path | None) -> Path:
    path = Path(value)
    if path.exists():
        return path
    for root in (compiled_dir, compiled_dir.parent, Path(data_root) if data_root else None):
        if root is None:
            continue
        candidate = root / value
        if candidate.exists():
            return candidate
        basename_candidate = root / Path(value).name
        if basename_candidate.exists():
            return basename_candidate
    return _resolve(value, data_root)


def _load_preset(compiled_dir: Path) -> dict[str, Any]:
    from importlib.resources import files

    candidates = [
        compiled_dir / "processed_hb_preset.json",
        compiled_dir.parent / "configs" / "presets" / "vendor_processed_hb_v1.json",
        Path(__file__).resolve().parents[2] / "configs" / "presets" / "vendor_processed_hb_v1.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    resource = files("fnirs_flow.resources.presets").joinpath("vendor_processed_hb_v1.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _unfrozen_preset_values(preset: dict[str, Any]) -> list[str]:
    required = {
        "time_regularization": preset.get("time_regularization", {}),
        "design_gates": preset.get("design_gates", {}),
        "solver_config": preset.get("solver_config", {}),
        "covariance_config": preset.get("covariance_config", {}),
        "qc_gates": preset.get("qc_gates", {}),
    }
    missing = []
    for section, values in required.items():
        if not isinstance(values, dict) or not values:
            missing.append(section)
            continue
        missing.extend(f"{section}.{key}" for key, value in values.items() if value is None or value == "TBD")
    if preset.get("scientific_parameters_frozen") is not True:
        missing.append("scientific_parameters_frozen")
    return missing


def _contrast_definitions(path: Path, bundles: list[Any]) -> dict[str, list[dict[str, Any]]]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        grouped: dict[tuple[str, str, str], dict[str, float]] = defaultdict(dict)
        component_order: dict[tuple[str, str], list[str]] = defaultdict(list)
        for row in rows:
            model_id, contrast_id = row.get("model_id", "").strip(), row.get("contrast_id", "").strip()
            regressor = row.get("regressor", row.get("regressor_name", "")).strip()
            component = (row.get("component_id") or row.get("component_name") or "component_1").strip()
            if not model_id or not contrast_id or not regressor:
                raise ValueError("contrast_matrix.csv requires model_id, contrast_id, regressor, and weight")
            key = (model_id, contrast_id, component)
            if regressor in grouped[key]:
                raise ValueError(f"duplicate contrast weight: {model_id}/{contrast_id}/{component}/{regressor}")
            grouped[key][regressor] = float(row.get("weight", ""))
            contrast_key = (model_id, contrast_id)
            if component not in component_order[contrast_key]:
                component_order[contrast_key].append(component)
        known_models = {bundle.model_id for bundle in bundles}
        unknown_models = sorted({model_id for model_id, _, _ in grouped} - PROCESSED_HB_MODEL_IDS)
        if unknown_models:
            raise ValueError(f"contrast table references unknown models: {unknown_models}")
        for bundle in bundles:
            contrast_ids = sorted({contrast_id for model_id, contrast_id, _ in grouped if model_id == bundle.model_id})
            for contrast_id in contrast_ids:
                model_id = bundle.model_id
                component_names = component_order[(model_id, contrast_id)]
                component_weights = []
                for component in component_names:
                    weights_by_name = grouped[(model_id, contrast_id, component)]
                    unknown = sorted(set(weights_by_name) - set(bundle.regressor_names))
                    if unknown:
                        raise ValueError(f"contrast {contrast_id} references unknown regressors: {unknown}")
                    weights = [weights_by_name.get(name, 0.0) for name in bundle.regressor_names]
                    if not any(weights):
                        raise ValueError(f"contrast {contrast_id}/{component} is all zero")
                    component_weights.append(weights)
                c = np.asarray(component_weights, dtype=float)
                if np.linalg.matrix_rank(c) != len(component_names):
                    raise ValueError(f"contrast {contrast_id} has linearly dependent components")
                projection = c @ np.linalg.pinv(bundle.matrix) @ bundle.matrix
                if not np.allclose(c, projection, rtol=1e-8, atol=1e-10):
                    raise ValueError(f"contrast {contrast_id} is not estimable")
                by_model[model_id].append(
                    {
                        "contrast_id": contrast_id,
                        "component_names": component_names,
                        "weights": c if len(component_names) > 1 else c[0],
                    }
                )
        if rows:
            missing_models = sorted(known_models - set(by_model))
            if missing_models:
                raise ValueError(f"contrast table is missing model definitions: {missing_models}")
    for bundle in bundles:
        if by_model[bundle.model_id]:
            continue
        if bundle.model_id == "fir_post_event_0_30_10s_v1":
            weights = [1 / 3 if name.startswith("offset__") else 0.0 for name in bundle.regressor_names]
            by_model[bundle.model_id].append(
                {"contrast_id": "offset__0_30s", "component_names": ["offset__0_30s"], "weights": weights}
            )
        else:
            for index, name in enumerate(bundle.regressor_names):
                if name.endswith("__canonical"):
                    weights = [0.0] * len(bundle.regressor_names)
                    weights[index] = 1.0
                    by_model[bundle.model_id].append(
                        {
                            "contrast_id": name.removesuffix("__canonical"),
                            "component_names": [name.removesuffix("__canonical")],
                            "weights": weights,
                        }
                    )
        by_model[bundle.model_id].sort(key=lambda definition: definition["contrast_id"])
    return by_model


def dry_run_processed_hb(
    compiled_dir: str | Path,
    *,
    data_root: str | Path | None = None,
    fnirs_record_ids: list[str] | None = None,
    record_pair_ids: list[str] | None = None,
) -> dict[str, Any]:
    manifest = _load_manifest(compiled_dir)
    selected = [
        run
        for run in manifest.runs
        if (not fnirs_record_ids or run.fnirs_record_id in fnirs_record_ids)
        and (not record_pair_ids or run.record_pair_id in record_pair_ids)
    ]
    records = []
    for run in selected:
        try:
            _resolve(run.signal_uri, data_root)
            discovery_status, reason = "available", ""
        except FileNotFoundError:
            discovery_status, reason = "missing", "SIGNAL_FILE_MISSING"
        eligible = run.analysis_included and run.event_primary_eligible and discovery_status == "available"
        records.append(
            {
                "fnirs_record_id": run.fnirs_record_id,
                "record_pair_id": run.record_pair_id,
                "discovery_status": discovery_status,
                "reason_code": reason or ("FROZEN_EXCLUDED" if not run.analysis_included else ""),
                "eligible": eligible,
                "expected_models": 3,
                "declared_channel_count": run.declared_channel_count,
                "expected_series_fits": (run.declared_channel_count * 2 * 3 if run.declared_channel_count else None),
            }
        )
    eligible_count = sum(bool(record["eligible"]) for record in records)
    return {
        "data_branch": "vendor_processed_hb",
        "records": records,
        "counts": {
            "total": len(records),
            "eligible": eligible_count,
            "missing": sum(r["discovery_status"] == "missing" for r in records),
        },
        "estimands": {
            model: {"eligible_record_pairs": eligible_count}
            for model in (
                "glm_conditions_canonical_td_v1",
                "fir_post_event_0_30_10s_v1",
                "glm_event_order_linear_canonical_td_v1",
            )
        },
    }


def _lag1(values: np.ndarray) -> float | None:
    if len(values) < 3 or np.std(values[:-1]) == 0 or np.std(values[1:]) == 0:
        return None
    return float(np.corrcoef(values[:-1], values[1:])[0, 1])


def _task_mark_observation(recording: Any, onset_s: float) -> str:
    if recording.task_values is None and recording.mark_values is None:
        return "unavailable"
    index = int(np.argmin(np.abs(recording.native_timestamps_s - onset_s)))
    observed = []
    for name, values in (("task", recording.task_values), ("mark", recording.mark_values)):
        if values is None:
            continue
        value = str(values[index]).strip()
        observed.append(f"{name}={value or '<blank>'}")
    return ";".join(observed)


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _failure_stage(reason: str, *, parser_completed: bool) -> str:
    if not parser_completed:
        return "parser"
    if reason.startswith(("TIME_", "SAMPLING_", "DUPLICATE_TIMESTAMP", "INTERPOLATION_")):
        return "timestamp"
    if reason.startswith(("HBT_", "ALL_ZERO", "NONFINITE_", "HBO_HBR_")):
        return "signal"
    if reason.startswith(("EVENT_", "DUPLICATE_WINDOW", "INSUFFICIENT_EVENTS")):
        return "event"
    if reason.startswith(("DESIGN_", "CONDITION_", "INSUFFICIENT_RESIDUAL")):
        return "design"
    if reason.startswith("COVARIANCE_"):
        return "covariance"
    if reason.startswith("CONTRAST_"):
        return "contrast"
    return "solver"


def run_processed_hb(
    compiled_dir: str | Path,
    outdir: str | Path,
    *,
    data_root: str | Path | None = None,
    fnirs_record_ids: list[str] | None = None,
    record_pair_ids: list[str] | None = None,
) -> dict[str, Any]:
    compiled = Path(compiled_dir)
    manifest = _load_manifest(compiled)
    preset = _load_preset(compiled)
    missing_preset_values = _unfrozen_preset_values(preset)
    if missing_preset_values:
        raise ValueError("UNFROZEN_CONFIRMATORY_THRESHOLDS:" + ",".join(sorted(missing_preset_values)))
    derivatives = Path(outdir) / "derivatives" / "processed_hb_first_level"
    started = datetime.now(timezone.utc)
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    solver = preset["solver"]
    events_path = _resolve_manifest_artifact(manifest.events_uri, compiled, data_root)
    contrast_path = (
        _resolve_manifest_artifact(manifest.contrast_matrix_uri, compiled, data_root)
        if manifest.contrast_matrix_uri
        else Path()
    )
    successful_pairs: set[str] = set()
    eligible_pairs: set[str] = set()
    requested_estimands: set[tuple[str, str, str]] = set()

    for run in manifest.runs:
        if fnirs_record_ids and run.fnirs_record_id not in fnirs_record_ids:
            continue
        if record_pair_ids and run.record_pair_id not in record_pair_ids:
            continue
        base = {
            "analysis_version": preset["analysis_version"],
            "linked_record_id": run.linked_record_id,
            "fnirs_record_id": run.fnirs_record_id,
            "record_pair_id": run.record_pair_id,
        }
        try:
            signal_path = _resolve(run.signal_uri, data_root)
        except FileNotFoundError:
            rows["runs"].append(
                {
                    **base,
                    "fnirs_signal_uri": run.signal_uri,
                    "analysis_included": run.analysis_included,
                    "discovery_status": "missing",
                    "discovery_reason_code": "SIGNAL_FILE_MISSING",
                }
            )
            rows["exclusions"].append(
                {
                    **base,
                    "stage": "discovery",
                    "scope_type": "record",
                    "scope_id": run.fnirs_record_id,
                    "status": "fail",
                    "reason_code": "SIGNAL_FILE_MISSING",
                    "message": "Frozen signal binding was not found",
                }
            )
            continue
        rows["runs"].append(
            {
                **base,
                "fnirs_signal_uri": run.signal_uri,
                "input_sha256": run.input_sha256,
                "sync_grade": run.sync_grade,
                "event_primary_eligible": run.event_primary_eligible,
                "lag_primary_eligible": run.lag_primary_eligible,
                "observed_coverage": run.observed_coverage,
                "analysis_included": run.analysis_included,
                "frozen_exclusion_reason": run.frozen_exclusion_reason,
                "discovery_status": "available",
                "discovery_reason_code": "",
            }
        )
        if not run.analysis_included or not run.event_primary_eligible:
            rows["exclusions"].append(
                {
                    **base,
                    "stage": "frozen_manifest",
                    "scope_type": "record",
                    "scope_id": run.fnirs_record_id,
                    "status": "excluded",
                    "reason_code": run.frozen_exclusion_reason or "EVENT_PRIMARY_INELIGIBLE",
                    "message": "Record is excluded by the frozen analysis population",
                }
            )
            continue
        eligible_pairs.add(run.record_pair_id)
        parser_added = False
        try:
            recording, parser_qc = parse_vendor_processed_hb(signal_path, uri=run.signal_uri)
            if run.input_sha256 and run.input_sha256 != recording.provenance.sha256:
                raise ValueError("INPUT_SHA256_MISMATCH")
            qc_gates = preset["qc_gates"]
            hbt_exceedance_fraction = None
            hbt_status = recording.provenance.hbt_check_status
            if recording.hbt_validation is not None:
                hbt_error = np.abs(recording.hbt_validation - (recording.hbo + recording.hbr))
                hbt_exceedance_fraction = float(np.mean(hbt_error > qc_gates["hbt_absolute_tolerance"]))
                hbt_status = (
                    "pass"
                    if hbt_exceedance_fraction <= qc_gates["hbt_exceedance_fraction_max"]
                    else "fail"
                )
            event_set = ingest_frozen_events(
                events_path,
                run.fnirs_record_id,
                coverage=(float(recording.native_timestamps_s[0]), float(recording.native_timestamps_s[-1])),
                coverage_tolerance_s=qc_gates["event_coverage_tolerance_s"],
            )
            time_config = preset["time_regularization"]
            regularized = regularize_processed_hb_time(
                recording,
                max_duplicate_fraction=time_config["max_duplicate_fraction"],
                max_jitter_abs_s=time_config["max_jitter_abs_s"],
                max_jitter_relative=time_config["max_jitter_relative"],
                interpolation_method=time_config["interpolation_method"],
                max_interpolation_deviation_s=time_config["max_interpolation_deviation_s"],
            )
            eligible_events = list(event_set.events)
            bundles = []
            compilers = (compile_condition_glm, compile_post_event_fir, compile_event_order_glm)
            for compiler in compilers:
                try:
                    bundles.append(compiler(regularized.timestamps_s, eligible_events))
                except Exception as exc:
                    model_id = {
                        "compile_condition_glm": "glm_conditions_canonical_td_v1",
                        "compile_post_event_fir": "fir_post_event_0_30_10s_v1",
                        "compile_event_order_glm": "glm_event_order_linear_canonical_td_v1",
                    }[compiler.__name__]
                    rows["exclusions"].append(
                        {
                            **base,
                            "model_id": model_id,
                            "stage": "event_design",
                            "scope_type": "model",
                            "scope_id": model_id,
                            "status": "fail",
                            "reason_code": "INSUFFICIENT_EVENTS",
                            "message": str(exc),
                            "observed_value": sum(event.event_eligible for event in eligible_events),
                            "threshold": "model_contract",
                            "policy_id": "processed_hb_design_v2",
                            "source_artifact": manifest.events_uri,
                        }
                    )
            design_gates = preset["design_gates"]
            gated_bundles = []
            for bundle in bundles:
                if bundle.condition_number > design_gates["condition_number_max"]:
                    reason, observed, threshold = (
                        "CONDITION_NUMBER_EXCEEDED",
                        bundle.condition_number,
                        design_gates["condition_number_max"],
                    )
                elif bundle.residual_df < design_gates["minimum_residual_df"]:
                    reason, observed, threshold = (
                        "INSUFFICIENT_RESIDUAL_DF",
                        bundle.residual_df,
                        design_gates["minimum_residual_df"],
                    )
                else:
                    gated_bundles.append(bundle)
                    continue
                rows["exclusions"].append(
                    {
                        **base,
                        "model_id": bundle.model_id,
                        "stage": "design",
                        "scope_type": "model",
                        "scope_id": bundle.model_id,
                        "status": "fail",
                        "reason_code": reason,
                        "message": "Frozen design threshold was not met",
                        "observed_value": observed,
                        "threshold": threshold,
                        "policy_id": "processed_hb_design_gates_v1",
                        "source_artifact": manifest.events_uri,
                    }
                )
            bundles = gated_bundles
            definitions = _contrast_definitions(contrast_path, bundles)
            requested_estimands.update(
                (bundle.model_id, definition["contrast_id"], chromophore)
                for bundle in bundles
                for definition in definitions[bundle.model_id]
                for chromophore in ("hbo", "hbr")
            )
            contrast_input_sha256 = (
                hashlib.sha256(contrast_path.read_bytes()).hexdigest() if contrast_path.is_file() else ""
            )
            bundles = [
                bind_design_contrasts(
                    bundle,
                    definitions[bundle.model_id],
                    contrast_input_sha256=contrast_input_sha256,
                )
                for bundle in bundles
            ]
            timestamp_uri, timestamp_sha = write_native_timestamps(
                derivatives, run.fnirs_record_id, recording.native_timestamps_s
            )
            provenance = object_dict(recording.provenance)
            provenance.update(
                {
                    "fnirs_record_id": run.fnirs_record_id,
                    "local_path": str(signal_path),
                    "regularized": True,
                    "target_sfreq_hz": regularized.target_sfreq_hz,
                    "interpolation_method": regularized.interpolation_method,
                    "max_time_deviation_s": regularized.max_time_deviation_s,
                    "native_timestamps_uri": timestamp_uri,
                    "native_timestamps_sha256": timestamp_sha,
                    "hbt_check_status": hbt_status,
                    "hbt_tolerance_exceedance_fraction": hbt_exceedance_fraction,
                }
            )
            rows["provenance"].append(provenance)
            parser_added = True
            hbt_failed = hbt_status == "fail"
            if hbt_status == "fail":
                rows["exclusions"].append(
                    {
                        **base,
                        "stage": "signal",
                        "scope_type": "record",
                        "scope_id": run.fnirs_record_id,
                        "status": "fail",
                        "reason_code": "HBT_TOLERANCE_EXCEEDED",
                        "message": "HbT differed from HbO + HbR beyond the frozen tolerance",
                        "observed_value": hbt_exceedance_fraction,
                        "threshold": qc_gates["hbt_exceedance_fraction_max"],
                        "policy_id": "processed_hb_qc_gates_v1",
                        "source_artifact": run.signal_uri,
                    }
                )
            for warning in parser_qc.warnings:
                rows["exclusions"].append(
                    {
                        **base,
                        "stage": "parser",
                        "scope_type": "record",
                        "scope_id": run.fnirs_record_id,
                        "status": "warn",
                        "reason_code": warning,
                        "message": "Header warning retained after downstream record-level gates",
                        "observed_value": (
                            abs((recording.provenance.declared_points or recording.provenance.actual_points)
                                - recording.provenance.actual_points)
                            if warning == "HEADER_POINT_COUNT_MISMATCH"
                            else "present"
                        ),
                        "threshold": 0 if warning == "HEADER_POINT_COUNT_MISMATCH" else "policy_review",
                        "policy_id": "processed_hb_parser_v1",
                        "source_artifact": run.signal_uri,
                    }
                )
            for channel in recording.channels:
                for chromophore in ("hbo", "hbr"):
                    rows["channel_map"].append(
                        {
                            "fnirs_record_id": run.fnirs_record_id,
                            "channel": channel.channel,
                            "vendor_channel_number": channel.vendor_channel_number,
                            "chromophore": chromophore,
                            "original_column_name": channel.original_column_name,
                            "model_included": channel.model_included,
                        }
                    )
            for event, audit in zip(event_set.events, event_set.audit, strict=True):
                rows["events"].append(
                    {
                        **base,
                        "source_row": event.source_row,
                        "window_id": event.window_id,
                        "event_number": event.event_number,
                        "trial_type": event.trial_type,
                        "onset": event.onset,
                        "duration": event.duration,
                        "event_time_layer": event.event_time_layer,
                        "event_source": event.event_source,
                        "sync_uncertainty_s": event.sync_uncertainty_s,
                        "event_eligible_input": event.event_eligible,
                        "duplicate_of_window": event.duplicate_of_window,
                        "design_included": event.event_eligible and not event.duplicate_of_window,
                        "audit_status": audit["status"],
                        "reason_code": audit["reason_code"],
                        "task_mark_consistency": _task_mark_observation(recording, event.onset),
                    }
                )
            if hbt_failed:
                continue
            record_pair_success = len(bundles) == 3
            for bundle in bundles:
                matrix_uri = write_design_matrix(derivatives, run.fnirs_record_id, bundle)
                rows["designs"].append(
                    {
                        "fnirs_record_id": run.fnirs_record_id,
                        "model_id": bundle.model_id,
                        "model_role": bundle.model_role,
                        "matrix_uri": matrix_uri,
                        "design_hash": bundle.design_hash,
                        "n_samples": bundle.matrix.shape[0],
                        "n_columns": bundle.matrix.shape[1],
                        "rank": bundle.rank,
                        "condition_number": bundle.condition_number,
                        "residual_df": bundle.residual_df,
                        "regressor_names_json": list(bundle.regressor_names),
                        "nonestimable_columns_json": list(bundle.nonestimable_columns),
                        "event_input_sha256": manifest.frozen_input_sha256.get("events", ""),
                        "contrast_input_sha256": contrast_input_sha256,
                        "design_status": "pass",
                        "reason_code": "",
                    }
                )
                for channel_index, channel in enumerate(recording.channels):
                    series_row_indices: dict[str, dict[str, list[int]]] = {
                        chromophore: {name: [] for name in ("estimates", "covariance", "contrasts", "residual_qc")}
                        for chromophore in ("hbo", "hbr")
                    }
                    series_pass: dict[str, bool] = {}
                    for chromophore, data in (("hbo", regularized.hbo), ("hbr", regularized.hbr)):
                        y = data[channel_index]
                        try:
                            fit = fit_first_level(
                                y,
                                bundle.matrix,
                                solver_requested=solver["requested"],
                                fallback_policy=solver["fallback_policy"],
                                solver_config=SolverConfig(
                                    **preset["solver_config"], **preset["covariance_config"]
                                ),
                            )
                        except Exception as exc:
                            reason = str(exc).split(":", 1)[0]
                            stage = "covariance" if reason.startswith("COVARIANCE_") else "solver"
                            series_pass[chromophore] = False
                            record_pair_success = False
                            rows["exclusions"].append(
                                {
                                    **base,
                                    "model_id": bundle.model_id,
                                    "channel": channel.channel,
                                    "chromophore": chromophore,
                                    "stage": stage,
                                    "scope_type": "chromophore",
                                    "scope_id": f"{bundle.model_id}/{channel.channel}/{chromophore}",
                                    "status": "fail",
                                    "reason_code": reason,
                                    "message": str(exc),
                                    "policy_id": "processed_hb_solver_v2",
                                    "source_artifact": run.signal_uri,
                                }
                            )
                            continue
                        residual_before = _lag1(
                            y - bundle.matrix @ np.linalg.lstsq(bundle.matrix, y, rcond=None)[0]
                        )
                        residual_after = _lag1(np.asarray(fit["whitened_residuals"]))
                        whitening_improvement = (
                            abs(residual_before) - abs(residual_after)
                            if residual_before is not None and residual_after is not None
                            else None
                        )
                        weights = np.asarray(fit["weights"])
                        low_weight_fraction = float(np.mean(weights < 0.5))
                        qc_reasons = []
                        if (
                            solver["requested"].startswith("ar1")
                            and whitening_improvement is not None
                            and whitening_improvement < qc_gates["whitening_improvement_min"]
                        ):
                            qc_reasons.append("WHITENING_IMPROVEMENT_INSUFFICIENT")
                        if low_weight_fraction > qc_gates["low_weight_fraction_max"]:
                            qc_reasons.append("LOW_WEIGHT_FRACTION_EXCEEDED")
                        series_pass[chromophore] = not qc_reasons
                        if qc_reasons:
                            record_pair_success = False
                            for reason in qc_reasons:
                                observed = (
                                    whitening_improvement
                                    if reason == "WHITENING_IMPROVEMENT_INSUFFICIENT"
                                    else low_weight_fraction
                                )
                                threshold = (
                                    qc_gates["whitening_improvement_min"]
                                    if reason == "WHITENING_IMPROVEMENT_INSUFFICIENT"
                                    else qc_gates["low_weight_fraction_max"]
                                )
                                rows["exclusions"].append(
                                    {
                                        **base,
                                        "model_id": bundle.model_id,
                                        "channel": channel.channel,
                                        "chromophore": chromophore,
                                        "stage": "solver_qc",
                                        "scope_type": "chromophore",
                                        "scope_id": f"{bundle.model_id}/{channel.channel}/{chromophore}",
                                        "status": "fail",
                                        "reason_code": reason,
                                        "message": "Frozen solver QC threshold was not met",
                                        "observed_value": observed,
                                        "threshold": threshold,
                                        "policy_id": "processed_hb_qc_gates_v1",
                                        "source_artifact": "residual_qc.csv",
                                    }
                                )
                        common = {
                            **base,
                            "model_id": bundle.model_id,
                            "channel": channel.channel,
                            "chromophore": chromophore,
                            "design_hash": bundle.design_hash,
                            "solver_requested": fit["solver_requested"],
                            "solver_effective": fit["solver_effective"],
                            "covariance_method": fit["covariance_method"],
                            "absolute_unit_verified": False,
                            "calculation_status": "success",
                            "reason_code": "",
                            "qc_status": "pass" if series_pass[chromophore] else "fail",
                        }
                        for index, name in enumerate(bundle.regressor_names):
                            series_row_indices[chromophore]["estimates"].append(len(rows["estimates"]))
                            rows["estimates"].append(
                                {
                                    **common,
                                    "regressor": name,
                                    "beta": fit["beta"][index],
                                    "standard_error": fit["standard_error"][index],
                                    "statistic": fit["statistic"][index],
                                    "statistic_type": "t",
                                    "df": fit["df"],
                                    "p_value": fit["p_value"][index],
                                    "input_sha256": recording.provenance.sha256,
                                }
                            )
                            for j, name_j in enumerate(bundle.regressor_names):
                                series_row_indices[chromophore]["covariance"].append(len(rows["covariance"]))
                                rows["covariance"].append(
                                    {
                                        **common,
                                        "regressor_i": name,
                                        "regressor_j": name_j,
                                        "covariance": fit["covariance"][index, j],
                                    }
                                )
                        for definition in definitions[bundle.model_id]:
                            try:
                                result = estimate_contrast(
                                    fit,
                                    np.asarray(definition["weights"]),
                                    contrast_id=definition["contrast_id"],
                                )
                            except Exception as exc:
                                reason = str(exc).split(":", 1)[0]
                                series_pass[chromophore] = False
                                record_pair_success = False
                                rows["contrasts"].append(
                                    {
                                        **common,
                                        "contrast_id": definition["contrast_id"],
                                        "contrast_dimension": len(definition["component_names"]),
                                        "component_names_json": definition["component_names"],
                                        "weights_json": np.asarray(definition["weights"]).tolist(),
                                        "calculation_status": "failed",
                                        "reason_code": reason,
                                        "qc_status": "fail",
                                    }
                                )
                                rows["exclusions"].append(
                                    {
                                        **base,
                                        "model_id": bundle.model_id,
                                        "channel": channel.channel,
                                        "chromophore": chromophore,
                                        "stage": "contrast",
                                        "scope_type": "contrast",
                                        "scope_id": definition["contrast_id"],
                                        "status": "fail",
                                        "reason_code": reason,
                                        "message": str(exc),
                                        "policy_id": "processed_hb_contrast_v1",
                                        "source_artifact": "contrast_matrix.csv",
                                    }
                                )
                                continue
                            series_row_indices[chromophore]["contrasts"].append(len(rows["contrasts"]))
                            rows["contrasts"].append(
                                {
                                    **common,
                                    "contrast_id": result["contrast_id"],
                                    "contrast_dimension": result["contrast_dimension"],
                                    "estimate": result["estimate"],
                                    "estimate_json": result.get("estimate_vector"),
                                    "component_names_json": definition["component_names"],
                                    "standard_error": result["standard_error"],
                                    "statistic": result["statistic"],
                                    "statistic_type": result["statistic_type"],
                                    "df_numerator": result["df_numerator"],
                                    "df_denominator": result["df_denominator"],
                                    "p_value": result["p_value"],
                                    "covariance_json": result["covariance_matrix"],
                                    "weights_json": result["weights"],
                                }
                            )
                        series_row_indices[chromophore]["residual_qc"].append(len(rows["residual_qc"]))
                        rows["residual_qc"].append(
                            {
                                "fnirs_record_id": run.fnirs_record_id,
                                "model_id": bundle.model_id,
                                "channel": channel.channel,
                                "chromophore": chromophore,
                                "n_samples": len(y),
                                "n_effective": len(y),
                                "nonfinite_count": 0,
                                "outlier_fraction": float(np.mean(np.abs(y - np.median(y)) > 3 * np.std(y))),
                                "residual_lag1_before": residual_before,
                                "residual_lag1_after": residual_after,
                                "whitening_improvement": whitening_improvement,
                                "ar1_rho": fit["ar1_rho"],
                                "ar_iterations": fit["ar_iterations"],
                                "ar_converged": fit["ar_converged"],
                                "irls_iterations": fit["irls_iterations"],
                                "irls_converged": fit["irls_converged"],
                                "weight_min": float(weights.min()),
                                "weight_median": float(np.median(weights)),
                                "weight_max": float(weights.max()),
                                "low_weight_fraction": low_weight_fraction,
                                "solver_requested": fit["solver_requested"],
                                "solver_effective": fit["solver_effective"],
                                "covariance_status": "pass",
                                "qc_status": "pass" if series_pass[chromophore] else "fail",
                                "reason_code": ";".join(qc_reasons),
                            }
                        )
                    if series_pass.get("hbo") is not True or series_pass.get("hbr") is not True:
                        record_pair_success = False
                        for chromophore in ("hbo", "hbr"):
                            if chromophore not in series_pass:
                                continue
                            for table, indices in series_row_indices[chromophore].items():
                                for row_index in indices:
                                    rows[table][row_index]["qc_status"] = "fail"
                                    if not rows[table][row_index].get("reason_code"):
                                        rows[table][row_index]["reason_code"] = "HBO_HBR_PAIRING_FAILURE"
                        rows["exclusions"].append(
                            {
                                **base,
                                "model_id": bundle.model_id,
                                "channel": channel.channel,
                                "stage": "pairing",
                                "scope_type": "channel",
                                "scope_id": f"{bundle.model_id}/{channel.channel}",
                                "status": "fail",
                                "reason_code": "HBO_HBR_PAIRING_FAILURE",
                                "message": "HbO and HbR did not both pass calculation and QC",
                                "policy_id": "processed_hb_pairing_v1",
                                "source_artifact": "first_level_glm_estimates.csv",
                            }
                        )
            if record_pair_success:
                successful_pairs.add(run.record_pair_id)
        except Exception as exc:
            if not parser_added:
                try:
                    payload = signal_path.read_bytes()
                    rows["provenance"].append(
                        {
                            "fnirs_record_id": run.fnirs_record_id,
                            "input_uri": run.signal_uri,
                            "local_path": str(signal_path),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "size_bytes": len(payload),
                            "parser_name": "vendor_processed_hb",
                            "absolute_unit_verified": False,
                            "warning_codes": [],
                            "parser_status": "fail",
                        }
                    )
                except OSError:
                    pass
            reason = str(exc).split(":", 1)[0]
            rows["exclusions"].append(
                {
                    **base,
                    "stage": _failure_stage(reason, parser_completed=parser_added),
                    "scope_type": "record",
                    "scope_id": run.fnirs_record_id,
                    "status": "fail",
                    "reason_code": reason,
                    "message": str(exc),
                    "policy_id": "processed_hb_failure_state_v1",
                    "source_artifact": run.signal_uri,
                }
            )

    finished = datetime.now(timezone.utc)
    summary = Counter(row.get("reason_code", "") for row in rows["exclusions"])
    contrast_counts = {}
    for model_id, contrast_id, chromophore in sorted(requested_estimands):
        matching = [
            row
            for row in rows["contrasts"]
            if row.get("model_id") == model_id
            and row.get("contrast_id") == contrast_id
            and row.get("chromophore") == chromophore
        ]
        attempted = {row["record_pair_id"] for row in matching}
        succeeded = {
            row["record_pair_id"]
            for row in matching
            if row.get("calculation_status") == "success" and row.get("qc_status") == "pass"
        }
        contrast_counts[f"{model_id}:{contrast_id}:{chromophore}"] = {
            "eligible": len(eligible_pairs),
            "attempted": len(attempted),
            "succeeded": len(succeeded),
            "failed": len(eligible_pairs - succeeded),
        }
    analysis_manifest = {
        "derivatives_contract": "1.0.0",
        "flow_schema": "0.4.0",
        "data_manifest_schema": "0.2.0",
        "analysis_version": preset["analysis_version"],
        "status": preset["status"],
        "fnirs_flow_version": fnirs_flow.__version__,
        "git_commit": _git_commit(),
        "python": sys.version,
        "os": platform.platform(),
        "numpy": np.__version__,
        "scipy": __import__("scipy").__version__,
        "statsmodels": __import__("statsmodels").__version__,
        "mne": __import__("mne").__version__,
        "solver": solver,
        "solver_config": preset["solver_config"],
        "covariance_config": preset["covariance_config"],
        "design_gates": preset["design_gates"],
        "qc_gates": preset["qc_gates"],
        "time_regularization": preset["time_regularization"],
        "parser": {"name": "vendor_processed_hb", "version": PARSER_VERSION},
        "design_implementation_version": DESIGN_IMPLEMENTATION_VERSION,
        "solver_implementation_version": "processed_hb_solver_v2",
        "execution": {"record_concurrency": 1, "blas_threads": "environment", "random_seed": None},
        "frozen_input_sha256": manifest.frozen_input_sha256,
        "filters": {"fnirs_record_ids": fnirs_record_ids or [], "record_pair_ids": record_pair_ids or []},
        "started_at": started.isoformat(),
        "completed_at": finished.isoformat(),
        "exit_status": (
            "success"
            if not any(row.get("status") in {"fail", "excluded"} for row in rows["exclusions"])
            else "completed_with_exclusions"
        ),
        "successful_record_pairs_by_chromophore": {"hbo": len(successful_pairs), "hbr": len(successful_pairs)},
        "available_record_pairs_by_model_chromophore": {
            f"{model}:{chromophore}": len(
                {
                    row["record_pair_id"]
                    for row in rows["estimates"]
                    if row["model_id"] == model
                    and row["chromophore"] == chromophore
                    and row["calculation_status"] == "success"
                }
            )
            for model in preset["models"]
            for chromophore in ("hbo", "hbr")
        },
        "record_pairs_by_contrast_chromophore": contrast_counts,
        "solver_requested_effective": dict(
            Counter(f"{row['solver_requested']}->{row['solver_effective']}" for row in rows["residual_qc"])
        ),
        "reason_code_counts": dict(summary),
        "stable_sort": "record/model/channel/chromophore/regressor",
    }
    for values in rows.values():
        values.sort(
            key=lambda item: tuple(
                str(item.get(key, ""))
                for key in (
                    "fnirs_record_id",
                    "model_id",
                    "channel",
                    "chromophore",
                    "regressor",
                    "regressor_i",
                    "regressor_j",
                    "contrast_id",
                )
            )
        )
    paths = write_processed_hb_derivatives(
        derivatives,
        provenance=rows["provenance"],
        runs=rows["runs"],
        events=rows["events"],
        designs=rows["designs"],
        estimates=rows["estimates"],
        covariance=rows["covariance"],
        contrasts=rows["contrasts"],
        residual_qc=rows["residual_qc"],
        exclusions=rows["exclusions"],
        channel_map=rows["channel_map"],
        analysis_manifest=analysis_manifest,
    )
    analysis_manifest["output_artifact_sha256"] = {
        path.relative_to(derivatives).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(derivatives.rglob("*"))
        if path.is_file() and path != paths["analysis_manifest"]
    }
    temporary_manifest = paths["analysis_manifest"].with_name(".analysis_manifest.json.tmp")
    temporary_manifest.write_text(
        json.dumps(analysis_manifest, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    temporary_manifest.replace(paths["analysis_manifest"])
    return {
        "derivatives": str(derivatives),
        "successful_record_pairs": len(successful_pairs),
        "exclusions": len(rows["exclusions"]),
        "artifacts": {key: str(value) for key, value in paths.items()},
    }
