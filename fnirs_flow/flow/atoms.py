"""First-class MethodAtom models for the fNIRS flow system.

This module provides the MethodAtom-first model definitions:
  - MethodAtomCategory: functional category of a MethodAtom
  - MethodAtomStatus: status of a FlowAtom (readiness/execution/security split)
  - MethodAtomOrigin: origin of a MethodAtom
  - AtomPort: input/output port on a FlowAtom
  - FlowAtom: business-level flow atom instance
  - FlowAtomStateContract: state contract for a FlowAtom
  - BoundaryContract: boundary condition contract

Legacy class names (NodeCategory, NodeStatus, NodeOrigin, NodePort, FlowNode,
NodeStateContract) are re-exported as backward-compatible aliases.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

CONTROL_CONFIG_KEYS = {
    "source_kind",
    "readiness_status",
    "execution_scope",
}

PROVENANCE_CONFIG_KEYS = {
    "source_atom_id",
    "source_study_id",
    "target_flow_slot",
    "scenario",
    "execution_readiness",
    "missing_for_execution",
    "confidence",
    "review_required",
    "verification_status",
    "parameter_candidates",
    "parameter_status",
    "method_note",
    "accuracy_caveat",
}

NON_USER_CONFIG_KEYS = CONTROL_CONFIG_KEYS | PROVENANCE_CONFIG_KEYS

# ============================================================================
# Enums
# ============================================================================


class MethodAtomCategory(str, Enum):
    """Functional category of a MethodAtom."""

    DATA = "data"
    DESIGN = "design"
    PREPROCESSING = "preprocessing"
    ANALYSIS = "analysis"
    OUTPUT = "output"
    VALIDATION = "validation"
    EXPORT = "export"


class MethodAtomOrigin(str, Enum):
    """Origin of a MethodAtom."""

    BUILTIN = "builtin"
    EVIDENCE_DERIVED = "evidence_derived"
    USER_CREATED = "user_created"
    IMPORTED = "imported"


class ReadinessStatus(str, Enum):
    """Readiness/configuration state of a MethodAtom."""

    NOT_CONFIGURED = "not_configured"
    CONFIGURED = "configured"
    NEEDS_ATTENTION = "needs_attention"
    READY = "ready"
    BLOCKED = "blocked"


class ExecutionStatus(str, Enum):
    """Execution state of a MethodAtom."""

    NOT_RUN = "not_run"
    QUEUED = "queued"
    RUNNING = "running"
    EXECUTED = "executed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SecurityStatus(str, Enum):
    """Security/trust state of a MethodAtom."""

    TRUSTED = "trusted"
    NEEDS_REVIEW = "needs_review"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"


class ExecutableTrustLevel(str, Enum):
    """Trust level for executable MethodAtoms."""

    BUILTIN_MANAGED = "builtin_managed"
    BACKEND_MANAGED = "backend_managed"
    PROJECT_CUSTOM = "project_custom"
    IMPORTED_CUSTOM = "imported_custom"


# ============================================================================
# Core Models
# ============================================================================


class BoundaryContract(BaseModel):
    """Boundary condition contract for port ingress/egress."""

    allowed_statuses: list[ReadinessStatus] = Field(default_factory=list)
    blocked_statuses: list[ReadinessStatus] = Field(default_factory=list)
    required_config_keys: list[str] = Field(default_factory=list)
    required_metadata_keys: list[str] = Field(default_factory=list)


class FlowAtomStateContract(BaseModel):
    """State contract for a FlowAtom."""

    ingress: BoundaryContract = Field(default_factory=BoundaryContract)
    egress: BoundaryContract = Field(default_factory=BoundaryContract)
    post_readiness_status: ReadinessStatus | None = None
    post_execution_status: ExecutionStatus | None = None


class AdapterStateContract(BaseModel):
    """State contract for an adapter between atoms."""

    ingress: BoundaryContract = Field(default_factory=BoundaryContract)
    egress: BoundaryContract = Field(default_factory=BoundaryContract)
    post_source_readiness: ReadinessStatus | None = None
    post_target_readiness: ReadinessStatus | None = None


class Position(BaseModel):
    """Position on the flow canvas."""

    x: float = 0.0
    y: float = 0.0


class AtomPort(BaseModel):
    """Input/output port on a FlowAtom."""

    name: str
    direction: str = Field(pattern="^(in|out)$")
    port_schema: str = Field(alias="schema")
    required: bool = True
    default: Any = None
    contract: BoundaryContract = Field(default_factory=BoundaryContract)

    model_config = {"populate_by_name": True}


class AtomReference(BaseModel):
    """Reference to external source or documentation."""

    source_project: str = ""
    source_file: str = ""
    license: str = ""
    divergence_reason: str = ""
    reuse_mode: str = Field(default="builtin", pattern="^(adapt|wrap|inspire|builtin)$")


class CapabilityManifest(BaseModel):
    """Capability manifest for a FlowAtom."""

    allowed_operations: list[str] = Field(default_factory=list)
    file_access: list[str] = Field(default_factory=list)
    network: bool = False
    shell: bool = False
    dependencies: list[str] = Field(default_factory=list)


class AIGenerationMetadata(BaseModel):
    """Metadata for AI-generated flow drafts.

    Attached to FlowMetadata.ai_generation when a flow was produced
    by a generative AI system. Human-created flows leave this as None.
    """

    generated_by: str = "generative_ai"
    model: str = "unspecified"
    created_at: str = ""
    input_summary: str = ""
    assumptions: list[str] = Field(default_factory=list)
    requires_user_confirmation: list[str] = Field(default_factory=list)
    confirmed_parameters: list[str] = Field(default_factory=list)
    confirmed_by: str = ""
    confirmed_at: str = ""
    not_used_for_execution: bool = True

    @property
    def pending_confirmations(self) -> list[str]:
        """Return required confirmation items not explicitly approved by a human."""
        confirmed = set(self.confirmed_parameters)
        return [item for item in self.requires_user_confirmation if item not in confirmed]


class AdapterDefinition(BaseModel):
    """Definition of an adapter between atoms."""

    adapter_id: str
    name: str
    source_type: str
    target_type: str
    transform: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    state_contract: AdapterStateContract = Field(default_factory=AdapterStateContract)
    reference: AtomReference | None = None


class AdapterInstance(BaseModel):
    """Instance of an adapter binding."""

    definition_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class BackendBinding(BaseModel):
    """Binding to an execution backend."""

    backend_id: str
    operation: str = ""
    version_spec: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Dependency profile reference (MethodAtom-first dependency management)
    dependency_profile_id: str | None = None
    required_capabilities: set[str] = Field(default_factory=set)


class FlowAtom(BaseModel):
    """Business-level flow atom instance.

    This is the primary MethodAtom-first model. Legacy code should use
    the FlowNode alias in models.py for backward compatibility.
    """

    id: str
    atom_type: str
    template_id: str | None = None
    operation: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    category: MethodAtomCategory
    origin: MethodAtomOrigin = MethodAtomOrigin.BUILTIN
    position: Position = Field(default_factory=Position)
    config: dict[str, Any] = Field(default_factory=dict)
    ports: list[AtomPort] = Field(default_factory=list)
    adapter_bindings: list[AdapterInstance] = Field(default_factory=list)
    backend_binding: BackendBinding | None = None
    # Dependency declaration (MethodAtom-first dependency management)
    dependency_profile_id: str | None = None
    required_capabilities: set[str] = Field(default_factory=set)
    dependency_optional: bool = False
    execution_scope: str = Field(default="run", pattern="^(run|subject|group|project)$")
    references: list[AtomReference] = Field(default_factory=list)
    execution_trust_level: ExecutableTrustLevel = ExecutableTrustLevel.BUILTIN_MANAGED
    capability_manifest: CapabilityManifest | None = None
    # Split status fields (MethodAtom-first)
    readiness_status: ReadinessStatus = ReadinessStatus.NOT_CONFIGURED
    execution_status: ExecutionStatus = ExecutionStatus.NOT_RUN
    security_status: SecurityStatus = SecurityStatus.TRUSTED
    state_contract: FlowAtomStateContract = Field(default_factory=FlowAtomStateContract)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_method_atom_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        config = result.get("config")
        if isinstance(config, dict):
            clean_config = dict(config)
            metadata = dict(result.get("metadata") or {})
            if "readiness_status" in clean_config and "readiness_status" not in result:
                result["readiness_status"] = clean_config.pop("readiness_status")
            else:
                clean_config.pop("readiness_status", None)
            if "execution_scope" in clean_config and "execution_scope" not in result:
                result["execution_scope"] = clean_config.pop("execution_scope")
            else:
                clean_config.pop("execution_scope", None)
            clean_config.pop("source_kind", None)
            for key in PROVENANCE_CONFIG_KEYS:
                if key in clean_config:
                    metadata.setdefault(key, clean_config.pop(key))
            result["config"] = clean_config
            if metadata:
                result["metadata"] = metadata
        return result

    @model_validator(mode="after")
    def _sync_method_atom_metadata(self) -> FlowAtom:
        if self.template_id is None and "template_id" in self.metadata:
            self.template_id = self.metadata.get("template_id")
        elif self.template_id is not None:
            self.metadata.setdefault("template_id", self.template_id)
        if self.operation is None:
            self.operation = self.config.get("operation")
        if not self.evidence_refs and "evidence_refs" in self.metadata:
            self.evidence_refs = list(self.metadata.get("evidence_refs", []))
        elif self.evidence_refs:
            self.metadata.setdefault("evidence_refs", list(self.evidence_refs))
        return self

    @property
    def type(self) -> str:
        """Deprecated read-only alias for legacy Python callers."""
        return self.atom_type
