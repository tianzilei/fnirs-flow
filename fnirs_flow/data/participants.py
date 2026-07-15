"""Participant and observation metadata tables.

This module owns the shared CSV/TSV ingestion path used by group statistics,
site covariates, ML labels, and repeated-measures designs.  It intentionally
does not run statistical tests; it validates, joins, and projects typed views
from external tabular metadata.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from fnirs_flow.data.manifest import DataManifest

TableKind = Literal["participant", "observation"]


class TableFileReference(BaseModel):
    """Auditable reference to an imported table file."""

    path: str
    format: str = "auto"
    id_column: str = "participant_id"
    include_column: str = "include"
    encoding: str = "utf-8-sig"
    delimiter: str = "auto"
    id_normalization: str = "bids_exact"
    sha256: str = ""
    size_bytes: int = 0


class TableColumn(BaseModel):
    name: str
    inferred_type: str = "text"
    missing_count: int = 0
    unique_count: int = 0
    possible_sensitive: bool = False


class ColumnRoleMap(BaseModel):
    id_column: str = "participant_id"
    include_column: str = "include"
    group_column: str = "group"
    label_column: str = ""
    site_column: str = "site"
    scanner_column: str = "scanner_id"
    covariate_columns: list[str] = Field(default_factory=list)
    session_column: str = "session"
    timepoint_column: str = "timepoint"
    pair_id_column: str = "pair_id"
    dyad_id_column: str = "dyad_id"
    participant_role_column: str = "participant_role"


class ParticipantTable(BaseModel):
    schema_version: str = "0.1.0"
    table_kind: TableKind = "participant"
    source: TableFileReference
    columns: list[TableColumn] = Field(default_factory=list)
    column_role_map: ColumnRoleMap = Field(default_factory=ColumnRoleMap)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class ObservationTable(ParticipantTable):
    table_kind: TableKind = "observation"


class ParticipantJoinPreview(BaseModel):
    matched_subjects: list[str] = Field(default_factory=list)
    unmatched_results: list[str] = Field(default_factory=list)
    metadata_without_data: list[str] = Field(default_factory=list)
    duplicate_ids: list[str] = Field(default_factory=list)
    excluded_subjects: list[str] = Field(default_factory=list)
    join_policy: str = "bids_exact"


class TableValidationReport(BaseModel):
    is_valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    column_role_map: ColumnRoleMap = Field(default_factory=ColumnRoleMap)
    join_preview: ParticipantJoinPreview = Field(default_factory=ParticipantJoinPreview)


class ParticipantTableBundle(BaseModel):
    participant_table_manifest: TableFileReference
    column_role_map: ColumnRoleMap
    validation_report: TableValidationReport
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(frozen=True)
class GroupDesignResult:
    analysis_table: list[dict[str, Any]]
    design_matrix: list[dict[str, float]]
    column_names: list[str]
    rank: int
    condition_number: float


@dataclass(frozen=True)
class GroupContrastSpec:
    name: str
    contrast_type: Literal["T", "F"] = "T"
    weights: list[float] | None = None
    weight_matrix: list[list[float]] | None = None
    expression: str = ""


@dataclass(frozen=True)
class GroupGLMResult:
    coefficients: list[dict[str, Any]]
    contrasts: list[dict[str, Any]]
    effect_sizes: list[dict[str, Any]]
    corrected: list[dict[str, Any]]
    sensitivity: list[dict[str, Any]] | None = None


def _ordered_levels(rows: list[dict[str, Any]], column: str) -> list[str]:
    levels: list[str] = []
    for row in rows:
        value = str(row.get(column, "")).strip()
        if value and value not in levels:
            levels.append(value)
    return levels


def _factor_columns(rows: list[dict[str, Any]], factors: list[str]) -> tuple[list[str], list[list[float]]]:
    column_names: list[str] = []
    matrix: list[list[float]] = [[] for _ in rows]
    for factor in factors:
        levels = _ordered_levels(rows, factor)
        if len(levels) < 2:
            raise ValueError(f"GROUP_METADATA_MISSING: factor {factor} requires at least two levels")
        for level in levels:
            column_names.append(f"{factor}[{level}]")
            for index, row in enumerate(rows):
                matrix[index].append(1.0 if str(row.get(factor, "")) == level else 0.0)
    return column_names, matrix


def _treatment_factor_columns(
    rows: list[dict[str, Any]], factors: list[str]
) -> tuple[list[str], list[list[float]], dict[str, list[str]]]:
    column_names: list[str] = []
    matrix: list[list[float]] = [[] for _ in rows]
    factor_levels: dict[str, list[str]] = {}
    for factor in factors:
        levels = _ordered_levels(rows, factor)
        if len(levels) < 2:
            raise ValueError(f"GROUP_METADATA_MISSING: factor {factor} requires at least two levels")
        factor_levels[factor] = levels
        for level in levels[1:]:
            column_names.append(f"{factor}[{level}]")
            for index, row in enumerate(rows):
                matrix[index].append(1.0 if str(row.get(factor, "")) == level else 0.0)
    return column_names, matrix, factor_levels


def _interaction_columns(
    rows: list[dict[str, Any]],
    factors: list[str],
    *,
    max_order: int | None = None,
) -> tuple[list[str], list[list[float]]]:
    from itertools import combinations, product

    if len(factors) < 2:
        return [], [[] for _ in rows]
    max_order = max_order or len(factors)
    column_names: list[str] = []
    matrix: list[list[float]] = [[] for _ in rows]
    factor_levels = {factor: _ordered_levels(rows, factor) for factor in factors}
    for order in range(2, min(max_order, len(factors)) + 1):
        for combo in combinations(factors, order):
            for levels in product(*(factor_levels[factor] for factor in combo)):
                name = ":".join(f"{factor}[{level}]" for factor, level in zip(combo, levels, strict=True))
                column_names.append(name)
                for index, row in enumerate(rows):
                    matrix[index].append(
                        1.0
                        if all(str(row.get(factor, "")) == level for factor, level in zip(combo, levels, strict=True))
                        else 0.0
                    )
    return column_names, matrix


def _treatment_interaction_columns(
    rows: list[dict[str, Any]],
    factors: list[str],
    factor_levels: dict[str, list[str]],
    *,
    max_order: int | None = None,
) -> tuple[list[str], list[list[float]]]:
    from itertools import combinations, product

    if len(factors) < 2:
        return [], [[] for _ in rows]
    max_order = max_order or len(factors)
    column_names: list[str] = []
    matrix: list[list[float]] = [[] for _ in rows]
    for order in range(2, min(max_order, len(factors)) + 1):
        for combo in combinations(factors, order):
            contrast_levels = [factor_levels[factor][1:] for factor in combo]
            for levels in product(*contrast_levels):
                name = ":".join(f"{factor}[{level}]" for factor, level in zip(combo, levels, strict=True))
                column_names.append(name)
                for index, row in enumerate(rows):
                    matrix[index].append(
                        1.0
                        if all(str(row.get(factor, "")) == level for factor, level in zip(combo, levels, strict=True))
                        else 0.0
                    )
    return column_names, matrix


SENSITIVE_NAME_HINTS = {
    "name",
    "email",
    "phone",
    "address",
    "dob",
    "birthday",
    "birth_date",
    "mrn",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_delimiter(path: Path, *, encoding: str = "utf-8-sig", requested: str = "auto") -> str:
    if requested and requested != "auto":
        return "\t" if requested in {"tab", "\\t"} else requested
    if path.suffix.lower() == ".tsv":
        return "\t"
    if path.suffix.lower() == ".csv":
        return ","
    sample = path.read_text(encoding=encoding, errors="replace")[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except csv.Error:
        return "\t" if "\t" in sample else ","


def _coerce_cell(value: str) -> Any:
    stripped = value.strip()
    if stripped == "":
        return ""
    lowered = stripped.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"nan", "na", "n/a", "null", "none"}:
        return ""
    try:
        number = float(stripped)
    except ValueError:
        return stripped
    if math.isfinite(number) and number.is_integer() and "." not in stripped:
        return int(number)
    return number


def _is_included(row: dict[str, Any], include_column: str) -> bool:
    if include_column not in row or row.get(include_column) == "":
        return True
    value = row.get(include_column)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "include", "included"}


def _infer_type(values: list[Any]) -> str:
    present = [value for value in values if value != ""]
    if not present:
        return "empty"
    if all(isinstance(value, bool) for value in present):
        return "boolean"
    if all(isinstance(value, int | float) and not isinstance(value, bool) for value in present):
        return "numeric"
    if len({str(value) for value in present}) <= max(20, len(present) // 2):
        return "categorical"
    return "text"


def _columns(rows: list[dict[str, Any]], fieldnames: list[str]) -> list[TableColumn]:
    result: list[TableColumn] = []
    for name in fieldnames:
        values = [row.get(name, "") for row in rows]
        lowered = name.lower()
        result.append(
            TableColumn(
                name=name,
                inferred_type=_infer_type(values),
                missing_count=sum(1 for value in values if value == ""),
                unique_count=len({str(value) for value in values if value != ""}),
                possible_sensitive=(
                    lowered in SENSITIVE_NAME_HINTS
                    or any(hint in lowered for hint in SENSITIVE_NAME_HINTS)
                ),
            )
        )
    return result


def read_participant_table(
    path: str | Path,
    *,
    table_kind: TableKind = "participant",
    id_column: str = "participant_id",
    include_column: str = "include",
    delimiter: str = "auto",
    encoding: str = "utf-8-sig",
    column_role_map: ColumnRoleMap | None = None,
) -> ParticipantTable:
    """Read a CSV/TSV participant or observation table with provenance."""
    table_path = Path(path)
    actual_delimiter = detect_delimiter(table_path, encoding=encoding, requested=delimiter)
    with table_path.open(newline="", encoding=encoding) as stream:
        reader = csv.DictReader(stream, delimiter=actual_delimiter)
        rows = [{key: _coerce_cell(value or "") for key, value in row.items()} for row in reader]
        fieldnames = list(reader.fieldnames or [])

    roles = column_role_map or ColumnRoleMap(id_column=id_column, include_column=include_column)
    source = TableFileReference(
        path=table_path.name,
        format=table_path.suffix.lower().lstrip(".") or "csv",
        id_column=roles.id_column,
        include_column=roles.include_column,
        encoding=encoding,
        delimiter="tab" if actual_delimiter == "\t" else actual_delimiter,
        sha256=file_sha256(table_path),
        size_bytes=table_path.stat().st_size,
    )
    model = ObservationTable if table_kind == "observation" else ParticipantTable
    return model(
        source=source,
        columns=_columns(rows, fieldnames),
        column_role_map=roles,
        rows=rows,
    )


def manifest_subject_ids(manifest: DataManifest | dict[str, Any]) -> list[str]:
    data = manifest.model_dump() if isinstance(manifest, DataManifest) else manifest
    subjects: list[str] = []
    for run in data.get("subject_session_runs", []):
        subject = str(run.get("subject", "")).strip()
        if not subject:
            continue
        subject_id = subject if subject.startswith("sub-") else f"sub-{subject}"
        if subject_id not in subjects:
            subjects.append(subject_id)
    return subjects


def validate_participant_table(
    table: ParticipantTable,
    manifest: DataManifest | dict[str, Any] | None = None,
) -> TableValidationReport:
    roles = table.column_role_map
    errors: list[str] = []
    warnings: list[str] = []
    duplicate_ids: list[str] = []
    seen: set[str] = set()
    table_ids: list[str] = []
    excluded: list[str] = []

    if roles.id_column not in {column.name for column in table.columns}:
        errors.append(f"Missing required id column: {roles.id_column}")
    for index, row in enumerate(table.rows, start=2):
        participant_id = str(row.get(roles.id_column, "")).strip()
        if not participant_id:
            errors.append(f"Empty participant id at row {index}")
            continue
        if participant_id in seen and participant_id not in duplicate_ids:
            duplicate_ids.append(participant_id)
        seen.add(participant_id)
        table_ids.append(participant_id)
        if not _is_included(row, roles.include_column):
            excluded.append(participant_id)
    if duplicate_ids:
        errors.append("Duplicate participant ids: " + ", ".join(sorted(duplicate_ids)))

    preview = ParticipantJoinPreview(
        duplicate_ids=sorted(duplicate_ids),
        excluded_subjects=sorted(set(excluded)),
        join_policy=table.source.id_normalization,
    )
    if manifest is not None:
        data_ids = manifest_subject_ids(manifest)
        table_id_set = set(table_ids)
        data_id_set = set(data_ids)
        preview.matched_subjects = sorted(table_id_set & data_id_set)
        preview.unmatched_results = sorted(data_id_set - table_id_set)
        preview.metadata_without_data = sorted(table_id_set - data_id_set)
        if preview.unmatched_results:
            warnings.append("Metadata does not cover all discovered subjects: " + ", ".join(preview.unmatched_results))

    return TableValidationReport(
        is_valid=not errors,
        errors=errors,
        warnings=warnings,
        column_role_map=roles,
        join_preview=preview,
    )


def write_participant_table_artifacts(
    table: ParticipantTable,
    outdir: str | Path,
    *,
    manifest: DataManifest | dict[str, Any] | None = None,
) -> ParticipantTableBundle:
    """Persist the standard participant metadata audit artifacts."""
    target = Path(outdir)
    target.mkdir(parents=True, exist_ok=True)
    report = validate_participant_table(table, manifest)
    bundle = ParticipantTableBundle(
        participant_table_manifest=table.source,
        column_role_map=table.column_role_map,
        validation_report=report,
        preview_rows=table.rows[:25],
    )
    (target / "participant_table_manifest.json").write_text(
        json.dumps(table.source.model_dump(), indent=2),
        encoding="utf-8",
    )
    (target / "column_role_map.json").write_text(
        json.dumps(table.column_role_map.model_dump(), indent=2),
        encoding="utf-8",
    )
    (target / "participant_table_preview.json").write_text(
        json.dumps(table.rows[:25], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (target / "participant_validation_report.json").write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    join = report.join_preview
    with (target / "participant_join_audit.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["participant_id", "join_status"])
        writer.writeheader()
        for participant_id in join.matched_subjects:
            writer.writerow({"participant_id": participant_id, "join_status": "matched"})
        for participant_id in join.unmatched_results:
            writer.writerow({"participant_id": participant_id, "join_status": "data_without_metadata"})
        for participant_id in join.metadata_without_data:
            writer.writerow({"participant_id": participant_id, "join_status": "metadata_without_data"})
    with (target / "participant_exclusion_manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["participant_id", "reason"])
        writer.writeheader()
        for participant_id in join.excluded_subjects:
            writer.writerow({"participant_id": participant_id, "reason": "include_column_false"})
    return bundle


def load_participant_table_from_artifacts(outdir: str | Path) -> ParticipantTable | None:
    manifest_path = Path(outdir) / "participant_table_manifest.json"
    preview_path = Path(outdir) / "participant_table_preview.json"
    role_path = Path(outdir) / "column_role_map.json"
    if not manifest_path.exists():
        return None
    source = TableFileReference.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    table_file = Path(source.path)
    if table_file.exists():
        roles = ColumnRoleMap.model_validate_json(role_path.read_text(encoding="utf-8")) if role_path.exists() else None
        return read_participant_table(
            table_file,
            id_column=source.id_column,
            include_column=source.include_column,
            delimiter=source.delimiter,
            encoding=source.encoding,
            column_role_map=roles,
        )
    rows = json.loads(preview_path.read_text(encoding="utf-8")) if preview_path.exists() else []
    roles = (
        ColumnRoleMap.model_validate_json(role_path.read_text(encoding="utf-8"))
        if role_path.exists()
        else ColumnRoleMap()
    )
    columns = _columns(rows, list(rows[0]) if rows else [])
    return ParticipantTable(source=source, rows=rows, columns=columns, column_role_map=roles)


def join_participant_metadata(
    subject_rows: list[dict[str, Any]],
    table: ParticipantTable,
    *,
    subject_column: str = "subject",
) -> dict[str, Any]:
    roles = table.column_role_map
    metadata_by_id = {str(row.get(roles.id_column, "")).strip(): row for row in table.rows}
    annotated: list[dict[str, Any]] = []
    unmatched_results: list[str] = []
    for row in subject_rows:
        subject = str(row.get(subject_column, row.get("participant_id", ""))).strip()
        participant_id = subject if subject.startswith("sub-") else f"sub-{subject}"
        metadata = metadata_by_id.get(participant_id)
        if metadata is None:
            unmatched_results.append(participant_id)
            annotated.append(row)
        elif _is_included(metadata, roles.include_column):
            annotated.append({**row, **metadata, "participant_id": participant_id})
    result_ids = {
        (str(row.get(subject_column, row.get("participant_id", ""))).strip())
        for row in subject_rows
    }
    normalized_result_ids = {item if item.startswith("sub-") else f"sub-{item}" for item in result_ids if item}
    metadata_ids = set(metadata_by_id)
    excluded = [
        participant_id
        for participant_id, row in metadata_by_id.items()
        if not _is_included(row, roles.include_column)
    ]
    return {
        "annotated_rows": annotated,
        "matched_subjects": sorted(normalized_result_ids & metadata_ids),
        "unmatched_results": sorted(set(unmatched_results)),
        "metadata_without_data": sorted(metadata_ids - normalized_result_ids),
        "duplicate_ids": validate_participant_table(table).join_preview.duplicate_ids,
        "excluded_subjects": sorted(excluded),
        "join_policy": table.source.id_normalization,
    }


def project_label_vector(table: ParticipantTable, label_column: str | None = None) -> dict[str, Any]:
    roles = table.column_role_map
    column = label_column or roles.label_column or roles.group_column
    labels = []
    for row in table.rows:
        if _is_included(row, roles.include_column):
            labels.append({"participant_id": row.get(roles.id_column), "label": row.get(column)})
    return {"type": "LabelVector", "label_column": column, "labels": labels}


def project_site_metadata(table: ParticipantTable, site_column: str | None = None) -> dict[str, Any]:
    roles = table.column_role_map
    site = site_column or roles.site_column
    rows = []
    for row in table.rows:
        if _is_included(row, roles.include_column):
            rows.append(
                {
                    "participant_id": row.get(roles.id_column),
                    "site": row.get(site, ""),
                    "scanner_id": row.get(roles.scanner_column, ""),
                }
            )
    return {"type": "SiteMetadata", "site_column": site, "rows": rows}


def project_covariate_matrix(table: ParticipantTable, covariate_columns: list[str]) -> dict[str, Any]:
    roles = table.column_role_map
    rows = [
        {"participant_id": row.get(roles.id_column), **{column: row.get(column, "") for column in covariate_columns}}
        for row in table.rows
        if _is_included(row, roles.include_column)
    ]
    return {"type": "CovariateMatrix", "columns": covariate_columns, "rows": rows}


def project_dpf_inputs(
    table: ParticipantTable,
    *,
    age_column: str = "age",
    wavelength_columns: list[str] | None = None,
) -> dict[str, Any]:
    roles = table.column_role_map
    if not table.rows or age_column not in table.rows[0]:
        raise ValueError(f"COVARIATE_MISSING_VALUES: missing age column {age_column}")
    rows = []
    for row in table.rows:
        if not _is_included(row, roles.include_column):
            continue
        age = row.get(age_column, "")
        if age == "":
            raise ValueError(f"COVARIATE_MISSING_VALUES: missing {age_column}")
        projected = {"participant_id": row.get(roles.id_column), "age_years": float(age)}
        for column in wavelength_columns or []:
            projected[column] = row.get(column, "")
        rows.append(projected)
    return {"type": "DPFInput", "age_column": age_column, "wavelength_columns": wavelength_columns or [], "rows": rows}


def project_outcome_vector(
    table: ParticipantTable,
    outcome_column: str,
    *,
    outcome_kind: str = "behavioral",
) -> dict[str, Any]:
    roles = table.column_role_map
    if not outcome_column:
        raise ValueError("COVARIATE_MISSING_VALUES: outcome column is required")
    if not table.rows or outcome_column not in table.rows[0]:
        raise ValueError(f"COVARIATE_MISSING_VALUES: missing outcome column {outcome_column}")
    rows = []
    for row in table.rows:
        if not _is_included(row, roles.include_column):
            continue
        value = row.get(outcome_column, "")
        if value == "":
            raise ValueError(f"COVARIATE_MISSING_VALUES: missing {outcome_column}")
        rows.append({"participant_id": row.get(roles.id_column), "value": float(value)})
    return {
        "type": "OutcomeVector",
        "outcome_column": outcome_column,
        "outcome_kind": outcome_kind,
        "rows": rows,
    }


def project_combat_manifest(
    table: ParticipantTable,
    *,
    site_column: str | None = None,
    biological_covariates: list[str] | None = None,
) -> dict[str, Any]:
    roles = table.column_role_map
    site = site_column or roles.site_column
    covariates = biological_covariates or roles.covariate_columns
    runs = []
    for row in table.rows:
        if not _is_included(row, roles.include_column):
            continue
        entry = {
            "subject": row.get(roles.id_column),
            "site": row.get(site, ""),
            "scanner_id": row.get(roles.scanner_column, ""),
            "group": row.get(roles.group_column, ""),
        }
        for column in covariates:
            entry[column] = row.get(column, "")
        runs.append(entry)
    return {
        "type": "ComBatManifest",
        "site_field": "site",
        "biological_covariates": covariates,
        "subject_session_runs": runs,
    }


def project_pairing_structure(table: ObservationTable) -> dict[str, Any]:
    roles = table.column_role_map
    rows = [
        {
            "participant_id": row.get(roles.id_column),
            "session": row.get(roles.session_column, ""),
            "timepoint": row.get(roles.timepoint_column, ""),
            "pair_id": row.get(roles.pair_id_column, ""),
        }
        for row in table.rows
        if _is_included(row, roles.include_column)
    ]
    return {"type": "PairingStructure", "rows": rows}


def project_dyad_structure(table: ObservationTable) -> dict[str, Any]:
    roles = table.column_role_map
    rows = [
        {
            "participant_id": row.get(roles.id_column),
            "dyad_id": row.get(roles.dyad_id_column, ""),
            "participant_role": row.get(roles.participant_role_column, ""),
            "group": row.get(roles.group_column, ""),
        }
        for row in table.rows
        if _is_included(row, roles.include_column)
    ]
    return {"type": "DyadStructure", "rows": rows}


def build_group_design_matrix(
    analysis_rows: list[dict[str, Any]],
    *,
    design_type: str,
    group_column: str = "group",
    covariates: list[str] | None = None,
    factors: list[str] | None = None,
    within_subject_factors: list[str] | None = None,
    random_effects: list[str] | None = None,
    condition_column: str = "condition",
    pair_id_column: str = "participant_id",
    response_column: str = "beta",
) -> GroupDesignResult:
    """Compile a small SPM-style group design matrix for MVP designs."""
    covariates = covariates or []
    factors = factors or []
    within_subject_factors = within_subject_factors or []
    random_effects = random_effects or []
    included = [row for row in analysis_rows if str(row.get("participant_id", row.get("subject", ""))).strip()]
    if not included:
        raise ValueError("GROUP_METADATA_MISSING: no analysis rows available for group design")

    column_names: list[str] = []
    matrix: list[list[float]] = []
    if design_type == "one_sample_t":
        column_names = ["intercept"]
        matrix = [[1.0] for _ in included]
    elif design_type == "two_sample_t":
        levels = sorted({str(row.get(group_column, "")) for row in included if row.get(group_column, "") != ""})
        if len(levels) != 2:
            raise ValueError("GROUP_METADATA_MISSING: two_sample_t requires exactly two group levels")
        column_names = [f"{group_column}[{level}]" for level in levels]
        for row in included:
            level = str(row.get(group_column, ""))
            matrix.append([1.0 if level == item else 0.0 for item in levels])
    elif design_type == "multiple_regression":
        column_names = ["intercept", *[f"{column}_centered" for column in covariates]]
        means: dict[str, float] = {}
        for column in covariates:
            values = [float(row[column]) for row in included if row.get(column, "") != ""]
            if not values:
                raise ValueError(f"COVARIATE_MISSING_VALUES: no numeric values for {column}")
            if float(np.var(values)) == 0.0:
                raise ValueError(f"DESIGN_MATRIX_RANK_DEFICIENT: zero variance covariate {column}")
            means[column] = float(np.mean(values))
        for row in included:
            vector = [1.0]
            for column in covariates:
                if row.get(column, "") == "":
                    raise ValueError(f"COVARIATE_MISSING_VALUES: missing {column}")
                vector.append(float(row[column]) - means[column])
            matrix.append(vector)
    elif design_type == "paired_t":
        paired_levels: list[str] = []
        for row in included:
            level = str(row.get(condition_column, "")).strip()
            if level and level not in paired_levels:
                paired_levels.append(level)
        if len(paired_levels) != 2:
            raise ValueError("PAIRING_INCOMPLETE: paired_t requires exactly two condition/timepoint levels")
        paired_rows: list[dict[str, Any]] = []
        rows_by_pair: dict[str, dict[str, dict[str, Any]]] = {}
        for row in included:
            pair_id = str(row.get(pair_id_column, row.get("participant_id", ""))).strip()
            level = str(row.get(condition_column, "")).strip()
            if not pair_id or not level:
                raise ValueError("PAIRING_INCOMPLETE: missing pair id or condition value")
            rows_by_pair.setdefault(pair_id, {})[level] = row
        for pair_id, level_rows in rows_by_pair.items():
            if set(level_rows) != set(paired_levels):
                raise ValueError(f"PAIRING_INCOMPLETE: pair {pair_id} does not contain both levels")
            first, second = paired_levels
            diff = float(level_rows[second][response_column]) - float(level_rows[first][response_column])
            paired_rows.append(
                {
                    **level_rows[second],
                    "participant_id": pair_id,
                    "paired_difference": diff,
                    "pair_id": pair_id,
                    "source_contrast": f"{second}_minus_{first}",
                    response_column: diff,
                }
            )
        included = paired_rows
        column_names = ["intercept"]
        matrix = [[1.0] for _ in included]
    elif design_type in {"full_factorial", "flexible_factorial"}:
        design_factors = factors or [group_column]
        main_columns, main_matrix, factor_levels = _treatment_factor_columns(included, design_factors)
        interaction_columns, interaction_matrix = _treatment_interaction_columns(
            included,
            design_factors,
            factor_levels,
            max_order=len(design_factors) if design_type == "full_factorial" else int(len(design_factors) >= 2) + 1,
        )
        column_names = ["intercept", *main_columns, *interaction_columns]
        matrix = [
            [1.0, *main_matrix[index], *interaction_matrix[index]]
            for index in range(len(included))
        ]
    elif design_type in {"repeated_measures", "mixed_effects"}:
        design_factors = [*(factors or [group_column]), *within_subject_factors]
        design_factors = list(dict.fromkeys(factor for factor in design_factors if factor))
        main_columns, main_matrix, _factor_levels = _treatment_factor_columns(included, design_factors)
        column_names = ["intercept", *main_columns]
        matrix = [[1.0, *row_values] for row_values in main_matrix]
        for random_effect in random_effects:
            levels = _ordered_levels(included, random_effect)
            if len(levels) <= 1:
                continue
            # Fixed-effect proxy for a random intercept. Drop first level so the
            # intercept remains estimable; keep only rank-increasing columns so
            # nested subjects do not make group designs singular.
            for level in levels[1:]:
                candidate = [1.0 if str(row.get(random_effect, "")) == level else 0.0 for row in included]
                current_rank = int(np.linalg.matrix_rank(np.asarray(matrix, dtype=float)))
                candidate_matrix = [row_values + [candidate[index]] for index, row_values in enumerate(matrix)]
                candidate_rank = int(np.linalg.matrix_rank(np.asarray(candidate_matrix, dtype=float)))
                if candidate_rank > current_rank:
                    column_names.append(f"{random_effect}[{level}]")
                    matrix = candidate_matrix
    else:
        raise ValueError(f"Unsupported group design type: {design_type}")

    if covariates and design_type != "multiple_regression":
        for column in covariates:
            values = [float(row[column]) for row in included if row.get(column, "") != ""]
            if len(values) != len(included):
                raise ValueError(f"COVARIATE_MISSING_VALUES: missing {column}")
            mean = float(np.mean(values))
            column_names.append(f"{column}_centered")
            for index, row in enumerate(included):
                matrix[index].append(float(row[column]) - mean)

    array = np.asarray(matrix, dtype=float)
    rank = int(np.linalg.matrix_rank(array))
    if rank < array.shape[1]:
        raise ValueError("DESIGN_MATRIX_RANK_DEFICIENT: design matrix is not full rank")
    condition_number = float(np.linalg.cond(array)) if array.size else 0.0
    return GroupDesignResult(
        analysis_table=included,
        design_matrix=[
            {column: float(value) for column, value in zip(column_names, row, strict=True)}
            for row in matrix
        ],
        column_names=column_names,
        rank=rank,
        condition_number=condition_number,
    )


def compile_contrast_expression(expression: str, column_names: list[str]) -> list[float]:
    """Compile a simple named-column T contrast expression.

    Supports sums and differences of design columns, optionally with scalar
    coefficients such as ``2 * age_centered - group[control]``.
    """
    expr = expression.strip()
    if not expr:
        raise ValueError("CONTRAST_NOT_ESTIMABLE: empty contrast expression")
    weights = [0.0 for _ in column_names]
    pattern = re.compile(r"([+-]?)\s*(?:(\d+(?:\.\d+)?)\s*\*\s*)?([A-Za-z_][A-Za-z0-9_\[\].:-]*)")
    position = 0
    matched = False
    for match in pattern.finditer(expr):
        skipped = expr[position:match.start()].strip()
        if skipped:
            raise ValueError(f"CONTRAST_NOT_ESTIMABLE: unsupported contrast syntax near '{skipped}'")
        sign_text, scalar_text, name = match.groups()
        if matched and not sign_text:
            raise ValueError(f"CONTRAST_NOT_ESTIMABLE: missing operator before '{name}'")
        if name not in column_names:
            raise ValueError(f"CONTRAST_NOT_ESTIMABLE: unknown design column '{name}'")
        sign = -1.0 if sign_text == "-" else 1.0
        scalar = float(scalar_text) if scalar_text else 1.0
        weights[column_names.index(name)] += sign * scalar
        position = match.end()
        matched = True
    if not matched or expr[position:].strip():
        raise ValueError(f"CONTRAST_NOT_ESTIMABLE: unsupported contrast expression '{expression}'")
    if all(value == 0.0 for value in weights):
        raise ValueError("CONTRAST_NOT_ESTIMABLE: contrast weights are all zero")
    return weights


def default_group_contrasts(design: GroupDesignResult) -> list[GroupContrastSpec]:
    """Create conservative default T contrasts for MVP designs."""
    if len(design.column_names) == 1 and design.column_names[0] == "intercept":
        return [GroupContrastSpec(name="Mean > 0", weights=[1.0], expression="intercept")]
    if len(design.column_names) == 2 and all("[" in column for column in design.column_names):
        left, right = design.column_names
        return [
            GroupContrastSpec(name=f"{right} > {left}", weights=[-1.0, 1.0], expression=f"{right} - {left}"),
            GroupContrastSpec(name=f"{left} > {right}", weights=[1.0, -1.0], expression=f"{left} - {right}"),
        ]
    return [
        GroupContrastSpec(name=column, weights=[1.0 if i == index else 0.0 for i in range(len(design.column_names))])
        for index, column in enumerate(design.column_names)
    ]


def compile_group_contrasts(
    contrast_specs: list[dict[str, Any]],
    column_names: list[str],
) -> list[GroupContrastSpec]:
    compiled: list[GroupContrastSpec] = []
    for index, spec in enumerate(contrast_specs, start=1):
        contrast_type = str(spec.get("type", "T")).upper()
        expression = str(spec.get("expression", "")).strip()
        raw_weights = spec.get("weights")
        raw_matrix = spec.get("weight_matrix")
        if contrast_type == "T":
            if expression:
                weights = compile_contrast_expression(expression, column_names)
            elif isinstance(raw_weights, list):
                weights = [float(value) for value in raw_weights]
                if len(weights) != len(column_names):
                    raise ValueError("CONTRAST_NOT_ESTIMABLE: contrast weight length does not match design columns")
            else:
                raise ValueError("CONTRAST_NOT_ESTIMABLE: T contrast requires expression or weights")
            compiled.append(
                GroupContrastSpec(
                    name=str(spec.get("name") or f"contrast_{index}"),
                    contrast_type="T",
                    weights=weights,
                    expression=expression,
                )
            )
            continue
        if contrast_type == "F":
            matrix: list[list[float]] = []
            raw_terms = spec.get("terms")
            if isinstance(raw_matrix, list):
                for row in raw_matrix:
                    if not isinstance(row, list):
                        raise ValueError("CONTRAST_NOT_ESTIMABLE: F contrast matrix rows must be lists")
                    weights = [float(value) for value in row]
                    if len(weights) != len(column_names):
                        raise ValueError("CONTRAST_NOT_ESTIMABLE: F contrast row length does not match design columns")
                    matrix.append(weights)
            elif isinstance(raw_terms, list):
                for term in raw_terms:
                    prefix = f"{term}["
                    matching = [
                        [1.0 if column == candidate else 0.0 for column in column_names]
                        for candidate in column_names
                        if candidate == term or candidate.startswith(prefix)
                    ]
                    matrix.extend(matching)
            elif expression:
                matrix.append(compile_contrast_expression(expression, column_names))
            else:
                raise ValueError("CONTRAST_NOT_ESTIMABLE: F contrast requires terms, expression, or weight_matrix")
            if not matrix:
                raise ValueError("CONTRAST_NOT_ESTIMABLE: F contrast has no estimable rows")
            compiled.append(
                GroupContrastSpec(
                    name=str(spec.get("name") or f"contrast_{index}"),
                    contrast_type="F",
                    weight_matrix=matrix,
                    expression=expression or ",".join(str(term) for term in raw_terms or []),
                )
            )
            continue
        raise ValueError(f"CONTRAST_NOT_ESTIMABLE: unsupported contrast type {contrast_type}")
    return compiled


def validate_site_group_confound(
    rows: list[dict[str, Any]],
    *,
    group_column: str = "group",
    site_column: str = "site",
) -> bool:
    """Return True when every site maps to exactly one group or vice versa."""
    pairs = {
        (str(row.get(site_column, "")), str(row.get(group_column, "")))
        for row in rows
        if row.get(site_column, "") != "" and row.get(group_column, "") != ""
    }
    if not pairs:
        return False
    groups_by_site: dict[str, set[str]] = {}
    sites_by_group: dict[str, set[str]] = {}
    for site, group in pairs:
        groups_by_site.setdefault(site, set()).add(group)
        sites_by_group.setdefault(group, set()).add(site)
    return all(len(groups) == 1 for groups in groups_by_site.values()) or all(
        len(sites) == 1 for sites in sites_by_group.values()
    )


def validate_subject_split_no_leakage(
    train_subjects: list[str],
    test_subjects: list[str],
) -> None:
    overlap = set(train_subjects) & set(test_subjects)
    if overlap:
        raise ValueError("ML_SUBJECT_LEAKAGE: subjects appear in both train and test: " + ", ".join(sorted(overlap)))


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    order = np.argsort(np.asarray(p_values, dtype=float))
    adjusted = np.empty(len(p_values), dtype=float)
    running = 1.0
    total = len(p_values)
    for rank_index, original_index in enumerate(order[::-1], start=1):
        rank = total - rank_index + 1
        value = min(running, p_values[int(original_index)] * total / rank)
        running = value
        adjusted[int(original_index)] = value
    return [float(min(1.0, value)) for value in adjusted]


def fit_group_glm(
    design: GroupDesignResult,
    *,
    response_column: str = "beta",
    feature_columns: list[str] | None = None,
    contrasts: list[GroupContrastSpec] | None = None,
    correction_method: str = "fdr_bh",
    covariance: str = "ols",
    cluster_column: str = "participant_id",
    permutation_count: int = 0,
    random_seed: int = 0,
    sensitivity_branches: list[dict[str, Any]] | None = None,
) -> GroupGLMResult:
    """Fit feature-wise OLS group models and named T/F contrasts.

    The implementation is intentionally small but auditable: every feature uses
    the same design matrix, repeated run rows should already be subject-averaged,
    and contrast weights are stored alongside design column names.
    """
    from scipy import stats

    feature_columns = feature_columns or ["source_atom_id", "roi", "channel", "source_contrast"]
    contrast_specs = contrasts or default_group_contrasts(design)
    x = np.asarray([[row[column] for column in design.column_names] for row in design.design_matrix], dtype=float)
    rows_by_feature: dict[tuple[str, ...], list[tuple[int, dict[str, Any]]]] = {}
    for index, row in enumerate(design.analysis_table):
        if row.get(response_column, "") == "":
            continue
        key = tuple(str(row.get(column, "")) for column in feature_columns)
        rows_by_feature.setdefault(key, []).append((index, row))

    coefficients: list[dict[str, Any]] = []
    contrast_rows: list[dict[str, Any]] = []
    effect_rows: list[dict[str, Any]] = []
    sensitivity_rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(random_seed)
    for feature_key, indexed_rows in sorted(rows_by_feature.items()):
        indices = [index for index, _ in indexed_rows]
        if len(indices) <= x.shape[1]:
            continue
        y = np.asarray([float(row[response_column]) for _, row in indexed_rows], dtype=float)
        x_feature = x[indices, :]
        beta_hat = np.linalg.pinv(x_feature) @ y
        residuals = y - x_feature @ beta_hat
        rank_x = int(np.linalg.matrix_rank(x_feature))
        df = len(y) - rank_x
        if df <= 0:
            continue
        mse = float((residuals.T @ residuals) / df)
        xtx_inv = np.linalg.pinv(x_feature.T @ x_feature)
        cov_beta = _estimate_cov_beta(
            x_feature,
            residuals,
            mse,
            xtx_inv,
            covariance=covariance,
            cluster_labels=[str(row.get(cluster_column, "")) for _, row in indexed_rows],
        )
        feature = {column: value for column, value in zip(feature_columns, feature_key, strict=True) if value}
        for column, value in zip(design.column_names, beta_hat, strict=True):
            coefficients.append({**feature, "term": column, "estimate": float(value), "degrees_of_freedom": df})
        pooled_sd = float(np.sqrt(mse)) if mse > 0 else 0.0
        for spec in contrast_specs:
            if spec.contrast_type == "F":
                matrix = np.asarray(spec.weight_matrix or [], dtype=float)
                if matrix.ndim != 2 or matrix.shape[1] != x_feature.shape[1]:
                    raise ValueError(f"CONTRAST_NOT_ESTIMABLE: {spec.name} has wrong F contrast shape")
                cbeta = matrix @ beta_hat
                middle = matrix @ cov_beta @ matrix.T
                rank_c = int(np.linalg.matrix_rank(matrix))
                if rank_c <= 0:
                    raise ValueError(f"CONTRAST_NOT_ESTIMABLE: {spec.name} has rank zero")
                f_value = float((cbeta.T @ np.linalg.pinv(middle) @ cbeta) / rank_c)
                p_value = float(stats.f.sf(f_value, rank_c, df))
                permutation_p = _permutation_f_p_value(
                    x_feature,
                    y,
                    matrix,
                    observed=f_value,
                    df=df,
                    n_permutations=permutation_count,
                    rng=rng,
                )
                contrast_rows.append(
                    {
                        **feature,
                        "contrast_name": spec.name,
                        "contrast_type": spec.contrast_type,
                        "contrast_expression": spec.expression,
                        "compiled_weights": json.dumps([[float(item) for item in row] for row in matrix]),
                        "design_column_names": json.dumps(design.column_names),
                        "estimate": "",
                        "standard_error": "",
                        "f_value": f_value,
                        "p_value": p_value,
                        "permutation_p_value": permutation_p,
                        "numerator_degrees_of_freedom": rank_c,
                        "degrees_of_freedom": df,
                        "n_subjects": len(y),
                        "covariance": covariance,
                    }
                )
                effect_rows.append(
                    {
                        **feature,
                        "contrast_name": spec.name,
                        "effect_size_metric": "partial_eta_squared",
                        "effect_size": (f_value * rank_c) / ((f_value * rank_c) + df) if df > 0 else 0.0,
                        "n_subjects": len(y),
                    }
                )
                continue
            if spec.weights is None:
                continue
            weights = np.asarray(spec.weights, dtype=float)
            if weights.shape[0] != x_feature.shape[1]:
                raise ValueError(f"CONTRAST_NOT_ESTIMABLE: {spec.name} has wrong length")
            estimate = float(weights @ beta_hat)
            variance = float(weights @ cov_beta @ weights.T)
            if variance <= 0:
                raise ValueError(f"CONTRAST_NOT_ESTIMABLE: {spec.name} has non-positive variance")
            standard_error = float(np.sqrt(variance))
            t_value = estimate / standard_error
            p_value = float(2.0 * stats.t.sf(abs(t_value), df))
            permutation_p = _permutation_t_p_value(
                x_feature,
                y,
                weights,
                observed=abs(float(t_value)),
                df=df,
                n_permutations=permutation_count,
                rng=rng,
            )
            row = {
                **feature,
                "contrast_name": spec.name,
                "contrast_type": spec.contrast_type,
                "contrast_expression": spec.expression,
                "compiled_weights": json.dumps([float(item) for item in weights]),
                "design_column_names": json.dumps(design.column_names),
                "estimate": estimate,
                "standard_error": standard_error,
                "t_value": float(t_value),
                "p_value": p_value,
                "permutation_p_value": permutation_p,
                "degrees_of_freedom": df,
                "n_subjects": len(y),
                "covariance": covariance,
            }
            contrast_rows.append(row)
            effect_rows.append(
                {
                    **feature,
                    "contrast_name": spec.name,
                    "effect_size_metric": "standardized_contrast",
                    "effect_size": estimate / pooled_sd if pooled_sd > 0 else 0.0,
                    "n_subjects": len(y),
                }
            )
        for branch in sensitivity_branches or []:
            branch_name = str(branch.get("name", "sensitivity"))
            row_filter = branch.get("filter", {})
            if not isinstance(row_filter, dict):
                continue
            kept = [
                row
                for _, row in indexed_rows
                if all(str(row.get(key, "")) == str(value) for key, value in row_filter.items())
            ]
            sensitivity_rows.append(
                {
                    **feature,
                    "branch_name": branch_name,
                    "filter": json.dumps(row_filter, sort_keys=True),
                    "n_subjects": len({str(row.get("participant_id", row.get("subject", ""))) for row in kept}),
                    "n_rows": len(kept),
                    "status": "ready" if len(kept) > x_feature.shape[1] else "underpowered",
                }
            )

    adjusted = _benjamini_hochberg([row["p_value"] for row in contrast_rows]) if correction_method == "fdr_bh" else []
    corrected = [
        {
            **row,
            "correction_method": correction_method,
            "family_scope": "features_x_contrasts",
            "adjusted_p_value": adjusted[index] if adjusted else row["p_value"],
            "permutation_count": permutation_count,
        }
        for index, row in enumerate(contrast_rows)
    ]
    return GroupGLMResult(
        coefficients=coefficients,
        contrasts=contrast_rows,
        effect_sizes=effect_rows,
        corrected=corrected,
        sensitivity=sensitivity_rows,
    )


def _estimate_cov_beta(
    x: np.ndarray,
    residuals: np.ndarray,
    mse: float,
    xtx_inv: np.ndarray,
    *,
    covariance: str,
    cluster_labels: list[str],
) -> np.ndarray:
    covariance = covariance.lower()
    if covariance == "ols":
        return mse * xtx_inv
    if covariance in {"hc0", "heteroscedastic", "robust"}:
        meat: np.ndarray = x.T @ np.diag(residuals ** 2) @ x
        result_robust: np.ndarray = xtx_inv @ meat @ xtx_inv
        return result_robust
    if covariance in {"cluster", "cluster_robust"}:
        clusters = sorted({label for label in cluster_labels if label})
        if len(clusters) <= 1:
            return mse * xtx_inv
        meat = np.zeros((x.shape[1], x.shape[1]), dtype=float)
        for cluster in clusters:
            selector = np.asarray([label == cluster for label in cluster_labels], dtype=bool)
            xg = x[selector, :]
            eg = residuals[selector]
            score: np.ndarray = xg.T @ eg
            meat += np.outer(score, score)
        result_cluster: np.ndarray = xtx_inv @ meat @ xtx_inv
        return result_cluster
    raise ValueError(f"Unsupported covariance estimator: {covariance}")


def _permutation_t_p_value(
    x: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    *,
    observed: float,
    df: int,
    n_permutations: int,
    rng: np.random.Generator,
) -> float | str:
    if n_permutations <= 0:
        return ""
    exceed = 0
    for _ in range(n_permutations):
        shuffled = rng.permutation(y)
        beta = np.linalg.pinv(x) @ shuffled
        residuals = shuffled - x @ beta
        mse = float((residuals.T @ residuals) / df)
        cov_beta = mse * np.linalg.pinv(x.T @ x)
        variance = float(weights @ cov_beta @ weights.T)
        if variance <= 0:
            continue
        statistic = abs(float((weights @ beta) / np.sqrt(variance)))
        if statistic >= observed:
            exceed += 1
    return float((exceed + 1) / (n_permutations + 1))


def _permutation_f_p_value(
    x: np.ndarray,
    y: np.ndarray,
    matrix: np.ndarray,
    *,
    observed: float,
    df: int,
    n_permutations: int,
    rng: np.random.Generator,
) -> float | str:
    if n_permutations <= 0:
        return ""
    rank_c = int(np.linalg.matrix_rank(matrix))
    exceed = 0
    for _ in range(n_permutations):
        shuffled = rng.permutation(y)
        beta = np.linalg.pinv(x) @ shuffled
        residuals = shuffled - x @ beta
        mse = float((residuals.T @ residuals) / df)
        cov_beta = mse * np.linalg.pinv(x.T @ x)
        cbeta = matrix @ beta
        middle = matrix @ cov_beta @ matrix.T
        statistic = float((cbeta.T @ np.linalg.pinv(middle) @ cbeta) / rank_c)
        if statistic >= observed:
            exceed += 1
    return float((exceed + 1) / (n_permutations + 1))


def summarize_cluster_inference(
    contrast_rows: list[dict[str, Any]],
    *,
    alpha: float = 0.05,
    adjacency_column: str = "channel",
) -> list[dict[str, Any]]:
    """Summarize simple feature clusters from significant contrast rows.

    This MVP treats adjacent numeric feature labels as a cluster when available;
    otherwise each significant feature is reported as a singleton cluster. It is
    intentionally auditable and conservative, not a replacement for spatial
    adjacency-aware permutation engines.
    """
    significant = [
        row for row in contrast_rows
        if row.get("p_value", "") != "" and float(row["p_value"]) <= alpha
    ]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in significant:
        key = (
            str(row.get("source_atom_id", "")),
            str(row.get("contrast_name", "")),
            str(row.get("roi", "")),
        )
        grouped.setdefault(key, []).append(row)

    clusters: list[dict[str, Any]] = []
    for (source_atom_id, contrast_name, roi), rows in sorted(grouped.items()):
        sortable: list[tuple[int | None, dict[str, Any]]] = []
        for row in rows:
            label = str(row.get(adjacency_column, ""))
            match = re.search(r"\d+", label)
            sortable.append((int(match.group(0)) if match else None, row))
        sortable.sort(
            key=lambda item: (
                item[0] is None,
                item[0] if item[0] is not None else str(item[1].get(adjacency_column, "")),
            )
        )
        current: list[dict[str, Any]] = []
        previous_index: int | None = None
        for index_value, row in sortable:
            adjacent = index_value is not None and previous_index is not None and index_value == previous_index + 1
            if current and not adjacent:
                clusters.append(_cluster_summary_row(source_atom_id, contrast_name, roi, current, adjacency_column))
                current = []
            current.append(row)
            previous_index = index_value
        if current:
            clusters.append(_cluster_summary_row(source_atom_id, contrast_name, roi, current, adjacency_column))
    return clusters


def _cluster_summary_row(
    source_atom_id: str,
    contrast_name: str,
    roi: str,
    rows: list[dict[str, Any]],
    adjacency_column: str,
) -> dict[str, Any]:
    p_values = [float(row["p_value"]) for row in rows]
    permutation_values = [
        float(row["permutation_p_value"])
        for row in rows
        if row.get("permutation_p_value", "") != ""
    ]
    return {
        "source_atom_id": source_atom_id,
        "contrast_name": contrast_name,
        "roi": roi,
        "cluster_size": len(rows),
        "features": json.dumps([row.get(adjacency_column, "") for row in rows]),
        "min_p_value": min(p_values) if p_values else "",
        "cluster_p_value": min(permutation_values) if permutation_values else min(p_values) if p_values else "",
        "inference_kind": "adjacent_feature_cluster",
    }
