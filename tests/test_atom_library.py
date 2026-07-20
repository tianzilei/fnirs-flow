"""Tests for MethodAtomTemplate and MethodAtomLibrary aliases."""

from fnirs_flow.flow.atoms import ReadinessStatus
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
        assert "source_atom_id" not in atom.config
        assert atom.metadata["source_atom_id"] == "ATOM_descriptive_statistics"

    def test_nirs_spm_spatial_registration_projection_atom(self):
        library = create_builtin_library()
        template = library.get("atom_nirs_spm_spatial_registration_projection")
        assert template is not None
        assert template.operation == "nirs_spm_spatial_registration_projection"
        assert "NIRS_SPM_UsersGuide_v4_spatial_registration" in template.evidence_refs
        assert template.default_config["software"] == "NIRS-SPM v4 r1"
        assert template.default_config["mri_registration_algorithm"] == "Horn absolute orientation"
        assert template.default_config["template_registration_algorithm"] == "NFRI MNI estimation"
        assert template.default_config["projection_sequence"] == [
            "rendered_brain",
            "hypothetical_head_surface",
            "cortical_surface",
        ]
        assert template.metadata["execution_readiness"] == "needs_attention"

    def test_localization_projection_import_atom_is_executable(self):
        library = create_builtin_library()
        template = library.get("localization_projection_import")
        assert template is not None
        assert template.operation == "localization_projection_import"
        assert template.default_execution_scope == "group"
        assert template.default_readiness_status == ReadinessStatus.READY
        assert template.output_ports[0].port_schema == "ProjectedMNIChannels"
        atom = library.create_atom("localization_projection_import", atom_id="loc")
        assert atom is not None
        assert atom.execution_scope == "group"
        assert atom.readiness_status == ReadinessStatus.READY

    def test_nirs_spm_surface_projection_atom_is_executable(self):
        library = create_builtin_library()
        template = library.get("nirs_spm_surface_projection")
        assert template is not None
        assert template.operation == "nirs_spm_surface_projection"
        assert template.default_execution_scope == "group"
        assert template.default_readiness_status == ReadinessStatus.NEEDS_ATTENTION
        assert template.output_ports[0].port_schema == "ProjectedMNIChannels"
        atom = library.create_atom("nirs_spm_surface_projection", atom_id="nirsspm-projection")
        assert atom is not None
        assert atom.execution_scope == "group"
        assert atom.readiness_status == ReadinessStatus.NEEDS_ATTENTION

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

    def test_cedalion_method_atoms_have_explicit_backend_bindings(self):
        library = create_builtin_library()
        template = library.get("atom_dot_image_recon")
        assert template is not None
        assert template.backend_binding is not None
        assert template.backend_binding.backend_id == "cedalion"
        assert template.backend_binding.operation == "reconstruct_image"
        assert "experimental" in template.tags
        assert template.metadata["verification_status"] == "contract_test_required"

    def test_cedalion_binding_is_preserved_when_atom_is_created(self):
        library = create_builtin_library()
        atom = library.create_atom("atom_dot_image_recon", atom_id="dot-recon")
        assert atom is not None
        assert atom.backend_binding is not None
        assert atom.backend_binding.backend_id == "cedalion"
        assert atom.backend_binding.operation == "reconstruct_image"
        assert atom.readiness_status == ReadinessStatus.NEEDS_ATTENTION

    def test_verified_cedalion_atom_is_ready(self):
        library = create_builtin_library()
        template = library.get("atom_extinction_coefficients")
        assert template is not None
        assert "experimental" not in template.tags
        atom = library.create_atom("atom_extinction_coefficients", atom_id="extinction")
        assert atom is not None
        assert atom.backend_binding is not None
        assert atom.backend_binding.operation == "get_extinction_coefficients"
        assert atom.readiness_status == ReadinessStatus.READY
