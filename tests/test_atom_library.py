"""Tests for MethodAtomTemplate and MethodAtomLibrary aliases."""

from fnirs_flow.flow.models import NodeCategory, NodeOrigin
from fnirs_flow.registry.atom_templates import (
    ALL_METHOD_ATOM_TEMPLATES,
    HANDWRITTEN_ATOM_TEMPLATES,
    LITERATURE_METHOD_ATOM_TEMPLATES,
    refresh_method_atom_templates,
)
from fnirs_flow.registry.methodatom_library import (
    method_atom_library_fingerprint,
)
from fnirs_flow.registry.node_library import (
    MethodAtomLibrary,
    MethodAtomTemplate,
    NodeLibrary,
    NodeTemplate,
    create_builtin_library,
)


class TestMethodAtomTemplateAlias:
    """Verify MethodAtomTemplate is an alias for NodeTemplate."""

    def test_alias_identity(self):
        assert MethodAtomTemplate is NodeTemplate

    def test_create_with_new_name(self):
        template = MethodAtomTemplate(
            template_id="test_atom",
            name="Test Atom",
            category=NodeCategory.PREPROCESSING,
            atom_type="optical_density",
        )
        assert template.template_id == "test_atom"
        assert template.category == NodeCategory.PREPROCESSING


class TestMethodAtomLibraryAlias:
    """Verify MethodAtomLibrary is an alias for NodeLibrary."""

    def test_alias_identity(self):
        assert MethodAtomLibrary is NodeLibrary

    def test_create_with_new_name(self):
        library = MethodAtomLibrary()
        assert isinstance(library, NodeLibrary)


class TestCreateAtomMethod:
    """Test that create_atom works as an alias for create_node."""

    def test_create_atom(self):
        library = create_builtin_library()
        atom = library.create_atom("optical_density", atom_id="test-od")
        assert atom is not None
        assert atom.id == "test-od"
        assert atom.type == "optical_density"

    def test_create_atom_returns_none_for_missing(self):
        library = create_builtin_library()
        assert library.create_atom("nonexistent") is None

    def test_create_atom_deterministic(self):
        library = create_builtin_library()
        atom1 = library.create_atom("optical_density", atom_id="same-id")
        library2 = create_builtin_library()
        atom2 = library2.create_atom("optical_density", atom_id="same-id")
        assert atom1.id == atom2.id
        assert atom1.type == atom2.type


class TestLiteratureDerivedMethodAtoms:
    """Verify synthesized MethodAtom records are bundled as built-in templates."""

    def test_literature_templates_are_loaded(self):
        fingerprint = method_atom_library_fingerprint()
        assert len(LITERATURE_METHOD_ATOM_TEMPLATES) == fingerprint["method_atoms_rows"]
        assert len(ALL_METHOD_ATOM_TEMPLATES) == len(HANDWRITTEN_ATOM_TEMPLATES) + fingerprint["method_atoms_rows"]

    def test_literature_template_is_in_builtin_library(self):
        library = create_builtin_library()
        template = library.get("atom_descriptive_statistics")
        assert template is not None
        assert template.origin == NodeOrigin.EVIDENCE_DERIVED
        assert "literature_derived" in template.tags
        assert len(template.evidence_refs) > 0

    def test_create_literature_derived_atom(self):
        library = create_builtin_library()
        atom = library.create_atom("atom_descriptive_statistics", atom_id="desc")
        assert atom is not None
        assert atom.origin == NodeOrigin.EVIDENCE_DERIVED
        assert atom.config["source_atom_id"] == "ATOM_descriptive_statistics"

    def test_runtime_fingerprint_reports_library_inputs(self):
        fingerprint = method_atom_library_fingerprint()
        assert fingerprint["method_atoms_rows"] > 0
        assert fingerprint["atom_evidence_links_rows"] >= 0
        assert fingerprint["fingerprint"]

    def test_refresh_keeps_literature_templates_current(self):
        fingerprint = method_atom_library_fingerprint()
        state = refresh_method_atom_templates(force=True, write_state=False)
        assert state["loaded_templates"] == fingerprint["method_atoms_rows"]
        assert state["total_templates"] == len(HANDWRITTEN_ATOM_TEMPLATES) + fingerprint["method_atoms_rows"]
