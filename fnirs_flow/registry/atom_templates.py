"""MethodAtom templates: the MethodAtom-first interface to node templates.

This module re-exports all built-in templates from node_templates.py
with MethodAtom-first naming. New code should import from this module.

Legacy imports from fnirs_flow.registry.node_templates continue to work
but are discouraged for new code.
"""

from __future__ import annotations

from fnirs_flow.registry import methodatom_library
from fnirs_flow.registry.node_library import MethodAtomLibrary, MethodAtomTemplate

# Re-export all templates with MethodAtom-first naming
from fnirs_flow.registry.node_templates import (
    ALL_NODE_TEMPLATES as ALL_ATOM_TEMPLATES,
)
from fnirs_flow.settings import settings

HANDWRITTEN_ATOM_TEMPLATES = list(ALL_ATOM_TEMPLATES)
LITERATURE_METHOD_ATOM_TEMPLATES = methodatom_library.LITERATURE_METHOD_ATOM_TEMPLATES
ALL_ATOM_TEMPLATES = [*HANDWRITTEN_ATOM_TEMPLATES, *LITERATURE_METHOD_ATOM_TEMPLATES]

# Aliases for clarity
ALL_METHOD_ATOM_TEMPLATES = ALL_ATOM_TEMPLATES
LOCAL_METHOD_ATOM_TEMPLATES: list[MethodAtomTemplate] = []
_LOCAL_LIBRARY_STATE: dict[str, object] | None = None


def _merge_compatible_operation_templates(
    templates: list[MethodAtomTemplate],
) -> tuple[list[MethodAtomTemplate], dict[str, str]]:
    """Fold evidence variants into canonical templates without losing evidence.

    Only same-category, same-operation templates without backend bindings are
    merged. Backend-specific templates remain separate because selecting a
    backend is executable policy, not a presentation duplicate.
    """
    consolidated: list[MethodAtomTemplate] = []
    canonical_by_operation: dict[tuple[str, object], int] = {}
    merged_ids: dict[str, str] = {}
    for source in templates:
        template = source.model_copy(deep=True)
        operation = str(template.operation or template.atom_type)
        key = (operation, template.category)
        canonical_index = canonical_by_operation.get(key)
        if canonical_index is None or template.backend_binding is not None:
            canonical_by_operation.setdefault(key, len(consolidated))
            consolidated.append(template)
            continue
        canonical = consolidated[canonical_index]
        if canonical.backend_binding is not None:
            consolidated.append(template)
            continue
        # Different port contracts or executable defaults are distinct atoms,
        # even when they share an operation name. They must remain selectable
        # separately and are only linked through the operation alias.
        if (
            [port.model_dump(mode="json", by_alias=True) for port in canonical.ports]
            != [port.model_dump(mode="json", by_alias=True) for port in template.ports]
            or canonical.default_config != template.default_config
        ):
            consolidated.append(template)
            continue
        # Preserve a complete definition snapshot for evidence/audit views.
        variants = list(canonical.metadata.get("merged_template_variants", []))
        variants.append(template.model_dump(mode="json", by_alias=True, exclude_none=True))
        canonical.metadata["merged_template_variants"] = variants
        canonical.metadata.setdefault("merged_template_ids", []).append(template.template_id)
        canonical.evidence_refs = list(dict.fromkeys([*canonical.evidence_refs, *template.evidence_refs]))
        canonical.tags = list(dict.fromkeys([*canonical.tags, *template.tags]))
        merged_ids[template.template_id] = canonical.template_id
    return consolidated, merged_ids


def refresh_method_atom_templates(
    *,
    force: bool = False,
    write_state: bool = True,
    local_atom_dir: str | None = None,
) -> dict[str, object]:
    """Refresh literature-derived built-in templates if bundled CSVs changed."""
    global LITERATURE_METHOD_ATOM_TEMPLATES, ALL_METHOD_ATOM_TEMPLATES, _LOCAL_LIBRARY_STATE

    from fnirs_flow.registry.local_atoms import (
        discover_local_method_atom_templates,
        local_atom_library_state,
    )

    state = methodatom_library.ensure_literature_method_atom_templates_current(
        force=force,
        write_state=write_state,
    )
    LITERATURE_METHOD_ATOM_TEMPLATES = methodatom_library.LITERATURE_METHOD_ATOM_TEMPLATES
    configured_local_atom_dir = local_atom_dir or str(settings.local_atom_dir)
    local_state = local_atom_library_state(configured_local_atom_dir)
    local_changed = force or local_state != _LOCAL_LIBRARY_STATE
    local_errors: list[str] = []
    if local_changed:
        local_discovery = discover_local_method_atom_templates(configured_local_atom_dir)
        if local_discovery.errors:
            local_errors = local_discovery.errors
        else:
            local_templates: list[MethodAtomTemplate] = []
            reserved_ids = {
                template.template_id
                for template in [*HANDWRITTEN_ATOM_TEMPLATES, *LITERATURE_METHOD_ATOM_TEMPLATES]
            }
            for template in local_discovery.templates:
                if template.template_id in reserved_ids:
                    local_errors.append(
                        f"{template.metadata.get('local_atom_file', '<local>')}: "
                        f"template_id {template.template_id!r} conflicts with a bundled Atom"
                    )
                    continue
                if any(item.template_id == template.template_id for item in local_templates):
                    local_errors.append(
                        f"{template.metadata.get('local_atom_file', '<local>')}: "
                        f"duplicate local template_id {template.template_id!r}"
                    )
                    continue
                local_templates.append(template)
            LOCAL_METHOD_ATOM_TEMPLATES[:] = local_templates
            _LOCAL_LIBRARY_STATE = local_state
    raw_combined = [
        *HANDWRITTEN_ATOM_TEMPLATES,
        *LITERATURE_METHOD_ATOM_TEMPLATES,
        *LOCAL_METHOD_ATOM_TEMPLATES,
    ]
    combined, merged_template_ids = _merge_compatible_operation_templates(raw_combined)
    operation_groups: dict[str, list[str]] = {}
    for template in combined:
        operation_groups.setdefault(str(template.operation or template.atom_type), []).append(template.template_id)
    for template in combined:
        group = operation_groups[str(template.operation or template.atom_type)]
        if len(group) > 1:
            template.metadata.setdefault("operation_group", group)
    # Registration is the composition gate: collisions across handwritten and
    # literature-derived sources fail loudly instead of silently shadowing.
    validation_library = MethodAtomLibrary()
    validation_library.register_many(combined)
    ALL_ATOM_TEMPLATES[:] = combined
    ALL_METHOD_ATOM_TEMPLATES = ALL_ATOM_TEMPLATES
    return {
        **state,
        "handwritten_templates": len(HANDWRITTEN_ATOM_TEMPLATES),
        "local_templates": len(LOCAL_METHOD_ATOM_TEMPLATES),
        "local_changed": local_changed,
        "local_errors": local_errors,
        "source_templates": len(raw_combined),
        "merged_templates": len(merged_template_ids),
        "merged_template_ids": merged_template_ids,
        **local_state,
        "total_templates": len(ALL_METHOD_ATOM_TEMPLATES),
    }


def create_method_atom_library() -> MethodAtomLibrary:
    """Create a MethodAtomLibrary with all built-in atom templates."""
    refresh_method_atom_templates()
    library = MethodAtomLibrary()
    library.register_many(ALL_METHOD_ATOM_TEMPLATES)
    return library
