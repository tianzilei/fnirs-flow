"""Application request/result contracts shared by interface adapters."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from fnirs_flow.validation.models import ReadinessResult


class ProjectCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[a-zA-Z0-9_\- ]+$",
    )
    description: str = Field(default="", max_length=1024)
    data_root: str = Field(default="", max_length=4096)


class ProjectRead(BaseModel):
    id: str
    name: str
    description: str
    data_root: str = ""
    flow_id: str = ""
    package_path: str = ""
    storage_format: str = "fnirsflow_bundle"
    revision: int = 0
    integrity_status: str = "unknown"
    last_verified_at: str | None = None
    verification_scope: str | None = None
    integrity_error: str | None = None
    busy_operation: str | None = None


class ProjectStatus(BaseModel):
    """Authoritative, reload-safe project readiness state."""

    flow_saved: bool = False
    validated: bool = False
    compiled: bool = False
    data_discovered: bool = False
    runnable_runs: int = 0
    executed: bool = False
    flow_revision: int = 0
    compiled_revision: int = 0
    last_attempt_id: str = ""
    last_execution_status: str = ""
    read_only: bool = False
    quarantined_atoms: list[str] = Field(default_factory=list)


class FlowUpdate(BaseModel):
    flow: dict[str, Any] = Field(..., description="Complete flow dict")
    debounce: bool = Field(False, description="Use debounced persist for rapid edits")

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
    revision: int = 0
    steps: int
    layers: int
    output_files: list[str] = Field(default_factory=list)
    dag_layers: list[list[dict[str, str]]] = Field(default_factory=list)
    # MethodAtom-first: atom count and atom types
    atoms: int = 0
    atom_types: list[str] = Field(default_factory=list)


class BackendDescription(BaseModel):
    backend_id: str
    class_path: str
    dependency_profile_id: str | None = None
    display_name: str
    description: str = ""
    is_available: bool
    is_loaded: bool


class DatasetRead(BaseModel):
    dataset_id: str
    name: str
    source_kind: str
    url: str = ""
    doi: str = ""
    citation: str = ""
    license: str = ""
    description: str = ""
    folder_name: str = ""


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
    metadata_tables: int = 0


class ParticipantTableImportRequest(BaseModel):
    path: str
    table_kind: str = Field(default="participant", pattern="^(participant|observation)$")
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
    delimiter: str = "auto"
    encoding: str = "utf-8-sig"


class ParticipantTableImportResult(BaseModel):
    table_kind: str
    rows: int
    columns: list[dict[str, Any]] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    column_role_map: dict[str, Any] = Field(default_factory=dict)
    validation_report: dict[str, Any] = Field(default_factory=dict)
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)


class ProjectSnapshot(BaseModel):
    snapshot_id: str
    revision: int
    created_at: str


class ExportResult(BaseModel):
    package_path: str
    size_bytes: int
    profile: str = "reproducibility_package"
    contents: list[str] = Field(default_factory=list)


class ExportRequest(BaseModel):
    profile: str = "reproducibility_package"
    snapshot_id: str | None = None
    attempt_id: str | None = None
    include_history: bool = False


class ArtifactSummary(BaseModel):
    artifact_id: str = ""
    type: str
    uri: str = ""
    path: str = ""
    resolved_path: str = ""
    relative_path: str = ""
    checksum: str = ""
    exists: bool = False
    atom_id: str = ""
    step_id: str = ""


class AtomResultSummary(BaseModel):
    atom_id: str
    status: str
    output_handles: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


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


class ExecutionJobRead(BaseModel):
    """Persistent state for one execution attempt."""

    attempt_id: str
    project_id: str
    commit_id: str = ""
    snapshot_id: str = ""
    status: str
    created_at: str
    started_at: str = ""
    completed_at: str = ""
    recovery_count: int = 0
    cancel_requested: bool = False
    result: ExecuteResult | None = None
    error: str | None = None


class ProjectLockInfo(BaseModel):
    """Current lock status for a project."""

    project_id: str
    locked: bool = False
    operation: str = ""
    holder_id: str = ""
    acquired_at: str = ""
    cross_process: bool = False


class BundleStatus(BaseModel):
    """Extended bundle status with integrity and lock information."""

    project_id: str
    package_path: str = ""
    storage_format: str = "fnirsflow_bundle"
    revision: int = 0
    saved_at: str = ""
    save_reason: str = ""
    size_bytes: int = 0
    integrity_status: str = "unknown"
    last_verified_at: str | None = None
    verification_scope: str | None = None
    integrity_error: str | None = None
    dirty: bool = False
    busy_operation: str | None = None
    lock_owner: str | None = None
    versions: list[dict[str, Any]] = Field(default_factory=list)


class FolderEntry(BaseModel):
    name: str
    path: str
    has_children: bool


class LocalFolderList(BaseModel):
    current: str = ""
    parent: str = ""
    folders: list[FolderEntry] = Field(default_factory=list)


class ProjectDataFolderList(BaseModel):
    parent: str = ""
    folders: list[FolderEntry] = Field(default_factory=list)


class ExampleFlowSummary(BaseModel):
    id: str
    label: str


class ImportStatus(BaseModel):
    imported: bool
    read_only: bool
    quarantined_atoms: list[str] = Field(default_factory=list)
    relinked: bool = False
    data_root: str = ""
    dataset_id: str = ""


class ResultFile(BaseModel):
    path: str
    data: Any


class ResultFigure(BaseModel):
    path: str
    svg: str


class ProjectResults(BaseModel):
    kind: Literal["qc", "channel", "roi", "group"]
    file_count: int
    files: list[ResultFile] = Field(default_factory=list)
    figures: list[ResultFigure] = Field(default_factory=list)


class PackageProfile(BaseModel):
    profile_id: str
    name: str
    description: str
    include_patterns: list[str] = Field(default_factory=list)


class PortDescription(BaseModel):
    model_config = {"populate_by_name": True}

    name: str
    port_schema: str = Field(alias="schema", serialization_alias="schema")
    required: bool


class OperationContract(BaseModel):
    canonical_operation: str
    execution_scope: str
    capabilities: list[str] = Field(default_factory=list)
    supported_backends: list[str] = Field(default_factory=list)
    handler_backends: list[str] = Field(default_factory=list)
    artifact_contract: dict[str, Any] = Field(default_factory=dict)
    allow_reviewed_noop: bool = False


class AtomTemplate(BaseModel):
    id: str
    atom_type: str
    display_name: str
    category: str
    operation: str
    description: str = ""
    default_config: dict[str, Any] = Field(default_factory=dict)
    parameter_options: dict[str, list[Any]] = Field(default_factory=dict)
    parameter_specs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    default_readiness_status: str = "not_configured"
    default_execution_scope: str = "run"
    input_ports: list[PortDescription] = Field(default_factory=list)
    output_ports: list[PortDescription] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    operation_contract: OperationContract | None = None


class EmptyMarkerSpec(BaseModel):
    category: str
    input_schema: str
    output_schema: str
    label: str
    atom_id: str
    template_id: str


class FlowChecklistStep(BaseModel):
    slot_id: str
    label: str
    required: bool
    recommended_template_ids: list[str] = Field(default_factory=list)
    recommended_atom_types: list[str] = Field(default_factory=list)
    default_template_id: str = ""
    alternative_template_ids: list[str] = Field(default_factory=list)
    input_requirements: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    allow_empty_marker: bool = False
    category: str = ""
    guidance: str = ""


class FlowChecklistSummary(BaseModel):
    scenario_id: str
    label: str
    description: str = ""
    version: str
    step_count: int


class FlowChecklist(BaseModel):
    scenario_id: str
    label: str
    description: str = ""
    version: str
    steps: list[FlowChecklistStep] = Field(default_factory=list)


class HealthStatus(BaseModel):
    status: str
    version: str


class VersionHistoryEntry(BaseModel):
    revision: int
    saved_at: str
    reason: str
    current: bool
    path: str


class CommitIdResponse(BaseModel):
    commit_id: str


class DesignHistoryStatus(BaseModel):
    head: dict[str, Any] | None = None
    branches: list[dict[str, Any]] = Field(default_factory=list)
    dirty: bool = False


class CheckoutResponse(BaseModel):
    flow: dict[str, Any]
    target: str


class HistoryMigrationReport(BaseModel):
    snapshots_imported: int = 0
    snapshots_skipped: int = 0
    revisions_imported: int = 0
    revisions_skipped: int = 0
    objects_deduplicated: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    success: bool


class AIDraftSettings(BaseModel):
    model_config = {"extra": "allow"}

    mode: str = "template"
    provider: str = ""
    base_url: str = ""
    model: str = ""
    organization: str = ""
    project: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout_seconds: float = 60
    api_key_present: bool = False


class GenerateAIDraftRequest(BaseModel):
    scenario: Literal["task", "resting_state", "machine_learning", "real_world", "hyperscanning", "multi_site"]
    study_name: str = ""
    data_format: str = "snirf"
    conditions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    user_confirmations: list[str] = Field(default_factory=list)
    ai_settings: AIDraftSettings | None = None


class AIDraftFlow(BaseModel):
    model_config = {"extra": "allow"}

    flow_id: str
    name: str
    description: str = ""
    flow_atoms: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIDraftEnvelope(BaseModel):
    status: str
    draft: AIDraftFlow


class AIDraftValidation(BaseModel):
    status: str
    flow_id: str
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    readiness: ReadinessResult
