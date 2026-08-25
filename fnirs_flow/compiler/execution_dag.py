"""Execution DAG model: the executable representation of a compiled flow.

MethodAtom-first naming:
  - atom_id, atom_type, template_id, operation are the preferred fields.
  - step_id and node_type are accepted only as legacy input aliases.
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

    Legacy input aliases:
      - step_id: same as atom_id
      - node_type: same as atom_type
    """

    atom_id: str
    atom_type: str
    template_id: str | None = None
    operation: str | None = None
    description: str = ""
    reference: str = ""
    tags: list[str] = Field(default_factory=list)
    template_snapshot: dict[str, Any] = Field(default_factory=dict)
    origin: str = "builtin"
    execution_trust_level: str = "builtin_managed"
    security_status: str = "trusted"
    capability_manifest: dict[str, Any] | None = None
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

    @property
    def step_id(self) -> str:
        """Deprecated read-only alias for legacy Python callers."""
        return self.atom_id

    @property
    def node_type(self) -> str:
        """Deprecated read-only alias for legacy Python callers."""
        return self.atom_type


class ExecutionDag(BaseModel):
    schema_version: str = "0.1.0"
    flow_id: str = ""
    atoms: list[DagNode] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
    execution_layers: list[list[str]] = Field(default_factory=list)
    @property
    def nodes(self) -> list[DagNode]:
        """Deprecated read-only alias for legacy Python callers."""
        return self.atoms

    def atom_map(self) -> dict[str, DagNode]:
        """Return the canonical atom map."""
        return {atom.atom_id: atom for atom in self.atoms}
