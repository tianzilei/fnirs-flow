"""Node library: manages reusable MethodAtom templates for the Flow canvas.

MethodAtom-first naming:
  - MethodAtomTemplate = template for creating FlowAtoms (legacy alias: NodeTemplate)
  - MethodAtomLibrary  = registry of MethodAtom templates (legacy alias: NodeLibrary)
  - create_atom()      = create a FlowAtom from a template (legacy: create_node())
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fnirs_flow.flow.atoms import (
    AtomPort,
    BackendBinding,
    ExecutableTrustLevel,
    FlowAtom,
    MethodAtomCategory,
    MethodAtomOrigin,
    Position,
    ReadinessStatus,
)


class MethodAtomTemplate(BaseModel):
    """Template for creating FlowAtoms."""

    template_id: str
    name: str
    category: MethodAtomCategory
    atom_type: str
    operation: str | None = None
    description: str = ""
    default_config: dict[str, Any] = Field(default_factory=dict)
    ports: list[AtomPort] = Field(default_factory=list)
    origin: MethodAtomOrigin = MethodAtomOrigin.BUILTIN
    evidence_refs: list[str] = Field(default_factory=list)
    reference: str = ""
    tags: list[str] = Field(default_factory=list)
    backend_binding: BackendBinding | None = None
    # Dependency declaration (§4.2 of design document)
    dependency_profile_id: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    dependency_optional: bool = False

    @property
    def node_id(self) -> str:
        """Backward-compatible template identifier alias."""
        return self.template_id

    @property
    def display_name(self) -> str:
        """Backward-compatible display label alias."""
        return self.name

    @property
    def input_ports(self) -> list[AtomPort]:
        """Backward-compatible accessor for input ports."""
        return [p for p in self.ports if p.direction == "in"]

    @property
    def output_ports(self) -> list[AtomPort]:
        """Backward-compatible accessor for output ports."""
        return [p for p in self.ports if p.direction == "out"]

    def matches_tags(self, tags: list[str]) -> bool:
        """Check if template matches any of the given tags."""
        return any(tag in self.tags for tag in tags)


class MethodAtomLibrary:
    """Registry of MethodAtom templates with extensibility support."""

    def __init__(self) -> None:
        self._templates: dict[str, MethodAtomTemplate] = {}

    def register(self, template: MethodAtomTemplate) -> None:
        """Register a MethodAtom template."""
        self._templates[template.template_id] = template

    def register_many(self, templates: list[MethodAtomTemplate]) -> int:
        """Register multiple templates. Returns count registered."""
        for t in templates:
            self.register(t)
        return len(templates)

    def get(self, template_id: str) -> MethodAtomTemplate | None:
        """Get a template by ID."""
        return self._templates.get(template_id)

    def by_category(self, category: MethodAtomCategory) -> list[MethodAtomTemplate]:
        """Get all templates in a category."""
        return [t for t in self._templates.values() if t.category == category]

    def by_tags(self, tags: list[str]) -> list[MethodAtomTemplate]:
        """Get templates matching any of the given tags."""
        return [t for t in self._templates.values() if t.matches_tags(tags)]

    def all_ids(self) -> list[str]:
        """Get all template IDs."""
        return sorted(self._templates.keys())

    def all(self) -> list[MethodAtomTemplate]:
        """Get all templates."""
        return list(self._templates.values())

    def create_atom(
        self,
        template_id: str,
        atom_id: str | None = None,
        position: Position | None = None,
        config_override: dict[str, Any] | None = None,
    ) -> FlowAtom | None:
        """Create a FlowAtom from a template.

        Args:
            template_id: Template ID to use
            atom_id: Optional custom atom ID (default: template_type-uuid)
            position: Optional position on canvas
            config_override: Optional config overrides

        Returns:
            FlowAtom or None if template not found
        """
        template = self._templates.get(template_id)
        if template is None:
            return None

        # Merge config
        config = dict(template.default_config)
        if config_override:
            config.update(config_override)

        # Generate atom ID
        import uuid

        if atom_id is None:
            atom_id = f"{template.atom_type}-{uuid.uuid4().hex[:8]}"

        readiness_value = config.get("readiness_status", ReadinessStatus.NOT_CONFIGURED.value)
        try:
            readiness_status = ReadinessStatus(readiness_value)
        except ValueError:
            readiness_status = ReadinessStatus.NOT_CONFIGURED

        return FlowAtom(
            id=atom_id,
            type=template.atom_type,
            atom_type=template.atom_type,
            template_id=template.template_id,
            operation=template.operation or config.get("operation"),
            evidence_refs=list(template.evidence_refs),
            category=template.category,
            origin=template.origin,
            position=position or Position(),
            config=config,
            ports=[p.model_copy() for p in template.ports],
            backend_binding=(template.backend_binding.model_copy(deep=True) if template.backend_binding else None),
            dependency_profile_id=template.dependency_profile_id,
            required_capabilities=set(template.required_capabilities),
            dependency_optional=template.dependency_optional,
            execution_trust_level=ExecutableTrustLevel.BUILTIN_MANAGED,
            readiness_status=readiness_status,
        )

    def load_from_file(self, filepath: str | Path) -> int:
        """Load templates from a JSON file.

        Args:
            filepath: Path to JSON file with template definitions

        Returns:
            Number of templates loaded
        """
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        templates = data if isinstance(data, list) else data.get("templates", [])
        count = 0
        for t_data in templates:
            try:
                template = MethodAtomTemplate.model_validate(t_data)
                self.register(template)
                count += 1
            except (ValueError, KeyError):
                continue

        return count

    def export_to_file(self, filepath: str | Path) -> int:
        """Export all templates to a JSON file.

        Args:
            filepath: Path to write JSON file

        Returns:
            Number of templates exported
        """
        templates = [t.model_dump() for t in self._templates.values()]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"templates": templates}, f, indent=2)
        return len(templates)


def create_builtin_library() -> MethodAtomLibrary:
    """Create a MethodAtomLibrary with all built-in templates."""
    from fnirs_flow.registry.atom_templates import ALL_METHOD_ATOM_TEMPLATES

    library = MethodAtomLibrary()
    library.register_many(ALL_METHOD_ATOM_TEMPLATES)
    return library


# ============================================================================
# Backward-compatible aliases
# ============================================================================
# DEPRECATED: Use MethodAtomTemplate and MethodAtomLibrary in new code.
# The old names (NodeTemplate, NodeLibrary) are kept for backward compatibility.

NodeTemplate = MethodAtomTemplate
NodeLibrary = MethodAtomLibrary
