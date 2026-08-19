"""Participant/observation table IO, validation, joins, and projections."""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from fnirs_flow.data.manifest import DataManifest

__all__ = [
    "ColumnRoleMap",
    "ObservationTable",
    "ParticipantJoinPreview",
    "ParticipantTable",
    "ParticipantTableBundle",
    "TableColumn",
    "TableFileReference",
    "TableValidationReport",
    "join_participant_metadata",
    "load_participant_table_from_artifacts",
    "manifest_subject_ids",
    "project_combat_manifest",
    "project_covariate_matrix",
    "project_dpf_inputs",
    "project_dyad_structure",
    "project_label_vector",
    "project_outcome_vector",
    "project_pairing_structure",
    "project_site_metadata",
    "read_participant_table",
    "validate_participant_table",
    "write_participant_table_artifacts",
]

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
    size_bytes: int = 0
    modified_at: str = ""


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

ALLOWED_PARTICIPANT_TABLE_SUFFIXES = {".csv", ".tsv", ".txt"}
MAX_PARTICIPANT_TABLE_BYTES = 10 * 1024**2
MAX_PARTICIPANT_TABLE_ROWS = 100_000
MAX_PARTICIPANT_TABLE_COLUMNS = 256


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
    max_bytes: int = MAX_PARTICIPANT_TABLE_BYTES,
    max_rows: int = MAX_PARTICIPANT_TABLE_ROWS,
    max_columns: int = MAX_PARTICIPANT_TABLE_COLUMNS,
) -> ParticipantTable:
    """Read a CSV/TSV participant or observation table with provenance."""
    table_path = Path(path)
    suffix = table_path.suffix.lower()
    if suffix not in ALLOWED_PARTICIPANT_TABLE_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_PARTICIPANT_TABLE_SUFFIXES))
        raise ValueError(f"Participant table must be one of: {allowed}")
    size_bytes = table_path.stat().st_size
    if size_bytes > max_bytes:
        raise ValueError(
            f"Participant table is too large ({size_bytes} bytes, max {max_bytes} bytes)"
        )
    actual_delimiter = detect_delimiter(table_path, encoding=encoding, requested=delimiter)
    with table_path.open(newline="", encoding=encoding) as stream:
        reader = csv.DictReader(stream, delimiter=actual_delimiter)
        fieldnames = list(reader.fieldnames or [])
        if len(fieldnames) > max_columns:
            raise ValueError(
                f"Participant table has too many columns ({len(fieldnames)}, max {max_columns})"
            )
        rows = []
        for index, row in enumerate(reader, start=1):
            if index > max_rows:
                raise ValueError(
                    f"Participant table has too many rows (max {max_rows})"
                )
            rows.append({key: _coerce_cell(value or "") for key, value in row.items()})

    roles = column_role_map or ColumnRoleMap(id_column=id_column, include_column=include_column)
    source = TableFileReference(
        path=table_path.name,
        format=table_path.suffix.lower().lstrip(".") or "csv",
        id_column=roles.id_column,
        include_column=roles.include_column,
        encoding=encoding,
        delimiter="tab" if actual_delimiter == "\t" else actual_delimiter,
        size_bytes=size_bytes,
        modified_at=datetime.fromtimestamp(
            table_path.stat().st_mtime, timezone.utc
        ).isoformat(),
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
