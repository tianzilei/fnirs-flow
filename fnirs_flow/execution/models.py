"""Request and result contracts for execution orchestration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class AtomExecutionResult(BaseModel):
    """Result of executing a single atom/operation."""

    atom_id: str
    status: str = "pending"
    output_handles: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class RunExecutionResult(BaseModel):
    """Result of executing all atoms for a single run.

    ``planned_steps`` describes the run-scoped DAG contract, while the
    completed/failed/skipped fields describe what actually happened.  The
    failure fields are intentionally separate from ``status`` so archived
    execution summaries remain diagnosable without opening atom manifests.
    """

    run_id: str
    status: str = "pending"
    planned_steps: list[str] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    failed_step: str = ""
    failed_error_code: str = ""
    failed_error: str = ""
    skipped_steps: list[str] = Field(default_factory=list)
    atom_results: list[AtomExecutionResult] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    roi_results: list[dict[str, Any]] = Field(default_factory=list)
    channel_results: list[dict[str, Any]] = Field(default_factory=list)
    qc_summary: dict[str, Any] = Field(default_factory=dict)
    started_at: str = ""
    completed_at: str = ""


class ExecutionResult(BaseModel):
    """Unified execution result returned by the orchestrator."""

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
    concurrency: dict[str, Any] = Field(default_factory=dict)
