"""Stable derivative contract 1.0.0 for processed-Hb analyses."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _fields(*groups: str) -> list[str]:
    return " ".join(groups).split()


ESTIMATE_FIELDS = _fields(
    "analysis_version record_pair_id linked_record_id fnirs_record_id model_id channel chromophore regressor",
    "beta standard_error statistic statistic_type df p_value solver_requested solver_effective covariance_method",
    "design_hash input_sha256 absolute_unit_verified calculation_status reason_code qc_status",
)
COVARIANCE_FIELDS = _fields(
    "analysis_version record_pair_id fnirs_record_id model_id channel chromophore regressor_i regressor_j",
    "covariance covariance_method design_hash solver_effective absolute_unit_verified calculation_status reason_code",
)
CONTRAST_FIELDS = _fields(
    "analysis_version record_pair_id linked_record_id fnirs_record_id model_id channel chromophore contrast_id",
    "contrast_dimension estimate estimate_json component_names_json standard_error statistic statistic_type",
    "df_numerator df_denominator p_value covariance_json weights_json design_hash solver_effective",
    "absolute_unit_verified calculation_status reason_code qc_status",
)
PROVENANCE_FIELDS = _fields(
    "fnirs_record_id input_uri local_path sha256 size_bytes parser_name parser_version encoding declared_points",
    "actual_points first_timestamp_s last_timestamp_s duration_s native_sfreq_hz dt_min_s dt_median_s dt_max_s",
    "dt_mad_s dt_iqr_s jitter_abs_max_s duplicate_timestamp_count channel_count absolute_unit_verified regularized",
    "target_sfreq_hz interpolation_method",
    "max_time_deviation_s hbt_check_status hbt_mae hbt_rmse hbt_max_abs_error native_timestamps_uri",
    "hbt_error_quantiles hbt_tolerance_exceedance_fraction native_timestamps_sha256 warning_codes parser_status",
)
RUN_FIELDS = _fields(
    "analysis_version linked_record_id fnirs_record_id record_pair_id fnirs_signal_uri input_sha256 sync_grade",
    "event_primary_eligible lag_primary_eligible observed_coverage analysis_included frozen_exclusion_reason",
    "discovery_status discovery_reason_code",
)
EVENT_FIELDS = _fields(
    "analysis_version fnirs_record_id record_pair_id source_row window_id event_number trial_type onset duration",
    "event_time_layer event_source sync_uncertainty_s event_eligible_input duplicate_of_window design_included",
    "audit_status reason_code task_mark_consistency",
)
DESIGN_FIELDS = _fields(
    "fnirs_record_id model_id model_role matrix_uri design_hash n_samples n_columns rank condition_number residual_df",
    "regressor_names_json nonestimable_columns_json event_input_sha256 contrast_input_sha256 design_status reason_code",
)
RESIDUAL_FIELDS = _fields(
    "fnirs_record_id model_id channel chromophore n_samples n_effective nonfinite_count outlier_fraction",
    "residual_lag1_before residual_lag1_after whitening_improvement ar1_rho ar_iterations ar_converged",
    "irls_iterations irls_converged weight_min weight_median",
    "weight_max low_weight_fraction solver_requested solver_effective covariance_status qc_status reason_code",
)
EXCLUSION_FIELDS = _fields(
    "fnirs_record_id record_pair_id stage scope_type scope_id model_id channel chromophore status reason_code",
    "message observed_value threshold policy_id source_artifact",
)
CHANNEL_FIELDS = _fields(
    "fnirs_record_id channel vendor_channel_number chromophore original_column_name model_included"
)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write_table(path: str | Path, fields: list[str], rows: Iterable[Mapping[str, object]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    opener = gzip.open if target.suffix == ".gz" else open
    with opener(temporary, "wt", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            normalized = {}
            for key in fields:
                value = row.get(key, "")
                if value is None or (isinstance(value, float) and not math.isfinite(value)):
                    value = ""
                elif isinstance(value, (list, tuple, dict)):
                    value = canonical_json(value)
                elif isinstance(value, bool):
                    value = str(value).lower()
                normalized[key] = value
            writer.writerow(normalized)
    temporary.replace(target)
    return target


def write_native_timestamps(root: Path, record_id: str, timestamps: Any) -> tuple[str, str]:
    path = root / "native_timestamps" / f"{record_id}.csv.gz"
    rows = ({"sample_index": index, "native_timestamp_s": float(value)} for index, value in enumerate(timestamps))
    write_table(path, ["sample_index", "native_timestamp_s"], rows)
    return path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


def write_design_matrix(root: Path, record_id: str, bundle: Any) -> str:
    path = root / "design_matrices" / f"{record_id}__{bundle.model_id}.csv.gz"
    rows = (dict(zip(bundle.regressor_names, row, strict=True)) for row in bundle.matrix)
    write_table(path, list(bundle.regressor_names), rows)
    return path.relative_to(root).as_posix()


def write_processed_hb_derivatives(
    outdir: str | Path,
    *,
    provenance=(),
    runs=(),
    events=(),
    designs=(),
    estimates=(),
    covariance=(),
    contrasts=(),
    residual_qc=(),
    exclusions=(),
    channel_map=(),
    analysis_manifest: Mapping[str, object] | None = None,
) -> dict[str, Path]:
    root = Path(outdir)
    root.mkdir(parents=True, exist_ok=True)
    tables = {
        "provenance": ("input_provenance.csv", PROVENANCE_FIELDS, provenance),
        "runs": ("run_manifest.csv", RUN_FIELDS, runs),
        "events": ("event_ingestion_audit.csv", EVENT_FIELDS, events),
        "designs": ("design_matrix_manifest.csv", DESIGN_FIELDS, designs),
        "estimates": ("first_level_glm_estimates.csv", ESTIMATE_FIELDS, estimates),
        "covariance": ("first_level_glm_covariance.csv", COVARIANCE_FIELDS, covariance),
        "contrasts": ("first_level_contrasts.csv", CONTRAST_FIELDS, contrasts),
        "residual_qc": ("residual_qc.csv", RESIDUAL_FIELDS, residual_qc),
        "exclusions": ("exclusion_manifest.csv", EXCLUSION_FIELDS, exclusions),
        "channel_map": ("channel_map.csv", CHANNEL_FIELDS, channel_map),
    }
    result = {key: write_table(root / name, fields, rows) for key, (name, fields, rows) in tables.items()}
    manifest_path = root / "analysis_manifest.json"
    manifest_path.write_text(
        json.dumps(dict(analysis_manifest or {}), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    result["analysis_manifest"] = manifest_path
    return result


def object_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)
