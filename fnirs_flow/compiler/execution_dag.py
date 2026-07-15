"""Execution DAG model: the executable representation of a compiled flow.

MethodAtom-first naming:
  - atom_id, atom_type, template_id, operation are the preferred fields.
  - step_id, node_type are retained for backward compatibility.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DagNode(BaseModel):
    """A single step in the execution DAG.

    MethodAtom-first fields (preferred):
      - atom_id: unique atom identifier
      - atom_type: method atom type (e.g. optical_density)
      - template_id: source MethodAtomTemplate ID
      - operation: the specific operation this atom performs

    Legacy fields (kept for backward compatibility):
      - step_id: same as atom_id
      - node_type: same as atom_type
    """

    step_id: str
    node_type: str
    # MethodAtom-first dual-write fields
    atom_id: str | None = None
    atom_type: str | None = None
    template_id: str | None = None
    operation: str | None = None
    category: str = ""
    execution_scope: str = "run"
    adapter_id: str | None = None
    backend_id: str | None = None
    backend_operation: str | None = None
    backend_version_spec: str | None = None
    # Dependency declaration (MethodAtom-first dependency management)
    dependency_profile_id: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    dependency_optional: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_sources: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        """Auto-sync legacy fields if atom fields are set."""
        if self.atom_id is None and self.step_id:
            self.atom_id = self.step_id
        if self.atom_type is None and self.node_type:
            self.atom_type = self.node_type


class ExecutionDag(BaseModel):
    schema_version: str = "0.1.0"
    flow_id: str = ""
    flow_hash: str = ""
    nodes: list[DagNode] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
    execution_layers: list[list[str]] = Field(default_factory=list)
    # v0.2 dual-write: atoms mirrors nodes with MethodAtom-first naming
    atoms: list[DagNode] | None = None

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Serialize with atoms dual-write."""
        result = super().model_dump(**kwargs)
        if result.get("atoms") is None:
            result["atoms"] = result.get("nodes", [])
        return result

    def atom_map(self) -> dict[str, DagNode]:
        """MethodAtom-first accessor: returns atoms if present, else nodes."""
        source = self.atoms if self.atoms is not None else self.nodes
        return {n.atom_id or n.step_id: n for n in source}
