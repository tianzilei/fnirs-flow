"""Node library: manages reusable MethodAtom templates for the Flow canvas.

MethodAtom-first naming:
  - MethodAtomTemplate = template for creating FlowAtoms (legacy alias: NodeTemplate)
  - MethodAtomLibrary  = registry of MethodAtom templates (legacy alias: NodeLibrary)
  - create_atom()      = create a FlowAtom from a template (legacy: create_node())
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from fnirs_flow.flow.atoms import (
    NON_USER_CONFIG_KEYS,
    PROVENANCE_CONFIG_KEYS,
    AtomPort,
    BackendBinding,
    CapabilityManifest,
    ExecutableTrustLevel,
    FlowAtom,
    MethodAtomCategory,
    MethodAtomOrigin,
    Position,
    ReadinessStatus,
    SecurityStatus,
)


def _split_non_user_config(
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str | None, str | None]:
    editable_config = dict(config)
    metadata: dict[str, Any] = {}
    readiness_status = editable_config.pop("readiness_status", None)
    execution_scope = editable_config.pop("execution_scope", None)
    for key in NON_USER_CONFIG_KEYS - PROVENANCE_CONFIG_KEYS - {"readiness_status", "execution_scope"}:
        editable_config.pop(key, None)
    for key in PROVENANCE_CONFIG_KEYS:
        if key in editable_config:
            metadata[key] = editable_config.pop(key)
    return (
        editable_config,
        metadata,
        str(readiness_status) if readiness_status not in (None, "") else None,
        str(execution_scope) if execution_scope not in (None, "") else None,
    )


def _portable_template_record(template: MethodAtomTemplate) -> tuple[dict[str, Any], dict[str, Any]]:
    """Remove machine-local source locations before a template enters a Flow."""
    snapshot = template.model_dump(mode="json", by_alias=True, exclude_none=True)
    metadata = dict(template.metadata)
    for record in (metadata, snapshot.get("metadata", {})):
        if isinstance(record, dict) and record.get("local_atom_file"):
            record["local_atom_file"] = Path(str(record["local_atom_file"])).name
    return snapshot, metadata


class MethodAtomTemplate(BaseModel):
    """Template for creating FlowAtoms."""

    template_id: str
    name: str
    category: MethodAtomCategory
    atom_type: str
    operation: str | None = None
    description: str = ""
    default_config: dict[str, Any] = Field(default_factory=dict)
    parameter_options: dict[str, list[Any]] = Field(default_factory=dict)
    parameter_specs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    default_readiness_status: ReadinessStatus | None = None
    default_execution_scope: str | None = Field(default=None, pattern="^(run|subject|group|project)$")
    metadata: dict[str, Any] = Field(default_factory=dict)
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
    implementation_module: str | None = None
    implementation_callable: str | None = None
    implementation_status: str = Field(
        default="managed",
        pattern="^(managed|implemented|delegated|dependency_gated|contract_test_required|metadata_only)$",
    )
    capability_manifest: CapabilityManifest | None = None

    @model_validator(mode="after")
    def _move_non_user_defaults_out_of_config(self) -> MethodAtomTemplate:
        config, metadata, readiness_status, execution_scope = _split_non_user_config(self.default_config)
        self.default_config = config
        self.metadata = {**metadata, **self.metadata}
        if self.default_readiness_status is None and readiness_status:
            try:
                self.default_readiness_status = ReadinessStatus(readiness_status)
            except ValueError:
                self.metadata.setdefault("invalid_readiness_status", readiness_status)
        if self.default_execution_scope is None and execution_scope:
            self.default_execution_scope = execution_scope
        return self

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
        if template.template_id in self._templates:
            raise ValueError(f"Duplicate MethodAtom template id: {template.template_id}")
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
        metadata = dict(template.metadata)
        readiness_value = (
            template.default_readiness_status.value
            if template.default_readiness_status is not None
            else ReadinessStatus.NOT_CONFIGURED.value
        )
        execution_scope = template.default_execution_scope or "run"
        if config_override:
            (
                override_config,
                override_metadata,
                override_readiness,
                override_scope,
            ) = _split_non_user_config(config_override)
            config.update(override_config)
            metadata.update(override_metadata)
            if override_readiness:
                readiness_value = override_readiness
            if override_scope:
                execution_scope = override_scope

        # Generate atom ID
        import uuid

        if atom_id is None:
            atom_id = f"{template.atom_type}-{uuid.uuid4().hex[:8]}"

        try:
            readiness_status = ReadinessStatus(readiness_value)
        except ValueError:
            readiness_status = ReadinessStatus.NOT_CONFIGURED

        execution_trust_level = (
            ExecutableTrustLevel.IMPORTED_CUSTOM
            if template.origin == MethodAtomOrigin.IMPORTED
            else ExecutableTrustLevel.BUILTIN_MANAGED
        )
        security_status = (
            SecurityStatus.QUARANTINED
            if template.origin == MethodAtomOrigin.IMPORTED
            else SecurityStatus.TRUSTED
        )
        template_snapshot, metadata = _portable_template_record(template)
        return FlowAtom(
            id=atom_id,
            atom_type=template.atom_type,
            template_id=template.template_id,
            operation=template.operation or config.get("operation"),
            description=template.description,
            reference=template.reference,
            tags=list(template.tags),
            template_snapshot=template_snapshot,
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
            execution_scope=execution_scope,
            execution_trust_level=execution_trust_level,
            security_status=security_status,
            capability_manifest=(
                template.capability_manifest.model_copy(deep=True)
                if template.capability_manifest
                else None
            ),
            readiness_status=readiness_status,
            metadata=metadata,
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


def discover_method_atom_templates(namespace: dict[str, Any]) -> list[MethodAtomTemplate]:
    """Discover declared templates in definition order and reject ID collisions.

    Keeping discovery here makes module-level template declarations self-registering:
    adding a ``MethodAtomTemplate`` constant is enough to include it in the built-in
    registry. Container values such as ``ALL_NODE_TEMPLATES`` are intentionally
    ignored, so discovery cannot register the same objects a second time.
    """
    templates: list[MethodAtomTemplate] = []
    names_by_id: dict[str, str] = {}
    object_ids: set[int] = set()
    for name, value in namespace.items():
        if not isinstance(value, MethodAtomTemplate) or id(value) in object_ids:
            continue
        previous_name = names_by_id.get(value.template_id)
        if previous_name is not None:
            raise ValueError(
                "Duplicate MethodAtom template id "
                f"{value.template_id!r} declared as {previous_name} and {name}"
            )
        names_by_id[value.template_id] = name
        object_ids.add(id(value))
        templates.append(value)
    return templates


def create_builtin_library() -> MethodAtomLibrary:
    """Create a MethodAtomLibrary with all built-in templates."""
    atom_templates = importlib.import_module("fnirs_flow.registry.atom_templates")
    atom_templates.refresh_method_atom_templates()
    library = MethodAtomLibrary()
    library.register_many(atom_templates.ALL_METHOD_ATOM_TEMPLATES)
    return library


# ============================================================================
# Backward-compatible aliases
# ============================================================================
# DEPRECATED: Use MethodAtomTemplate and MethodAtomLibrary in new code.
# The old names (NodeTemplate, NodeLibrary) are kept for backward compatibility.

NodeTemplate = MethodAtomTemplate
NodeLibrary = MethodAtomLibrary
