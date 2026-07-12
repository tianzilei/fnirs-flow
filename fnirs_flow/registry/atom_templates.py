"""MethodAtom templates: the MethodAtom-first interface to node templates.

This module re-exports all built-in templates from node_templates.py
with MethodAtom-first naming. New code should import from this module.

Legacy imports from fnirs_flow.registry.node_templates continue to work
but are discouraged for new code.
"""

from __future__ import annotations

from fnirs_flow.registry import methodatom_library
from fnirs_flow.registry.node_library import MethodAtomLibrary

# Re-export all templates with MethodAtom-first naming
from fnirs_flow.registry.node_templates import (
    ALL_NODE_TEMPLATES as ALL_ATOM_TEMPLATES,
)

HANDWRITTEN_ATOM_TEMPLATES = ALL_ATOM_TEMPLATES
LITERATURE_METHOD_ATOM_TEMPLATES = methodatom_library.LITERATURE_METHOD_ATOM_TEMPLATES
ALL_ATOM_TEMPLATES = [*HANDWRITTEN_ATOM_TEMPLATES, *LITERATURE_METHOD_ATOM_TEMPLATES]

# Aliases for clarity
ALL_METHOD_ATOM_TEMPLATES = ALL_ATOM_TEMPLATES


def refresh_method_atom_templates(*, force: bool = False, write_state: bool = True) -> dict[str, object]:
    """Refresh literature-derived built-in templates if bundled CSVs changed."""
    global LITERATURE_METHOD_ATOM_TEMPLATES, ALL_ATOM_TEMPLATES, ALL_METHOD_ATOM_TEMPLATES

    state = methodatom_library.ensure_literature_method_atom_templates_current(
        force=force,
        write_state=write_state,
    )
    LITERATURE_METHOD_ATOM_TEMPLATES = methodatom_library.LITERATURE_METHOD_ATOM_TEMPLATES
    ALL_ATOM_TEMPLATES = [*HANDWRITTEN_ATOM_TEMPLATES, *LITERATURE_METHOD_ATOM_TEMPLATES]
    ALL_METHOD_ATOM_TEMPLATES = ALL_ATOM_TEMPLATES
    return {
        **state,
        "handwritten_templates": len(HANDWRITTEN_ATOM_TEMPLATES),
        "total_templates": len(ALL_METHOD_ATOM_TEMPLATES),
    }


def create_method_atom_library() -> MethodAtomLibrary:
    """Create a MethodAtomLibrary with all built-in atom templates."""
    refresh_method_atom_templates()
    library = MethodAtomLibrary()
    library.register_many(ALL_METHOD_ATOM_TEMPLATES)
    return library
