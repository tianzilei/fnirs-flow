"""Core Flow models: FlowGraph, FlowAtom, FlowEdge, adapters, references.

MethodAtom-first naming convention:
  - FlowAtom       = business-level flow atom instance (legacy alias: FlowNode)
  - AtomPort       = input/output port on a FlowAtom (legacy alias: NodePort)
  - MethodAtomCategory = functional category of a MethodAtom (legacy alias: NodeCategory)
  - ReadinessStatus    = readiness state (legacy alias: NodeStatus)
  - ExecutionStatus    = execution state (new)
  - SecurityStatus     = security state (new)
  - MethodAtomOrigin   = origin of a MethodAtom (legacy alias: NodeOrigin)

GraphNode is reserved for graph implementation layer (React Flow, DAG).

Split status fields:
  - readiness_status: not_configured | configured | needs_attention | ready | blocked
  - execution_status: not_run | queued | running | executed | failed | skipped
  - security_status: trusted | needs_review | quarantined | blocked
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# Import first-class models from atoms.py
from fnirs_flow.flow.atoms import (
    AdapterDefinition,
    AIGenerationMetadata,
    AtomPort,
    AtomReference,
    FlowAtom,
    FlowAtomStateContract,
    MethodAtomCategory,
    MethodAtomOrigin,
)

# ============================================================================
# Backward-compatible re-exports
# ============================================================================
# These aliases ensure existing code continues to work while new code
# can use the MethodAtom-first naming convention.

# Business-level atom instance (DEPRECATED: use FlowAtom)
FlowNode = FlowAtom

# Port on a FlowAtom (DEPRECATED: use AtomPort)
NodePort = AtomPort

# Functional category (DEPRECATED: use MethodAtomCategory)
NodeCategory = MethodAtomCategory

# Origin (DEPRECATED: use MethodAtomOrigin)
NodeOrigin = MethodAtomOrigin


# Legacy status enum - maps to ReadinessStatus for backward compatibility
class NodeStatus(str, Enum):
    """Legacy status enum. DEPRECATED: use ReadinessStatus, ExecutionStatus, or SecurityStatus."""

    NOT_CONFIGURED = "not_configured"
    CONFIGURED = "configured"
    WARNING = "warning"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"
    READY = "ready"
    EXECUTED = "executed"
    FAILED = "failed"


# State contract for a FlowAtom (DEPRECATED: use FlowAtomStateContract)
FlowAtomStateContractAlias = FlowAtomStateContract
NodeStateContract = FlowAtomStateContract

# Reference (DEPRECATED: use AtomReference)
NodeReference = AtomReference


# ============================================================================
# FlowGraph
# ============================================================================


class FlowEdge(BaseModel):
    id: str
    source: str
    target: str
    source_handle: str
    target_handle: str
    adapter_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "0.1.0"


class FlowOrderPolicy(BaseModel):
    """Risk acceptance switches for atom ordering and empty-link handling."""

    allow_order_violations: bool = False
    allow_empty_edges: bool = False


class FlowMetadata(BaseModel):
    created_at: str = ""
    modified_at: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    ai_generation: AIGenerationMetadata | None = None
    order_policy: FlowOrderPolicy = Field(default_factory=FlowOrderPolicy)
    checklist: dict[str, Any] = Field(default_factory=dict)


class FlowGraph(BaseModel):
    schema_version: str = "0.1.0"
    flow_id: str = ""
    name: str = ""
    description: str = ""
    nodes: list[FlowAtom] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)
    adapter_registry: list[AdapterDefinition] = Field(default_factory=list)
    metadata: FlowMetadata = Field(default_factory=FlowMetadata)
    # v0.2 dual-write: flow_atoms mirrors nodes with MethodAtom-first naming
    flow_atoms: list[FlowAtom] | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_atom_collections(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        flow_atoms = result.get("flow_atoms")
        nodes = result.get("nodes")
        if flow_atoms is not None and not nodes:
            result["nodes"] = flow_atoms
        return result

    def node_map(self) -> dict[str, FlowAtom]:
        return {n.id: n for n in self.nodes}

    def edge_map(self) -> dict[str, FlowEdge]:
        return {e.id: e for e in self.edges}

    def get_node(self, node_id: str) -> FlowAtom | None:
        return self.node_map().get(node_id)

    def atom_map(self) -> dict[str, FlowAtom]:
        """MethodAtom-first accessor: returns atoms from flow_atoms if present, else nodes."""
        source = self.flow_atoms if self.flow_atoms is not None else self.nodes
        return {n.id: n for n in source}

    def get_atom(self, atom_id: str) -> FlowAtom | None:
        """MethodAtom-first accessor."""
        return self.atom_map().get(atom_id)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Serialize with flow_atoms dual-write.

        When flow_atoms was not explicitly set, auto-populates it from nodes for v0.2 export.
        """
        result = super().model_dump(**kwargs)
        # Auto-populate flow_atoms from nodes only if not explicitly set by caller
        if "flow_atoms" not in self.model_fields_set and result.get("flow_atoms") is None:
            result["flow_atoms"] = result.get("nodes", [])
        return result
