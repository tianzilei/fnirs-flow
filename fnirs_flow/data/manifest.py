"""Data manifest model and writer."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class DataFile(BaseModel):
    path: str
    uri: str = ""
    size_bytes: int = 0
    modified_at: str = ""
    role: str = "raw_snirf"


class DataSource(BaseModel):
    kind: str = ""
    url: str = ""
    doi: str = ""
    citation: str = ""


class SubjectSessionRun(BaseModel):
    subject: str
    session: str = ""
    run: str = ""
    task: str = ""
    path: str = ""
    uri: str = ""
    relative_path: str = ""
    size_bytes: int = 0
    modified_at: str = ""
    source_file_role: str = "raw_snirf"
    events_path: str = ""
    events_uri: str = ""


class MetadataTableReference(BaseModel):
    path: str
    uri: str = ""
    table_kind: str = "participant"
    format: str = "auto"
    id_column: str = "participant_id"
    include_column: str = "include"
    encoding: str = "utf-8-sig"
    delimiter: str = "auto"
    id_normalization: str = "bids_exact"
    size_bytes: int = 0
    modified_at: str = ""
    columns: list[dict[str, str | int | bool]] = Field(default_factory=list)


class DataManifest(BaseModel):
    schema_version: str = "0.1.0"
    dataset_id: str = ""
    source: DataSource = Field(default_factory=DataSource)
    local_root: str = ""
    runtime_local_root: str = Field(default="", exclude=True)
    external_data_uri_prefix: str = ""
    files: list[DataFile] = Field(default_factory=list)
    subject_session_runs: list[SubjectSessionRun] = Field(default_factory=list)
    metadata_tables: list[MetadataTableReference] = Field(default_factory=list)
    access_instructions: str = ""
    license: str = ""
    created_at: str = ""


def write_data_manifest(manifest: DataManifest, outdir: Path) -> Path:
    """Write data_manifest.json to outdir."""
    path = outdir / "data_manifest.json"
    path.write_text(json.dumps(manifest.model_dump(), indent=2), encoding="utf-8")
    return path


def load_data_manifest(path: Path) -> DataManifest:
    """Load a DataManifest from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return DataManifest.model_validate(data)
