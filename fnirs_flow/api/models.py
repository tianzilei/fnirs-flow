"""API request/response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[a-zA-Z0-9_\- ]+$",
    )
    description: str = Field(default="", max_length=1024)


class ProjectRead(BaseModel):
    id: str
    name: str
    description: str
    flow_id: str = ""


class FlowUpdate(BaseModel):
    flow: dict[str, Any] = Field(..., description="Complete flow dict")

    @field_validator("flow")
    @classmethod
    def validate_flow_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        import json

        size = len(json.dumps(v).encode())
        if size > 1_000_000:  # 1MB limit for flow dict
            raise ValueError(f"Flow dict too large ({size} bytes, max 1MB)")
        return v


class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)


class CompileResult(BaseModel):
    flow_id: str
    flow_hash: str
    steps: int
    layers: int
    output_files: list[str] = Field(default_factory=list)
    # MethodAtom-first: atom count and atom types
    atoms: int = 0
    atom_types: list[str] = Field(default_factory=list)


class DryRunResult(BaseModel):
    total_runs: int
    planned_runs: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class DiscoverResult(BaseModel):
    dataset_id: str
    files: int
    runs: int
    local_root: str
    source_url: str = ""


class ProjectSnapshot(BaseModel):
    snapshot_id: str
    flow_hash: str
    created_at: str


class ExportResult(BaseModel):
    package_path: str
    size_bytes: int


class AtomResultSummary(BaseModel):
    atom_id: str
    status: str
    error: str | None = None


class ArtifactSummary(BaseModel):
    type: str
    path: str = ""
    checksum: str = ""


class RunSummary(BaseModel):
    run_id: str
    status: str
    subject: str = ""
    session: str = ""
    run: str = ""
    started_at: str = ""
    completed_at: str = ""
    atom_results: list[AtomResultSummary] = Field(default_factory=list)
    artifacts: list[ArtifactSummary] = Field(default_factory=list)


class ExecuteResult(BaseModel):
    attempt_id: str = ""
    total_runs: int
    successful: int
    failed: int
    runs: list[RunSummary] = Field(default_factory=list)
    failure_ids: list[str] = Field(default_factory=list)
